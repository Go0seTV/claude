"""Connexion à Instagram et lecture des posts enregistrés, avec Instaloader.

Les collections (« Recettes », « À tester »…) ne sont pas proposées par Instaloader :
on interroge directement l'API de l'appli Instagram via
``context.get_iphone_json``, puis on transforme chaque réponse en ``Post``.
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
        return ("Instagram veut vérifier que c'est bien toi. Ouvre Instagram sur ton téléphone ou "
                "dans ton navigateur et confirme « C'était moi », puis réessaie. Si ça bloque "
                "encore, utilise « Utiliser ma connexion Firefox » ou « Coller un cookie ».")
    if isinstance(exc, ie.TooManyRequestsException) or "429" in msg:
        return ("Instagram trouve qu'on va trop vite (erreur 429). Attends une heure, puis "
                "relance : les recettes déjà importées sont gardées.")
    if isinstance(exc, ie.LoginRequiredException) or "login_required" in msg:
        return "La connexion à Instagram a expiré. Reconnecte-toi dans l'onglet Importer."
    if isinstance(exc, ie.LoginException):
        if '"fail" status' in msg:
            return ("Instagram refuse la connexion par mot de passe depuis ce logiciel (ça arrive "
                    "souvent). Utilise plutôt « Coller un cookie sessionid… » : connecte-toi à "
                    "instagram.com dans ton navigateur et suis les étapes affichées.")
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
            request_timeout=60.0, iphone_support=True)
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
        return True

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

    def login_with_cookies(self, cookies):
        """Session à partir des cookies d'un navigateur (au moins « sessionid »)."""
        data = {k: cookie_value(v) for k, v in cookies.items() if v}
        sid = data.get("sessionid", "")
        if not sid:
            raise InstaError("Cookie « sessionid » introuvable.")
        data.setdefault("csrftoken", "")
        if not data.get("ds_user_id"):
            data["ds_user_id"] = urllib.parse.unquote(sid).split(":", 1)[0]
        self.L.context.load_session("?", data)
        self.L.context.user_id = data["ds_user_id"]
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
        return user

    def login_with_firefox(self):
        return self.login_with_cookies(firefox_cookies())

    def logout(self):
        if self.username:
            try:
                os.remove(self.session_file(self.username))
            except OSError:
                pass
        self.L.context.username = None
        self.L.context.user_id = None

    def _api(self, path, params=None):
        """Requête à l'API d'Instagram, comme le site web, puis comme l'appli si ça échoue."""
        import instaloader.exceptions as ie
        params = dict(params or {})
        try:
            return self.L.context.get_json(path, params)
        except (ie.TooManyRequestsException, ie.LoginRequiredException,
                ie.QueryReturnedNotFoundException):
            raise
        except ie.InstaloaderException as web_exc:
            log.warning("API web %s : %s ; essai par l'API de l'appli", path, web_exc)
            try:
                return self.L.context.get_iphone_json(path, params)
            except ie.InstaloaderException as app_exc:
                log.warning("API appli %s : %s", path, app_exc)
                raise web_exc

    def current_user(self):
        """Nom du compte connecté."""
        uid = self.L.context.user_id
        tries = [("api/v1/accounts/edit/web_form_data/", {},
                  lambda d: d["form_data"]["username"]),
                 ("api/v1/accounts/current_user/", {"edit": "true"},
                  lambda d: d["user"]["username"])]
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
    text = (text or "").strip()
    if text.lower().startswith("cookie:"):
        text = text[7:]
    if "sessionid=" not in text:
        return {"sessionid": text}
    cookies = {}
    for part in text.split(";"):
        if "=" in part:
            name, value = part.split("=", 1)
            cookies[name.strip()] = value.strip()
    return cookies


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
