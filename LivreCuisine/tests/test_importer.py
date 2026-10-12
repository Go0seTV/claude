import shutil
import threading

import pytest

from livrecuisine import importer, media
from livrecuisine.importer import Importer, Options, build_fields
from livrecuisine.store import Store, empty_recipe

CAPTION = ("Gâteau au yaourt\nIngrédients :\n1 pot de yaourt\n3 œufs\n2 pots de sucre\n"
           "Préparation :\n1. Mélange tout.\n2. Enfourne 30 min à 180°C.\n#gateau")


class FakePost:
    def __init__(self, code):
        self.shortcode = code


class FakeInsta:
    """Remplace Instagram : chaque post a une image, BBB a aussi une vidéo."""

    def __init__(self, image, video=None, captions=None):
        self.image, self.video = image, video
        self.captions = captions or {}
        self.downloads = []

    def post_info(self, post):
        m = [{"video": False, "image_url": f"https://cdn/{post.shortcode}.jpg", "video_url": None}]
        if post.shortcode == "BBB":
            m.append({"video": True, "image_url": "https://cdn/v.jpg",
                      "video_url": "https://cdn/v.mp4"})
        return {"shortcode": post.shortcode, "url": f"https://www.instagram.com/p/{post.shortcode}/",
                "author": "cheffe", "posted": "2025-01-02",
                "caption": self.captions.get(post.shortcode, CAPTION), "media": m}

    def download(self, url, path):
        self.downloads.append(url)
        shutil.copy(self.video if url.endswith(".mp4") else self.image, path)


def make_video(path, seconds=2):
    import av
    import numpy as np
    with av.open(path, "w") as out:
        s = out.add_stream("mpeg4", rate=10)
        s.width, s.height, s.pix_fmt = 64, 48, "yuv420p"
        for i in range(seconds * 10):
            img = np.full((48, 64, 3), i * 10 % 255, dtype=np.uint8)
            for packet in s.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                out.mux(packet)
        for packet in s.encode():
            out.mux(packet)
    return path


def opts(**kw):
    o = Options({"claude_key": "", "transcribe": False, "pause_seconds": 0})
    o.__dict__.update(kw)
    return o


def test_import_without_claude(tmp_path, make_jpeg):
    store = Store(str(tmp_path / "livre"))
    store.put(empty_recipe(id="OLD", title="Déjà là"))
    insta = FakeInsta(make_jpeg(size=(3000, 2000)),
                      captions={"NOP": "Ma nouvelle cuisine 😍 #deco"})
    said = []
    imp = Importer(store, insta, opts(), said.append, threading.Event())
    counts = imp.run([FakePost("AAA"), FakePost("OLD"), FakePost("NOP")])
    assert counts == {"new": 1, "known": 1, "others": 1, "errors": 0}

    rec = Store(str(tmp_path / "livre")).get("AAA")
    assert rec["title"] == "Gâteau au yaourt" and rec["method"] == "auto"
    assert rec["ingredients"][0]["items"] == ["1 pot de yaourt", "3 œufs", "2 pots de sucre"]
    assert rec["steps"] == ["Mélange tout.", "Enfourne 30 min à 180°C."]
    assert rec["photos"] == ["AAA_1.jpg"] and rec["author"] == "cheffe"
    from PIL import Image
    with Image.open(store.photo_path("AAA_1.jpg")) as im:
        assert max(im.size) == 1600  # photo réduite
    assert not store.get("NOP")["is_recipe"]
    assert any("Gâteau au yaourt" in s for s in said)


def test_import_stop(tmp_path, make_jpeg):
    store = Store(str(tmp_path))
    stop = threading.Event()
    stop.set()
    counts = Importer(store, FakeInsta(make_jpeg()), opts(), print, stop).run([FakePost("A")])
    assert counts["new"] == 0 and not store.has("A")


def test_one_bad_post_does_not_stop_import(tmp_path, make_jpeg):
    class Broken(FakeInsta):
        def post_info(self, post):
            if post.shortcode == "BAD":
                raise RuntimeError("boum")
            return super().post_info(post)
    store = Store(str(tmp_path))
    counts = Importer(store, Broken(make_jpeg()), opts(), print, threading.Event()).run(
        [FakePost("BAD"), FakePost("AAA")])
    assert counts["errors"] == 1 and store.has("AAA")


def test_video_with_claude_sends_transcript_photos_and_frames(tmp_path, make_jpeg, monkeypatch):
    pytest.importorskip("av")
    video = make_video(str(tmp_path / "v.mp4"))
    monkeypatch.setattr(media, "transcribe", lambda path, model: "Mets deux œufs et du sucre")
    sent = {}

    def fake_structure(key, caption, transcript, images, author):
        sent.update(key=key, transcript=transcript, n_images=len(images), author=author)
        return {"is_recipe": True, "title": "Crêpes", "category": "Dessert", "servings": "",
                "prep_time": "", "cook_time": "", "steps": ["Mélange."], "tips": "", "tags": [],
                "ingredients": [{"group": "", "items": ["2 œufs"]}]}
    monkeypatch.setattr(importer.ai, "structure", fake_structure)
    store = Store(str(tmp_path / "livre"))
    insta = FakeInsta(make_jpeg(), video, captions={"BBB": "Recette en vidéo 👆"})
    o = opts(claude_key="sk-test", transcribe=True, whisper_model="base")
    Importer(store, insta, o, print, threading.Event()).run([FakePost("BBB")])

    rec = store.get("BBB")
    assert rec["method"] == "claude" and rec["title"] == "Crêpes"
    assert rec["transcript"] == "Mets deux œufs et du sucre"
    assert rec["photos"] == ["BBB_1.jpg", "BBB_2.jpg"]
    assert sent["transcript"] == "Mets deux œufs et du sucre" and sent["author"] == "cheffe"
    assert sent["n_images"] == 2 + 6  # 2 photos + 6 images tirées de la vidéo
    assert "https://cdn/v.mp4" in insta.downloads


def test_claude_failure_falls_back_to_caption(monkeypatch):
    def boom(*a, **k):
        raise importer.ai.AIError("Crédit épuisé.")
    monkeypatch.setattr(importer.ai, "structure", boom)
    said = []
    fields = build_fields(CAPTION, "", [], "x", opts(claude_key="sk"), said.append)
    assert fields["method"] == "auto" and fields["title"] == "Gâteau au yaourt"
    assert "Crédit épuisé." in said[0]


def test_spoken_recipe_kept_without_claude():
    fields = build_fields("Regarde ça 😍", "Tu mets 200 grammes de farine puis au four",
                          [], "x", opts())
    assert fields["is_recipe"]


def test_video_frames(tmp_path):
    pytest.importorskip("av")
    frames = media.video_frames(make_video(str(tmp_path / "v.mp4")), count=4)
    assert len(frames) == 4 and all(f[:2] == b"\xff\xd8" for f in frames)
