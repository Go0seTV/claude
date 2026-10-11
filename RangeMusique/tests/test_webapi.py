import pytest

from rangemusique.cache import MemoryCache
from rangemusique.webapi import NetworkError, WebAPI


class Scripted(WebAPI):
    def __init__(self, responses):
        super().__init__(MemoryCache(), "key")
        self.responses = list(responses)
        self.urls = []

    def _request(self, url, data=None, rate=None, retries=4, binary=False):
        self.urls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_acoustid_parsing_and_cache():
    api = Scripted([{"status": "ok", "results": [
        {"id": "a", "score": 0.95, "recordings": [{"id": "rec1"}, {"id": "rec2"}]},
        {"id": "b", "score": 0.4}]}])
    assert api.acoustid_lookup(200.4, "FP") == [(0.95, ["rec1", "rec2"])]
    assert api.acoustid_lookup(200.4, "FP") == [[0.95, ["rec1", "rec2"]]]  # cache
    assert len(api.urls) == 1


def test_acoustid_bad_key():
    api = Scripted([{"status": "error", "error": {"code": 4, "message": "invalid API key"}}])
    with pytest.raises(NetworkError):
        api.acoustid_lookup(10, "FP")


def test_musicbrainz_error_is_not_cached():
    api = Scripted([{"error": "rate limited"}, {"releases": [{"id": "r"}]}])
    with pytest.raises(NetworkError):
        api.mb_releases_of_recording("rec")
    assert api.mb_releases_of_recording("rec") == [{"id": "r"}]
    assert api.mb_releases_of_recording("rec") == [{"id": "r"}]
    assert len(api.urls) == 2


def test_offline_breaker():
    api = WebAPI(MemoryCache(), "k")
    api._do_request = lambda *a: (_ for _ in ()).throw(NetworkError("down"))
    for _ in range(5):
        with pytest.raises(NetworkError):
            api.mb_search("x")
    assert api.offline
