"""Découpe une légende Instagram en recette, sans intelligence artificielle.

Sert quand aucune clé Claude n'est réglée, ou quand l'appel à Claude échoue.
Les légendes suivent souvent le même schéma : un titre, « Ingrédients : »,
une liste, « Préparation : », des étapes numérotées, puis des hashtags.
"""

import re
import unicodedata

CATEGORIES = (
    "Apéritif", "Entrée", "Plat", "Accompagnement", "Dessert", "Goûter",
    "Petit-déjeuner", "Boisson", "Sauce", "Pain et pâte", "Autre",
)

_CATEGORY_WORDS = [
    ("Boisson", r"cocktail|smoothie|jus |limonade|milkshake|latte|matcha|mocktail|sirop"),
    ("Petit-déjeuner", r"pancake|porridge|granola|overnight|petit[- ]d[ée]j|brunch|cr[êe]pe"),
    ("Sauce", r"\bsauce|vinaigrette|pesto|houmous|hummus|mayonnaise|\bdip\b|tartinade"),
    ("Pain et pâte", r"\bpain\b|brioche|focaccia|p[âa]te à pizza|p[âa]te bris[ée]e|naan|bagel"),
    ("Dessert", r"g[âa]teau|tarte au|tiramisu|mousse au|cookie|brownie|cheesecake|fondant|"
                r"crumble|flan|cr[èe]me br[ûu]l[ée]e|dessert|chocolat|panna cotta|glace|"
                r"muffin|madeleine|financier|cake"),
    ("Apéritif", r"ap[ée]ro|ap[ée]ritif|toast|tapas|feuillet[ée]s|bouch[ée]es|rillettes"),
    ("Entrée", r"\bentr[ée]e|velout[ée]|soupe|salade|gaspacho|carpaccio|tartare"),
    ("Accompagnement", r"pur[ée]e|gratin|frites|l[ée]gumes r[ôo]tis|riz |accompagnement"),
    ("Plat", r"poulet|b[œoe]uf|porc|saumon|poisson|crevette|p[âa]tes|lasagne|curry|risotto|"
             r"pasta|burger|pizza|quiche|tajine|wok|bowl|steak|canard|agneau|plat"),
]

UNIT = (r"(?:k?g|mg|cl|ml|dl|l|litres?|c\.?\s?à\s?[sc]\.?|cuill[eè]res?|cs|cc|càs|càc|"
        r"tasses?|verres?|pinc[ée]es?|sachets?|gousses?|tranches?|bottes?|poign[ée]es?|"
        r"bo[iî]tes?|pots?|filets?|feuilles?|brins?|morceaux?|cups?|tbsp|tsp|oz)")
_QTY = re.compile(r"^(?:\d+[\d.,/½¼¾ ]*|un|une|deux|trois|quatre|cinq|six|½|¼|¾)\s*"
                  r"(?:" + UNIT + r"\b|[a-zàâçéèêëîïôûùüÿœ])", re.I)
_ING_HEADER = re.compile(r"^(?:les\s+)?ingr[ée]dients?\b", re.I)
_STEP_HEADER = re.compile(
    r"^(?:la\s+)?(?:pr[ée]paration|[ée]tapes?|instructions?|m[ée]thode|recette\s*:|"
    r"d[ée]roul[ée]|r[ée]alisation|progression|comment faire)\b", re.I)
_END_HEADER = re.compile(r"^(?:astuces?|conseils?|tips?|notes?|à savoir|variantes?)\b", re.I)
_NUMBERED = re.compile(r"^(?:[ée]tape\s*)?(\d{1,2})\s*(?:[.)]|[-–:](?=\s))\s*"
                       r"([a-zà-öø-ÿœ].+)", re.I)
_BULLET = re.compile(r"^[-–—•·*▪▫◦●○►▶➤✓✔☑→>+]\s*")
_SERVINGS = re.compile(r"pour\s+(\d+(?:\s*(?:à|-)\s*\d+)?)\s*(personnes?|pers\.?|parts?|"
                       r"portions?|gourmands?|enfants?|adultes?|pi[èe]ces?|cookies?|"
                       r"muffins?|cr[êe]pes?|pancakes?)", re.I)
_PREP = re.compile(r"pr[ée]paration\s*:?\s*(\d+\s*(?:h|min|minutes?|heures?)(?:\s*\d+)?)", re.I)
_COOK = re.compile(r"cuisson\s*:?\s*(\d+\s*(?:h|min|minutes?|heures?)(?:\s*\d+)?)", re.I)
_RECIPE_WORD = re.compile(r"recette|ingr[ée]dient|cuisson|four|pr[ée]chauffe|m[ée]lange|"
                          r"ajoute|faire cuire|saupoudre|fouette|enfourne", re.I)


_KEEP = set("°℃℉€£$×½¼¾⅓⅔⅛%")
_INVISIBLE = "\ufe0f\u200d\u20e3"


def strip_symbols(text):
    """Retire les émojis et symboles décoratifs, garde lettres, chiffres, ponctuation et °."""
    text = re.sub("(\\d)\ufe0f?\u20e3", r"\1. ", text)  # 1️⃣ -> « 1. »
    out = []
    for ch in text:
        if ch not in _KEEP and (unicodedata.category(ch) in ("So", "Sk", "Cs", "Co")
                                or ch in _INVISIBLE):
            continue
        out.append(ch)
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def clean_caption(caption):
    """Légende sans hashtags ni mentions en fin de texte, lignes nettoyées."""
    lines = []
    for raw in (caption or "").splitlines():
        line = strip_symbols(raw)
        if re.fullmatch(r"[\s.·•_\-–—]*", line):
            line = ""
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        words = line.split()
        tags = sum(1 for w in words if w.startswith(("#", "@")))
        if words and tags / len(words) > 0.6:
            continue  # ligne de hashtags
        lines.append(re.sub(r"\s#\w+", "", line).strip())
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def hashtags(caption):
    seen = []
    for tag in re.findall(r"#(\w+)", caption or ""):
        t = tag.lower()
        if t not in seen:
            seen.append(t)
    return seen[:15]


def guess_category(title, text=""):
    """Devine la catégorie, d'abord avec le titre, puis avec tout le texte."""
    for chunk in (title, text):
        low = (chunk or "").lower()
        for name, pattern in _CATEGORY_WORDS:
            if re.search(pattern, low):
                return name
    return "Autre"


def _title_from(lines, author=""):
    for line in lines[:4]:
        t = line.strip(" :-–—!.")
        if not t or _ING_HEADER.match(t) or _STEP_HEADER.match(t) or _QTY.match(t):
            continue
        t = re.sub(r"^(?:recette\s*(?:du jour|facile)?\s*[:\-–]\s*)", "", t, flags=re.I)
        if len(t) > 70:
            cut = re.split(r"(?<=[a-zé])[.!?]\s|\s[-–—|]\s", t)
            t = cut[0] if len(cut[0]) >= 8 else t[:70]
            if len(t) > 70:
                t = t[:67].rsplit(" ", 1)[0] + "…"
        if len(t) >= 3:
            return t[0].upper() + t[1:]
    return f"Recette de @{author}" if author else "Recette sans titre"


def _is_group_title(line):
    return (line.endswith(":") and len(line) < 45 and not _QTY.match(line)
            and not _STEP_HEADER.match(line) and not _ING_HEADER.match(line))


def parse_caption(caption, author=""):
    """Transforme une légende en dict de recette (champs de store.empty_recipe)."""
    text = clean_caption(caption)
    lines = [ln for ln in text.splitlines()]
    nonempty = [ln for ln in lines if ln]
    groups = [{"group": "", "items": []}]
    steps, tips, intro = [], [], []
    section = None  # None, "ing", "steps", "tips"
    seen_header = False

    for line in nonempty:
        bare = _BULLET.sub("", line).strip()
        if _ING_HEADER.match(bare):
            section, seen_header = "ing", True
            rest = re.sub(r"^.*?ingr[ée]dients?\s*(?:\([^)]*\))?\s*:?\s*", "", bare, flags=re.I)
            if rest:
                groups[-1]["items"].append(rest)
            continue
        if _STEP_HEADER.match(bare) and not _PREP.match(bare):
            section, seen_header = "steps", True
            rest = re.sub(r"^[^:]*:\s*", "", bare) if ":" in bare else ""
            if rest:
                steps.append(rest)
            continue
        if _END_HEADER.match(bare):
            section = "tips"
            rest = re.sub(r"^[^:]*:\s*", "", bare) if ":" in bare else ""
            if rest:
                tips.append(rest)
            continue

        numbered = _NUMBERED.match(bare)
        if section == "ing":
            if _is_group_title(bare):
                if groups[-1]["items"] or groups[-1]["group"]:
                    groups.append({"group": bare.rstrip(" :"), "items": []})
                else:
                    groups[-1]["group"] = bare.rstrip(" :")
            elif numbered and not _QTY.match(bare) and len(bare) > 60:
                section = "steps"
                steps.append(numbered.group(2).strip())
            else:
                groups[-1]["items"].append(bare)
        elif section == "steps":
            steps.append(numbered.group(2).strip() if numbered else bare)
        elif section == "tips":
            tips.append(bare)
        else:
            # Pas encore de titre de section : on devine ligne par ligne.
            if numbered:
                steps.append(numbered.group(2).strip())
            elif _BULLET.match(line) or (_QTY.match(bare) and len(bare) < 60):
                groups[-1]["items"].append(bare)
            else:
                intro.append(bare)

    if not seen_header and not steps and len(intro) > 1:
        # Texte libre : chaque phrase après le titre devient une étape.
        steps = [ln for ln in intro[1:] if len(ln) > 25]
    groups = [g for g in groups if g["items"]]
    servings = _SERVINGS.search(text)
    prep = _PREP.search(text)
    cook = _COOK.search(text)
    n_ing = sum(len(g["items"]) for g in groups)
    quantities = sum(1 for ln in nonempty if _QTY.match(_BULLET.sub("", ln)))
    is_recipe = n_ing >= 2 or quantities >= 3 or (bool(_RECIPE_WORD.search(text)) and len(steps) >= 2)
    title = _title_from(nonempty, author)
    return {
        "title": title,
        "category": guess_category(title, text),
        "servings": " ".join(servings.groups()) if servings else "",
        "prep_time": prep.group(1) if prep else "",
        "cook_time": cook.group(1) if cook else "",
        "ingredients": groups,
        "steps": steps,
        "tips": "\n".join(tips),
        "tags": hashtags(caption),
        "is_recipe": bool(is_recipe),
    }
