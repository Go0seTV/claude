"""Exécution du rangement, nettoyage des dossiers et annulation."""

import csv
import json
import os
import shutil
import time

from . import tagio
from .planner import DUPLICATE, JOURNAL_DIR, MOVE, REVIEW, REVIEW_DIR

# Petits fichiers sans intérêt qui empêchent un dossier d'être « vide »
JUNK_NAMES = {"thumbs.db", "desktop.ini", ".ds_store", "folder.jpg", "albumartsmall.jpg"}
JUNK_EXT = {".m3u", ".m3u8", ".pls", ".nfo", ".sfv", ".md5", ".url", ".db"}


def is_junk(filename):
    low = filename.lower()
    return (low in JUNK_NAMES or os.path.splitext(low)[1] in JUNK_EXT or
            (low.startswith("albumart_{") and low.endswith(".jpg")) or low.startswith("._"))


def _move(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        raise FileExistsError(f"existe déjà : {dst}")
    shutil.move(src, dst)


class Journal:
    """Journal (une ligne JSON par opération) pour pouvoir tout annuler."""

    def __init__(self, dest):
        folder = os.path.join(dest, JOURNAL_DIR)
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, time.strftime("rangement_%Y-%m-%d_%H-%M-%S.jsonl"))
        self._fh = open(self.path, "a", encoding="utf-8")

    def add(self, **entry):
        self._fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self):
        self._fh.close()


def execute(plan, source, dest, api=None, write_tags=True, covers=True, cleanup=True,
            progress=None, stop=None):
    """Déplace les fichiers selon le plan. Renvoie un rapport (dict)."""
    progress = progress or (lambda i, n, msg: None)
    report = {"moved": 0, "duplicates": 0, "review": 0, "errors": [],
              "removed_dirs": 0, "journal": ""}
    journal = Journal(dest)
    report["journal"] = journal.path
    cover_mem = {}
    n = len(plan)
    try:
        for i, it in enumerate(plan):
            if stop is not None and stop.is_set():
                report["errors"].append("Rangement arrêté avant la fin.")
                break
            t = it.track
            progress(i, n, t.filename)
            try:
                _move(t.path, it.dest)
            except Exception as e:
                report["errors"].append(f"{t.path} : {e}")
                continue
            entry = {"op": "move", "src": t.path, "dst": it.dest, "action": it.action}
            if it.action == MOVE and write_tags:
                cover = None
                c = t.chosen
                if covers and api is not None and c is not None and c.release_id:
                    if c.release_id not in cover_mem:
                        try:
                            cover_mem[c.release_id] = api.cover(c.release_id, c.rg_id)
                        except Exception:
                            cover_mem[c.release_id] = None
                    cover = cover_mem[c.release_id]
                try:
                    entry["old_tags"] = t.old
                    tagio.write(it.dest, t.new, cover)
                except Exception as e:
                    report["errors"].append(f"tags non écrits pour {it.dest} : {e}")
                if cover:
                    cover_path = os.path.join(os.path.dirname(it.dest), "cover.jpg")
                    if not os.path.exists(cover_path):
                        try:
                            with open(cover_path, "wb") as fh:
                                fh.write(cover)
                            journal.add(op="cover", path=cover_path)
                        except OSError:
                            pass
            journal.add(**entry)
            t.path = it.dest
            key = {MOVE: "moved", DUPLICATE: "duplicates", REVIEW: "review"}[it.action]
            report[key] += 1

        _write_review_list(plan, dest)
        if cleanup:
            removed = remove_empty_dirs(source, keep_root=True, exclude=dest)
            for d in removed:
                journal.add(op="rmdir", path=d)
            report["removed_dirs"] = len(removed)
        # le dossier de destination peut aussi contenir d'anciens dossiers vides
        remove_empty_dirs(dest, keep_root=True, delete_junk=False)
    finally:
        journal.close()
    progress(n, n, "Terminé")
    return report


def write_tags_in_place(tracks, api=None, covers=True, progress=None, stop=None):
    """Écrit les tags corrigés sans déplacer les fichiers. Renvoie (nb, erreurs)."""
    progress = progress or (lambda i, n, msg: None)
    todo = [t for t in tracks if t.is_ok()]
    errors, done, cover_mem = [], 0, {}
    for i, t in enumerate(todo):
        if stop is not None and stop.is_set():
            break
        progress(i, len(todo), t.filename)
        cover = None
        c = t.chosen
        if covers and api is not None and c is not None and c.release_id:
            if c.release_id not in cover_mem:
                try:
                    cover_mem[c.release_id] = api.cover(c.release_id, c.rg_id)
                except Exception:
                    cover_mem[c.release_id] = None
            cover = cover_mem[c.release_id]
        try:
            tagio.write(t.path, t.new, cover)
            t.old = dict(t.old, **{k: v for k, v in t.new.items() if v})
            t.has_cover = t.has_cover or bool(cover)
            done += 1
        except Exception as e:
            errors.append(f"{t.path} : {e}")
    progress(len(todo), len(todo), "Terminé")
    return done, errors


def _write_review_list(plan, dest):
    rows = [it for it in plan if it.action == REVIEW]
    if not rows:
        return
    folder = os.path.join(dest, REVIEW_DIR)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "_suggestions.csv")
    with open(path, "a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        if fh.tell() == 0:
            w.writerow(["Fichier", "Raison", "Suggestion 1", "Suggestion 2", "Suggestion 3"])
        for it in rows:
            sugg = [c.describe() for c in it.track.candidates[:3]]
            w.writerow([os.path.basename(it.dest), it.reason] + sugg)


def remove_empty_dirs(root, keep_root=True, exclude=None, delete_junk=True):
    """Supprime les dossiers devenus vides (ou ne contenant que des fichiers
    inutiles : Thumbs.db, desktop.ini, .m3u…). Renvoie la liste supprimée."""
    root = os.path.abspath(root)
    excl = os.path.normcase(os.path.abspath(exclude)) if exclude else None
    removed = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        nd = os.path.normcase(os.path.abspath(dirpath))
        if excl and (nd == excl or nd.startswith(excl + os.sep) or excl.startswith(nd + os.sep)):
            continue
        if keep_root and nd == os.path.normcase(root):
            continue
        try:
            entries = os.listdir(dirpath)
        except OSError:
            continue
        files = [e for e in entries if not os.path.isdir(os.path.join(dirpath, e))]
        if any(os.path.isdir(os.path.join(dirpath, e)) for e in entries):
            continue
        if files and not (delete_junk and all(is_junk(f) for f in files)):
            continue
        try:
            for f in files:
                p = os.path.join(dirpath, f)
                try:
                    os.chmod(p, 0o666)
                except OSError:
                    pass
                os.remove(p)
            os.rmdir(dirpath)
            removed.append(dirpath)
        except OSError:
            pass
    return removed


def last_journal(dest):
    folder = os.path.join(dest, JOURNAL_DIR)
    try:
        names = sorted(n for n in os.listdir(folder)
                       if n.startswith("rangement_") and n.endswith(".jsonl"))
    except OSError:
        return None
    return os.path.join(folder, names[-1]) if names else None


def undo(journal_path, progress=None):
    """Remet chaque fichier à sa place d'origine (et restaure ses anciens tags)."""
    progress = progress or (lambda i, n, msg: None)
    with open(journal_path, encoding="utf-8") as fh:
        entries = [json.loads(line) for line in fh if line.strip()]
    errors, restored = [], 0
    dest_dirs = set()
    n = len(entries)
    for i, e in enumerate(reversed(entries)):
        progress(i, n, e.get("dst") or e.get("path", ""))
        try:
            if e["op"] == "rmdir":
                os.makedirs(e["path"], exist_ok=True)
            elif e["op"] == "cover":
                if os.path.exists(e["path"]):
                    os.remove(e["path"])
            elif e["op"] == "move":
                if not os.path.exists(e["dst"]):
                    errors.append(f"introuvable : {e['dst']}")
                    continue
                if e.get("old_tags"):
                    try:
                        tagio.write(e["dst"], e["old_tags"], clear_empty=True)
                    except Exception as ex:
                        errors.append(f"anciens tags non restaurés ({e['dst']}) : {ex}")
                _move(e["dst"], e["src"])
                dest_dirs.add(os.path.dirname(e["dst"]))
                restored += 1
        except Exception as ex:
            errors.append(f"{e} : {ex}")
    for d in sorted(dest_dirs, key=len, reverse=True):
        for p in (d, os.path.dirname(d)):
            try:
                left = os.listdir(p)
                if all(is_junk(f) or f == "cover.jpg" for f in left):
                    for f in left:
                        os.remove(os.path.join(p, f))
                    os.rmdir(p)
            except OSError:
                pass
    os.replace(journal_path, journal_path + ".annulé")
    progress(n, n, "Terminé")
    return restored, errors
