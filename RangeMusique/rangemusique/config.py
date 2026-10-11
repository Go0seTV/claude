"""Réglages enregistrés dans config.json, à côté de l'application."""

import json
import os
import shutil
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
CACHE_PATH = os.path.join(APP_DIR, "cache_musique.sqlite")
COVER_CACHE_DIR = os.path.join(APP_DIR, "cache_pochettes")
LOG_PATH = os.path.join(APP_DIR, "RangeMusique.log")

DEFAULTS = {
    "acoustid_key": "",
    "fpcalc_path": "",
    "source_dir": "",
    "dest_dir": "",
    "fast_mode": False,
    "write_tags": True,
    "covers": True,
    "cleanup": True,
}


def load():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)


def find_fpcalc(configured=""):
    """Cherche fpcalc(.exe) : réglage, dossier de l'appli, PATH."""
    exe = "fpcalc.exe" if sys.platform == "win32" else "fpcalc"
    candidates = []
    if configured:
        candidates.append(configured)
        if os.path.isdir(configured):
            candidates.append(os.path.join(configured, exe))
    candidates += [os.path.join(APP_DIR, exe), os.path.join(APP_DIR, "fpcalc", exe)]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return shutil.which(exe) or shutil.which("fpcalc") or ""
