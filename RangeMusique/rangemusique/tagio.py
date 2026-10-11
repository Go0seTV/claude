"""Lecture / écriture des tags pour tous les formats courants (via mutagen).

Les tags sont manipulés sous forme d'un dictionnaire simple :
    title, artist, album, albumartist, track, tracktotal, disc, disctotal,
    year, genre
"""

import base64
import os

import mutagen
from mutagen._vorbis import VComment
from mutagen.apev2 import APEv2, APEValue, BINARY
from mutagen.asf import ASFTags
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK,
)
from mutagen.mp4 import MP4Cover, MP4Tags

FIELDS = ("title", "artist", "album", "albumartist", "track", "tracktotal",
          "disc", "disctotal", "year", "genre")

LOSSLESS_EXT = {".flac", ".wav", ".aif", ".aiff", ".ape", ".wv", ".alac"}


class AudioInfo:
    __slots__ = ("duration", "bitrate", "lossless", "codec")

    def __init__(self, duration=0.0, bitrate=0, lossless=False, codec=""):
        self.duration = duration
        self.bitrate = bitrate
        self.lossless = lossless
        self.codec = codec


def _split_num(value):
    """'3/12' -> (3, 12) ; '3' -> (3, None)."""
    if value is None:
        return None, None
    s = str(value).strip()
    if not s:
        return None, None
    a, _, b = s.partition("/")
    try:
        n = int(a.strip())
    except ValueError:
        n = None
    try:
        t = int(b.strip()) if b.strip() else None
    except ValueError:
        t = None
    return n, t


def _first(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    return str(v).strip()


def open_file(path):
    f = mutagen.File(path)
    if f is None:
        raise ValueError("format non reconnu")
    return f


def read_info(f, path):
    info = getattr(f, "info", None)
    ext = os.path.splitext(path)[1].lower()
    duration = float(getattr(info, "length", 0) or 0)
    bitrate = int(getattr(info, "bitrate", 0) or 0) // 1000
    codec = str(getattr(info, "codec", "") or "")
    lossless = ext in LOSSLESS_EXT or codec.lower() == "alac" or isinstance(f, FLAC)
    if not bitrate and duration:
        try:
            bitrate = int(os.path.getsize(path) * 8 / duration / 1000)
        except OSError:
            pass
    return AudioInfo(duration, bitrate, lossless, codec)


def read(path):
    """Renvoie (tags: dict, info: AudioInfo, has_cover: bool)."""
    f = open_file(path)
    info = read_info(f, path)
    tags = {k: "" for k in FIELDS}
    t = f.tags
    has_cover = False
    if t is None:
        pass
    elif isinstance(t, ID3):
        g = lambda k: _first(t[k].text) if k in t else ""  # noqa: E731
        tags.update(title=g("TIT2"), artist=g("TPE1"), album=g("TALB"),
                    albumartist=g("TPE2"), genre=g("TCON"))
        tags["year"] = g("TDRC") or g("TYER")
        tags["track"], tags["tracktotal"] = _split_num(g("TRCK"))
        tags["disc"], tags["disctotal"] = _split_num(g("TPOS"))
        has_cover = bool(t.getall("APIC"))
    elif isinstance(t, VComment):
        g = lambda k: _first(t.get(k))  # noqa: E731
        tags.update(title=g("title"), artist=g("artist"), album=g("album"),
                    albumartist=g("albumartist") or g("album artist"),
                    year=g("date") or g("year"), genre=g("genre"))
        tags["track"], tot = _split_num(g("tracknumber"))
        tags["tracktotal"] = tot or _split_num(g("tracktotal") or g("totaltracks"))[0]
        tags["disc"], tot = _split_num(g("discnumber"))
        tags["disctotal"] = tot or _split_num(g("disctotal") or g("totaldiscs"))[0]
        has_cover = bool(getattr(f, "pictures", None)) or "metadata_block_picture" in t
    elif isinstance(t, MP4Tags):
        g = lambda k: _first(t.get(k))  # noqa: E731
        tags.update(title=g("\xa9nam"), artist=g("\xa9ART"), album=g("\xa9alb"),
                    albumartist=g("aART"), year=g("\xa9day"), genre=g("\xa9gen"))
        if t.get("trkn"):
            tags["track"], tags["tracktotal"] = (t["trkn"][0] + (None, None))[:2]
        if t.get("disk"):
            tags["disc"], tags["disctotal"] = (t["disk"][0] + (None, None))[:2]
        has_cover = bool(t.get("covr"))
    elif isinstance(t, ASFTags):
        g = lambda k: _first(t.get(k))  # noqa: E731
        tags.update(title=g("Title"), artist=g("Author"), album=g("WM/AlbumTitle"),
                    albumartist=g("WM/AlbumArtist"), year=g("WM/Year"),
                    genre=g("WM/Genre"))
        tags["track"], tags["tracktotal"] = _split_num(g("WM/TrackNumber"))
        tags["disc"], tags["disctotal"] = _split_num(g("WM/PartOfSet"))
        has_cover = "WM/Picture" in t
    elif isinstance(t, APEv2):
        g = lambda k: _first(str(t[k]) if k in t else "")  # noqa: E731
        tags.update(title=g("Title"), artist=g("Artist"), album=g("Album"),
                    albumartist=g("Album Artist"), year=g("Year"), genre=g("Genre"))
        tags["track"], tags["tracktotal"] = _split_num(g("Track"))
        tags["disc"], tags["disctotal"] = _split_num(g("Disc"))
        has_cover = "Cover Art (Front)" in t
    for k in ("track", "tracktotal", "disc", "disctotal"):
        tags[k] = tags[k] or None
    return tags, info, has_cover


def _num(n, total):
    if not n:
        return ""
    return f"{n}/{total}" if total else str(n)


def _image_mime(data):
    return "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


# Clés utilisées par chaque format (pour effacer un champ lors d'une annulation)
_KEYS = {
    "id3": {"title": ["TIT2"], "artist": ["TPE1"], "album": ["TALB"],
            "albumartist": ["TPE2"], "genre": ["TCON"], "year": ["TDRC", "TYER"],
            "track": ["TRCK"], "disc": ["TPOS"]},
    "vorbis": {"title": ["title"], "artist": ["artist"], "album": ["album"],
               "albumartist": ["albumartist"], "genre": ["genre"], "year": ["date"],
               "track": ["tracknumber"], "tracktotal": ["tracktotal", "totaltracks"],
               "disc": ["discnumber"], "disctotal": ["disctotal", "totaldiscs"]},
    "mp4": {"title": ["\xa9nam"], "artist": ["\xa9ART"], "album": ["\xa9alb"],
            "albumartist": ["aART"], "genre": ["\xa9gen"], "year": ["\xa9day"],
            "track": ["trkn"], "disc": ["disk"]},
    "asf": {"title": ["Title"], "artist": ["Author"], "album": ["WM/AlbumTitle"],
            "albumartist": ["WM/AlbumArtist"], "genre": ["WM/Genre"], "year": ["WM/Year"],
            "track": ["WM/TrackNumber"], "disc": ["WM/PartOfSet"]},
    "ape": {"title": ["Title"], "artist": ["Artist"], "album": ["Album"],
            "albumartist": ["Album Artist"], "genre": ["Genre"], "year": ["Year"],
            "track": ["Track"], "disc": ["Disc"]},
}


def _kind(t):
    if isinstance(t, ID3):
        return "id3"
    if isinstance(t, VComment):
        return "vorbis"
    if isinstance(t, MP4Tags):
        return "mp4"
    if isinstance(t, ASFTags):
        return "asf"
    if isinstance(t, APEv2):
        return "ape"
    return None


def write(path, tags, cover=None, clear_empty=False):
    """Écrit les tags et la pochette. Les champs vides sont laissés tels quels,
    sauf avec clear_empty=True (utilisé pour restaurer les tags d'origine)."""
    f = open_file(path)
    if f.tags is None:
        f.add_tags()
    t = f.tags
    if clear_empty:
        for field_name, keys in _KEYS.get(_kind(t), {}).items():
            if tags.get(field_name):
                continue
            for k in keys:
                if isinstance(t, ID3):
                    t.delall(k)
                elif k in t:
                    del t[k]
    val = lambda k: (str(tags.get(k) or "")).strip()  # noqa: E731
    is_id3 = isinstance(t, ID3)

    if is_id3:
        frames = {"title": TIT2, "artist": TPE1, "album": TALB,
                  "albumartist": TPE2, "genre": TCON, "year": TDRC}
        for k, cls in frames.items():
            if val(k):
                t.setall(cls.__name__, [cls(encoding=3, text=[val(k)])])
        if tags.get("year"):
            t.delall("TYER")
        if tags.get("track"):
            t.setall("TRCK", [TRCK(encoding=3, text=[_num(tags["track"], tags.get("tracktotal"))])])
        if tags.get("disc"):
            t.setall("TPOS", [TPOS(encoding=3, text=[_num(tags["disc"], tags.get("disctotal"))])])
        if cover:
            t.delall("APIC")
            t.add(APIC(encoding=3, mime=_image_mime(cover), type=3, desc="Cover", data=cover))
    elif isinstance(t, VComment):
        for k, key in (("title", "title"), ("artist", "artist"), ("album", "album"),
                       ("albumartist", "albumartist"), ("genre", "genre"), ("year", "date")):
            if val(k):
                t[key] = [val(k)]
        if tags.get("track"):
            t["tracknumber"] = [str(tags["track"])]
            if tags.get("tracktotal"):
                t["tracktotal"] = [str(tags["tracktotal"])]
        if tags.get("disc"):
            t["discnumber"] = [str(tags["disc"])]
            if tags.get("disctotal"):
                t["disctotal"] = [str(tags["disctotal"])]
        if cover:
            pic = Picture()
            pic.type = 3
            pic.mime = _image_mime(cover)
            pic.desc = "Cover"
            pic.data = cover
            if isinstance(f, FLAC):
                f.clear_pictures()
                f.add_picture(pic)
            else:
                t["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
    elif isinstance(t, MP4Tags):
        for k, key in (("title", "\xa9nam"), ("artist", "\xa9ART"), ("album", "\xa9alb"),
                       ("albumartist", "aART"), ("genre", "\xa9gen"), ("year", "\xa9day")):
            if val(k):
                t[key] = [val(k)]
        if tags.get("track"):
            t["trkn"] = [(int(tags["track"]), int(tags.get("tracktotal") or 0))]
        if tags.get("disc"):
            t["disk"] = [(int(tags["disc"]), int(tags.get("disctotal") or 0))]
        if cover:
            fmt = MP4Cover.FORMAT_PNG if _image_mime(cover) == "image/png" else MP4Cover.FORMAT_JPEG
            t["covr"] = [MP4Cover(cover, imageformat=fmt)]
    elif isinstance(t, ASFTags):
        for k, key in (("title", "Title"), ("artist", "Author"), ("album", "WM/AlbumTitle"),
                       ("albumartist", "WM/AlbumArtist"), ("genre", "WM/Genre"),
                       ("year", "WM/Year")):
            if val(k):
                t[key] = [val(k)]
        if tags.get("track"):
            t["WM/TrackNumber"] = [str(tags["track"])]
        if tags.get("disc"):
            t["WM/PartOfSet"] = [_num(tags["disc"], tags.get("disctotal"))]
    elif isinstance(t, APEv2):
        for k, key in (("title", "Title"), ("artist", "Artist"), ("album", "Album"),
                       ("albumartist", "Album Artist"), ("genre", "Genre"), ("year", "Year")):
            if val(k):
                t[key] = val(k)
        if tags.get("track"):
            t["Track"] = _num(tags["track"], tags.get("tracktotal"))
        if tags.get("disc"):
            t["Disc"] = _num(tags["disc"], tags.get("disctotal"))
        if cover:
            t["Cover Art (Front)"] = APEValue(b"cover.jpg\x00" + cover, BINARY)
    else:
        raise ValueError(f"type de tags non géré : {type(t).__name__}")

    if is_id3:
        try:
            f.save(v2_version=3)  # ID3v2.3 : le mieux lu par Windows
        except TypeError:
            f.save()
    else:
        f.save()
