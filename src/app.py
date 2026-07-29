#!/usr/bin/env python3
"""
Contrôle Prépresse PDF — petite app macOS
Import d'un PDF → prévisualisation + analyse :
  • nombre de couleurs (plaques CMJN réellement encrées + tons directs)
  • format avec / sans fond perdu, traits de coupe
  • détection planches vs page à page + calcul du nombre de pages finales
Dépendance : pip3 install pymupdf
"""
import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

import fitz
import prepress_core as core

BG = "#1e1e1e"
FG = "#e8e8e8"
ACCENT = "#e30613"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Contrôle Prépresse PDF")
        self.geometry("1100x720")
        self.configure(bg=BG)
        self.doc = None
        self.res = None
        self.page_idx = 0
        self._photo = None
        self._build()

    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=12, pady=10)
        tk.Button(top, text="📂  Ouvrir un PDF…", command=self.open_pdf,
                  font=("Helvetica", 13, "bold")).pack(side="left")
        self.status = tk.Label(top, text="Glissez un PDF ou cliquez sur Ouvrir",
                               bg=BG, fg="#999", font=("Helvetica", 11))
        self.status.pack(side="left", padx=14)

        main = tk.PanedWindow(self, orient="horizontal", bg=BG, sashwidth=4)
        main.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # ── gauche : prévisu
        left = tk.Frame(main, bg="#2a2a2a")
        self.canvas = tk.Canvas(left, bg="#2a2a2a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        nav = tk.Frame(left, bg="#2a2a2a")
        nav.pack(fill="x")
        tk.Button(nav, text="◀", command=lambda: self.goto(-1)).pack(side="left", padx=6, pady=4)
        self.page_lbl = tk.Label(nav, text="—", bg="#2a2a2a", fg=FG)
        self.page_lbl.pack(side="left", expand=True)
        tk.Button(nav, text="▶", command=lambda: self.goto(+1)).pack(side="right", padx=6, pady=4)
        main.add(left, minsize=420)

        # ── droite : rapport
        right = tk.Frame(main, bg=BG)
        self.report = tk.Text(right, bg="#161616", fg=FG, font=("Menlo", 12),
                              relief="flat", padx=14, pady=12, wrap="word")
        self.report.pack(fill="both", expand=True)
        self.report.tag_configure("h", foreground=ACCENT, font=("Menlo", 12, "bold"))
        self.report.tag_configure("warn", foreground="#ffb020")
        self.report.tag_configure("ok", foreground="#5fd068")
        self.toggle_btn = tk.Button(right, text="↔ Basculer planche / page à page",
                                    command=self.toggle_spread, state="disabled")
        self.toggle_btn.pack(fill="x", pady=(6, 0))
        main.add(right, minsize=380)

        self.canvas.bind("<Configure>", lambda e: self.render_page())

    # ── actions ──────────────────────────────────────────
    def open_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        self.load(path)

    def load(self, path):
        try:
            if self.doc:
                self.doc.close()
            self.doc = fitz.open(path)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le PDF :\n{e}")
            return
        self.page_idx = 0
        self.render_page()
        self.set_report("Analyse en cours…\n")
        self.toggle_btn.config(state="disabled")
        threading.Thread(target=self._analyze, args=(path,), daemon=True).start()

    def _analyze(self, path):
        def prog(msg):
            self.after(0, lambda: self.status.config(text=msg))
        try:
            res = core.analyze(path, progress=prog)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Erreur d'analyse", str(e)))
            return
        self.res = res
        self.after(0, self.show_report)

    def show_report(self):
        self.status.config(text=os.path.basename(self.res["path"]))
        self.set_report(core.report_text(self.res))
        # bascule activée si paysage (toujours utile de pouvoir forcer)
        tw, th = self.res["trim_mm"]
        self.toggle_btn.config(state="normal" if tw > th else "disabled")

    def toggle_spread(self):
        r = self.res
        r["is_spread"] = not r["is_spread"]
        tw, th = r["trim_mm"]
        if r["is_spread"]:
            r["page_size_mm"] = (round(tw / 2, 1), th)
            r["n_final_pages"] = r["n_pdf_pages"] * 2
            r["format_single_name"] = core._match_format(tw / 2, th)
        else:
            r["page_size_mm"] = r["trim_mm"]
            r["n_final_pages"] = r["n_pdf_pages"]
        self.set_report(core.report_text(r) + "\n\n(interprétation forcée manuellement)")

    def set_report(self, text):
        self.report.config(state="normal")
        self.report.delete("1.0", "end")
        for line in text.split("\n"):
            if line.startswith("──"):
                self.report.insert("end", line + "\n", "h")
            elif "⚠" in line or "NON DÉTECTÉ" in line:
                self.report.insert("end", line + "\n", "warn")
            elif line.startswith("TOTAL"):
                self.report.insert("end", line + "\n", "ok")
            else:
                self.report.insert("end", line + "\n")
        self.report.config(state="disabled")

    # ── prévisu ──────────────────────────────────────────
    def goto(self, d):
        if not self.doc:
            return
        self.page_idx = max(0, min(len(self.doc) - 1, self.page_idx + d))
        self.render_page()

    def render_page(self):
        if not self.doc:
            return
        page = self.doc[self.page_idx]
        cw = max(self.canvas.winfo_width(), 50)
        ch = max(self.canvas.winfo_height(), 50)
        zoom = min(cw / page.rect.width, ch / page.rect.height) * 0.95
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        self._photo = tk.PhotoImage(data=pix.tobytes("ppm"))
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self._photo)
        # contour TrimBox en rouge si différent de la MediaBox
        t, m = page.trimbox, page.mediabox
        if abs(m.width - t.width) > 1 or abs(m.height - t.height) > 1:
            ox = cw // 2 - pix.width / 2
            oy = ch // 2 - pix.height / 2
            self.canvas.create_rectangle(
                ox + (t.x0 - m.x0) * zoom, oy + (t.y0 - m.y0) * zoom,
                ox + (t.x1 - m.x0) * zoom, oy + (t.y1 - m.y0) * zoom,
                outline=ACCENT, width=2, dash=(6, 3))
        self.page_lbl.config(text=f"Page {self.page_idx + 1} / {len(self.doc)}")


if __name__ == "__main__":
    App().mainloop()
