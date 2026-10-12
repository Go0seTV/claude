"""Préparation du rangement : destination de chaque fichier et doublons.

Structure produite dans le dossier de destination :
    Artiste\\Album\\01 - Titre.mp3
    Artiste\\Album\\1-01 - Titre.flac           (albums sur plusieurs CD)
    _Doublons\\Artiste - Titre (MP3 128 kbps).mp3
    _À vérifier\\nom d'origine.mp3
"""

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass

from .textutil import main_artist, norm, safe_name, title_key

MOVE = "Ranger"
DUPLICATE = "Doublon"
REVIEW = "À vérifier"

NO_ALBUM_DIR = "Divers"  # morceaux sans album : Artiste\\Divers\\Titre
DUP_DIR = "_Doublons"
REVIEW_DIR = "_À vérifier"
JOURNAL_DIR = "_Journal"


@dataclass
class PlanItem:
    track: object
    action: str
    dest: str
    reason: str = ""
    kept: object = None  # pour un doublon : le fichier conservé


def quality(t):
    """Plus c'est grand, meilleur c'est : sans perte > débit > tags complets."""
    filled = sum(1 for k in ("title", "artist", "album", "track", "year") if t.old.get(k))
    return (1 if t.lossless else 0, t.bitrate or 0, int(t.has_cover), filled, t.size)


def quality_label(t):
    fmt = t.ext.lstrip(".").upper()
    if t.lossless:
        return f"{fmt} sans perte"
    return f"{fmt} {t.bitrate} kbps" if t.bitrate else fmt


def _quick_hash(path, size):
    """Empreinte rapide du contenu (début + fin du fichier)."""
    h = hashlib.sha1(str(size).encode())
    try:
        with open(path, "rb") as fh:
            h.update(fh.read(1 << 20))
            if size > 2 << 20:
                fh.seek(-(1 << 20), os.SEEK_END)
                h.update(fh.read(1 << 20))
    except OSError:
        return None
    return h.hexdigest()


def _exact_copies(tracks):
    """Groupes de fichiers strictement identiques (même contenu)."""
    by_size = defaultdict(list)
    for t in tracks:
        if t.size:
            by_size[t.size].append(t)
    groups = []
    for same in by_size.values():
        if len(same) < 2:
            continue
        by_hash = defaultdict(list)
        for t in same:
            hsh = _quick_hash(t.path, t.size)
            if hsh:
                by_hash[hsh].append(t)
        groups += [g for g in by_hash.values() if len(g) > 1]
    return groups


def _duration_clusters(group, tolerance=15.0):
    """Sépare les versions de durées très différentes (live, version longue…)."""
    group = sorted(group, key=lambda t: t.duration or 0)
    clusters = []
    for t in group:
        if clusters and (not t.duration or not clusters[-1][-1].duration or
                         t.duration - clusters[-1][-1].duration <= tolerance):
            clusters[-1].append(t)
        else:
            clusters.append([t])
    return clusters


def _track_filename(new, ext):
    title = safe_name(new.get("title"), maxlen=90, default="Sans titre")
    n = new.get("track")
    if n:
        prefix = f"{int(n):02d}"
        if new.get("disc") and (new.get("disctotal") or 1) > 1:
            prefix = f"{int(new['disc'])}-{prefix}"
        return f"{prefix} - {title}{ext}"
    return f"{title}{ext}"


def build_plan(tracks, dest):
    dest = os.path.abspath(dest)
    duplicates_of = {}

    # 1. Copies strictement identiques (même si le morceau n'est pas reconnu)
    for group in _exact_copies(tracks):
        group.sort(key=lambda t: (t.is_ok(), quality(t)), reverse=True)
        for t in group[1:]:
            duplicates_of[id(t)] = (group[0], "copie exacte")

    ok = [t for t in tracks if t.is_ok() and id(t) not in duplicates_of]

    # 2. Même artiste + même titre (+ durée proche) => doublon
    by_key = defaultdict(list)
    for t in ok:
        by_key[(norm(t.new["albumartist"]), title_key(t.new["title"]))].append(t)
    for group in by_key.values():
        if len(group) < 2:
            continue
        for cluster in _duration_clusters(group):
            cluster.sort(key=quality, reverse=True)
            for t in cluster[1:]:
                duplicates_of[id(t)] = (cluster[0], "même morceau")

    # 3. Noms d'artistes / albums homogènes (« BERLIN » et « Berlin » -> un seul dossier)
    artist_names, album_names = {}, {}
    for t in ok:
        if id(t) in duplicates_of:
            continue
        a = artist_names.setdefault(norm(t.new["albumartist"]) or t.new["albumartist"],
                                    t.new["albumartist"])
        album_names.setdefault((norm(a), norm(t.new["album"])), t.new["album"])

    used = set()

    def unique(path, own=None):
        """Chemin libre ; le fichier lui-même peut garder sa place actuelle."""
        base, ext = os.path.splitext(path)
        candidate, i = path, 2
        own = os.path.normcase(own) if own else None
        while os.path.normcase(candidate) in used or (
                os.path.exists(candidate) and os.path.normcase(candidate) != own):
            candidate = f"{base} ({i}){ext}"
            i += 1
        used.add(os.path.normcase(candidate))
        return candidate

    plan = []
    for t in tracks:
        if id(t) in duplicates_of:
            kept, why = duplicates_of[id(t)]
            src = t.new if t.is_ok() else t.old
            artist = main_artist(src.get("albumartist") or src.get("artist") or "")
            label = " - ".join(x for x in (artist, src.get("title")) if x) or \
                os.path.splitext(t.filename)[0]
            name = safe_name(f"{label} ({quality_label(t)})", maxlen=120) + t.ext
            dup_path = unique(os.path.join(dest, DUP_DIR, name), own=t.path)
            plan.append(PlanItem(t, DUPLICATE, dup_path,
                                 f"{why} – on garde : {kept.filename} ({quality_label(kept)})",
                                 kept))
        elif t.is_ok():
            artist = artist_names[norm(t.new["albumartist"]) or t.new["albumartist"]]
            album = album_names[(norm(artist), norm(t.new["album"]))]
            folder = os.path.join(dest, safe_name(artist),
                                  safe_name(album or NO_ALBUM_DIR, maxlen=100))
            path = unique(os.path.join(folder, _track_filename(t.new, t.ext)), own=t.path)
            reason = {"sûr": f"reconnu ({t.method})", "tags": "tags / nom du fichier",
                      "manuel": "corrigé à la main"}.get(t.confidence, t.confidence)
            if not t.new.get("album"):
                reason += " – sans album"
            plan.append(PlanItem(t, MOVE, path, reason))
        else:
            reason = t.error or t.note or "morceau non reconnu avec certitude"
            review_path = unique(os.path.join(dest, REVIEW_DIR, t.filename), own=t.path)
            plan.append(PlanItem(t, REVIEW, review_path,
                                 reason))
    return plan


def summary(plan):
    counts = defaultdict(int)
    for it in plan:
        counts[it.action] += 1
    return counts
