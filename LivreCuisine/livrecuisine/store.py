"""Le livre lui-même : recettes.json + dossier photos, dans le dossier « Mes recettes »."""

import datetime
import json
import os
import shutil
import threading
import unicodedata
import uuid


def empty_recipe(**fields):
    rec = {
        "id": "",
        "title": "Nouvelle recette",
        "category": "Autre",
        "servings": "",
        "prep_time": "",
        "cook_time": "",
        "ingredients": [],   # [{"group": "Pour la pâte", "items": ["200 g de farine", …]}]
        "steps": [],
        "tips": "",
        "tags": [],
        "photos": [],        # noms de fichiers dans photos/
        "source_url": "",
        "author": "",
        "posted": "",
        "imported": datetime.datetime.now().isoformat(timespec="seconds"),
        "caption": "",
        "transcript": "",
        "method": "manuel",  # claude, auto (légende découpée) ou manuel
        "is_recipe": True,
        "favorite": False,
        "notes": "",
    }
    rec.update(fields)
    return rec


def fold(text):
    """Minuscules sans accents, pour la recherche (« creme » trouve « crème »)."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def search_text(rec):
    parts = [rec.get("title", ""), rec.get("category", ""), rec.get("author", ""),
             rec.get("tips", ""), rec.get("notes", ""), " ".join(rec.get("tags", []))]
    for g in rec.get("ingredients", []):
        parts.append(g.get("group", ""))
        parts.extend(g.get("items", []))
    return fold("\n".join(parts))


class Store:
    def __init__(self, folder):
        self.folder = folder
        self.photo_dir = os.path.join(folder, "photos")
        self.path = os.path.join(folder, "recettes.json")
        self.lock = threading.RLock()
        os.makedirs(self.photo_dir, exist_ok=True)
        self.recipes = {}
        self.load()

    def load(self):
        with self.lock:
            try:
                with open(self.path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except FileNotFoundError:
                data = {"recettes": []}
            self.recipes = {}
            for r in data.get("recettes", []):
                rec = empty_recipe()
                rec.update(r)
                self.recipes[rec["id"]] = rec

    def save(self):
        with self.lock:
            data = {"version": 1, "recettes": sorted(
                self.recipes.values(), key=lambda r: r.get("imported", ""))}
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1, ensure_ascii=False)
            if os.path.exists(self.path):
                shutil.copy2(self.path, self.path + ".bak")
            os.replace(tmp, self.path)

    def has(self, rid):
        with self.lock:
            return rid in self.recipes

    def get(self, rid):
        with self.lock:
            return self.recipes.get(rid)

    def put(self, rec):
        with self.lock:
            if not rec.get("id"):
                rec["id"] = "manuel-" + uuid.uuid4().hex[:10]
            self.recipes[rec["id"]] = rec
            self.save()
        return rec["id"]

    def delete(self, rid):
        with self.lock:
            rec = self.recipes.pop(rid, None)
            if rec:
                for name in rec.get("photos", []):
                    try:
                        os.remove(os.path.join(self.photo_dir, name))
                    except OSError:
                        pass
                self.save()

    def photo_path(self, name):
        return os.path.join(self.photo_dir, name)

    def all(self):
        with self.lock:
            return list(self.recipes.values())

    def categories(self):
        return sorted({r.get("category") or "Autre" for r in self.all() if r.get("is_recipe")})

    def query(self, text="", category="", favorites=False, show="recipes"):
        """show : « recipes » (recettes), « others » (posts qui ne sont pas des recettes), « all »."""
        words = fold(text).split()
        out = []
        for r in self.all():
            if show == "recipes" and not r.get("is_recipe"):
                continue
            if show == "others" and r.get("is_recipe"):
                continue
            if category and (r.get("category") or "Autre") != category:
                continue
            if favorites and not r.get("favorite"):
                continue
            if words:
                hay = search_text(r)
                if not all(w in hay for w in words):
                    continue
            out.append(r)
        out.sort(key=lambda r: fold(r.get("title", "")))
        return out


def ingredients_to_text(groups):
    """Pour le formulaire : une ligne par ingrédient, « Pour la pâte : » pour un groupe."""
    lines = []
    for g in groups:
        if g.get("group"):
            if lines:
                lines.append("")
            lines.append(g["group"].rstrip(" :") + " :")
        lines.extend(g.get("items", []))
    return "\n".join(lines)


def text_to_ingredients(text):
    groups = [{"group": "", "items": []}]
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-•* ").strip()
        if not line:
            continue
        if line.endswith(":"):
            name = line.rstrip(" :")
            if groups[-1]["items"] or groups[-1]["group"]:
                groups.append({"group": name, "items": []})
            else:
                groups[-1]["group"] = name
        else:
            groups[-1]["items"].append(line)
    return [g for g in groups if g["items"]]


def text_to_steps(text):
    import re
    steps = []
    for raw in (text or "").splitlines():
        line = re.sub(r"^\s*(?:\d{1,2}\s*[.)\-:]|[-•*])\s*", "", raw).strip()
        if line:
            steps.append(line)
    return steps
