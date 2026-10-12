"""Connexion à Instagram et lecture des posts enregistrés, avec Instaloader.

Les collections (« Recettes », « À tester »…) ne sont pas proposées par Instaloader :
on interroge directement l'API qu'utilise le site instagram.com (``_api``), avec les
cookies de la session, puis on transforme chaque réponse en ``Post`` d'Instaloader.
"""

import glob
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import urllib.parse

log = logging.getLogger("livrecuisine")

ALL_SAVED = "__tous__"
ALL_SAVED_LABEL = "Tous mes posts enregistrés"
API_TIMEOUT = 20
# Instaloader se présente comme Chrome sous Linux : sur un PC Windows, ça ressemble à un
# appareil inconnu. On prend l'identité du navigateur quand on l'a (copie cURL), sinon celle-ci.
DEFAULT_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36")


class InstaError(Exception):
    """Erreur à montrer telle quelle à l'utilisateur."""


class TwoFactorNeeded(Exception):
    pass


def shortcode_from_link(text):
    m = re.search(r"instagram\.com/(?:[\w.]+/)?(?:p|reel|reels|tv)/([\w-]{5,})", text or "")
    return m.group(1) if m else None


def friendly(exc):
    """Message en français pour une exception Instaloader."""
    import instaloader.exceptions as ie
    msg = str(exc)
    if isinstance(exc, InstaError):
        return msg
    if isinstance(exc, ie.BadCredentialsException):
        return "Mot de passe incorrect."
    if isinstance(exc, ie.TwoFactorAuthRequiredException):
        return "Instagram demande le code de vérification en deux étapes."
    if "checkpoint" in msg.lower() or "challenge" in msg.lower():
        return ("Instagram a refusé la connexion par sécurité (il ne reconnaît pas le logiciel "
                "comme ton navigateur). Ouvre instagram.com dans ton navigateur : si une "
                "vérification s'affiche, fais-la. Puis reconnecte le logiciel avec « Copier la "
                "connexion du navigateur… », en suivant la méthode « Copier en tant que cURL ».")
    if isinstance(exc, ie.TooManyRequestsException) or "429" in msg:
        return ("Instagram trouve qu'on va trop vite (erreur 429). Attends une heure, puis "
                "relance : les recettes déjà importées sont gardées.")
    if isinstance(exc, ie.LoginRequiredException) or "login_required" in msg:
        return "La connexion à Instagram a expiré. Reconnecte-toi dans l'onglet Importer."
    if isinstance(exc, ie.LoginException):
        if '"fail" status' in msg:
            return ("Instagram refuse la connexion par mot de passe depuis ce logiciel (ça arrive "
                    "souvent). Utilise plutôt « Copier la connexion du navigateur… » : "
                    "connecte-toi à instagram.com dans ton navigateur et suis les étapes.")
        return f"Connexion refusée par Instagram : {msg}"
    if isinstance(exc, ie.QueryReturnedNotFoundException):
        return "Post introuvable (supprimé ou compte privé)."
    if isinstance(exc, ie.ConnectionException):
        return f"Problème de connexion avec Instagram : {msg}"
    return f"{type(exc).__name__} : {msg}"


class Insta:
    def __init__(self, session_dir):
        import instaloader
        self.session_dir = session_dir
        self.L = instaloader.Instaloader(
            quiet=True, download_pictures=False, download_videos=False,
            download_video_thumbnails=False, download_geotags=False, download_comments=False,
            save_metadata=False, compress_json=False, max_connection_attempts=3,
            request_timeout=60.0, iphone_support=True, user_agent=DEFAULT_USER_AGENT)
        self.pending_user = None

    # ------------------------------------------------------------- connexion
    @property
    def username(self):
        return self.L.context.username

    def session_file(self, user):
        return os.path.join(self.session_dir, f"session-{user.lower()}")

    def _after_login(self):
        cookies = self.L.context._session.cookies.get_dict()
        if cookies.get("ds_user_id"):
            # Instaloader ne remet l'identifiant qu'après un vrai login, pas après un
            # chargement de session ; l'API de l'appli en a besoin.
            self.L.context.user_id = cookies["ds_user_id"]
        os.makedirs(self.session_dir, exist_ok=True)
        self.L.save_session_to_file(self.session_file(self.L.context.username))

    def resume(self, user):
        """Recharge la session enregistrée. Renvoie False s'il n'y en a pas."""
        path = self.session_file(user)
        if not user or not os.path.isfile(path):
            return False
        self.L.load_session_from_file(user, path)
        uid = self.L.context._session.cookies.get_dict().get("ds_user_id")
        if uid:
            self.L.context.user_id = uid
        try:
            with open(self._ua_file(user), encoding="utf-8") as fh:
                self._set_user_agent(fh.read().strip())
        except OSError:
            pass
        return True

    def _ua_file(self, user):
        return os.path.join(self.session_dir, f"navigateur-{user.lower()}.txt")

    def _set_user_agent(self, ua):
        if ua:
            self.L.context.user_agent = ua
            self.L.context._session.headers["User-Agent"] = ua

    def login(self, user, password):
        import instaloader.exceptions as ie
        user = user.strip().lstrip("@")
        try:
            self.L.login(user, password)
        except ie.TwoFactorAuthRequiredException:
            self.pending_user = user
            raise TwoFactorNeeded()
        self._after_login()

    def two_factor(self, code):
        self.L.two_factor_login(re.sub(r"\D", "", code))
        self._after_login()

    def login_with_cookies(self, cookies, user_agent=None):
        """Session à partir des cookies d'un navigateur (au moins « sessionid »).

        user_agent : identité du navigateur d'où viennent les cookies, si on la connaît."""
        data = {k.strip(): v.strip() for k, v in cookies.items() if k.strip() and v}
        if data.get("sessionid"):
            data["sessionid"] = cookie_value(data["sessionid"])
        sid = data.get("sessionid", "")
        if not sid:
            raise InstaError("Cookie « sessionid » introuvable.")
        data.setdefault("csrftoken", "")
        if not data.get("ds_user_id"):
            data["ds_user_id"] = urllib.parse.unquote(sid).split(":", 1)[0]
        self.L.context.load_session("?", data)
        self.L.context.user_id = data["ds_user_id"]
        self._set_user_agent(user_agent)
        try:
            user = self.current_user()
        except Exception as exc:
            log.warning("Nom du compte illisible (%s), on essaie les collections", exc)
            self.collections()  # lève l'erreur si le cookie ne marche vraiment pas
            user = data["ds_user_id"]
        if not user:
            raise InstaError("Ce cookie ne donne pas accès à un compte Instagram connecté.")
        self.L.context.username = user
        self._after_login()
        if user_agent:
            with open(self._ua_file(user), "w", encoding="utf-8") as fh:
                fh.write(user_agent)
        return user

    def login_with_firefox(self):
        return self.login_with_cookies(firefox_cookies())

    def logout(self):
        if self.username:
            for path in (self.session_file(self.username), self._ua_file(self.username)):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self.L.context.username = None
        self.L.context.user_id = None

    def _api(self, path, params=None):
        """Une requête à l'API utilisée par le site instagram.com, avec les cookies de la session.

        Volontairement sans les nouvelles tentatives ni les longues pauses d'Instaloader :
        une réponse en 20 secondes au plus, ou une erreur claire.
        """
        import instaloader.exceptions as ie
        import requests
        sess = self.L.context._session
        url = f"https://www.instagram.com/{path}"
        headers = {"X-IG-WWW-Claim": "0", "Referer": "https://www.instagram.com/",
                   "Accept": "*/*", "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                   "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors",
                   "Sec-Fetch-Dest": "empty"}
        try:
            resp = sess.get(url, params=dict(params or {}), headers=headers, timeout=API_TIMEOUT,
                            allow_redirects=False)
        except requests.exceptions.Timeout:
            raise ie.ConnectionException(f"Instagram ne répond pas ({path}).")
        except requests.exceptions.RequestException as exc:
            raise ie.ConnectionException(f"Pas de connexion à Instagram ({exc}).")
        body = resp.text[:300].replace("\n", " ")
        log.info("Instagram %s -> %s", path, resp.status_code)
        if resp.is_redirect:
            where = resp.headers.get("location", "")
            if "challenge" in where or "checkpoint" in where or "auth_platform" in where:
                raise ie.LoginException(f"Checkpoint required ({where})")
            raise ie.LoginRequiredException(f"login_required : redirection vers {where}")
        if resp.status_code == 429:
            raise ie.TooManyRequestsException(f"429 Too Many Requests ({path})")
        if resp.status_code in (401, 403):
            raise ie.LoginRequiredException(f"login_required : {resp.status_code} {body}")
        if resp.status_code == 404:
            raise ie.QueryReturnedNotFoundException(f"404 ({path})")
        try:
            data = resp.json()
        except ValueError:
            raise ie.ConnectionException(f"Réponse inattendue d'Instagram ({resp.status_code}) : "
                                         f"{body}")
        message = str(data.get("message", "")) if isinstance(data, dict) else ""
        if any(w in message for w in ("checkpoint", "challenge", "feedback_required")):
            raise ie.LoginException(f"Checkpoint required : {message}")
        if "login_required" in message:
            raise ie.LoginRequiredException("login_required")
        if resp.status_code != 200 or (isinstance(data, dict) and data.get("status") == "fail"):
            raise ie.ConnectionException(f"{resp.status_code} {message or body} ({path})")
        return data

    def current_user(self):
        """Nom du compte connecté."""
        uid = self.L.context.user_id
        tries = [("api/v1/accounts/edit/web_form_data/", {},
                  lambda d: d["form_data"]["username"])]
        if uid:
            tries.insert(0, (f"api/v1/users/{uid}/info/", {}, lambda d: d["user"]["username"]))
        error = None
        for path, params, pick in tries:
            try:
                name = pick(self._api(path, params))
                if name:
                    return name
            except (KeyError, TypeError) as exc:
                error = error or exc
            except Exception as exc:
                error = exc
        if error:
            raise error
        return None

    # ------------------------------------------------------------- collections
    def _pages(self, path, params=None):
        params = dict(params or {})
        while True:
            data = self._api(path, params)
            yield data
            nxt = data.get("next_max_id")
            if not data.get("more_available") or not nxt:
                return
            params["max_id"] = nxt

    def collections(self):
        """[(id, nom, nombre de posts ou None)], « Tous mes posts enregistrés » en premier."""
        out = [(ALL_SAVED, ALL_SAVED_LABEL, None)]
        params = {"collection_types": '["ALL_MEDIA_AUTO_COLLECTION","MEDIA"]',
                  "include_public_only": "0", "get_cover_media_lists": "false"}
        for page in self._pages("api/v1/collections/list/", params):
            for c in page.get("items", []):
                if c.get("collection_type") == "ALL_MEDIA_AUTO_COLLECTION":
                    continue
                cid = str(c.get("collection_id") or c.get("collection_pk") or "")
                if cid:
                    out.append((cid, c.get("collection_name") or "?",
                                c.get("collection_media_count")))
        return out

    def iter_posts(self, collection_id):
        """Posts d'une collection, du plus récemment enregistré au plus ancien."""
        from instaloader import Post
        if collection_id == ALL_SAVED:
            path = "api/v1/feed/saved/posts/"
        else:
            path = f"api/v1/feed/collection/{collection_id}/posts/"
        for page in self._pages(path):
            for item in page.get("items", []):
                media = _normalize(item.get("media", item))
                try:
                    yield Post.from_iphone_struct(self.L.context, media)
                except (KeyError, TypeError) as exc:
                    log.warning("Post ignoré (format inattendu %s) : %s", exc, media.get("code"))

    def post_from_link(self, link):
        from instaloader import Post
        code = shortcode_from_link(link)
        if not code:
            raise InstaError(f"Lien non reconnu : {link}")
        try:
            data = self._api(f"api/v1/media/{Post.shortcode_to_mediaid(code)}/info/")
            return Post.from_iphone_struct(self.L.context, _normalize(data["items"][0]))
        except (KeyError, IndexError, TypeError) as exc:
            log.warning("Lien %s lu autrement (%s)", code, exc)
            return Post.from_shortcode(self.L.context, code)

    # ------------------------------------------------------------- contenu
    @staticmethod
    def post_info(post):
        """Texte et médias d'un post, sous forme de dict simple."""
        media = []
        try:
            if post.typename == "GraphSidecar":
                for node in post.get_sidecar_nodes():
                    media.append({"video": node.is_video, "image_url": node.display_url,
                                  "video_url": node.video_url})
            else:
                media.append({"video": post.is_video, "image_url": post.url,
                              "video_url": post.video_url if post.is_video else None})
        except Exception as exc:  # un média manquant ne doit pas faire perdre la recette
            log.warning("Médias illisibles pour %s : %s", post.shortcode, exc)
        try:
            author = post.owner_username
        except Exception:
            author = ""
        try:
            posted = post.date_utc.strftime("%Y-%m-%d")
        except Exception:
            posted = ""
        return {
            "shortcode": post.shortcode,
            "url": f"https://www.instagram.com/p/{post.shortcode}/",
            "author": author,
            "posted": posted,
            "caption": post.caption or "",
            "media": [m for m in media if m.get("image_url") or m.get("video_url")],
        }

    def download(self, url, path):
        resp = self.L.context.get_raw(url)
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            shutil.copyfileobj(resp.raw, fh)
        os.replace(tmp, path)
        return path


def cookie_value(value):
    """Valeur de cookie telle que le navigateur l'envoie (« 123%3Aabc », pas « 123:abc »)."""
    value = (value or "").strip().strip('"').strip()
    return urllib.parse.quote(urllib.parse.unquote(value), safe="")


def parse_cookie_text(text):
    """Accepte la seule valeur de « sessionid », ou une ligne « a=b; sessionid=c; … »."""
    return parse_browser_copy(text)[0]


def parse_browser_copy(text):
    """Ce que l'utilisateur a copié dans son navigateur -> (cookies, user-agent ou None).

    Accepte « Copier en tant que cURL » (bash ou cmd), « Copier les en-têtes de la requête »,
    une ligne de cookies « a=b; sessionid=c », ou la seule valeur de sessionid.
    """
    text = (text or "").strip()
    if '^"' in text:  # cURL (cmd) : ^ sert de caractère d'échappement
        text = re.sub(r"\^(.)", r"\1", text).replace('\\"', '"')
    ua = None
    m = re.search(r"user-agent:\s*([^'\"\r\n]+)", text, re.I)
    if m:
        ua = m.group(1).strip()
    line = None
    m = re.search(r"(?:^|\s)(?:-b|--cookie)\s+(['\"])(.*?)\1", text, re.S)
    if m:
        line = m.group(2)
    else:
        m = re.search(r"(?:^|['\"\s])cookie:\s*([^'\"\r\n]+)", text, re.I)
        if m:
            line = m.group(1)
        elif "sessionid=" in text:
            line = text
    if line is None:
        return {"sessionid": text.strip().strip("'\"")}, ua
    cookies = {}
    for part in line.split(";"):
        if "=" in part:
            name, value = part.split("=", 1)
            cookies[name.strip()] = value.strip()
    return cookies, ua


def _normalize(media):
    """Complète les champs qu'Instaloader exige mais dont on n'a pas besoin."""
    media = dict(media)
    media.setdefault("has_liked", False)
    media.setdefault("like_count", 0)
    media.setdefault("taken_at", 0)
    if isinstance(media.get("user"), dict):
        user = {"pk": 0, "username": "", "is_private": False, "full_name": "",
                "profile_pic_url": ""}
        user.update({k: v for k, v in media["user"].items() if v is not None})
        media["user"] = user
    return media


def firefox_profiles():
    roots = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(os.path.join(appdata, "Mozilla", "Firefox", "Profiles"))
    home = os.path.expanduser("~")
    roots += [os.path.join(home, ".mozilla", "firefox"),
              os.path.join(home, "Library", "Application Support", "Firefox", "Profiles")]
    found = []
    for root in roots:
        found += glob.glob(os.path.join(root, "*", "cookies.sqlite"))
    found.sort(key=os.path.getmtime, reverse=True)
    return found


def firefox_cookies():
    """Cookies instagram.com du profil Firefox utilisé le plus récemment."""
    for db in firefox_profiles():
        tmpdir = tempfile.mkdtemp()
        try:
            copy = os.path.join(tmpdir, "cookies.sqlite")
            shutil.copy2(db, copy)  # Firefox verrouille le fichier quand il est ouvert
            for ext in ("-wal", "-shm"):
                if os.path.exists(db + ext):
                    shutil.copy2(db + ext, copy + ext)
            con = sqlite3.connect(copy)
            try:
                rows = con.execute("SELECT name, value FROM moz_cookies "
                                   "WHERE host LIKE '%instagram.com'").fetchall()
            finally:
                con.close()
        except (OSError, sqlite3.Error) as exc:
            log.warning("Cookies Firefox illisibles (%s) : %s", db, exc)
            continue
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        cookies = dict(rows)
        if cookies.get("sessionid"):
            return cookies
    raise InstaError("Aucune connexion Instagram trouvée dans Firefox. Ouvre instagram.com "
                     "dans Firefox, connecte-toi, puis réessaie.")
