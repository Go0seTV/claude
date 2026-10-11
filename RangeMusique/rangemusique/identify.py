"""Identification des morceaux et choix du bon album.

Pour chaque fichier :
 1. on lit les tags existants + des indices (nom du fichier, dossiers) ;
 2. on « écoute » le morceau (empreinte AcoustID) pour savoir ce que c'est,
    même si le fichier s'appelle « track07.mp3 » ;
 3. sinon, on cherche sur MusicBrainz avec le titre / l'artiste connus ;
 4. on choisit l'album le plus logique (album studio ou BO plutôt que
    compilation, album déjà indiqué dans les tags ou le nom du dossier,
    album partagé par les autres fichiers du même dossier…).
"""

import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import AUDIO_EXTENSIONS, tagio
from .textutil import (
    clean_folder_name, main_artist, parse_filename, similarity, year_of,
)
from .webapi import NetworkError, fingerprint

# Niveaux de confiance
SURE = "sûr"          # reconnu avec certitude
TAGS = "tags"         # pas trouvé en ligne mais tags existants complets
MANUAL = "manuel"     # corrigé à la main
UNSURE = "incertain"  # des suggestions, mais pas de certitude
UNKNOWN = "inconnu"   # rien trouvé

OK_LEVELS = (SURE, TAGS, MANUAL)

_BAD_SECONDARY = {"live", "remix", "dj-mix", "mixtape/street", "demo", "interview",
                  "spokenword", "audiobook", "audio drama", "field recording"}


@dataclass
class Candidate:
    recording_id: str = ""
    title: str = ""
    artist: str = ""          # crédit complet : « David Guetta feat. Sia »
    main_artist: str = ""     # artiste principal : « David Guetta »
    album: str = ""
    release_id: str = ""
    rg_id: str = ""
    primary_type: str = ""
    secondary_types: tuple = ()
    status: str = ""
    year: str = ""
    track: int = None
    tracktotal: int = None
    disc: int = None
    disctotal: int = None
    score: float = 0.0        # calculé au moment du choix

    def describe(self):
        kind = self.primary_type or "?"
        if self.secondary_types:
            kind += " / " + ", ".join(self.secondary_types)
        num = f" – piste {self.track}" if self.track else ""
        year = f" ({self.year})" if self.year else ""
        return f"{self.main_artist} – {self.title} | {self.album}{year} [{kind}]{num}"


@dataclass
class Track:
    path: str
    root: str = ""
    size: int = 0
    duration: float = 0.0
    bitrate: int = 0
    lossless: bool = False
    has_cover: bool = False
    old: dict = field(default_factory=dict)       # tags d'origine
    fname: dict = field(default_factory=dict)     # indices du nom de fichier
    folders: list = field(default_factory=list)   # noms de dossiers parents
    candidates: list = field(default_factory=list)
    chosen: Candidate = None
    new: dict = field(default_factory=dict)       # tags finaux
    confidence: str = UNKNOWN
    method: str = ""                              # empreinte / recherche / tags / manuel
    fp_score: float = 0.0
    note: str = ""
    error: str = ""

    @property
    def folder(self):
        return os.path.dirname(self.path)

    @property
    def ext(self):
        return os.path.splitext(self.path)[1].lower()

    @property
    def filename(self):
        return os.path.basename(self.path)

    def is_ok(self):
        return self.confidence in OK_LEVELS and bool(
            self.new.get("albumartist") and self.new.get("title") and self.new.get("album")
        )


# --- Parcours ------------------------------------------------------------------

def scan(root, exclude=()):
    """Liste les fichiers audio sous root (en ignorant les dossiers exclus)."""
    root = os.path.abspath(root)
    excl = [os.path.normcase(os.path.abspath(e)) for e in exclude if e]
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        nd = os.path.normcase(os.path.abspath(dirpath))
        dirnames[:] = [
            d for d in sorted(dirnames)
            if not any(os.path.normcase(os.path.join(dirpath, d)) == e or
                       os.path.normcase(os.path.join(dirpath, d)).startswith(e + os.sep)
                       for e in excl)
        ]
        if any(nd == e or nd.startswith(e + os.sep) for e in excl):
            continue
        for fn in sorted(filenames):
            if os.path.splitext(fn)[1].lower() in AUDIO_EXTENSIONS:
                out.append(os.path.join(dirpath, fn))
    return out


def load_track(path, root):
    t = Track(path=path, root=root)
    try:
        t.size = os.path.getsize(path)
    except OSError:
        pass
    try:
        t.old, info, t.has_cover = tagio.read(path)
        t.duration, t.bitrate, t.lossless = info.duration, info.bitrate, info.lossless
    except Exception as e:  # fichier abîmé ou format exotique
        t.old = {k: "" for k in tagio.FIELDS}
        t.error = f"lecture impossible : {e}"
        t.lossless = t.ext in tagio.LOSSLESS_EXT
    t.fname = parse_filename(os.path.splitext(t.filename)[0])
    # dossiers parents situés sous la racine choisie (2 niveaux maximum)
    rel = os.path.relpath(t.folder, root)
    if rel != ".":
        parts = [p for p in rel.split(os.sep) if p and p != ".."]
        t.folders = [clean_folder_name(p) for p in reversed(parts[-2:])]
    return t


# --- Indices -------------------------------------------------------------------

def _uniq(values):
    seen, out = set(), []
    for v in values:
        v = (v or "").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def folder_pieces(t):
    pieces = []
    for f in t.folders:
        pieces.append(f)
        if " - " in f:
            pieces += [p.strip() for p in f.split(" - ") if p.strip()]
    return _uniq(pieces)


def title_hints(t):
    return _uniq([t.old.get("title"), t.fname.get("title")])


def artist_hints(t):
    return _uniq([main_artist(t.old.get("artist")), t.old.get("albumartist"),
                  main_artist(t.fname.get("artist"))])


def album_hints(t):
    return _uniq([t.old.get("album"), t.fname.get("album")] + folder_pieces(t))


# --- Lecture des réponses MusicBrainz -------------------------------------------

def _credit(ac):
    if not ac:
        return "", ""
    full = "".join((c.get("name") or c.get("artist", {}).get("name", "")) +
                   (c.get("joinphrase") or "") for c in ac).strip()
    first = ac[0]
    main = first.get("artist", {}).get("name") or first.get("name") or full
    return full, main


def _rg_info(release):
    rg = release.get("release-group") or {}
    return (rg.get("id", ""), rg.get("primary-type") or "",
            tuple(rg.get("secondary-types") or ()))


def candidates_from_releases(rec_id, releases, rec_title="", rec_credit=None):
    """Transforme une liste d'albums MusicBrainz en candidats pour un enregistrement."""
    out = []
    for rel in releases:
        rg_id, prim, sec = _rg_info(rel)
        media = rel.get("media") or []
        for medium in media:
            tracks = medium.get("tracks") or medium.get("track") or []
            for tr in tracks:
                tr_rec = (tr.get("recording") or {}).get("id")
                if tr_rec and tr_rec != rec_id:
                    continue
                if not tr_rec and len(tracks) > 1:
                    continue  # résultat de recherche : une seule piste attendue
                title = (tr.get("recording") or {}).get("title") or rec_title or tr.get("title", "")
                full, main = _credit(tr.get("artist-credit") or rec_credit or
                                     (tr.get("recording") or {}).get("artist-credit"))
                try:
                    pos = int(tr.get("position") or tr.get("number"))
                except (TypeError, ValueError):
                    pos = None
                out.append(Candidate(
                    recording_id=rec_id, title=title, artist=full, main_artist=main,
                    album=rel.get("title", ""), release_id=rel.get("id", ""), rg_id=rg_id,
                    primary_type=prim, secondary_types=sec, status=rel.get("status") or "",
                    year=year_of(rel.get("date")), track=pos,
                    tracktotal=medium.get("track-count"),
                    disc=medium.get("position") or 1,
                    disctotal=len(media) if len(media) > 1 else
                    (rel.get("media-count") or None),
                ))
                break
    return out


# --- Identification d'un fichier -------------------------------------------------

class Identifier:
    def __init__(self, api, fpcalc="", fast_mode=False, log=None):
        self.api = api
        self.fpcalc = fpcalc
        self.fast_mode = fast_mode
        self.log = log or (lambda msg: None)

    def identify(self, t):
        o = t.old
        if self.fast_mode and o.get("title") and o.get("artist") and o.get("album"):
            t.method = "tags"
            return
        found = False
        if self.fpcalc and self.api.acoustid_key and not self.api.offline:
            try:
                found = self._by_fingerprint(t)
            except NetworkError as e:
                t.note = str(e)
            except Exception as e:
                t.note = f"empreinte impossible : {e}"
        if not found and not self.api.offline:
            try:
                self._by_search(t)
            except NetworkError as e:
                t.note = str(e)

    def _by_fingerprint(self, t):
        duration, fp = fingerprint(self.fpcalc, t.path)
        if not t.duration:
            t.duration = duration
        results = self.api.acoustid_lookup(duration, fp)
        if not results:
            return False
        score, rec_ids = max(results, key=lambda r: r[0])
        if score < 0.5:
            return False
        cands = []
        for rec_id in rec_ids[:3]:
            releases = self.api.mb_releases_of_recording(rec_id)
            if releases:
                cands += candidates_from_releases(rec_id, releases)
            else:  # enregistrement isolé, sans album
                rec = self.api.mb_recording(rec_id)
                if rec.get("title"):
                    full, main = _credit(rec.get("artist-credit"))
                    cands.append(Candidate(recording_id=rec_id, title=rec["title"],
                                           artist=full, main_artist=main))
        if not cands:
            return False
        t.candidates = cands
        t.fp_score = score
        t.method = "empreinte"
        return True

    def _by_search(self, t):
        titles = title_hints(t)
        if not titles:
            return False
        artists = artist_hints(t)
        folder_artists = [p for p in folder_pieces(t)
                          if p.lower() not in {a.lower() for a in artists}]
        queries = [(title, a) for title in titles[:2] for a in artists + folder_artists]
        for title, artist in queries[:4]:
            recs = self.api.mb_search(title, artist)
            good = [r for r in recs
                    if similarity(r.get("title"), title) >= 0.85
                    and similarity(_credit(r.get("artist-credit"))[1], artist) >= 0.8]
            if good:
                t.candidates = self._from_search(good)
                if t.candidates:
                    t.method = "recherche"
                    return True
        if not artists and not folder_artists:
            # Titre seul : on garde des suggestions, sans certitude
            recs = self.api.mb_search(titles[0])
            good = [r for r in recs if similarity(r.get("title"), titles[0]) >= 0.9][:3]
            t.candidates = self._from_search(good)
            if t.candidates:
                t.method = "recherche (titre seul)"
        return False

    @staticmethod
    def _from_search(recs):
        cands = []
        for r in recs:
            cands += candidates_from_releases(
                r.get("id", ""), r.get("releases") or [], r.get("title", ""),
                r.get("artist-credit"))
            if not r.get("releases"):
                full, main = _credit(r.get("artist-credit"))
                cands.append(Candidate(recording_id=r.get("id", ""), title=r.get("title", ""),
                                       artist=full, main_artist=main))
        return cands


# --- Choix de l'album -------------------------------------------------------------

def album_variants(album):
    """'Top Gun: Original Motion Picture Soundtrack' -> aussi 'Top Gun'."""
    out = [album]
    for sep in (":", " - ", " (", " ["):
        head = album.split(sep)[0].strip()
        if head and head not in out:
            out.append(head)
    return out


def base_score(c, t):
    s = 0.0
    st = (c.status or "").lower()
    s += 3 if st == "official" else (0 if not st else -5)
    prim = (c.primary_type or "").lower()
    s += {"album": 3, "ep": 1, "single": -1, "": -1}.get(prim, -2)
    if not c.album:
        s -= 20
    sec = {x.lower() for x in c.secondary_types}
    hinted = " ".join([t.old.get("title", ""), t.old.get("album", "")] + t.folders).lower()
    if "soundtrack" not in sec and "compilation" in sec:
        s -= 15  # compilation (« Now 80s »…) : seulement s'il n'y a rien d'autre
    for bad in sec & _BAD_SECONDARY:
        if bad not in hinted:
            s -= 3
    if c.album:
        variants = album_variants(c.album)
        best = max([similarity(v, h) for v in variants for h in album_hints(t)] or [0])
        if best >= 0.85:
            s += 10
    if c.year:
        s += (2100 - int(c.year)) / 100.0  # préfère la première sortie
    if (c.disctotal or 1) > 3:
        s -= 1  # coffrets
    return s


def choose_all(tracks):
    """Choisit le meilleur candidat pour chaque morceau, en tenant compte
    des autres morceaux du même dossier (un album rippé reste groupé)."""
    votes = defaultdict(Counter)
    for t in tracks:
        rgs = {c.rg_id for c in t.candidates if c.rg_id and
               not ("compilation" in {x.lower() for x in c.secondary_types} and
                    "soundtrack" not in {x.lower() for x in c.secondary_types})}
        for rg in rgs:
            votes[t.folder][rg] += 1
    for t in tracks:
        if t.confidence == MANUAL:
            continue
        for c in t.candidates:
            c.score = base_score(c, t)
            others = votes[t.folder][c.rg_id] - 1 if c.rg_id else 0
            if others > 0:
                c.score += min(2.0 * others, 8.0)
        t.candidates.sort(key=lambda c: c.score, reverse=True)
        finalize(t)


def finalize(t):
    """Calcule les tags finaux et le niveau de confiance."""
    o = t.old
    t.chosen = t.candidates[0] if t.candidates else None
    c = t.chosen
    if c:
        t.new = {
            "title": c.title, "artist": c.artist or c.main_artist,
            "albumartist": c.main_artist, "album": c.album,
            "track": c.track, "tracktotal": c.tracktotal,
            "disc": c.disc if (c.disctotal or 1) > 1 else None,
            "disctotal": c.disctotal if (c.disctotal or 1) > 1 else None,
            "year": c.year or year_of(o.get("year")), "genre": o.get("genre", ""),
        }
        if t.method == "empreinte":
            sure = t.fp_score >= 0.8 or any(
                similarity(c.title, h) >= 0.8 for h in title_hints(t))
        elif t.method == "recherche":
            sure = True
        else:
            sure = False
        t.confidence = SURE if (sure and c.album) else UNSURE
        if t.confidence == SURE:
            return
    # Pas de reconnaissance certaine : les tags existants suffisent-ils ?
    artist = o.get("artist") or o.get("albumartist")
    if o.get("title") and artist and o.get("album"):
        t.new = {
            "title": o["title"], "artist": artist,
            "albumartist": main_artist(artist), "album": o["album"],
            "track": o.get("track") or t.fname.get("track"), "tracktotal": o.get("tracktotal"),
            "disc": o.get("disc") if (o.get("disctotal") or 1) > 1 else None,
            "disctotal": o.get("disctotal") if (o.get("disctotal") or 1) > 1 else None,
            "year": year_of(o.get("year")), "genre": o.get("genre", ""),
        }
        t.confidence = TAGS
        if not t.method:
            t.method = "tags"
    elif not c:
        t.new = {}
        t.confidence = UNKNOWN


def set_manual(t, values, candidate=None):
    """Valeurs saisies à la main dans l'appli."""
    t.chosen = candidate
    t.new = dict(values)
    t.new["albumartist"] = main_artist(values.get("albumartist") or values.get("artist", ""))
    t.confidence = MANUAL
    t.method = "manuel"


# --- Analyse complète ---------------------------------------------------------------

def analyze(root, identifier, exclude=(), progress=None, stop=None):
    """Lit et identifie tous les morceaux de root. Renvoie la liste des Track."""
    progress = progress or (lambda i, n, msg: None)
    progress(0, 0, "Recherche des fichiers…")
    paths = scan(root, exclude)
    n = len(paths)
    tracks = []
    for i, path in enumerate(paths):
        if stop is not None and stop.is_set():
            break
        progress(i, n, os.path.basename(path))
        t = load_track(path, root)
        if not t.error:
            identifier.identify(t)
        tracks.append(t)
    choose_all(tracks)
    progress(n, n, "Analyse terminée")
    return tracks
