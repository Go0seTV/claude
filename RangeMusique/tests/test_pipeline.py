"""Test de bout en bout avec un faux AcoustID / MusicBrainz (pas d'internet)."""

import os

import pytest

from rangemusique import executor, identify, planner, tagio
from rangemusique.cache import MemoryCache
from rangemusique.webapi import WebAPI

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64


def ac(name):
    return [{"name": name, "joinphrase": "", "artist": {"name": name}}]


def track(pos, rec_id, title, artist):
    return {"position": pos, "number": str(pos), "title": title,
            "recording": {"id": rec_id, "title": title}, "artist-credit": ac(artist)}


TOP_GUN = {
    "id": "rel-topgun", "title": "Top Gun: Original Motion Picture Soundtrack",
    "status": "Official", "date": "1986-05-13",
    "release-group": {"id": "rg-topgun", "primary-type": "Album",
                      "secondary-types": ["Soundtrack"]},
    "media": [{"position": 1, "track-count": 10, "tracks": [
        track(1, "rec-dz", "Danger Zone", "Kenny Loggins"),
        track(3, "rec-tmba", "Take My Breath Away", "Berlin"),
    ]}],
}
COUNT_THREE = {
    "id": "rel-c3p", "title": "Count Three & Pray", "status": "Official",
    "date": "1986-10-01",
    "release-group": {"id": "rg-c3p", "primary-type": "Album", "secondary-types": []},
    "media": [{"position": 1, "track-count": 10, "tracks": [
        track(9, "rec-tmba", "Take My Breath Away", "Berlin")]}],
}
NOW_80S = {
    "id": "rel-now", "title": "Now That's What I Call the 80s", "status": "Official",
    "date": "1984-01-01",
    "release-group": {"id": "rg-now", "primary-type": "Album",
                      "secondary-types": ["Compilation"]},
    "media": [{"position": 1, "track-count": 20, "tracks": [
        track(5, "rec-tmba", "Take My Breath Away", "Berlin"),
        track(6, "rec-dz", "Danger Zone", "Kenny Loggins")]}],
}
GUETTA = {
    "id": "rel-guetta", "title": "Nothing but the Beat", "status": "Official",
    "date": "2011-08-26",
    "release-group": {"id": "rg-guetta", "primary-type": "Album", "secondary-types": []},
    "media": [{"position": 1, "track-count": 14, "tracks": [{
        "position": 2, "title": "Titanium", "recording": {"id": "rec-titanium",
                                                          "title": "Titanium"},
        "artist-credit": [
            {"name": "David Guetta", "joinphrase": " feat. ", "artist": {"name": "David Guetta"}},
            {"name": "Sia", "joinphrase": "", "artist": {"name": "Sia"}}]}]}],
}

RELEASES = {"rec-tmba": [NOW_80S, TOP_GUN, COUNT_THREE], "rec-dz": [NOW_80S, TOP_GUN],
            "rec-titanium": [GUETTA]}
# empreinte simulée : fréquence du son -> enregistrement reconnu
FINGERPRINTS = {"fp440": "rec-tmba", "fp550": "rec-dz", "fp660": "rec-titanium"}


class FakeAPI(WebAPI):
    def __init__(self):
        super().__init__(MemoryCache(), "fake-key")
        self.calls = []

    def _request(self, url, data=None, rate=None, retries=4, binary=False):
        raise AssertionError(f"pas d'internet dans les tests : {url}")

    def acoustid_lookup(self, duration, fp):
        rec = FINGERPRINTS.get(fp)
        return [(0.97, [rec])] if rec else []

    def mb_releases_of_recording(self, rec_id, limit=100):
        return RELEASES.get(rec_id, [])

    def mb_recording(self, rec_id):
        return {}

    def mb_search(self, title, artist="", album="", limit=15):
        self.calls.append((title, artist))
        return []

    def cover(self, release_id, release_group_id=""):
        return JPEG


@pytest.fixture
def library(tmp_path, make_audio, monkeypatch):
    src = tmp_path / "Musique"
    # Fichier mal nommé, rangé à l'envers (Top Gun / Berlin / …)
    make_audio(src / "Top Gun" / "Berlin" / "track07.mp3", freq=440)
    make_audio(src / "Top Gun" / "Kenny Loggins" / "piste 01.mp3", freq=550)
    # Doublon de meilleure qualité, ailleurs
    make_audio(src / "Vrac" / "Berlin - Take My Breath Away.flac", freq=440)
    # Copie exacte d'un fichier
    make_audio(src / "Vrac" / "copie" / "track07.mp3", freq=440)
    # Featuring
    make_audio(src / "Vrac" / "titanium.m4a", freq=660)
    # Bien tagué mais inconnu en ligne
    q = make_audio(src / "Queen" / "A Night at the Opera" / "01.mp3", freq=770, seconds=4)
    tagio.write(q, {"title": "Death on Two Legs", "artist": "Queen",
                    "album": "A Night at the Opera", "track": 1, "year": "1975"})
    # Totalement inconnu
    make_audio(src / "Divers" / "zzz.ogg", freq=880)
    # fichiers inutiles
    (src / "Top Gun" / "Berlin" / "Thumbs.db").write_bytes(b"x")
    (src / "Divers" / "desktop.ini").write_text("x")
    # un fichier non audio reste en place
    (src / "Queen" / "paroles.txt").write_text("Bohemian…")

    def fake_fp(fpcalc, path, timeout=120):
        _, info, _ = tagio.read(path)
        # on retrouve la fréquence à partir du fichier d'origine (taille de durée)
        return info.duration, FAKE_FP[os.path.basename(os.path.dirname(path)) + "/" +
                                      os.path.basename(path)]
    FAKE_FP = {
        "Berlin/track07.mp3": "fp440", "Kenny Loggins/piste 01.mp3": "fp550",
        "Vrac/Berlin - Take My Breath Away.flac": "fp440", "copie/track07.mp3": "fp440",
        "Vrac/titanium.m4a": "fp660", "A Night at the Opera/01.mp3": "unknown",
        "Divers/zzz.ogg": "unknown",
    }
    monkeypatch.setattr(identify, "fingerprint", fake_fp)
    return src


def rel_files(root):
    out = set()
    for d, _, files in os.walk(root):
        for f in files:
            out.add(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"))
    return out


def test_full_run_and_undo(library, tmp_path):
    src, dest = str(library), str(tmp_path / "Musique rangée")
    before = rel_files(src)
    api = FakeAPI()
    ident = identify.Identifier(api, fpcalc="fpcalc", fast_mode=False)
    tracks = identify.analyze(src, ident, exclude=[dest])
    by_name = {os.path.relpath(t.path, src).replace(os.sep, "/"): t for t in tracks}

    tmba = by_name["Top Gun/Berlin/track07.mp3"]
    assert tmba.confidence == identify.SURE
    assert tmba.new["album"].startswith("Top Gun")  # BO, pas la compilation
    assert tmba.new["albumartist"] == "Berlin" and tmba.new["track"] == 3
    loose = by_name["Vrac/Berlin - Take My Breath Away.flac"]
    assert loose.new["album"].startswith("Top Gun")  # première sortie, pas la compil
    tit = by_name["Vrac/titanium.m4a"]
    assert tit.new["artist"] == "David Guetta feat. Sia"
    assert tit.new["albumartist"] == "David Guetta"
    assert by_name["Queen/A Night at the Opera/01.mp3"].confidence == identify.TAGS
    assert by_name["Divers/zzz.ogg"].confidence == identify.UNKNOWN

    plan = planner.build_plan(tracks, dest)
    actions = {os.path.relpath(it.track.path, src).replace(os.sep, "/"): it for it in plan}
    assert actions["Top Gun/Berlin/track07.mp3"].action == planner.DUPLICATE
    assert actions["Vrac/copie/track07.mp3"].action == planner.DUPLICATE
    assert actions["Vrac/Berlin - Take My Breath Away.flac"].action == planner.MOVE
    assert actions["Divers/zzz.ogg"].action == planner.REVIEW

    report = executor.execute(plan, src, dest, api)
    assert not report["errors"], report["errors"]
    after = rel_files(dest)
    tg = "Top Gun - Original Motion Picture Soundtrack"
    assert f"Berlin/{tg}/03 - Take My Breath Away.flac" in after
    assert f"Berlin/{tg}/cover.jpg" in after
    assert f"Kenny Loggins/{tg}/01 - Danger Zone.mp3" in after
    assert "David Guetta/Nothing but the Beat/02 - Titanium.m4a" in after
    assert "Queen/A Night at the Opera/01 - Death on Two Legs.mp3" in after
    assert "_À vérifier/zzz.ogg" in after and "_À vérifier/_suggestions.csv" in after
    assert len([f for f in after if f.startswith("_Doublons/")]) == 2

    # tags et pochette bien écrits
    tags, _, has_cover = tagio.read(os.path.join(dest, "Berlin", tg,
                                                 "03 - Take My Breath Away.flac"))
    assert tags["artist"] == "Berlin" and tags["album"].startswith("Top Gun")
    assert tags["track"] == 3 and has_cover

    # anciens dossiers : seuls restent ceux qui contiennent encore autre chose
    left = rel_files(src)
    assert left == {"Queen/paroles.txt"}
    assert sorted(os.listdir(src)) == ["Queen"]

    # annulation : tout revient comme avant
    restored, errors = executor.undo(executor.last_journal(dest))
    assert not errors, errors
    assert restored == len(plan)
    junk = {"Top Gun/Berlin/Thumbs.db", "Divers/desktop.ini"}
    assert rel_files(src) == before - junk
    q, _, _ = tagio.read(os.path.join(src, "Top Gun", "Berlin", "track07.mp3"))
    assert not q["title"] and not q["album"]
    assert not any(n for n in os.listdir(dest) if not n.startswith("_"))


def test_folder_vote_keeps_album_together(tmp_path, make_audio, monkeypatch):
    """Un album rippé (dossier) reste groupé même si un titre existe ailleurs."""
    src = tmp_path / "M"
    make_audio(src / "cd" / "a.mp3", freq=440)
    make_audio(src / "cd" / "b.mp3", freq=550)
    fps = {"a.mp3": "fp440", "b.mp3": "fp550"}
    monkeypatch.setattr(identify, "fingerprint",
                        lambda f, p, timeout=120: (3.0, fps[os.path.basename(p)]))
    # sans le vote : Take My Breath Away irait aussi sur Top Gun ; ici on retire
    # Top Gun pour Danger Zone afin de forcer la compilation pour les deux
    releases = dict(RELEASES)
    releases["rec-dz"] = [NOW_80S]
    releases["rec-tmba"] = [NOW_80S, COUNT_THREE]
    monkeypatch.setattr(FakeAPI, "mb_releases_of_recording",
                        lambda self, r, limit=100: releases.get(r, []))
    tracks = identify.analyze(str(src), identify.Identifier(FakeAPI(), "fpcalc"))
    albums = {t.new["album"] for t in tracks}
    # la compilation est pénalisée : Take My Breath Away va sur l'album studio
    assert "Count Three & Pray" in albums


def test_search_fallback_uses_tags(tmp_path, make_audio):
    src = tmp_path / "M"
    make_audio(src / "x" / "Berlin - Take My Breath Away.mp3")
    api = FakeAPI()
    identify.analyze(str(src), identify.Identifier(api, fpcalc=""))
    assert ("Take My Breath Away", "Berlin") in api.calls


def test_compilation_folder_still_goes_to_original_album(tmp_path, make_audio, monkeypatch):
    src = tmp_path / "M"
    make_audio(src / "Now That's What I Call the 80s" / "05.mp3", freq=440)
    monkeypatch.setattr(identify, "fingerprint", lambda f, p, timeout=120: (3.0, "fp440"))
    [t] = identify.analyze(str(src), identify.Identifier(FakeAPI(), "fpcalc"))
    assert t.new["album"].startswith("Top Gun")


def test_reanalyse_and_rerange_the_organised_folder(library, tmp_path):
    """Bug signalé : analyser le dossier rangé (qui est aussi la destination
    réglée) ne trouvait aucun fichier."""
    src, dest = str(library), str(tmp_path / "Musique rangée")
    api = FakeAPI()
    tracks = identify.analyze(src, identify.Identifier(api, "fpcalc"), exclude=[dest])
    executor.execute(planner.build_plan(tracks, dest), src, dest, api)
    first = rel_files(dest)

    # 1. réanalyse du dossier rangé, avec la même destination réglée
    again = identify.analyze(dest, identify.Identifier(api, "fpcalc"), exclude=[dest])
    names = {os.path.relpath(t.path, dest).replace(os.sep, "/") for t in again}
    assert "Berlin/Top Gun - Original Motion Picture Soundtrack/03 - Take My Breath Away.flac" \
        in names
    assert "_À vérifier/zzz.ogg" in names
    assert not any(n.startswith("_Doublons/") for n in names)  # doublons ignorés

    # 2. rangement sur place : rien ne bouge, rien n'est renommé en « (2) »
    plan = planner.build_plan(again, dest)
    ranged = [it for it in plan if it.action == planner.MOVE]
    assert ranged and all(os.path.normcase(it.dest) == os.path.normcase(it.track.path)
                          for it in ranged)
    report = executor.execute(plan, dest, dest, api)
    assert not report["errors"], report["errors"]
    after = {f for f in rel_files(dest) if not f.startswith("_Journal/")}
    assert after == {f for f in first if not f.startswith("_Journal/")}


def test_fix_review_folder_then_range(library, tmp_path):
    """Corriger un morceau de _À vérifier puis le ranger dans la destination."""
    src, dest = str(library), str(tmp_path / "Musique rangée")
    api = FakeAPI()
    tracks = identify.analyze(src, identify.Identifier(api, "fpcalc"), exclude=[dest])
    executor.execute(planner.build_plan(tracks, dest), src, dest, api)

    review = os.path.join(dest, "_À vérifier")
    [t] = identify.analyze(review, identify.Identifier(api, "fpcalc"), exclude=[dest])
    identify.set_manual(t, {"artist": "Daft Punk", "title": "Da Funk",
                            "album": "Homework", "track": 7, "year": "1997"})
    report = executor.execute(planner.build_plan([t], dest), review, dest, api)
    assert not report["errors"], report["errors"]
    assert "Daft Punk/Homework/07 - Da Funk.ogg" in rel_files(dest)
    assert os.path.isdir(review)  # le dossier analysé lui-même est gardé


def test_offline_tracks_completed_from_filename(tmp_path, make_audio):
    """Cas réel : sketchs de François Pérusse, inconnus en ligne, avec des tags
    partiels. Le nom du fichier doit compléter les tags."""
    src = tmp_path / "_À vérifier"
    a = make_audio(src / "François Pérusse - Horscope.mp3", freq=300)
    tagio.write(a, {"artist": "François Pérusse", "album": "Les deux minutes du peuple"})
    b = make_audio(src / "François Pérusse - Je bricole.mp3", freq=310)
    tagio.write(b, {"artist": "François Pérusse", "title": "Je bricole", "year": "2001"})
    c = make_audio(src / "François Pérusse - L'Hôpital - Dans les Couloirs.mp3", freq=320)
    tagio.write(c, {"artist": "François Pérusse", "title": "L'Hôpital - Dans les Couloirs",
                    "year": "0099"})
    make_audio(src / "François Pérusse - Jacques Cartier 2.mp3", freq=330)  # aucun tag

    api = FakeAPI()
    tracks = identify.analyze(str(src), identify.Identifier(api, fpcalc=""))
    by = {t.filename: t for t in tracks}
    assert all(t.confidence == identify.TAGS and t.is_ok() for t in tracks)
    assert by["François Pérusse - Horscope.mp3"].new["title"] == "Horscope"
    assert by["François Pérusse - Horscope.mp3"].new["album"] == "Les deux minutes du peuple"
    assert by["François Pérusse - Je bricole.mp3"].new["album"] == ""
    cart = by["François Pérusse - Jacques Cartier 2.mp3"].new
    assert cart["artist"] == "François Pérusse" and cart["title"] == "Jacques Cartier 2"
    hop = by["François Pérusse - L'Hôpital - Dans les Couloirs.mp3"].new
    assert hop["album"] == "" and hop["year"] == ""  # pas d'album inventé, 0099 ignoré

    dest = str(tmp_path / "Musique rangée")
    report = executor.execute(planner.build_plan(tracks, dest), str(src), dest, api)
    assert not report["errors"], report["errors"]
    files = rel_files(dest)
    assert "François Pérusse/Les deux minutes du peuple/Horscope.mp3" in files
    assert "François Pérusse/Divers/Je bricole.mp3" in files
    assert "François Pérusse/Divers/Jacques Cartier 2.mp3" in files
    tags, _, _ = tagio.read(os.path.join(dest, "François Pérusse", "Les deux minutes du peuple",
                                         "Horscope.mp3"))
    assert tags["title"] == "Horscope" and tags["albumartist"] == "François Pérusse"


def test_unsure_online_match_with_partial_tags_stays_in_review(tmp_path, make_audio,
                                                               monkeypatch):
    """Empreinte peu sûre + tags incomplets => reste « à vérifier »."""
    src = tmp_path / "M"
    p = make_audio(src / "François Pérusse - L'ambiance de la situtation.mp3", freq=440)
    tagio.write(p, {"artist": "François Pérusse"})
    monkeypatch.setattr(identify, "fingerprint", lambda f, x, timeout=120: (3.0, "fp440"))
    api = FakeAPI()
    monkeypatch.setattr(api, "acoustid_lookup", lambda d, fp: [(0.6, ["rec-tmba"])])
    [t] = identify.analyze(str(src), identify.Identifier(api, "fpcalc"))
    assert t.confidence == identify.UNSURE and not t.is_ok()
