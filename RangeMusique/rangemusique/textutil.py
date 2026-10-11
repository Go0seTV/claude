"""Petits outils texte : normalisation, similarité, noms de fichiers Windows."""

import re
import unicodedata
from difflib import SequenceMatcher

_FEAT_RE = re.compile(
    r"\s*[\(\[]?\s*\b(?:feat\.?|featuring|ft\.?)\s+.*$", re.IGNORECASE
)
_PAREN_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_REMASTER_RE = re.compile(
    r"\s*(?:[\(\[][^\)\]]*remaster[^\)\]]*[\)\]]|-\s*[^-]*remaster.*$)", re.IGNORECASE
)

# Morceaux de noms de fichiers à ignorer (sites, mentions vidéo, qualité…)
_JUNK_RE = re.compile(
    r"\[[^\]]*\]"
    r"|\((?:[^)]*(?:official|video|clip|lyrics?|audio|visuali[sz]er|hq|hd|kbps)[^)]*)\)"
    r"|\b(?:official (?:music )?video|lyrics?|hq|hd|320 ?kbps|128 ?kbps)\b"
    r"|www\.\S+|\S+\.(?:com|net|org|fr|ru)\b",
    re.IGNORECASE,
)


def strip_accents(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def norm(s):
    """Version simplifiée d'un texte pour les comparaisons."""
    if not s:
        return ""
    s = strip_accents(str(s)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    if s.startswith("the "):
        s = s[4:]
    return s


def _ratio(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def similarity(a, b):
    """Similarité entre 0 et 1, tolérante aux parenthèses et aux accents."""
    if not a or not b:
        return 0.0
    na, nb = norm(a), norm(b)
    best = _ratio(na, nb)
    sa, sb = norm(_PAREN_RE.sub("", a)), norm(_PAREN_RE.sub("", b))
    if sa and sb:
        best = max(best, _ratio(sa, sb) * 0.98)
    return best


def main_artist(credit):
    """'David Guetta feat. Sia' -> 'David Guetta'."""
    if not credit:
        return ""
    return _FEAT_RE.sub("", credit).strip() or credit.strip()


def title_key(title):
    """Clé de titre pour détecter les doublons (ignore 'Remastered 2011', etc.)."""
    t = _REMASTER_RE.sub("", title or "")
    t = re.sub(r"\(\s*(?:album|original|lp) version\s*\)", "", t, flags=re.IGNORECASE)
    t = _FEAT_RE.sub("", t)
    return norm(t)


# --- Noms de fichiers / dossiers Windows -------------------------------------

_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
    f"LPT{i}" for i in range(1, 10)
}
_REPLACEMENTS = {
    ":": " -", "/": "-", "\\": "-", "|": "-", "?": "", "*": "",
    '"': "'", "<": "(", ">": ")",
}


def safe_name(s, maxlen=80, default="Inconnu"):
    """Rend un texte utilisable comme nom de fichier ou dossier Windows."""
    s = str(s or "")
    for bad, good in _REPLACEMENTS.items():
        s = s.replace(bad, good)
    s = re.sub(r"[\x00-\x1f]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > maxlen:
        s = s[:maxlen].rstrip()
    s = s.rstrip(". ")
    if not s:
        s = default
    if s.split(".")[0].upper() in _RESERVED:
        s = "_" + s
    return s


# --- Indices à partir du nom de fichier --------------------------------------

_LEADING_TRACK_RE = re.compile(r"^(?:(0\d{1,2})[\s._)-]*|(\d{1,3})\s*[._)-]\s*)(.+)$")
_DISC_TRACK_RE = re.compile(r"^(\d)-(\d{2})\s+(.+)$")


def clean_filename_text(stem):
    s = stem.replace("_", " ")
    s = _JUNK_RE.sub(" ", s)
    s = re.sub(r"\(\s*\)", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -.")
    return s


def parse_filename(stem):
    """Devine artiste / titre / album / piste à partir d'un nom de fichier.

    'Berlin - Take My Breath Away'   -> artiste + titre
    '07 - Take My Breath Away'       -> piste + titre
    '07. Berlin - Top Gun - Take…'   -> piste + artiste + album + titre
    """
    s = clean_filename_text(stem)
    out = {}
    m = _DISC_TRACK_RE.match(s)
    if m:
        out["disc"], out["track"], s = int(m.group(1)), int(m.group(2)), m.group(3)
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+|\s*[-–—]{2,}\s*", s) if p.strip()]
    if not parts:
        return out
    m = _LEADING_TRACK_RE.match(parts[0])
    if m and "track" not in out and not re.fullmatch(r"\d+", parts[0]):
        num = m.group(1) or m.group(2)
        if int(num) <= 199:
            out["track"] = int(num)
            parts[0] = m.group(3).strip()
    text_parts = []
    for p in parts:
        if re.fullmatch(r"\d{1,3}", p) and "track" not in out:
            out["track"] = int(p)
        elif not re.fullmatch(r"\d{1,3}", p):
            text_parts.append(p)
    if len(text_parts) >= 2:
        out["artist"] = text_parts[0]
        out["title"] = text_parts[-1]
        if len(text_parts) >= 3:
            out["album"] = text_parts[1]
    elif text_parts:
        out["title"] = text_parts[0]
    return out


_YEAR_RE = re.compile(r"\s*[\(\[]\s*(19|20)\d{2}\s*[\)\]]\s*")


def clean_folder_name(name):
    """'Berlin - Top Gun (1986) [FLAC]' -> 'Berlin - Top Gun'."""
    s = _YEAR_RE.sub(" ", name.replace("_", " "))
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.sub(r"\((?:[^)]*(?:flac|mp3|kbps|cd\s*rip|web)[^)]*)\)", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip(" -")


def year_of(date):
    m = re.match(r"\s*(\d{4})", str(date or ""))
    return m.group(1) if m else ""
