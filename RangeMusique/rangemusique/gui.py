"""Fenêtre principale (Tkinter, inclus avec Python sous Windows)."""

import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

from . import __version__, config, executor, identify, planner
from .cache import Cache
from .webapi import NetworkError, WebAPI, fingerprint

log = logging.getLogger("rangemusique")

STATUS_LABELS = {
    identify.SURE: "Reconnu",
    identify.TAGS: "Tags d'origine",
    identify.MANUAL: "Corrigé à la main",
    identify.UNSURE: "À vérifier",
    identify.UNKNOWN: "Inconnu",
}
STATUS_COLORS = {
    identify.SURE: "#dff3df",
    identify.TAGS: "#eef3fb",
    identify.MANUAL: "#e3ecff",
    identify.UNSURE: "#fff1d6",
    identify.UNKNOWN: "#fde0e0",
}
ACTION_COLORS = {
    planner.MOVE: "#dff3df",
    planner.DUPLICATE: "#eeeeee",
    planner.REVIEW: "#fff1d6",
}
FILTERS = ("Tout afficher", "À vérifier / inconnus", "Reconnus")


def open_in_explorer(path):
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
        self.cache = Cache(config.CACHE_PATH)
        self.api = WebAPI(self.cache, self.cfg["acoustid_key"], config.COVER_CACHE_DIR)
        self.tracks = []
        self.plan = []
        self.q = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.busy_buttons = []

        root.title(f"RangeMusique {__version__}")
        root.geometry("1180x720")
        root.minsize(900, 560)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=24)
        style.configure("Big.TButton", padding=(12, 6))

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self._build_tab_analyse()
        self._build_tab_ranger()
        self._build_tab_reglages()

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", padx=8, pady=8)
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill="x")
        self.status = tk.StringVar(value="Prêt.")
        ttk.Label(bottom, textvariable=self.status).pack(anchor="w", pady=(4, 0))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll)
        if not self.cfg["acoustid_key"] or not config.find_fpcalc(self.cfg["fpcalc_path"]):
            self.nb.select(2)
            self.status.set("Commence par l'onglet Réglages : clé AcoustID et fpcalc.exe.")

    # ------------------------------------------------------------------ onglets
    def _folder_row(self, parent, label, var, title):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text=label, width=42).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=4)

        def browse():
            d = filedialog.askdirectory(title=title, initialdir=var.get() or None)
            if d:
                var.set(os.path.normpath(d))
        ttk.Button(row, text="Parcourir…", command=browse).pack(side="left")

    def _tree(self, parent, columns):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=6)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings",
                            selectmode="extended")
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w", stretch=width > 120)
        ys = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xs = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def _build_tab_analyse(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="  1. Analyser et taguer  ")
        self.src_var = tk.StringVar(value=self.cfg["source_dir"])
        self._folder_row(tab, "Dossier de ta musique :", self.src_var,
                         "Choisis le dossier qui contient ta musique")
        self.fast_var = tk.BooleanVar(value=self.cfg["fast_mode"])
        ttk.Checkbutton(
            tab, variable=self.fast_var,
            text="Analyse rapide : ne pas vérifier en ligne les fichiers qui ont déjà "
                 "artiste + titre + album",
        ).pack(anchor="w")

        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(8, 0))
        b1 = ttk.Button(row, text="Analyser", style="Big.TButton", command=self.do_analyse)
        b1.pack(side="left")
        ttk.Button(row, text="Arrêter", command=self.do_stop).pack(side="left", padx=6)
        ttk.Label(row, text="   Afficher :").pack(side="left")
        self.filter_var = tk.StringVar(value=FILTERS[0])
        cb = ttk.Combobox(row, textvariable=self.filter_var, values=FILTERS,
                          state="readonly", width=22)
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_tracks())
        self.count_var = tk.StringVar()
        ttk.Label(row, textvariable=self.count_var).pack(side="right")

        self.tree = self._tree(tab, [
            ("fichier", "Fichier actuel", 230), ("artiste", "Artiste", 150),
            ("titre", "Titre", 190), ("album", "Album", 170), ("piste", "N°", 40),
            ("annee", "Année", 55), ("statut", "Statut", 120),
        ])
        for level, color in STATUS_COLORS.items():
            self.tree.tag_configure(level, background=color)
        self.tree.bind("<Double-1>", lambda e: self.do_edit())

        row = ttk.Frame(tab)
        row.pack(fill="x")
        b2 = ttk.Button(row, text="Corriger le morceau sélectionné…", command=self.do_edit)
        b2.pack(side="left")
        b3 = ttk.Button(row, text="Écrire les tags dans les fichiers (sans les déplacer)",
                        command=self.do_write_tags)
        b3.pack(side="left", padx=6)
        ttk.Label(row, text="Double-clic sur une ligne pour la corriger.",
                  foreground="#666").pack(side="right")
        self.busy_buttons += [b1, b2, b3]

    def _build_tab_ranger(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="  2. Ranger  ")
        self.dest_var = tk.StringVar(value=self.cfg["dest_dir"])
        self._folder_row(tab, "Dossier de destination (nouveau dossier) :", self.dest_var,
                         "Choisis (ou crée) le dossier où ranger la musique")
        self.tags_var = tk.BooleanVar(value=self.cfg["write_tags"])
        self.covers_var = tk.BooleanVar(value=self.cfg["covers"])
        self.cleanup_var = tk.BooleanVar(value=self.cfg["cleanup"])
        ttk.Checkbutton(tab, variable=self.tags_var,
                        text="Écrire les tags corrigés dans les fichiers").pack(anchor="w")
        ttk.Checkbutton(tab, variable=self.covers_var,
                        text="Ajouter les pochettes (dans chaque morceau + cover.jpg dans "
                             "chaque album)").pack(anchor="w")
        ttk.Checkbutton(tab, variable=self.cleanup_var,
                        text="Supprimer ensuite les dossiers vides de l'ancien emplacement "
                             "(et les fichiers inutiles : Thumbs.db, desktop.ini, .m3u…)"
                        ).pack(anchor="w")

        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(8, 0))
        b1 = ttk.Button(row, text="Préparer l'aperçu", style="Big.TButton",
                        command=self.do_plan)
        b1.pack(side="left")
        b2 = ttk.Button(row, text="Lancer le rangement", style="Big.TButton",
                        command=self.do_execute)
        b2.pack(side="left", padx=6)
        b3 = ttk.Button(row, text="Annuler le dernier rangement", command=self.do_undo)
        b3.pack(side="left", padx=6)
        self.busy_buttons += [b1, b2, b3]
        self.plan_var = tk.StringVar(value="Analyse d'abord ta musique (onglet 1), puis "
                                           "prépare l'aperçu.")
        ttk.Label(tab, textvariable=self.plan_var, foreground="#333").pack(anchor="w",
                                                                           pady=(8, 0))
        self.plan_tree = self._tree(tab, [
            ("action", "Action", 90), ("avant", "Emplacement actuel", 330),
            ("apres", "Nouvel emplacement", 380), ("raison", "Détail", 260),
        ])
        for action, color in ACTION_COLORS.items():
            self.plan_tree.tag_configure(action, background=color)

    def _build_tab_reglages(self):
        tab = ttk.Frame(self.nb, padding=16)
        self.nb.add(tab, text="  Réglages  ")
        self.key_var = tk.StringVar(value=self.cfg["acoustid_key"])
        self.fpcalc_var = tk.StringVar(value=self.cfg["fpcalc_path"])

        ttk.Label(tab, text="Reconnaissance par empreinte audio (AcoustID)",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="Clé d'application AcoustID :", width=30).pack(side="left")
        ttk.Entry(row, textvariable=self.key_var, width=30).pack(side="left", padx=4)
        ttk.Button(row, text="Tester la clé", command=self.test_key).pack(side="left")

        row = ttk.Frame(tab)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="Programme fpcalc.exe :", width=30).pack(side="left")
        ttk.Entry(row, textvariable=self.fpcalc_var).pack(side="left", fill="x",
                                                           expand=True, padx=4)

        def browse():
            f = filedialog.askopenfilename(
                title="Où se trouve fpcalc.exe ?",
                filetypes=[("fpcalc", "fpcalc*"), ("Tous les fichiers", "*.*")])
            if f:
                self.fpcalc_var.set(os.path.normpath(f))
        ttk.Button(row, text="Parcourir…", command=browse).pack(side="left")
        ttk.Button(row, text="Tester fpcalc", command=self.test_fpcalc).pack(side="left",
                                                                             padx=4)
        ttk.Button(tab, text="Enregistrer les réglages", style="Big.TButton",
                   command=self.save_settings).pack(anchor="w", pady=(10, 16))
        help_text = (
            "• La clé AcoustID se crée gratuitement sur acoustid.org → « Register "
            "application ».\n"
            "• fpcalc.exe (Chromaprint) calcule l'empreinte audio. Indique où il se trouve, "
            "ou mets-le\n   à côté de l'application : il sera trouvé tout seul.\n"
            "• Sans clé ou sans fpcalc, l'appli marche quand même, mais reconnaît seulement "
            "les morceaux\n   à partir de leurs tags et de leur nom de fichier.\n"
            "• Les résultats internet sont gardés en mémoire (cache_musique.sqlite) : une "
            "analyse\n   interrompue reprend très vite."
        )
        ttk.Label(tab, text=help_text, justify="left", foreground="#444").pack(anchor="w")

    # ------------------------------------------------------------------ réglages
    def collect_settings(self):
        self.cfg.update(
            acoustid_key=config.clean_key(self.key_var.get()), fpcalc_path=self.fpcalc_var.get().strip(),
            source_dir=self.src_var.get().strip(), dest_dir=self.dest_var.get().strip(),
            fast_mode=self.fast_var.get(), write_tags=self.tags_var.get(),
            covers=self.covers_var.get(), cleanup=self.cleanup_var.get(),
        )
        self.api.acoustid_key = self.cfg["acoustid_key"]
        if self.key_var.get() != self.cfg["acoustid_key"]:
            self.key_var.set(self.cfg["acoustid_key"])
        try:
            config.save(self.cfg)
        except OSError as e:
            log.warning("config non enregistrée : %s", e)

    def save_settings(self):
        self.collect_settings()
        fp = config.find_fpcalc(self.cfg["fpcalc_path"])
        msg = "Réglages enregistrés.\n\n"
        msg += f"fpcalc : {fp}" if fp else "⚠ fpcalc.exe introuvable."
        if not self.cfg["acoustid_key"]:
            msg += "\n⚠ Pas de clé AcoustID."
        messagebox.showinfo("Réglages", msg)

    def test_key(self):
        self.collect_settings()
        if not self.cfg["acoustid_key"]:
            messagebox.showwarning("AcoustID", "Colle d'abord ta clé.")
            return
        self.api.offline = False
        try:
            ok, msg = self.api.check_acoustid_key()
        except NetworkError as e:
            messagebox.showerror("AcoustID", f"Impossible de joindre AcoustID :\n{e}")
            return
        key = self.cfg["acoustid_key"]
        if ok:
            messagebox.showinfo("AcoustID", "La clé fonctionne ✔")
        else:
            messagebox.showerror(
                "AcoustID",
                f"Clé refusée par AcoustID ({msg}).\n\n"
                f"Clé testée : {key}  ({len(key)} caractères)\n\n"
                "Attention, il existe deux clés sur acoustid.org :\n"
                "• « Your API key » sur ta page de compte = clé UTILISATEUR → ne marche pas ici ;\n"
                "• la clé d'APPLICATION : menu « Applications » → « Register a new application »"
                " (nom : RangeMusique, version : 1.0), puis copie la clé « API key » de "
                "cette application.")

    def test_fpcalc(self):
        self.collect_settings()
        fp = config.find_fpcalc(self.cfg["fpcalc_path"])
        if not fp:
            messagebox.showerror("fpcalc", "fpcalc.exe introuvable.")
            return
        sample = next((t.path for t in self.tracks if os.path.exists(t.path)), None)
        if not sample:
            messagebox.showinfo("fpcalc", f"fpcalc trouvé :\n{fp}\n\n(Analyse un dossier "
                                          "pour le tester sur un vrai morceau.)")
            return
        try:
            duration, _ = fingerprint(fp, sample)
            messagebox.showinfo("fpcalc", f"fpcalc fonctionne ✔\n{os.path.basename(sample)} "
                                          f": {int(duration)} s")
        except Exception as e:
            messagebox.showerror("fpcalc", f"Erreur avec fpcalc :\n{e}")

    # ------------------------------------------------------------------ tâches
    def run_task(self, label, func, on_done):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Patience", "Une opération est déjà en cours.")
            return
        self.stop.clear()
        for b in self.busy_buttons:
            b.state(["disabled"])
        self.status.set(label)
        self.progress.configure(value=0, maximum=1)

        def progress(i, n, msg):
            self.q.put(("progress", i, n, msg))

        def target():
            try:
                res = func(progress)
                self.q.put(("done", on_done, res, None))
            except Exception as e:
                log.error("Erreur : %s", traceback.format_exc())
                self.q.put(("done", on_done, None, e))

        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def _poll(self):
        try:
            last_progress = None
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "progress":
                    last_progress = msg
                else:
                    if last_progress:
                        self._show_progress(*last_progress[1:])
                        last_progress = None
                    _, on_done, res, err = msg
                    for b in self.busy_buttons:
                        b.state(["!disabled"])
                    if err:
                        self.status.set("Erreur.")
                        messagebox.showerror("Erreur", f"{err}\n\nDétails dans "
                                                       f"{config.LOG_PATH}")
                    else:
                        on_done(res)
        except queue.Empty:
            pass
        if last_progress:
            self._show_progress(*last_progress[1:])
        self.root.after(100, self._poll)

    def _show_progress(self, i, n, msg):
        if n:
            self.progress.configure(maximum=n, value=i)
            self.status.set(f"{i}/{n} – {msg}")
        else:
            self.progress.configure(maximum=1, value=0)
            self.status.set(msg)

    def do_stop(self):
        self.stop.set()
        self.status.set("Arrêt demandé… (le travail déjà fait est gardé en cache)")

    # ------------------------------------------------------------------ analyse
    def do_analyse(self):
        self.collect_settings()
        src = self.cfg["source_dir"]
        if not src or not os.path.isdir(src):
            messagebox.showwarning("Dossier", "Choisis le dossier qui contient ta musique.")
            return
        fp = config.find_fpcalc(self.cfg["fpcalc_path"])
        if not fp or not self.cfg["acoustid_key"]:
            if not messagebox.askyesno(
                    "Reconnaissance limitée",
                    "La clé AcoustID ou fpcalc.exe n'est pas configuré : les morceaux mal "
                    "nommés ne pourront pas être reconnus à l'écoute.\n\nContinuer quand "
                    "même ?"):
                return
        self.api.offline = False
        ident = identify.Identifier(self.api, fp, self.cfg["fast_mode"])
        dest = self.cfg["dest_dir"]
        self.plan = []
        self.refresh_plan()

        def work(progress):
            return identify.analyze(src, ident, exclude=[dest] if dest else [],
                                    progress=progress, stop=self.stop)

        self.run_task("Analyse en cours…", work, self._analyse_done)

    def _analyse_done(self, tracks):
        self.tracks = tracks
        self.refresh_tracks()
        counts = {}
        for t in tracks:
            counts[t.confidence] = counts.get(t.confidence, 0) + 1
        msg = (f"{len(tracks)} morceaux analysés : "
               f"{counts.get(identify.SURE, 0)} reconnus, "
               f"{counts.get(identify.TAGS, 0)} gardés avec leurs tags, "
               f"{counts.get(identify.UNSURE, 0) + counts.get(identify.UNKNOWN, 0)} à vérifier.")
        if self.api.offline:
            msg += "  ⚠ Internet injoignable : reconnaissance en ligne interrompue."
        self.status.set(msg)

    def visible_tracks(self):
        f = self.filter_var.get()
        for i, t in enumerate(self.tracks):
            if f == FILTERS[1] and t.is_ok():
                continue
            if f == FILTERS[2] and not t.is_ok():
                continue
            yield i, t

    def _track_values(self, t):
        n = t.new if t.new else t.old
        status = STATUS_LABELS.get(t.confidence, t.confidence)
        if t.confidence in identify.OK_LEVELS and not t.is_ok():
            status = "Incomplet"
        return (t.filename, n.get("artist", ""), n.get("title", ""), n.get("album", ""),
                n.get("track") or "", n.get("year", ""), status)

    def refresh_tracks(self):
        self.tree.delete(*self.tree.get_children())
        for i, t in self.visible_tracks():
            self.tree.insert("", "end", iid=str(i), values=self._track_values(t),
                             tags=(t.confidence,))
        ok = sum(1 for t in self.tracks if t.is_ok())
        self.count_var.set(f"{ok} prêts à ranger / {len(self.tracks)} morceaux")

    def refresh_row(self, i):
        t = self.tracks[i]
        if self.tree.exists(str(i)):
            self.tree.item(str(i), values=self._track_values(t), tags=(t.confidence,))
        ok = sum(1 for t in self.tracks if t.is_ok())
        self.count_var.set(f"{ok} prêts à ranger / {len(self.tracks)} morceaux")

    def do_edit(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Corriger", "Sélectionne d'abord un morceau dans la liste.")
            return
        i = int(sel[0])
        EditDialog(self.root, self.tracks[i], lambda: self._edited(i))

    def _edited(self, i):
        self.refresh_row(i)
        self.plan = []
        self.refresh_plan()

    def do_write_tags(self):
        ready = [t for t in self.tracks if t.is_ok()]
        if not ready:
            messagebox.showinfo("Tags", "Rien à écrire : analyse d'abord ta musique.")
            return
        if not messagebox.askyesno(
                "Écrire les tags",
                f"Écrire les tags corrigés dans {len(ready)} fichiers, sans les déplacer ?\n\n"
                "(Les morceaux « À vérifier » ne sont pas modifiés.)"):
            return
        self.collect_settings()
        covers = self.cfg["covers"]

        def work(progress):
            return executor.write_tags_in_place(self.tracks, self.api, covers,
                                                progress, self.stop)

        def done(res):
            n, errors = res
            self.status.set(f"Tags écrits dans {n} fichiers.")
            self._show_errors(errors, f"Tags écrits dans {n} fichiers.")
        self.run_task("Écriture des tags…", work, done)

    # ------------------------------------------------------------------ rangement
    def _check_dest(self):
        self.collect_settings()
        src, dest = self.cfg["source_dir"], self.cfg["dest_dir"]
        if not dest:
            messagebox.showwarning("Destination", "Choisis un dossier de destination.")
            return None
        a = os.path.normcase(os.path.abspath(src))
        b = os.path.normcase(os.path.abspath(dest))
        if a == b or a.startswith(b + os.sep):
            messagebox.showwarning(
                "Destination", "Choisis un NOUVEAU dossier de destination, distinct du "
                               "dossier de ta musique (par exemple « D:\\Musique rangée »).")
            return None
        return dest

    def do_plan(self):
        if not self.tracks:
            messagebox.showinfo("Aperçu", "Analyse d'abord ta musique (onglet 1).")
            return
        dest = self._check_dest()
        if not dest:
            return
        tracks = [t for t in self.tracks if os.path.exists(t.path)]

        def work(progress):
            progress(0, 0, "Préparation de l'aperçu (recherche des doublons)…")
            return planner.build_plan(tracks, dest)

        self.run_task("Préparation de l'aperçu…", work, self._plan_done)

    def _plan_done(self, plan):
        self.plan = plan
        self.refresh_plan()
        self.status.set("Aperçu prêt. Vérifie, puis clique sur « Lancer le rangement ».")

    def refresh_plan(self):
        self.plan_tree.delete(*self.plan_tree.get_children())
        if not self.plan:
            self.plan_var.set("Aucun aperçu pour l'instant.")
            return
        dest = self.cfg["dest_dir"]
        for i, it in enumerate(self.plan):
            after = os.path.relpath(it.dest, dest)
            self.plan_tree.insert("", "end", iid=str(i), tags=(it.action,), values=(
                it.action, it.track.path, after, it.reason))
        c = planner.summary(self.plan)
        self.plan_var.set(
            f"{c[planner.MOVE]} morceaux à ranger • {c[planner.DUPLICATE]} doublons "
            f"(→ _Doublons) • {c[planner.REVIEW]} à vérifier (→ _À vérifier)")

    def do_execute(self):
        if not self.plan:
            messagebox.showinfo("Rangement", "Clique d'abord sur « Préparer l'aperçu ».")
            return
        dest = self._check_dest()
        if not dest:
            return
        c = planner.summary(self.plan)
        if not messagebox.askyesno(
                "Lancer le rangement",
                f"Déplacer {len(self.plan)} fichiers vers :\n{dest}\n\n"
                f"• {c[planner.MOVE]} rangés par Artiste\\Album\n"
                f"• {c[planner.DUPLICATE]} doublons dans _Doublons\n"
                f"• {c[planner.REVIEW]} dans _À vérifier\n\n"
                "Tu pourras tout annuler avec « Annuler le dernier rangement ».\nOn y va ?"):
            return
        plan, src = self.plan, self.cfg["source_dir"]
        opts = dict(write_tags=self.cfg["write_tags"], covers=self.cfg["covers"],
                    cleanup=self.cfg["cleanup"])

        def work(progress):
            return executor.execute(plan, src, dest, self.api, progress=progress,
                                    stop=self.stop, **opts)

        self.run_task("Rangement en cours…", work, self._execute_done)

    def _execute_done(self, report):
        self.plan = []
        self.refresh_plan()
        self.refresh_tracks()
        msg = (f"Rangement terminé ✔\n\n"
               f"• {report['moved']} morceaux rangés\n"
               f"• {report['duplicates']} doublons mis dans _Doublons\n"
               f"• {report['review']} morceaux dans _À vérifier "
               f"(liste et suggestions : _suggestions.csv)\n"
               f"• {report['removed_dirs']} anciens dossiers vides supprimés")
        self.status.set("Rangement terminé.")
        self._show_errors(report["errors"], msg)
        open_in_explorer(self.cfg["dest_dir"])

    def do_undo(self):
        self.collect_settings()
        dest = self.cfg["dest_dir"]
        journal = executor.last_journal(dest) if dest else None
        if not journal:
            messagebox.showinfo("Annuler", "Aucun rangement à annuler dans ce dossier de "
                                           "destination.")
            return
        if not messagebox.askyesno(
                "Annuler",
                f"Remettre tous les fichiers du rangement\n{os.path.basename(journal)}\n"
                "à leur place d'origine (avec leurs anciens tags) ?"):
            return

        def work(progress):
            return executor.undo(journal, progress)

        def done(res):
            n, errors = res
            self.tracks = []
            self.refresh_tracks()
            self.status.set(f"{n} fichiers remis à leur place.")
            self._show_errors(errors, f"{n} fichiers remis à leur place d'origine.\n"
                                      "Relance une analyse avant un nouveau rangement.")
        self.run_task("Annulation en cours…", work, done)

    def _show_errors(self, errors, msg):
        if not errors:
            messagebox.showinfo("Terminé", msg)
            return
        log.warning("Problèmes :\n%s", "\n".join(errors))
        shown = "\n".join(errors[:12])
        more = f"\n… et {len(errors) - 12} autres" if len(errors) > 12 else ""
        messagebox.showwarning("Terminé avec des problèmes",
                               f"{msg}\n\n{len(errors)} problème(s) :\n{shown}{more}\n\n"
                               f"Liste complète : {config.LOG_PATH}")

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Quitter", "Une opération est en cours. Quitter "
                                                  "quand même ?"):
                return
            self.stop.set()
        self.collect_settings()
        self.root.destroy()


class EditDialog:
    """Correction manuelle d'un morceau, avec les suggestions trouvées."""

    FIELDS = (("artist", "Artiste"), ("title", "Titre"), ("album", "Album"),
              ("track", "N° de piste"), ("year", "Année"), ("genre", "Genre"))

    def __init__(self, parent, track, on_save):
        self.t = track
        self.on_save = on_save
        self.top = top = tk.Toplevel(parent)
        top.title("Corriger le morceau")
        top.transient(parent)
        top.geometry("760x520")
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=track.path, foreground="#555", wraplength=720).pack(anchor="w")
        row = ttk.Frame(frm)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="▶ Écouter", command=lambda: open_in_explorer(track.path)
                   ).pack(side="left")
        ttk.Button(row, text="Ouvrir le dossier",
                   command=lambda: open_in_explorer(track.folder)).pack(side="left", padx=6)
        if track.note or track.error:
            ttk.Label(row, text=track.error or track.note, foreground="#a33").pack(side="left")

        grid = ttk.Frame(frm)
        grid.pack(fill="x", pady=8)
        cur = track.new or track.old
        self.vars = {}
        for r, (key, label) in enumerate(self.FIELDS):
            ttk.Label(grid, text=label + " :", width=14).grid(row=r, column=0, sticky="w",
                                                              pady=2)
            v = tk.StringVar(value=str(cur.get(key) or ""))
            ttk.Entry(grid, textvariable=v, width=70).grid(row=r, column=1, sticky="we")
            self.vars[key] = v
        grid.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Suggestions trouvées (clic pour les utiliser) :").pack(anchor="w")
        self.lb = tk.Listbox(frm, height=8)
        self.lb.pack(fill="both", expand=True)
        for c in track.candidates[:40]:
            self.lb.insert("end", c.describe())
        if not track.candidates:
            self.lb.insert("end", "(aucune suggestion – remplis les champs à la main)")
        self.lb.bind("<<ListboxSelect>>", self._pick)
        self.picked = None

        row = ttk.Frame(frm)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Enregistrer", style="Big.TButton", command=self._save
                   ).pack(side="right")
        ttk.Button(row, text="Annuler", command=top.destroy).pack(side="right", padx=6)
        top.grab_set()

    def _pick(self, _event):
        sel = self.lb.curselection()
        if not sel or not self.t.candidates:
            return
        c = self.t.candidates[sel[0]]
        self.picked = c
        for key, val in (("artist", c.artist or c.main_artist), ("title", c.title),
                         ("album", c.album), ("track", c.track or ""), ("year", c.year)):
            self.vars[key].set(str(val or ""))

    def _save(self):
        v = {k: var.get().strip() for k, var in self.vars.items()}
        if not (v["artist"] and v["title"] and v["album"]):
            messagebox.showwarning("Incomplet", "Artiste, titre et album sont obligatoires.",
                                   parent=self.top)
            return
        try:
            v["track"] = int(v["track"]) if v["track"] else None
        except ValueError:
            messagebox.showwarning("N° de piste", "Le numéro de piste doit être un nombre.",
                                   parent=self.top)
            return
        c = self.picked
        if c and (c.album != v["album"] or c.title != v["title"]):
            c = None  # l'utilisateur a modifié la suggestion : pas de pochette auto
        if c:
            v.update(tracktotal=c.tracktotal,
                     disc=c.disc if (c.disctotal or 1) > 1 else None,
                     disctotal=c.disctotal if (c.disctotal or 1) > 1 else None,
                     albumartist=c.main_artist)
        identify.set_manual(self.t, v, c)
        self.top.destroy()
        self.on_save()


def main():
    logging.basicConfig(
        filename=config.LOG_PATH, level=logging.INFO, encoding="utf-8",
        format="%(asctime)s %(levelname)s %(message)s")
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # texte net sur écrans HD
        except Exception:
            pass
    root = tk.Tk()

    def report(exc, val, tb):
        log.error("".join(traceback.format_exception(exc, val, tb)))
        messagebox.showerror("Erreur", f"{val}\n\nDétails dans {config.LOG_PATH}")
    root.report_callback_exception = report
    App(root)
    root.mainloop()
