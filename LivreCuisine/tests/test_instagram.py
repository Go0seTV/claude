import json
import sqlite3

import requests

import pytest

from livrecuisine import instagram
from livrecuisine.instagram import ALL_SAVED, Insta, InstaError, shortcode_from_link


def media(code, kind=1, caption="Tarte\\nIngrédients :\\n200 g de farine", user=None):
    m = {"code": code, "pk": hash(code) & 0xFFFF, "media_type": kind, "taken_at": 1760000000,
         "caption": {"text": caption}, "has_liked": False, "like_count": 3,
         "user": user or {"pk": 1, "username": "cheffe", "is_private": False,
                          "full_name": "La Cheffe", "profile_pic_url": "https://x/p.jpg"},
         "image_versions2": {"candidates": [{"url": f"https://cdn/{code}.jpg"}]}}
    if kind == 2:
        m["video_versions"] = [{"url": f"https://cdn/{code}.mp4"}]
        m["video_duration"] = 30.0
        m["view_count"] = 10
    if kind == 8:
        m["carousel_media"] = [
            {"media_type": 1, "image_versions2": {"candidates": [{"url": "https://cdn/c1.jpg"}]}},
            {"media_type": 2, "image_versions2": {"candidates": [{"url": "https://cdn/c2.jpg"}]},
             "video_versions": [{"url": "https://cdn/c2.mp4"}]},
        ]
    return m


class FakeResp:
    def __init__(self, status=200, data=None, location=None):
        self.status_code = status
        self._data = data
        self.headers = {"location": location} if location else {}
        self.is_redirect = bool(location)
        self.text = json.dumps(data) if data is not None else "<html>"

    def json(self):
        if self._data is None:
            raise ValueError("pas du JSON")
        return self._data


def install_fake_web(monkeypatch, handler):
    """handler(path, params) -> dict, ou FakeResp, ou lève une exception."""
    seen = []

    def get(self, url, params=None, **kw):
        assert url.startswith("https://www.instagram.com/")
        assert kw.get("timeout") == instagram.API_TIMEOUT
        seen.append(dict(self.cookies.get_dict()))
        out = handler(url[len("https://www.instagram.com/"):], dict(params or {}))
        return out if isinstance(out, FakeResp) else FakeResp(200, out)
    monkeypatch.setattr(requests.Session, "get", get)
    return seen


@pytest.fixture
def insta(tmp_path, monkeypatch):
    ins = Insta(str(tmp_path / "session"))
    calls = []

    def fake_json(path, params):
        calls.append((path, dict(params)))
        if path == "api/v1/collections/list/":
            return {"items": [
                {"collection_id": "1", "collection_name": "Tous", "collection_type":
                 "ALL_MEDIA_AUTO_COLLECTION"},
                {"collection_id": "17890", "collection_name": "Recettes",
                 "collection_media_count": 3, "collection_type": "MEDIA"}],
                "more_available": False}
        if path == "api/v1/feed/collection/17890/posts/":
            if "max_id" not in params:
                return {"items": [{"media": media("AAA")}, {"media": media("BBB", 2)}],
                        "more_available": True, "next_max_id": "page2"}
            return {"items": [{"media": media("CCC", 8, user={"pk": 2, "username": "bob"})},
                              {"media": {"code": "BAD", "media_type": 99, "pk": 1}}],
                    "more_available": False}
        if path == "api/v1/feed/saved/posts/":
            return {"items": [{"media": media("SSS")}], "more_available": False}
        if path == "api/v1/users/123456/info/":
            return {"user": {"username": "moi"}}
        raise AssertionError(path)

    install_fake_web(monkeypatch, fake_json)
    ins.calls = calls
    return ins


def test_collections(insta):
    assert insta.collections() == [(ALL_SAVED, "Tous mes posts enregistrés", None),
                                   ("17890", "Recettes", 3)]


def test_iter_posts_paginates_and_reads_media(insta):
    posts = list(insta.iter_posts("17890"))
    assert [p.shortcode for p in posts] == ["AAA", "BBB", "CCC"]  # BAD ignoré
    assert insta.calls[-1] == ("api/v1/feed/collection/17890/posts/", {"max_id": "page2"})

    a, b, c = (insta.post_info(p) for p in posts)
    assert a["author"] == "cheffe" and a["posted"] == "2025-10-09"
    assert a["caption"].startswith("Tarte")
    assert a["media"] == [{"video": False, "image_url": "https://cdn/AAA.jpg", "video_url": None}]
    assert b["media"][0]["video"] and b["media"][0]["video_url"] == "https://cdn/BBB.mp4"
    assert c["author"] == "bob"  # utilisateur incomplet complété
    assert [m["video"] for m in c["media"]] == [False, True]
    assert c["url"] == "https://www.instagram.com/p/CCC/"


def test_all_saved(insta):
    assert [p.shortcode for p in insta.iter_posts(ALL_SAVED)] == ["SSS"]


def test_shortcode_from_link():
    assert shortcode_from_link("https://www.instagram.com/p/C1a2B3c4D5e/?igsh=xx") == "C1a2B3c4D5e"
    assert shortcode_from_link("https://instagram.com/reel/DAbc_-123/") == "DAbc_-123"
    assert shortcode_from_link("https://www.instagram.com/cheffe/reel/DXyz12345/") == "DXyz12345"
    assert shortcode_from_link("https://example.com") is None


def test_login_with_cookie_saves_session(insta, tmp_path):
    user = insta.login_with_cookies({"sessionid": " 123456:abc:9\n"})  # décodé, à réencoder
    assert user == "moi"
    assert insta.L.context.user_id == "123456"
    assert insta.L.context._session.cookies.get_dict()["sessionid"] == "123456%3Aabc%3A9"
    assert (tmp_path / "session" / "session-moi").is_file()

    again = Insta(str(tmp_path / "session"))
    assert again.resume("moi")
    assert again.username == "moi" and again.L.context.user_id == "123456"
    assert not again.resume("personne")


def test_firefox_cookies(tmp_path, monkeypatch):
    db = tmp_path / "cookies.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE moz_cookies (name TEXT, value TEXT, host TEXT)")
    con.executemany("INSERT INTO moz_cookies VALUES (?, ?, ?)", [
        ("sessionid", "42%3Axyz", ".instagram.com"), ("csrftoken", "tok", ".instagram.com"),
        ("sessionid", "autre", ".example.com")])
    con.commit()
    con.close()
    monkeypatch.setattr(instagram, "firefox_profiles", lambda: [str(db)])
    assert instagram.firefox_cookies() == {"sessionid": "42%3Axyz", "csrftoken": "tok"}
    monkeypatch.setattr(instagram, "firefox_profiles", lambda: [])
    with pytest.raises(InstaError):
        instagram.firefox_cookies()


def test_friendly_messages():
    import instaloader.exceptions as ie
    assert "Mot de passe" in instagram.friendly(ie.BadCredentialsException("x"))
    assert "vérifier" in instagram.friendly(ie.LoginException("Checkpoint required. Point..."))
    assert "429" in instagram.friendly(ie.TooManyRequestsException("429 Too Many Requests"))


def test_parse_cookie_text():
    assert instagram.parse_cookie_text(" 123%3Aabc ") == {"sessionid": "123%3Aabc"}
    assert instagram.parse_cookie_text("cookie: csrftoken=t; sessionid=1%3Ax; ds_user_id=1") == {
        "csrftoken": "t", "sessionid": "1%3Ax", "ds_user_id": "1"}
    assert instagram.cookie_value('"1%3Ax"') == "1%3Ax"


def test_api_errors_are_quick_and_clear(tmp_path, monkeypatch):
    import instaloader.exceptions as ie
    ins = Insta(str(tmp_path))
    answers = {}
    install_fake_web(monkeypatch, lambda path, params: answers["r"])
    cases = [
        (FakeResp(429, {"status": "fail"}), ie.TooManyRequestsException),
        (FakeResp(302, location="https://www.instagram.com/accounts/login/"),
         ie.LoginRequiredException),
        (FakeResp(302, location="https://www.instagram.com/challenge/xyz/"), ie.LoginException),
        (FakeResp(400, {"message": "checkpoint_required", "status": "fail"}), ie.LoginException),
        (FakeResp(200, {"status": "fail", "message": "something went wrong"}),
         ie.ConnectionException),
        (FakeResp(200, None), ie.ConnectionException),
    ]
    for resp, exc in cases:
        answers["r"] = resp
        with pytest.raises(exc):
            ins.collections()
    assert "vérifier" in instagram.friendly(ie.LoginException("Checkpoint required (x)"))


def test_cookie_accepted_even_if_account_name_unreadable(tmp_path, monkeypatch):
    ins = Insta(str(tmp_path / "s"))

    def web(path, params):
        if path == "api/v1/collections/list/":
            return {"items": [], "more_available": False}
        return FakeResp(200, {"status": "fail", "message": "something went wrong"})
    install_fake_web(monkeypatch, web)
    assert ins.login_with_cookies({"sessionid": "777%3Az"}) == "777"


def test_password_login_refused_message():
    import instaloader.exceptions as ie
    msg = instagram.friendly(ie.LoginException('Login error: "fail" status, message "".'))
    assert "cookie" in msg
