"""Fenêtre principale (Tkinter, inclus avec Python sous Windows)."""

import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__, ai, config, export, media
from .importer import Importer, Options, reformat
from .instagram import (ALL_SAVED, ALL_SAVED_LABEL, Insta, TwoFactorNeeded,
                        collection_from_link, friendly, parse_browser_copy)
from .parse import CATEGORIES
from .store import (Store, empty_recipe, ingredients_to_text, text_to_ingredients,
                    text_to_steps)

log = logging.getLogger("livrecuisine")

ACCENT = "#b4532a"
SHOW_CHOICES = {"Recettes": "recipes", "Pas des recettes": "others", "Tout": "all"}
ALL_CATEGORIES = "Toutes les catégories"
UI_FONT = "Segoe UI" if sys.platform == "win32" else "TkDefaultFont"
TITLE_FONT = "Georgia"


def open_path(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 (Windows uniquement)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = config.load()
        self.store = Store(config.data_dir(self.cfg))
        self.insta = None
        self.q = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.busy_buttons = []
        self.current_id = None
        self.photo_index = 0
        self._photo_ref = None
        self.collections = []

        root.title(f"Livre de cuisine {__version__}")
        root.geometry("1200x760")
        root.minsize(920, 580)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=26)
        style.configure("Big.TButton", padding=(12, 6))

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self._build_tab_book()
        self._build_tab_import()
        self._build_tab_settings()

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", padx=8, pady=8)
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill="x")
        self.status = tk.StringVar(value="Prêt.")
        ttk.Label(bottom, textvariable=self.status).pack(anchor="w", pady=(4, 0))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll)
        self.refresh_list()
        self._resume_session()
        if not self.store.all():
            self.nb.select(1)
            self.status.set("Ton livre est vide : connecte-toi à Instagram pour importer "
                            "tes recettes.")

    # ================================================================ onglet Livre
    def _build_tab_book(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab, text="  📖 Mes recettes  ")
        pane = ttk.PanedWindow(tab, orient="horizontal")
        pane.pack(fill="both", expand=True)

        left = ttk.Frame(pane, padding=(0, 0, 8, 0))
        pane.add(left, weight=1)
        self.search_var = tk.StringVar()
        row = ttk.Frame(left)
        row.pack(fill="x")
        ttk.Label(row, text="🔍").pack(side="left")
        ent = ttk.Entry(row, textvariable=self.search_var)
        ent.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.search_var.trace_add("write", lambda *a: self.refresh_list())

        row = ttk.Frame(left)
        row.pack(fill="x", pady=(6, 0))
        self.cat_var = tk.StringVar(value=ALL_CATEGORIES)
        self.cat_box = ttk.Combobox(row, textvariable=self.cat_var, state="readonly", width=20)
        self.cat_box.pack(side="left", fill="x", expand=True)
        self.cat_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())
        self.show_var = tk.StringVar(value="Recettes")
        box = ttk.Combobox(row, textvariable=self.show_var, state="readonly", width=15,
                           values=list(SHOW_CHOICES))
        box.pack(side="left", padx=(6, 0))
        box.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())
        self.fav_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(left, text="★ Seulement mes favoris", variable=self.fav_only,
                        command=self.refresh_list).pack(anchor="w", pady=6)

        frame = ttk.Frame(left)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=("title", "cat"), show="headings",
                                 selectmode="browse")
        self.tree.heading("title", text="Recette")
        self.tree.heading("cat", text="Catégorie")
        self.tree.column("title", width=260, stretch=True)
        self.tree.column("cat", width=110, stretch=False)
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        self.tree.bind("<Double-1>", lambda e: self.edit_recipe())

        self.count_var = tk.StringVar()
        ttk.Label(left, textvariable=self.count_var).pack(anchor="w", pady=(4, 0))
        row = ttk.Frame(left)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="+ Nouvelle recette", command=self.new_recipe).pack(side="left")
        ttk.Button(row, text="Supprimer", command=self.delete_recipe).pack(side="left", padx=4)
        ttk.Button(row, text="🖨 Exporter la liste", command=self.export_list).pack(side="right")

        right = ttk.Frame(pane)
        pane.add(right, weight=3)
        bar = ttk.Frame(right)
        bar.pack(fill="x")
        self.fav_btn = ttk.Button(bar, text="☆ Favori", command=self.toggle_favorite)
        self.fav_btn.pack(side="left")
        ttk.Button(bar, text="✏ Modifier", command=self.edit_recipe).pack(side="left", padx=4)
        ttk.Button(bar, text="Instagram", command=self.open_source).pack(side="left")
        self.ai_btn = ttk.Button(bar, text="✨ Mise en forme Claude",
                                 command=self.reformat_current)
        self.ai_btn.pack(side="left", padx=4)
        self.busy_buttons.append(self.ai_btn)
        ttk.Button(bar, text="🖨 Imprimer", command=self.export_current).pack(side="right")
        self.next_photo = ttk.Button(bar, text="▶", width=3, command=lambda: self._photo_step(1))
        self.prev_photo = ttk.Button(bar, text="◀", width=3, command=lambda: self._photo_step(-1))
        self.next_photo.pack(side="right", padx=(0, 8))
        self.prev_photo.pack(side="right")

        frame = ttk.Frame(right)
        frame.pack(fill="both", expand=True, pady=(6, 0))
        self.view = tk.Text(frame, wrap="word", relief="flat", padx=18, pady=14,
                            background="#fffdf9", foreground="#2b2522", cursor="arrow",
                            font=(UI_FONT, 11), spacing1=2, spacing3=2)
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.view.yview)
        self.view.configure(yscrollcommand=ys.set)
        self.view.pack(side="left", fill="both", expand=True)
        ys.pack(side="left", fill="y")
        v = self.view
        v.tag_configure("title", font=(TITLE_FONT, 22, "bold"), spacing3=4)
        v.tag_configure("meta", font=(UI_FONT, 10), foreground="#7a6f68", spacing3=10)
        v.tag_configure("h", font=(UI_FONT, 10, "bold"), foreground=ACCENT, spacing1=14,
                        spacing3=4)
        v.tag_configure("group", font=(UI_FONT, 11, "italic"), spacing1=6)
        v.tag_configure("item", lmargin1=8, lmargin2=24)
        v.tag_configure("step", lmargin1=8, lmargin2=30, spacing3=8)
        v.tag_configure("raw", font=(UI_FONT, 9), foreground="#7a6f68", lmargin1=4, lmargin2=4)
        v.tag_configure("center", justify="center")
        v.configure(state="disabled")

        notes = ttk.LabelFrame(right, text="Mes notes (modifications, avis, à refaire…)",
                               padding=6)
        notes.pack(fill="x", pady=(6, 0))
        self.notes = tk.Text(notes, height=3, width=40, wrap="word", font=(UI_FONT, 10))
        self.notes.pack(side="left", fill="x", expand=True)
        ttk.Button(notes, text="Enregistrer", command=self.save_notes).pack(side="left", padx=6)

    def refresh_list(self, select=None):
        cats = [ALL_CATEGORIES] + self.store.categories()
        self.cat_box.configure(values=cats)
        if self.cat_var.get() not in cats:
            self.cat_var.set(ALL_CATEGORIES)
        cat = "" if self.cat_var.get() == ALL_CATEGORIES else self.cat_var.get()
        found = self.store.query(self.search_var.get(), cat, self.fav_only.get(),
                                 SHOW_CHOICES.get(self.show_var.get(), "recipes"))
        keep = select or self.current_id
        self.tree.delete(*self.tree.get_children())
        for r in found:
            title = ("★ " if r.get("favorite") else "") + r.get("title", "")
            self.tree.insert("", "end", iid=r["id"], values=(title, r.get("category", "")))
        total = sum(1 for r in self.store.all() if r.get("is_recipe"))
        self.count_var.set(f"{len(found)} affichée(s) · {total} recette(s) dans le livre")
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
            self.tree.see(keep)
        elif found:
            self.tree.selection_set(found[0]["id"])
        else:
            self.show_recipe(None)

    def _on_select(self):
        sel = self.tree.selection()
        if sel and sel[0] != self.current_id:
            self.photo_index = 0
        self.show_recipe(self.store.get(sel[0]) if sel else None)

    def _photo_step(self, delta):
        rec = self.store.get(self.current_id) if self.current_id else None
        if rec and rec.get("photos"):
            self.photo_index = (self.photo_index + delta) % len(rec["photos"])
            self.show_recipe(rec)

    def _photo_image(self, rec):
        photos = rec.get("photos") or []
        if not photos:
            return None
        path = self.store.photo_path(photos[self.photo_index % len(photos)])
        if not os.path.isfile(path):
            return None
        try:
            from PIL import Image, ImageTk
            with Image.open(path) as im:
                width = max(280, min(560, self.view.winfo_width() - 60))
                im = im.convert("RGB")
                im.thumbnail((width, 300))
                return ImageTk.PhotoImage(im)
        except Exception as exc:
            log.warning("Photo illisible %s : %s", path, exc)
            return None

    def show_recipe(self, rec):
        self.current_id = rec["id"] if rec else None
        v = self.view
        v.configure(state="normal")
        v.delete("1.0", "end")
        self.notes.delete("1.0", "end")
        if not rec:
            v.insert("end", "\nChoisis une recette dans la liste.", "meta")
            v.configure(state="disabled")
            self.fav_btn.configure(text="☆ Favori")
            return
        self.fav_btn.configure(text="★ Favori" if rec.get("favorite") else "☆ Favori")
        n = len(rec.get("photos") or [])
        state = "normal" if n > 1 else "disabled"
        self.prev_photo.configure(state=state)
        self.next_photo.configure(state=state)

        v.insert("end", rec.get("title", "") + "\n", "title")
        meta = [rec.get("category", "")]
        if rec.get("servings"):
            meta.append("Pour " + rec["servings"])
        if rec.get("prep_time"):
            meta.append("Préparation " + rec["prep_time"])
        if rec.get("cook_time"):
            meta.append("Cuisson " + rec["cook_time"])
        if rec.get("author"):
            meta.append("@" + rec["author"])
        v.insert("end", "  ·  ".join(m for m in meta if m) + "\n", "meta")

        self._photo_ref = self._photo_image(rec)
        if self._photo_ref:
            v.image_create("end", image=self._photo_ref)
            v.insert("end", f"\n{self.photo_index % n + 1}/{n}\n" if n > 1 else "\n", "meta")

        if not rec.get("is_recipe"):
            v.insert("end", "Ce post ne ressemble pas à une recette. Clique sur « Modifier » "
                            "et coche « C'est une recette » si c'en est une.\n", "meta")
        groups = rec.get("ingredients") or []
        if groups:
            v.insert("end", "INGRÉDIENTS\n", "h")
            for g in groups:
                if g.get("group"):
                    v.insert("end", g["group"] + "\n", "group")
                for item in g.get("items", []):
                    v.insert("end", f"•  {item}\n", "item")
        if rec.get("steps"):
            v.insert("end", "PRÉPARATION\n", "h")
            for i, step in enumerate(rec["steps"], 1):
                v.insert("end", f"{i}.  {step}\n", "step")
        if rec.get("tips"):
            v.insert("end", "ASTUCES\n", "h")
            v.insert("end", rec["tips"] + "\n")
        if not groups and not rec.get("steps") and rec.get("is_recipe"):
            v.insert("end", "\nLa recette n'a pas pu être découpée automatiquement : elle est "
                            "dans le texte ci-dessous. Tu peux la ranger avec « Modifier », ou "
                            "régler une clé Claude pour la mise en forme automatique.\n", "meta")
        if rec.get("transcript"):
            v.insert("end", "CE QUI EST DIT DANS LA VIDÉO\n", "h")
            v.insert("end", rec["transcript"] + "\n", "raw")
        if rec.get("caption"):
            v.insert("end", "TEXTE D'ORIGINE DU POST\n", "h")
            v.insert("end", rec["caption"] + "\n", "raw")
        v.configure(state="disabled")
        v.yview_moveto(0)
        self.notes.insert("1.0", rec.get("notes", ""))

    # ---------------------------------------------------------------- actions livre
    def _current(self):
        rec = self.store.get(self.current_id) if self.current_id else None
        if not rec:
            messagebox.showinfo("Livre de cuisine", "Choisis d'abord une recette.")
        return rec

    def toggle_favorite(self):
        rec = self._current()
        if rec:
            rec["favorite"] = not rec.get("favorite")
            self.store.put(rec)
            self.refresh_list()

    def save_notes(self):
        rec = self._current()
        if rec:
            rec["notes"] = self.notes.get("1.0", "end").strip()
            self.store.put(rec)
            self.status.set("Notes enregistrées.")

    def open_source(self):
        rec = self._current()
        if rec and rec.get("source_url"):
            webbrowser.open(rec["source_url"])

    def new_recipe(self):
        RecipeDialog(self.root, empty_recipe(), self._saved_from_dialog)

    def edit_recipe(self):
        rec = self._current()
        if rec:
            RecipeDialog(self.root, dict(rec), self._saved_from_dialog)

    def _saved_from_dialog(self, rec):
        rid = self.store.put(rec)
        if not rec.get("is_recipe"):
            self.show_var.set("Tout")
        self.refresh_list(select=rid)
        self.show_recipe(self.store.get(rid))

    def delete_recipe(self):
        rec = self._current()
        if rec and messagebox.askyesno(
                "Supprimer", f"Supprimer « {rec['title']} » du livre ?\n\nSi elle vient "
                             "d'Instagram, elle sera réimportée au prochain import, sauf si "
                             "tu la retires de ta collection."):
            self.store.delete(rec["id"])
            self.current_id = None
            self.refresh_list()

    def _export(self, recipes, name, title):
        if not recipes:
            messagebox.showinfo("Exporter", "Aucune recette à exporter.")
            return
        path = os.path.join(self.store.folder, "Exports", name)
        export.export_html(self.store, recipes, path, title)
        open_path(path)
        self.status.set(f"Export ouvert dans le navigateur ({path}). Ctrl+P pour imprimer "
                        "ou enregistrer en PDF.")

    def export_current(self):
        rec = self._current()
        if rec:
            safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in rec["title"])[:60]
            self._export([rec], f"{safe.strip() or rec['id']}.html", rec["title"])

    def export_list(self):
        recs = [self.store.get(i) for i in self.tree.get_children()]
        self._export([r for r in recs if r], "Mon livre de cuisine.html", "Mon livre de cuisine")

    def reformat_current(self):
        rec = self._current()
        if not rec:
            return
        opts = Options(self.cfg)
        if not opts.claude_key:
            messagebox.showinfo("Claude", "Règle d'abord ta clé Claude dans l'onglet Réglages.")
            self.nb.select(2)
            return
        if rec.get("method") == "manuel" and not messagebox.askyesno(
                "Claude", "Tu as modifié cette recette à la main. La remettre en forme "
                          "remplacera tes modifications (pas tes notes). Continuer ?"):
            return
        self.run_bg(lambda: reformat(self.store, rec, opts),
                    lambda r: (self.refresh_list(select=r["id"]), self.show_recipe(r),
                               self.status.set(f"« {r['title']} » remise en forme.")),
                    f"Claude met en forme « {rec['title']} »…")

    # ================================================================ onglet Import
    def _build_tab_import(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="  ⬇ Importer depuis Instagram  ")

        box = ttk.LabelFrame(tab, text="1. Connexion à Instagram", padding=8)
        box.pack(fill="x")
        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="Identifiant :").pack(side="left")
        self.user_var = tk.StringVar(value=self.cfg["insta_user"])
        ttk.Entry(row, textvariable=self.user_var, width=24).pack(side="left", padx=(4, 12))
        ttk.Label(row, text="Mot de passe :").pack(side="left")
        self.pass_var = tk.StringVar()
        pw = ttk.Entry(row, textvariable=self.pass_var, show="•", width=24)
        pw.pack(side="left", padx=4)
        pw.bind("<Return>", lambda e: self.do_login())
        b = ttk.Button(row, text="Se connecter", command=self.do_login)
        b.pack(side="left", padx=4)
        self.busy_buttons.append(b)
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Conseillé :").pack(side="left")
        for text, cmd in (("Copier la connexion du navigateur…", self.do_cookie),
                          ("Utiliser ma connexion Firefox", self.do_firefox)):
            b = ttk.Button(row, text=text, command=cmd)
            b.pack(side="left", padx=4)
            self.busy_buttons.append(b)
        ttk.Button(row, text="Se déconnecter", command=self.do_logout).pack(side="right")
        self.conn_var = tk.StringVar(value="Pas connecté.")
        ttk.Label(box, textvariable=self.conn_var, foreground=ACCENT).pack(anchor="w",
                                                                          pady=(8, 0))
        ttk.Label(box, foreground="#666", text=(
            "Le mot de passe n'est jamais enregistré : seule la session est gardée dans le "
            "dossier session_instagram, pour ne pas avoir à te reconnecter.")).pack(anchor="w")

        box = ttk.LabelFrame(tab, text="2. Ta collection de recettes", padding=8)
        box.pack(fill="x", pady=8)
        row = ttk.Frame(box)
        row.pack(fill="x")
        self.coll_var = tk.StringVar(value=self.cfg["collection_name"])
        self.coll_box = ttk.Combobox(row, textvariable=self.coll_var, state="readonly",
                                     width=40)
        self.coll_box.pack(side="left")
        b = ttk.Button(row, text="Charger mes collections", command=self.load_collections)
        b.pack(side="left", padx=6)
        self.busy_buttons.append(b)
        ttk.Button(row, text="Coller le lien de ma collection…",
                   command=self.paste_collection_link).pack(side="left")
        ttk.Label(box, foreground="#666", text=(
            "Le lien : sur instagram.com, ouvre ton profil → Enregistrements → ta collection, "
            "puis copie l'adresse de la page (elle contient /saved/).")).pack(anchor="w",
                                                                             pady=(6, 0))

        box = ttk.LabelFrame(tab, text="3. Importer", padding=8)
        box.pack(fill="x")
        row = ttk.Frame(box)
        row.pack(fill="x")
        b = ttk.Button(row, text="Importer les nouvelles recettes", style="Big.TButton",
                       command=self.do_import)
        b.pack(side="left")
        self.busy_buttons.append(b)
        b = ttk.Button(row, text="Importer des liens…", command=self.do_import_links)
        b.pack(side="left", padx=6)
        self.busy_buttons.append(b)
        ttk.Button(row, text="Arrêter", command=self.stop.set).pack(side="left")
        self.caps_var = tk.StringVar()
        ttk.Label(box, textvariable=self.caps_var, foreground="#555", justify="left").pack(
            anchor="w", pady=(8, 0))
        self._update_caps()

        frame = ttk.Frame(tab)
        frame.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text = tk.Text(frame, height=10, wrap="word", font=(UI_FONT, 9),
                                state="disabled")
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=ys.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        ys.pack(side="left", fill="y")

    def _update_caps(self):
        opts = Options(self.cfg)
        lines = []
        if opts.claude_key:
            lines.append("✨ Claude : activé. Les recettes sont mises en forme à partir de la "
                         "légende, de la vidéo et des images.")
        else:
            lines.append("✨ Claude : pas de clé. La légende est découpée automatiquement "
                         "(moins fiable, voir Réglages).")
        if opts.transcribe:
            lines.append(f"🎤 Vidéos : la voix est transcrite (modèle « {opts.whisper_model} »).")
        elif self.cfg.get("transcribe") and not media.can_transcribe():
            lines.append("🎤 Vidéos : transcription pas installée (bouton dans Réglages).")
        else:
            lines.append("🎤 Vidéos : transcription désactivée.")
        self.caps_var.set("\n".join(lines))

    def say(self, text):
        self.q.put(("log", text))

    def _append_log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _get_insta(self):
        if self.insta is None:
            self.insta = Insta(config.SESSION_DIR)
            self.insta.notify = self.say
        return self.insta

    def _resume_session(self):
        user = self.cfg.get("insta_user")
        if not user:
            return
        try:
            if self._get_insta().resume(user):
                self.conn_var.set(f"Session enregistrée pour @{user}.")
        except Exception as exc:
            log.warning("Session illisible : %s", exc)

    def _logged_in(self, user):
        self.cfg["insta_user"] = user
        self.user_var.set(user)
        self.pass_var.set("")
        config.save(self.cfg)
        self.conn_var.set(f"Connecté en tant que @{user}.")
        self.say(f"Connecté en tant que @{user}.")
        self.load_collections()

    def do_login(self):
        user = self.user_var.get().strip().lstrip("@")
        password = self.pass_var.get()
        if not user or not password:
            messagebox.showinfo("Connexion", "Indique ton identifiant et ton mot de passe "
                                             "Instagram.")
            return

        def job():
            insta = self._get_insta()
            try:
                insta.login(user, password)
            except TwoFactorNeeded:
                return "2fa"
            return insta.username

        self.run_bg(job, self._after_login_step, "Connexion à Instagram…")

    def _after_login_step(self, result):
        if result != "2fa":
            self._logged_in(result)
            return
        code = simpledialog.askstring(
            "Vérification", "Instagram t'a envoyé un code de vérification (SMS ou appli "
                            "d'authentification).\n\nCode :", parent=self.root)
        if code:
            self.run_bg(lambda: (self.insta.two_factor(code), self.insta.username)[1],
                        self._logged_in, "Vérification du code…")

    def do_firefox(self):
        self.run_bg(lambda: self._get_insta().login_with_firefox(), self._logged_in,
                    "Lecture de la connexion Firefox…")

    def do_cookie(self):
        def go(text):
            cookies, ua = parse_browser_copy(text)
            self.run_bg(lambda: self._get_insta().login_with_cookies(cookies, ua),
                        self._logged_in, "Vérification de la connexion…")
        BrowserCopyDialog(self.root, go)

    def do_logout(self):
        if self.insta:
            self.insta.logout()
        self.cfg["insta_user"] = ""
        config.save(self.cfg)
        self.conn_var.set("Pas connecté.")

    def _need_login(self):
        insta = self._get_insta()
        if not insta.username:
            messagebox.showinfo("Instagram", "Connecte-toi d'abord à Instagram (étape 1).")
            return None
        return insta

    def load_collections(self):
        insta = self._need_login()
        if insta:
            self.run_bg(insta.collections, self._show_collections,
                        "Lecture de tes collections…")

    def _show_collections(self, colls):
        self.collections = colls
        labels = [self._coll_label(c) for c in colls]
        self.coll_box.configure(values=labels)
        current = next((c for c in colls if c[0] == self.cfg.get("collection_id")), None)
        if current is None:
            current = next((c for c in colls if "recette" in c[1].lower()), None)
        if current:
            self.coll_var.set(self._coll_label(current))
        self.say(f"{len(colls) - 1} collection(s) trouvée(s). Choisis celle de tes recettes.")
        if any("nom inconnu" in c[1] for c in colls):
            self.say("Instagram ne donne plus le nom des collections. Le plus simple : clique sur "
                     "« Coller le lien de ma collection… ».")

    def paste_collection_link(self):
        text = simpledialog.askstring(
            "Lien de la collection",
            "Sur instagram.com, ouvre ton profil → Enregistrements → ta collection de "
            "recettes,\npuis copie l'adresse de la page (Ctrl+L puis Ctrl+C). Elle ressemble "
            "à :\nhttps://www.instagram.com/ton_nom/saved/recettes/17912345678901234/\n\n"
            "Colle-la ici :", parent=self.root)
        if not text:
            return
        found = collection_from_link(text)
        if not found:
            messagebox.showinfo("Lien de la collection", "Ce lien ne ressemble pas au lien "
                                "d'une collection (il doit contenir /saved/).")
            return
        cid, name = found
        self.collections = [c for c in self.collections if c[0] != cid]
        self.collections.append((cid, name, None))
        self.coll_box.configure(values=[self._coll_label(c) for c in self.collections])
        self.coll_var.set(name)
        self.cfg["collection_id"], self.cfg["collection_name"] = cid, name
        config.save(self.cfg)
        self.say(f"Collection choisie : « {name} ».")

    @staticmethod
    def _coll_label(c):
        return c[1] if c[2] is None else f"{c[1]}  ({c[2]} posts)"

    def _selected_collection(self):
        label = self.coll_var.get()
        for c in self.collections:
            if self._coll_label(c) == label:
                return c[0], c[1]
        if self.cfg.get("collection_id") and label == self.cfg.get("collection_name"):
            return self.cfg["collection_id"], self.cfg["collection_name"]
        return None, None

    def do_import(self):
        insta = self._need_login()
        if not insta:
            return
        cid, name = self._selected_collection()
        if not cid:
            messagebox.showinfo("Import", "Choisis ta collection de recettes (étape 2). "
                                          "Clique sur « Charger mes collections » si la liste "
                                          "est vide.")
            return
        self.cfg["collection_id"], self.cfg["collection_name"] = cid, name
        config.save(self.cfg)
        total = next((c[2] for c in self.collections if c[0] == cid), None)
        label = ALL_SAVED_LABEL if cid == ALL_SAVED else f"la collection « {name} »"
        self.say(f"— Import de {label} —")
        self._start_import(lambda: insta.iter_posts(cid), total)

    def do_import_links(self):
        insta = self._need_login()
        if not insta:
            return
        LinksDialog(self.root, lambda links: self._start_import(
            lambda: (insta.post_from_link(link) for link in links), len(links)))

    def _start_import(self, make_posts, total):
        opts = Options(self.cfg)

        def job():
            imp = Importer(self.store, self.insta, opts, self.say, self.stop)
            return imp.run(make_posts(), progress=self._progress, total=total)

        def done(counts):
            msg = (f"Import terminé : {counts['new']} nouvelle(s) recette(s), "
                   f"{counts['others']} post(s) qui ne sont pas des recettes, "
                   f"{counts['known']} déjà dans le livre, {counts['errors']} erreur(s).")
            if self.stop.is_set():
                msg = "Import arrêté. " + msg
            self.say(msg)
            self.status.set(msg)
            self.refresh_list()

        self.run_bg(job, done, "Import des recettes… (tu peux cliquer sur Arrêter)")

    def _progress(self, done, total):
        self.q.put(("progress", done, total))

    # ================================================================ onglet Réglages
    def _build_tab_settings(self):
        tab = ttk.Frame(self.nb, padding=12)
        self.nb.add(tab, text="  ⚙ Réglages  ")

        box = ttk.LabelFrame(tab, text="Dossier du livre", padding=8)
        box.pack(fill="x")
        row = ttk.Frame(box)
        row.pack(fill="x")
        self.dir_var = tk.StringVar(value=config.data_dir(self.cfg))
        ttk.Entry(row, textvariable=self.dir_var).pack(side="left", fill="x", expand=True)

        def browse():
            d = filedialog.askdirectory(title="Où ranger le livre de cuisine ?",
                                        initialdir=self.dir_var.get() or None)
            if d:
                self.dir_var.set(os.path.normpath(d))
        ttk.Button(row, text="Parcourir…", command=browse).pack(side="left", padx=4)
        ttk.Button(row, text="Ouvrir", command=lambda: open_path(self.store.folder)).pack(
            side="left")
        ttk.Label(box, foreground="#666", text=(
            "Les recettes (recettes.json) et leurs photos y sont rangées. Mets-le dans un "
            "dossier synchronisé (OneDrive…) pour le sauvegarder.")).pack(anchor="w", pady=(4, 0))

        box = ttk.LabelFrame(tab, text="✨ Mise en forme par Claude (facultatif, payant)",
                             padding=8)
        box.pack(fill="x", pady=8)
        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="Clé API Anthropic :").pack(side="left")
        self.key_var = tk.StringVar(value=self.cfg["claude_key"])
        ttk.Entry(row, textvariable=self.key_var, show="•", width=50).pack(side="left", padx=4)
        b = ttk.Button(row, text="Tester la clé", command=self.test_key)
        b.pack(side="left")
        self.busy_buttons.append(b)
        ttk.Button(row, text="Créer une clé…", command=lambda: webbrowser.open(
            "https://console.anthropic.com/settings/keys")).pack(side="left", padx=4)
        ttk.Label(box, foreground="#666", justify="left", text=(
            "Sans clé, la légende est découpée automatiquement : ça marche bien quand la "
            "recette est écrite proprement sous le post.\nAvec une clé, Claude lit aussi ce "
            "qui est dit dans la vidéo et le texte affiché à l'écran ou sur les photos, et range "
            "la recette en français.\nCompte quelques centimes par recette (crédit à acheter "
            "sur console.anthropic.com).")).pack(anchor="w", pady=(4, 0))
        if not ai.available():
            ttk.Label(box, foreground=ACCENT, text=(
                "Le composant « anthropic » n'est pas installé : relance « Lancer Livre de "
                "cuisine.bat ».")).pack(anchor="w")

        box = ttk.LabelFrame(tab, text="🎤 Transcription des vidéos", padding=8)
        box.pack(fill="x")
        row = ttk.Frame(box)
        row.pack(fill="x")
        self.tr_var = tk.BooleanVar(value=self.cfg["transcribe"])
        ttk.Checkbutton(row, text="Écouter les vidéos pour récupérer la recette dite à l'oral",
                        variable=self.tr_var).pack(side="left")
        ttk.Label(row, text="   Précision :").pack(side="left")
        self.model_var = tk.StringVar(value=self.cfg["whisper_model"])
        ttk.Combobox(row, textvariable=self.model_var, state="readonly", width=8,
                     values=config.WHISPER_MODELS).pack(side="left", padx=4)
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(6, 0))
        self.install_btn = ttk.Button(row, text="Installer la transcription",
                                      command=self.install_transcription)
        self.install_btn.pack(side="left")
        self.busy_buttons.append(self.install_btn)
        self.tr_status = tk.StringVar()
        ttk.Label(row, textvariable=self.tr_status).pack(side="left", padx=8)
        self._update_tr_status()
        ttk.Label(box, foreground="#666", justify="left", text=(
            "Fonctionne sur ton PC, sans internet ni frais. L'installation prend environ "
            "300 Mo, puis le modèle se télécharge à la première vidéo.\n« base » = rapide, "
            "« small » = bon équilibre, « medium » = plus précis mais lent.")).pack(
            anchor="w", pady=(4, 0))

        box = ttk.LabelFrame(tab, text="Prudence avec Instagram", padding=8)
        box.pack(fill="x", pady=8)
        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="Pause entre deux posts (secondes) :").pack(side="left")
        self.pause_var = tk.IntVar(value=int(self.cfg.get("pause_seconds", 4)))
        ttk.Spinbox(row, from_=0, to=60, textvariable=self.pause_var, width=5).pack(
            side="left", padx=4)
        ttk.Label(box, foreground="#666", text=(
            "Aller trop vite peut faire bloquer ton compte quelques heures par Instagram. "
            "Garde au moins 3 secondes.")).pack(anchor="w", pady=(4, 0))

        ttk.Button(tab, text="Enregistrer les réglages", style="Big.TButton",
                   command=self.save_settings).pack(anchor="w", pady=8)

    def _update_tr_status(self):
        if media.can_transcribe():
            self.tr_status.set("✓ Transcription installée.")
            self.install_btn.configure(text="Réinstaller")
        else:
            self.tr_status.set("Pas encore installée.")

    def save_settings(self):
        self.cfg["claude_key"] = config.clean_key(self.key_var.get())
        self.key_var.set(self.cfg["claude_key"])
        self.cfg["transcribe"] = self.tr_var.get()
        self.cfg["whisper_model"] = self.model_var.get()
        try:
            self.cfg["pause_seconds"] = max(0, int(self.pause_var.get()))
        except (tk.TclError, ValueError):
            self.cfg["pause_seconds"] = 4
        folder = os.path.normpath(self.dir_var.get().strip() or config.DEFAULT_DATA_DIR)
        if os.path.normpath(folder) != os.path.normpath(self.store.folder):
            if self.worker and self.worker.is_alive():
                messagebox.showinfo("Réglages", "Attends la fin de l'opération en cours pour "
                                                "changer de dossier.")
                return
            self.store = Store(folder)
            self.current_id = None
        self.cfg["data_dir"] = "" if folder == os.path.normpath(config.DEFAULT_DATA_DIR) \
            else folder
        config.save(self.cfg)
        self._update_caps()
        self.refresh_list()
        self.status.set("Réglages enregistrés.")

    def test_key(self):
        key = config.clean_key(self.key_var.get())
        self.key_var.set(key)
        if not key:
            messagebox.showinfo("Claude", "Colle d'abord ta clé (elle commence par sk-ant-).")
            return
        if not ai.available():
            messagebox.showerror("Claude", "Le composant « anthropic » n'est pas installé.")
            return

        def done(err):
            if err:
                messagebox.showerror("Claude", err)
            else:
                messagebox.showinfo("Claude", "La clé fonctionne. Pense à cliquer sur "
                                              "« Enregistrer les réglages ».")
        self.run_bg(lambda: ai.test_key(key), done, "Test de la clé…")

    def install_transcription(self):
        def done(result):
            ok, out = result
            self._update_tr_status()
            self._update_caps()
            if ok:
                messagebox.showinfo("Transcription", "Transcription installée.")
            else:
                log.error("pip install faster-whisper :\n%s", out)
                messagebox.showerror("Transcription", "L'installation a échoué. Le détail est "
                                                      "dans LivreCuisine.log.\n\n" + out[-600:])
        self.run_bg(media.install_transcription, done,
                    "Installation de la transcription (plusieurs minutes)…")

    # ================================================================ tâches de fond
    def run_bg(self, fn, on_done=None, label=""):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Livre de cuisine", "Une opération est déjà en cours.")
            return
        self.stop.clear()
        self.status.set(label)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        for b in self.busy_buttons:
            b.configure(state="disabled")

        def target():
            try:
                result = fn()
                self.q.put(("done", on_done, result))
            except Exception as exc:
                log.error("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                self.q.put(("error", friendly(exc)))

        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def _idle(self):
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        for b in self.busy_buttons:
            b.configure(state="normal")

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._append_log(msg[1])
                elif kind == "progress":
                    done, total = msg[1], msg[2]
                    if total:
                        self.progress.stop()
                        self.progress.configure(mode="determinate", maximum=total,
                                                value=min(done, total))
                        self.status.set(f"Post {done} sur {total}…")
                    else:
                        self.status.set(f"Post {done}…")
                elif kind == "done":
                    self._idle()
                    self.status.set("Terminé.")
                    if msg[1]:
                        msg[1](msg[2])
                elif kind == "error":
                    self._idle()
                    self.status.set(msg[1])
                    self._append_log("✗ " + msg[1])
                    self.refresh_list()
                    messagebox.showerror("Livre de cuisine", msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Quitter", "Une opération est en cours. Quitter quand "
                                                  "même ? Les recettes déjà importées sont "
                                                  "gardées."):
                return
            self.stop.set()
        self.root.destroy()


class RecipeDialog(tk.Toplevel):
    """Formulaire pour créer ou corriger une recette."""

    def __init__(self, parent, rec, on_save):
        super().__init__(parent)
        self.rec = rec
        self.on_save = on_save
        self.title("Recette")
        self.geometry("760x780")
        self.transient(parent)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        self.vars = {}
        r = 0
        for key, label in (("title", "Titre"), ("servings", "Pour combien"),
                           ("prep_time", "Préparation"), ("cook_time", "Cuisson")):
            ttk.Label(f, text=label + " :").grid(row=r, column=0, sticky="w", pady=2)
            self.vars[key] = tk.StringVar(value=rec.get(key, ""))
            ttk.Entry(f, textvariable=self.vars[key]).grid(row=r, column=1, sticky="ew", pady=2)
            r += 1
        ttk.Label(f, text="Catégorie :").grid(row=r, column=0, sticky="w", pady=2)
        self.vars["category"] = tk.StringVar(value=rec.get("category") or "Autre")
        ttk.Combobox(f, textvariable=self.vars["category"], values=CATEGORIES).grid(
            row=r, column=1, sticky="w", pady=2)
        r += 1

        def area(label, text, height, hint=""):
            nonlocal r
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="nw", pady=(8, 0))
            if hint:
                ttk.Label(f, text=hint, foreground="#666").grid(row=r, column=1, sticky="w",
                                                                pady=(8, 0))
            r += 1
            t = tk.Text(f, height=height, wrap="word", font=(UI_FONT, 10), undo=True)
            t.grid(row=r, column=0, columnspan=2, sticky="nsew")
            f.rowconfigure(r, weight=height)
            t.insert("1.0", text)
            r += 1
            return t

        self.ing = area("Ingrédients :", ingredients_to_text(rec.get("ingredients", [])), 9,
                        "Un par ligne. Une ligne qui finit par « : » démarre un groupe "
                        "(« Pour la sauce : »).")
        self.steps = area("Étapes :", "\n".join(rec.get("steps", [])), 9, "Une étape par ligne.")
        self.tips = area("Astuces :", rec.get("tips", ""), 3)
        ttk.Label(f, text="Mots-clés :").grid(row=r, column=0, sticky="w", pady=(8, 0))
        self.vars["tags"] = tk.StringVar(value=", ".join(rec.get("tags", [])))
        ttk.Entry(f, textvariable=self.vars["tags"]).grid(row=r, column=1, sticky="ew",
                                                          pady=(8, 0))
        r += 1
        self.is_recipe = tk.BooleanVar(value=rec.get("is_recipe", True))
        ttk.Checkbutton(f, text="C'est une recette", variable=self.is_recipe).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=6)
        r += 1
        row = ttk.Frame(f)
        row.grid(row=r, column=0, columnspan=2, sticky="e", pady=(6, 0))
        if rec.get("caption") or rec.get("transcript"):
            ttk.Button(row, text="Voir le texte d'origine", command=self.show_raw).pack(
                side="left", padx=4)
        ttk.Button(row, text="Annuler", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(row, text="Enregistrer", style="Big.TButton", command=self.save).pack(
            side="left")
        self.grab_set()

    def show_raw(self):
        win = tk.Toplevel(self)
        win.title("Texte d'origine")
        win.geometry("560x600")
        t = tk.Text(win, wrap="word", font=(UI_FONT, 10), padx=10, pady=10)
        t.pack(fill="both", expand=True)
        if self.rec.get("transcript"):
            t.insert("end", "Dit dans la vidéo :\n" + self.rec["transcript"] + "\n\n")
        t.insert("end", "Légende :\n" + self.rec.get("caption", ""))

    def save(self):
        rec = self.rec
        for key in ("title", "servings", "prep_time", "cook_time", "category"):
            rec[key] = self.vars[key].get().strip()
        rec["title"] = rec["title"] or "Recette sans titre"
        rec["category"] = rec["category"] or "Autre"
        rec["ingredients"] = text_to_ingredients(self.ing.get("1.0", "end"))
        rec["steps"] = text_to_steps(self.steps.get("1.0", "end"))
        rec["tips"] = self.tips.get("1.0", "end").strip()
        rec["tags"] = [t.strip().lstrip("#").lower() for t in self.vars["tags"].get().split(",")
                       if t.strip()]
        rec["is_recipe"] = self.is_recipe.get()
        rec["method"] = "manuel"
        self.destroy()
        self.on_save(rec)


class BrowserCopyDialog(tk.Toplevel):
    """Pour coller la connexion Instagram copiée depuis Chrome ou Edge."""

    STEPS = (
        "Dans Chrome ou Edge :\n"
        "  1. Ouvre instagram.com et vérifie que tu es connecté (tu vois ton fil).\n"
        "  2. Appuie sur F12, puis va dans l'onglet « Réseau » (ou « Network »).\n"
        "  3. Appuie sur F5 pour recharger la page : une liste de lignes apparaît.\n"
        "  4. Tout en haut, fais un clic droit sur la ligne « www.instagram.com »\n"
        "     → « Copier » → « Copier en tant que cURL (bash) » (ou « (cmd) »).\n"
        "  5. Colle tout ici avec Ctrl+V, puis clique sur « Se connecter ».\n\n"
        "Ça copie ta connexion et l'identité de ton navigateur : Instagram la reconnaît "
        "alors comme la tienne.\nCe texte donne accès à ton compte : ne le colle nulle part "
        "ailleurs. On peut aussi coller seulement la valeur du cookie « sessionid »."
    )

    def __init__(self, parent, on_ok):
        super().__init__(parent)
        self.on_ok = on_ok
        self.title("Copier la connexion du navigateur")
        self.geometry("720x520")
        self.transient(parent)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=self.STEPS, justify="left", wraplength=690).pack(anchor="w")
        self.text = tk.Text(f, height=8, wrap="char", font=(UI_FONT, 9))
        self.text.pack(fill="both", expand=True, pady=8)
        self.text.focus_set()
        row = ttk.Frame(f)
        row.pack(anchor="e")
        ttk.Button(row, text="Annuler", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(row, text="Se connecter", style="Big.TButton", command=self.ok).pack(
            side="left")
        self.grab_set()

    def ok(self):
        text = self.text.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Connexion", "Colle d'abord ce que tu as copié.", parent=self)
            return
        cookies, _ua = parse_browser_copy(text)
        if not cookies.get("sessionid") or " " in cookies["sessionid"]:
            messagebox.showinfo("Connexion", (
                "Je ne trouve pas le cookie « sessionid » dans ce texte. Vérifie que tu es bien "
                "connecté à Instagram dans le navigateur, et que tu as copié la ligne "
                "« www.instagram.com »."), parent=self)
            return
        self.destroy()
        self.on_ok(text)


class LinksDialog(tk.Toplevel):
    def __init__(self, parent, on_ok):
        super().__init__(parent)
        self.on_ok = on_ok
        self.title("Importer des liens")
        self.geometry("620x420")
        self.transient(parent)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Colle des liens de posts Instagram, un par ligne "
                          "(Partager → Copier le lien) :").pack(anchor="w")
        self.text = tk.Text(f, wrap="none", font=(UI_FONT, 10))
        self.text.pack(fill="both", expand=True, pady=6)
        row = ttk.Frame(f)
        row.pack(anchor="e")
        ttk.Button(row, text="Annuler", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(row, text="Importer", style="Big.TButton", command=self.ok).pack(side="left")
        self.grab_set()

    def ok(self):
        import re
        links = re.findall(r"https?://\S*instagram\.com/\S+", self.text.get("1.0", "end"))
        if not links:
            messagebox.showinfo("Liens", "Aucun lien Instagram trouvé.", parent=self)
            return
        self.destroy()
        self.on_ok(list(dict.fromkeys(links)))


def main():
    logging.basicConfig(
        filename=config.LOG_PATH, level=logging.INFO, encoding="utf-8",
        format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # texte net sur écrans HD
        except Exception:
            pass
    root = tk.Tk()

    def report(exc, val, tb):
        log.error("".join(traceback.format_exception(exc, val, tb)))
        messagebox.showerror("Erreur", f"{val}\n\nLe détail est dans {config.LOG_PATH}")

    root.report_callback_exception = report
    App(root)
    root.mainloop()
