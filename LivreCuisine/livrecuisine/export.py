"""Export en page web à imprimer (ou à enregistrer en PDF depuis le navigateur)."""

import base64
import datetime
import html
import os

from . import __version__

CSS = """
:root { --ink:#2b2522; --soft:#7a6f68; --line:#e8dfd6; --accent:#b4532a; --paper:#fffdf9; }
* { box-sizing: border-box; }
body { margin:0; background:var(--paper); color:var(--ink);
       font: 16px/1.55 Georgia, "Times New Roman", serif; }
main { max-width: 820px; margin: 0 auto; padding: 32px 20px 60px; }
h1.book { font-size: 2.4em; margin: 0 0 4px; }
.sub { color: var(--soft); margin: 0 0 28px; font-family: system-ui, sans-serif; font-size:.9em; }
nav ol { columns: 2; column-gap: 32px; padding-left: 1.4em; }
nav h2 { font-family: system-ui, sans-serif; font-size: 1em; text-transform: uppercase;
         letter-spacing: .08em; color: var(--accent); margin: 22px 0 6px; }
nav a { color: var(--ink); text-decoration: none; }
article { border-top: 1px solid var(--line); padding-top: 28px; margin-top: 36px; }
article h2 { font-size: 1.9em; margin: 0 0 6px; line-height: 1.2; }
.meta { font-family: system-ui, sans-serif; font-size: .88em; color: var(--soft); margin-bottom: 16px; }
.meta span + span::before { content: " · "; }
.photo { width: 100%; max-height: 420px; object-fit: cover; border-radius: 6px; margin: 6px 0 18px; }
.cols { display: grid; grid-template-columns: 1fr 1.6fr; gap: 28px; }
h3 { font-family: system-ui, sans-serif; font-size: .82em; text-transform: uppercase;
     letter-spacing: .1em; color: var(--accent); margin: 0 0 8px; }
h4 { font-size: 1em; margin: 14px 0 4px; font-style: italic; }
ul { padding-left: 1.1em; margin: 0; } li { margin: 3px 0; }
ol.steps { padding-left: 1.3em; margin: 0; } ol.steps li { margin: 0 0 10px; }
.tips, .notes { margin-top: 18px; padding: 12px 14px; background: #f6efe6; border-radius: 6px; }
.raw { white-space: pre-wrap; font-size: .9em; color: var(--soft); }
.src { font-family: system-ui, sans-serif; font-size: .8em; color: var(--soft); margin-top: 16px; }
.src a { color: var(--soft); }
@media (max-width: 640px) { .cols { grid-template-columns: 1fr; } nav ol { columns: 1; } }
@media print {
  body { background: #fff; font-size: 12pt; }
  main { max-width: none; padding: 0; }
  article { break-before: page; border: 0; margin: 0; padding: 0; }
  .photo { max-height: 9cm; }
  .src a { text-decoration: none; }
}
"""


def _e(text):
    return html.escape(text or "")


def _photo_tag(store, rec):
    for name in rec.get("photos", [])[:1]:
        path = store.photo_path(name)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                data = base64.b64encode(fh.read()).decode("ascii")
            return f'<img class="photo" alt="" src="data:image/jpeg;base64,{data}">'
    return ""


def recipe_html(store, rec, anchor):
    meta = [rec.get("category")]
    if rec.get("servings"):
        meta.append("Pour " + rec["servings"])
    if rec.get("prep_time"):
        meta.append("Préparation " + rec["prep_time"])
    if rec.get("cook_time"):
        meta.append("Cuisson " + rec["cook_time"])
    out = [f'<article id="{anchor}">', f"<h2>{_e(rec.get('title'))}</h2>",
           '<div class="meta">' + "".join(f"<span>{_e(m)}</span>" for m in meta if m) + "</div>",
           _photo_tag(store, rec)]
    ing = []
    for g in rec.get("ingredients", []):
        if g.get("group"):
            ing.append(f"<h4>{_e(g['group'])}</h4>")
        ing.append("<ul>" + "".join(f"<li>{_e(i)}</li>" for i in g.get("items", [])) + "</ul>")
    steps = "".join(f"<li>{_e(s)}</li>" for s in rec.get("steps", []))
    if ing or steps:
        out.append('<div class="cols">')
        out.append("<section><h3>Ingrédients</h3>" + ("".join(ing) or "<p>—</p>") + "</section>")
        out.append("<section><h3>Préparation</h3>"
                   + (f'<ol class="steps">{steps}</ol>' if steps else "<p>—</p>") + "</section>")
        out.append("</div>")
    else:
        raw = rec.get("transcript") or rec.get("caption")
        if raw:
            out.append(f'<h3>Texte du post</h3><p class="raw">{_e(raw)}</p>')
    if rec.get("tips"):
        out.append(f'<div class="tips"><h3>Astuces</h3>{_e(rec["tips"])}</div>')
    if rec.get("notes"):
        out.append(f'<div class="notes"><h3>Mes notes</h3>{_e(rec["notes"])}</div>')
    if rec.get("source_url"):
        who = f"@{rec['author']}" if rec.get("author") else "Instagram"
        out.append(f'<p class="src">Recette de {_e(who)} · '
                   f'<a href="{_e(rec["source_url"])}">{_e(rec["source_url"])}</a></p>')
    out.append("</article>")
    return "\n".join(out)


def export_html(store, recipes, path, title="Mon livre de cuisine"):
    recipes = list(recipes)
    by_cat = {}
    for i, r in enumerate(recipes):
        by_cat.setdefault(r.get("category") or "Autre", []).append((i, r))
    nav = []
    if len(recipes) > 1:
        nav.append("<nav>")
        for cat in sorted(by_cat):
            nav.append(f"<h2>{_e(cat)}</h2><ol>")
            nav += [f'<li><a href="#r{i}">{_e(r.get("title"))}</a></li>' for i, r in by_cat[cat]]
            nav.append("</ol>")
        nav.append("</nav>")
    ordered = [(i, r) for cat in sorted(by_cat) for i, r in by_cat[cat]] if len(recipes) > 1 \
        else list(enumerate(recipes))
    today = datetime.date.today().strftime("%d/%m/%Y")
    page = [
        "<!doctype html>", '<html lang="fr"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_e(title)}</title><style>{CSS}</style></head><body><main>",
        f'<h1 class="book">{_e(title)}</h1>',
        f'<p class="sub">{len(recipes)} recette(s) · {today} · Livre de cuisine {__version__}'
        " · Ctrl+P pour imprimer ou enregistrer en PDF</p>",
        *nav, *(recipe_html(store, r, f"r{i}") for i, r in ordered),
        "</main></body></html>",
    ]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(page))
    return path
