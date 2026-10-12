"""Réglages enregistrés dans config.json, à côté de l'application."""

import json
import os
import re

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "LivreCuisine.log")
SESSION_DIR = os.path.join(APP_DIR, "session_instagram")
DEFAULT_DATA_DIR = os.path.join(APP_DIR, "Mes recettes")

DEFAULTS = {
    "data_dir": "",
    "insta_user": "",
    "collection_id": "",
    "collection_name": "",
    "claude_key": "",
    "transcribe": True,
    "whisper_model": "small",
    "pause_seconds": 4,
}

WHISPER_MODELS = ("base", "small", "medium")


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


def data_dir(cfg):
    return cfg.get("data_dir") or DEFAULT_DATA_DIR


def clean_key(key):
    """Retire espaces, retours à la ligne et caractères invisibles d'un copier-coller."""
    return re.sub(r"[^A-Za-z0-9_-]", "", key or "")
