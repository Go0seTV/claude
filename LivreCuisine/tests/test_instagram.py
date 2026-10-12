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
    assert "sécurité" in instagram.friendly(ie.LoginException("Checkpoint required. Point..."))
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
    assert "sécurité" in instagram.friendly(ie.LoginException("Checkpoint required (x)"))


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
    assert "connexion du navigateur" in msg


CURL_BASH = """curl 'https://www.instagram.com/' \\
  -H 'accept: text/html,application/xhtml+xml' \\
  -H 'accept-language: fr-FR,fr;q=0.9' \\
  -b 'csrftoken=TOK; ds_user_id=123456; sessionid=123456%3Aabc%3A9; mid=MID; rur="CCO\\0541\\0542"' \\
  -H 'user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0.0.0 Safari/537.36'"""

CURL_CMD = ('curl ^"https://www.instagram.com/^" ^\n'
            '  -H ^"accept: text/html^" ^\n'
            '  -b ^"csrftoken=TOK; ds_user_id=123456; sessionid=123456^%^3Aabc^%^3A9^" ^\n'
            '  -H ^"user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/141.0^"')


def test_parse_browser_copy_formats():
    cookies, ua = instagram.parse_browser_copy(CURL_BASH)
    assert cookies["sessionid"] == "123456%3Aabc%3A9" and cookies["mid"] == "MID"
    assert cookies["csrftoken"] == "TOK"
    assert ua.startswith("Mozilla/5.0 (Windows NT 10.0") and ua.endswith("Safari/537.36")
    cookies, ua = instagram.parse_browser_copy(CURL_CMD)
    assert cookies == {"csrftoken": "TOK", "ds_user_id": "123456", "sessionid": "123456%3Aabc%3A9"}
    assert ua.endswith("Edg/141.0")
    cookies, ua = instagram.parse_browser_copy("cookie: a=1; sessionid=9%3Ax\nuser-agent: UA 1")
    assert cookies == {"a": "1", "sessionid": "9%3Ax"} and ua == "UA 1"
    assert instagram.parse_browser_copy("'123%3Aabc'") == ({"sessionid": "123%3Aabc"}, None)


def test_curl_login_sends_all_cookies_and_browser_identity(insta, tmp_path, monkeypatch):
    sent = []
    real_get = requests.Session.get

    def spy(self, url, params=None, **kw):
        sent.append((dict(self.cookies.get_dict()), self.headers.get("User-Agent"),
                     self.headers.get("X-CSRFToken")))
        return real_get(self, url, params=params, **kw)
    monkeypatch.setattr(requests.Session, "get", spy)

    cookies, ua = instagram.parse_browser_copy(CURL_BASH)
    assert insta.login_with_cookies(cookies, ua) == "moi"
    jar, agent, csrf = sent[0]
    assert jar["mid"] == "MID" and jar["sessionid"] == "123456%3Aabc%3A9"
    assert agent == ua and csrf == "TOK"

    again = Insta(str(tmp_path / "session"))
    assert again.resume("moi")
    assert again.L.context._session.headers["User-Agent"] == ua  # identité gardée
    again.logout()
    assert not (tmp_path / "session" / "navigateur-moi.txt").exists()


def test_default_identity_is_windows():
    assert "Windows" in instagram.DEFAULT_USER_AGENT


@pytest.fixture(autouse=True)
def no_page_pause(monkeypatch):
    monkeypatch.setattr(instagram, "PAGE_PAUSE", 0)


def saved_feed_handler(with_ids=True):
    """Comme Instagram aujourd'hui : plus de liste des collections ni de lecture directe."""
    pages = [
        [("R1", ["555"]), ("X1", ["999"]), ("R2", ["555", "999"])],
        [("X2", []), ("R3", [555])],
    ]

    def handler(path, params):
        if path in ("api/v1/collections/list/", "api/v1/feed/collection/555/posts/"):
            return FakeResp(404, {"status": "fail", "message": "Dead endpoint"})
        if path == "api/v1/feed/saved/posts/":
            n = 1 if params.get("max_id") == "p2" else 0
            items = []
            for code, ids in pages[n]:
                m = media(code)
                if with_ids:
                    m["saved_collection_ids"] = ids
                items.append({"media": m})
            return {"items": items, "more_available": n == 0, "next_max_id": "p2" if n == 0 else None}
        raise AssertionError(path)
    return handler


def test_collections_rebuilt_from_saved_posts(tmp_path, monkeypatch):
    ins = Insta(str(tmp_path))
    install_fake_web(monkeypatch, saved_feed_handler())
    assert ins.collections() == [(ALL_SAVED, "Tous mes posts enregistrés", None),
                                 ("555", "Collection 1 (nom inconnu)", None),
                                 ("999", "Collection 2 (nom inconnu)", None)]


def test_collection_posts_filtered_from_saved_posts(tmp_path, monkeypatch):
    ins = Insta(str(tmp_path))
    said = []
    ins.notify = said.append
    install_fake_web(monkeypatch, saved_feed_handler())
    assert [p.shortcode for p in ins.iter_posts("555")] == ["R1", "R2", "R3"]
    assert "parcours tous tes posts" in said[0]
    assert "5 posts enregistrés parcourus, 3 dans ta collection." in said[-1]
    assert [p.shortcode for p in ins.iter_posts(ALL_SAVED)] == ["R1", "X1", "R2", "X2", "R3"]


def test_collection_filter_without_ids_says_what_to_do(tmp_path, monkeypatch):
    ins = Insta(str(tmp_path))
    install_fake_web(monkeypatch, saved_feed_handler(with_ids=False))
    with pytest.raises(InstaError, match="Tous mes posts"):
        list(ins.iter_posts("555"))


def test_collection_from_link():
    assert instagram.collection_from_link(
        "https://www.instagram.com/go0se/saved/recettes-faciles/17912345678901234/") == (
        "17912345678901234", "Recettes faciles")
    assert instagram.collection_from_link(
        "https://www.instagram.com/go0se/saved/r%C3%A9gal/1791/?hl=fr") == ("1791", "Régal")
    assert instagram.collection_from_link("https://www.instagram.com/go0se/saved/all-posts/") == (
        ALL_SAVED, "Tous mes posts enregistrés")
    assert instagram.collection_from_link("https://www.instagram.com/p/ABC/") is None


def test_friendly_404_is_not_always_a_post():
    import instaloader.exceptions as ie
    assert "404" in instagram.friendly(ie.QueryReturnedNotFoundException("404 (api/v1/collections/list/)"))
    assert "Post" in instagram.friendly(ie.QueryReturnedNotFoundException("404 (api/v1/media/1/info/)"))
