"""Transforme des posts Instagram en recettes du livre."""

import logging
import os
import re
import shutil
import tempfile
import time

from . import ai, media
from .parse import parse_caption
from .store import empty_recipe

log = logging.getLogger("livrecuisine")

_SPOKEN_RECIPE = re.compile(r"ingr[ée]dient|cuill[eè]re|grammes|\bfour\b|degr[ée]s|m[ée]lange|"
                            r"ajoute|recipe|tablespoon|teaspoon|oven|\bcups?\b", re.I)


class Options:
    def __init__(self, cfg):
        self.claude_key = cfg.get("claude_key", "") if ai.available() else ""
        self.transcribe = bool(cfg.get("transcribe")) and media.can_transcribe()
        self.whisper_model = cfg.get("whisper_model", "small")
        self.pause = max(0, int(cfg.get("pause_seconds", 4) or 0))


def describe(rec):
    kind = {"claude": "mise en forme par Claude", "auto": "découpage automatique",
            "manuel": "à la main"}.get(rec.get("method"), "")
    if not rec.get("is_recipe"):
        return f"« {rec['title']} » : pas une recette, mise de côté"
    return f"« {rec['title']} » ({kind})"


def build_fields(caption, transcript, images, author, opts, say=lambda m: None):
    """Champs de la recette : Claude si possible, sinon découpage de la légende."""
    if opts.claude_key:
        try:
            fields = ai.structure(opts.claude_key, caption, transcript, images, author)
            fields["method"] = "claude"
            return fields
        except ai.AIError as exc:
            say(f"   Claude : {exc} On découpe la légende à la place.")
            log.warning("Claude indisponible : %s", exc)
    fields = parse_caption(caption, author)
    fields["method"] = "auto"
    if transcript and not fields["is_recipe"] and _SPOKEN_RECIPE.search(transcript):
        fields["is_recipe"] = True
    return fields


class Importer:
    def __init__(self, store, insta, opts, say, stop):
        self.store = store
        self.insta = insta
        self.opts = opts
        self.say = say      # say(message) : écrit dans le journal de l'appli
        self.stop = stop    # threading.Event
        self.counts = {"new": 0, "known": 0, "others": 0, "errors": 0}

    def _sleep(self):
        end = time.time() + self.opts.pause
        while time.time() < end and not self.stop.is_set():
            time.sleep(0.2)

    def run(self, posts, progress=lambda done, total: None, total=None):
        from instaloader.exceptions import TooManyRequestsException
        from .instagram import friendly
        done = 0
        for post in posts:
            if self.stop.is_set():
                break
            done += 1
            progress(done, total)
            try:
                code = post.shortcode
                if self.store.has(code):
                    self.counts["known"] += 1
                    continue
                rec = self.import_post(post)
                self.counts["new" if rec["is_recipe"] else "others"] += 1
                self.say(f"✓ {describe(rec)}")
            except TooManyRequestsException as exc:
                self.say("✗ " + friendly(exc))
                raise
            except Exception as exc:
                self.counts["errors"] += 1
                log.exception("Import impossible")
                self.say(f"✗ Post {getattr(post, 'shortcode', '?')} : {friendly(exc)}")
            self._sleep()
        return self.counts

    def import_post(self, post):
        info = self.insta.post_info(post)
        code = info["shortcode"]
        tmp = tempfile.mkdtemp(prefix="livrecuisine-")
        try:
            photos, images = self._photos(info, tmp)
            transcript, frames = self._video(info, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        fields = build_fields(info["caption"], transcript, images + frames, info["author"],
                              self.opts, self.say)
        rec = empty_recipe(
            id=code, source_url=info["url"], author=info["author"], posted=info["posted"],
            caption=info["caption"], transcript=transcript, photos=photos)
        rec.update(fields)
        if not rec.get("title"):
            rec["title"] = f"Post de @{info['author']}" if info["author"] else code
        self.store.put(rec)
        return rec

    def _photos(self, info, tmp):
        """Enregistre les images du post. Renvoie (noms de fichiers, octets JPEG pour Claude)."""
        names, images = [], []
        for i, m in enumerate(info["media"][:10]):
            if not m.get("image_url"):
                continue
            raw = os.path.join(tmp, f"img{i}")
            try:
                self.insta.download(m["image_url"], raw)
                name = f"{info['shortcode']}_{i + 1}.jpg"
                media.save_photo(raw, self.store.photo_path(name))
                names.append(name)
                if self.opts.claude_key:
                    images.append(media.jpeg_bytes(raw))
            except Exception as exc:
                log.warning("Photo %d de %s : %s", i, info["shortcode"], exc)
        return names, images

    def _video(self, info, tmp):
        """Transcription et images de la première vidéo du post."""
        url = next((m["video_url"] for m in info["media"] if m.get("video") and m.get("video_url")),
                   None)
        want_frames = bool(self.opts.claude_key) and media.can_read_video()
        if not url or not (self.opts.transcribe or want_frames):
            return "", []
        path = os.path.join(tmp, "video.mp4")
        transcript, frames = "", []
        try:
            self.insta.download(url, path)
        except Exception as exc:
            log.warning("Vidéo de %s : %s", info["shortcode"], exc)
            return "", []
        if self.opts.transcribe:
            self.say("   Écoute de la vidéo…")
            try:
                transcript = media.transcribe(path, self.opts.whisper_model)
            except Exception as exc:
                log.exception("Transcription")
                self.say(f"   Transcription impossible : {exc}")
        if want_frames:
            try:
                frames = media.video_frames(path)
            except Exception as exc:
                log.warning("Images de la vidéo %s : %s", info["shortcode"], exc)
        return transcript, frames


def reformat(store, rec, opts):
    """Refait la mise en forme d'une recette déjà importée, avec ses données gardées."""
    if not opts.claude_key:
        raise ai.AIError("Il faut une clé Claude (onglet Réglages) pour la mise en forme.")
    images = []
    for name in rec.get("photos", [])[:ai.MAX_IMAGES]:
        path = store.photo_path(name)
        if os.path.isfile(path):
            images.append(media.jpeg_bytes(path))
    fields = ai.structure(opts.claude_key, rec.get("caption", ""), rec.get("transcript", ""),
                          images, rec.get("author", ""))
    fields["method"] = "claude"
    rec = dict(rec)
    rec.update(fields)
    store.put(rec)
    return rec
