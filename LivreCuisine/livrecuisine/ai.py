"""Mise en forme des recettes par Claude (facultatif, avec ta clé API Anthropic).

Claude reçoit la légende, la transcription de la vidéo et quelques images
(photos du carrousel, images de la vidéo) et renvoie une recette bien rangée.
C'est ce qui permet de récupérer les recettes dites à l'oral ou écrites à l'écran.
"""

import base64
import json
import logging

from .parse import CATEGORIES

log = logging.getLogger("livrecuisine")

MODEL = "claude-opus-5-5"
MAX_IMAGES = 12

SCHEMA = {
    "type": "object",
    "properties": {
        "is_recipe": {"type": "boolean"},
        "title": {"type": "string"},
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "servings": {"type": "string"},
        "prep_time": {"type": "string"},
        "cook_time": {"type": "string"},
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "group": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["group", "items"],
                "additionalProperties": False,
            },
        },
        "steps": {"type": "array", "items": {"type": "string"}},
        "tips": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["is_recipe", "title", "category", "servings", "prep_time", "cook_time",
                 "ingredients", "steps", "tips", "tags"],
    "additionalProperties": False,
}

SYSTEM = """Tu ranges des recettes de cuisine trouvées sur Instagram dans un livre de cuisine personnel.

Tu reçois un post : sa légende, parfois la transcription de ce qui est dit dans la vidéo, \
et des images (photos du post, ou images tirées de la vidéo où la recette est souvent écrite à l'écran).

Rassemble toutes ces sources pour écrire la recette la plus complète possible, en français \
(traduis si le post est dans une autre langue) :
- title : un nom de plat court et clair, sans émoji ni hashtag.
- ingredients : un groupe par partie de la recette (« Pour la pâte », « Pour la sauce »…), \
avec group vide s'il n'y a qu'une liste. Une ligne par ingrédient, quantité d'abord \
(« 200 g de farine »).
- steps : une étape par élément, à l'impératif, sans numéro au début.
- servings, prep_time, cook_time : seulement s'ils sont indiqués ou évidents, sinon chaîne vide.
- tips : astuces, variantes ou conservation mentionnées ; vide sinon.
- tags : 3 à 6 mots-clés utiles pour chercher (ingrédient principal, type de cuisine, \
« végétarien », « rapide »…), en minuscules.

N'invente pas de quantités : si une quantité n'est donnée nulle part, écris l'ingrédient sans quantité. \
Si le post n'est pas une recette (paysage, publicité sans recette, simple photo de plat sans \
aucune indication), mets is_recipe à false et laisse les autres champs vides."""


class AIError(Exception):
    pass


def available():
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def _client(key):
    import anthropic
    return anthropic.Anthropic(api_key=key, max_retries=4, timeout=300)


def test_key(key):
    """Vérifie la clé sans rien dépenser. Renvoie un message d'erreur, ou None si c'est bon."""
    import anthropic
    try:
        _client(key).models.retrieve(MODEL)
        return None
    except anthropic.AuthenticationError:
        return "Clé refusée : vérifie que tu l'as copiée en entier."
    except anthropic.PermissionDeniedError:
        return "Cette clé n'a pas accès à ce modèle."
    except anthropic.APIConnectionError:
        return "Pas de connexion internet vers Anthropic."
    except anthropic.APIStatusError as exc:
        return f"Erreur Anthropic {exc.status_code} : {exc.message}"


def build_content(caption, transcript, images, author=""):
    content = []
    for data in images[:MAX_IMAGES]:
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg",
            "data": base64.standard_b64encode(data).decode("ascii")}})
    parts = []
    if author:
        parts.append(f"Compte : @{author}")
    parts.append("Légende du post :\n" + (caption.strip() or "(aucune légende)"))
    if transcript:
        parts.append("Transcription de la vidéo :\n" + transcript.strip())
    if images:
        parts.append(f"{len(images[:MAX_IMAGES])} image(s) du post ci-dessus.")
    content.append({"type": "text", "text": "\n\n".join(parts)})
    return content


def structure(key, caption, transcript="", images=(), author=""):
    """Renvoie un dict de recette (mêmes champs que parse.parse_caption)."""
    import anthropic
    try:
        resp = _client(key).beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user",
                       "content": build_content(caption, transcript, list(images), author)}],
        )
    except anthropic.AuthenticationError:
        raise AIError("Clé Claude refusée. Vérifie-la dans l'onglet Réglages.")
    except anthropic.RateLimitError:
        raise AIError("Trop de demandes à Claude en même temps, ou crédit épuisé.")
    except anthropic.BadRequestError as exc:
        if "credit" in str(exc.message).lower():
            raise AIError("Crédit Anthropic épuisé : recharge-le sur console.anthropic.com.")
        raise AIError(f"Demande refusée par Anthropic : {exc.message}")
    except anthropic.APIConnectionError:
        raise AIError("Pas de connexion internet vers Anthropic.")
    except anthropic.APIStatusError as exc:
        raise AIError(f"Erreur Anthropic {exc.status_code} : {exc.message}")

    if resp.stop_reason == "refusal":
        raise AIError("Claude n'a pas voulu traiter ce post.")
    if resp.stop_reason == "max_tokens":
        raise AIError("Réponse de Claude coupée (recette trop longue).")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError:
        raise AIError("Réponse de Claude illisible.")
    log.info("Claude : %s (%s jetons en entrée, %s en sortie)", data.get("title"),
             resp.usage.input_tokens, resp.usage.output_tokens)
    data["ingredients"] = [g for g in data.get("ingredients", []) if g.get("items")]
    data["tags"] = [t.lower().lstrip("#") for t in data.get("tags", []) if t.strip()]
    if data.get("category") not in CATEGORIES:
        data["category"] = "Autre"
    return data
