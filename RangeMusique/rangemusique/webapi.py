"""Accès internet : empreinte (fpcalc), AcoustID, MusicBrainz, Cover Art Archive."""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

USER_AGENT = f"RangeMusique/{__version__} ( https://github.com/go0setv/claude )"
MB_ROOT = "https://musicbrainz.org/ws/2"
ACOUSTID_URL = "https://api.acoustid.org/v2/lookup"
CAA_ROOT = "https://coverartarchive.org"


class NetworkError(Exception):
    pass


class _RateLimiter:
    def __init__(self, interval):
        self.interval = interval
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            if now < self._next:
                time.sleep(self._next - now)
            self._next = time.monotonic() + self.interval


def fingerprint(fpcalc, path, timeout=120):
    """Calcule l'empreinte audio avec fpcalc. Renvoie (durée, empreinte)."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    out = subprocess.run(
        [fpcalc, path], capture_output=True, timeout=timeout, **kwargs
    )
    text = out.stdout.decode("utf-8", "replace")
    duration, fp = None, None
    for line in text.splitlines():
        if line.startswith("DURATION="):
            duration = float(line.split("=", 1)[1])
        elif line.startswith("FINGERPRINT="):
            fp = line.split("=", 1)[1].strip()
    if not fp or not duration:
        err = out.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(err or "fpcalc n'a pas pu lire le fichier")
    return duration, fp


class WebAPI:
    """Toutes les requêtes passent par le cache et respectent les limites
    (MusicBrainz : 1 requête/seconde, AcoustID : 3/seconde)."""

    def __init__(self, cache, acoustid_key="", cover_dir=None):
        self.cache = cache
        self.acoustid_key = acoustid_key
        self.cover_dir = cover_dir
        self._mb_rate = _RateLimiter(1.1)
        self._aid_rate = _RateLimiter(0.35)
        self._caa_rate = _RateLimiter(0.2)
        self._failures = 0
        self.offline = False

    # --- HTTP -----------------------------------------------------------------
    def _request(self, url, data=None, rate=None, retries=4, binary=False):
        if self.offline:
            raise NetworkError("pas de connexion internet (requêtes suspendues)")
        try:
            res = self._do_request(url, data, rate, retries, binary)
        except NetworkError:
            self._failures += 1
            if self._failures >= 5:
                self.offline = True
            raise
        self._failures = 0
        return res

    def _do_request(self, url, data, rate, retries, binary):
        last = None
        for attempt in range(retries):
            if rate:
                rate.wait()
            req = urllib.request.Request(url, data=data, headers={
                "User-Agent": USER_AGENT, "Accept": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read()
                    return body if binary else json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code == 400 and not binary:
                    try:
                        return json.loads(e.read().decode("utf-8"))
                    except ValueError:
                        pass
                last = e
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                last = e
                if attempt >= 1 and not isinstance(e, TimeoutError):
                    break  # pas de connexion : inutile d'insister
            time.sleep(2 ** attempt)
        raise NetworkError(f"{url.split('?')[0]} : {last}")

    # --- AcoustID ---------------------------------------------------------------
    def acoustid_lookup(self, duration, fp):
        """Renvoie [(score, [recording_id, ...]), ...]."""
        key = f"{int(duration)}:{fp}"
        cached = self.cache.get("acoustid", key)
        if cached is not None:
            return cached
        data = urllib.parse.urlencode({
            "client": self.acoustid_key, "meta": "recordingids",
            "duration": int(duration), "fingerprint": fp,
        }).encode("ascii")
        res = self._request(ACOUSTID_URL, data=data, rate=self._aid_rate)
        if not res or res.get("status") != "ok":
            msg = (res or {}).get("error", {}).get("message", "réponse invalide")
            raise NetworkError(f"AcoustID : {msg}")
        out = []
        for r in res.get("results", []):
            ids = [rec["id"] for rec in r.get("recordings", []) if rec.get("id")]
            if ids:
                out.append((float(r.get("score", 0)), ids))
        self.cache.put("acoustid", key, out)
        return out

    def check_acoustid_key(self):
        """True si la clé est acceptée par AcoustID."""
        data = urllib.parse.urlencode({
            "client": self.acoustid_key, "duration": 1, "fingerprint": "AQAAAA",
        }).encode("ascii")
        res = self._request(ACOUSTID_URL, data=data, retries=1) or {}
        msg = res.get("error", {}).get("message", "").lower()
        return "api key" not in msg and "client" not in msg

    # --- MusicBrainz ---------------------------------------------------------
    def _mb_json(self, url):
        res = self._request(url, rate=self._mb_rate)
        if res is None:  # 404 : n'existe pas (réponse définitive)
            return {}
        if "error" in res:
            raise NetworkError(f"MusicBrainz : {res['error']}")
        return res

    def mb_recording(self, rec_id):
        """Fiche d'un enregistrement (titre, artistes)."""
        cached = self.cache.get("mb_rec", rec_id)
        if cached is not None:
            return cached
        url = f"{MB_ROOT}/recording/{rec_id}?fmt=json&inc=artists"
        res = self._mb_json(url)
        self.cache.put("mb_rec", rec_id, res)
        return res

    def mb_releases_of_recording(self, rec_id, limit=100):
        """Tous les albums contenant cet enregistrement, avec les
        listes de pistes (pour connaître le numéro de piste)."""
        cached = self.cache.get("mb_rel", rec_id)
        if cached is not None:
            return cached
        url = f"{MB_ROOT}/release?" + urllib.parse.urlencode({
            "recording": rec_id, "limit": limit, "fmt": "json",
            "inc": "artist-credits+recordings+release-groups+media",
        })
        res = self._mb_json(url)
        releases = res.get("releases", [])
        self.cache.put("mb_rel", rec_id, releases)
        return releases

    def mb_search(self, title, artist="", album="", limit=15):
        def q(s):
            return '"' + s.replace("\\", " ").replace('"', " ") + '"'
        parts = [f"recording:{q(title)}"]
        if artist:
            parts.append(f"artist:{q(artist)}")
        if album:
            parts.append(f"release:{q(album)}")
        query = " AND ".join(parts)
        cached = self.cache.get("mb_search", query)
        if cached is not None:
            return cached
        url = f"{MB_ROOT}/recording/?" + urllib.parse.urlencode(
            {"query": query, "fmt": "json", "limit": limit}
        )
        res = self._mb_json(url)
        recs = res.get("recordings", [])
        self.cache.put("mb_search", query, recs)
        return recs

    # --- Pochettes ---------------------------------------------------------------
    def cover(self, release_id, release_group_id=""):
        """Image de la pochette (bytes) ou None."""
        if not release_id:
            return None
        path = os.path.join(self.cover_dir, release_id + ".img") if self.cover_dir else None
        if path and os.path.exists(path):
            with open(path, "rb") as fh:
                data = fh.read()
            return data or None
        data = None
        for kind, ident in (("release", release_id), ("release-group", release_group_id)):
            if not ident:
                continue
            data = self._request(f"{CAA_ROOT}/{kind}/{ident}/front-500",
                                 rate=self._caa_rate, binary=True, retries=2)
            if data:
                break
        if path:
            os.makedirs(self.cover_dir, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data or b"")
        return data
