#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyse complète d'un PDF pour la prépresse :
  - Mode colorimétrique global (RVB / CMJN)
  - Présence de tons directs (Pantone, etc.)
  - Résolution par page (DPI) — pages conformes / non conformes
  - Présence et état de la surimpression (overprinting)

Dépendances (pip uniquement, pas de Homebrew) :
  pip3 install pymupdf pikepdf

Usage: python3 analyse_pdf_mail.py /chemin/vers/fichier.pdf [--json|--html out.html]
"""

import sys
import os
import json
import subprocess
import glob
from collections import defaultdict

# ── Ajouter les user site-packages du Python courant ────────────────────────
# Quand l'app est lancée depuis macOS, les packages installés avec --user
# (dans ~/Library/Python/X.Y/...) ne sont pas chargés automatiquement.
def _add_user_site():
    v = sys.version_info
    # Chemin exact pour la version courante
    paths_to_try = [
        os.path.expanduser(f'~/Library/Python/{v.major}.{v.minor}/lib/python/site-packages'),
        # Chercher toutes les versions 3.x au cas où
    ] + sorted(glob.glob(os.path.expanduser('~/Library/Python/3.*/lib/python/site-packages')), reverse=True)
    for p in paths_to_try:
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)

_add_user_site()

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False

try:
    from PIL import Image as _PIL_Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ════════════════════════════════════════════════════════════
# ANALYSE DPI PAR PAGE (via PyMuPDF — sans pdfimages)
# ════════════════════════════════════════════════════════════

def _cs_name_to_label(cs_name, n_components):
    """Convertit le nom de colorspace fitz en étiquette lisible."""
    cs = (cs_name or "").lower()
    if "cmyk" in cs or n_components == 4:
        return "cmyk", 4
    if "rgb" in cs or n_components == 3:
        return "rgb", 3
    if "gray" in cs or n_components == 1:
        return "gray", 1
    return cs or "inconnu", n_components


def analyser_dpi_par_page(pdf_path):
    """
    Retourne un dict { page_num: {"dpi_min", "dpi_max", "couleurs"} },
    une liste de toutes les images, et un set de (couleur, comp).
    Utilise get_image_info() (PyMuPDF ≥ 1.18) pour un placement précis.
    """
    import math as _math
    if not HAS_FITZ:
        return None, None, "fitz_manquant"

    pages_dpi = defaultdict(lambda: {"dpis": [], "couleurs": set()})
    toutes_couleurs = set()
    toutes_images = []

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return {}, [], set()

    # Collecter les xrefs SMask (alpha) pour les exclure
    smask_xrefs = set()
    for pg in doc:
        for info in pg.get_images(full=True):
            if info[1] > 0:
                smask_xrefs.add(info[1])

    for page_idx in range(len(doc)):
        page     = doc[page_idx]
        page_num = page_idx + 1

        # get_image_info() donne la matrice de transformation exacte par page
        try:
            img_infos = page.get_image_info(xrefs=True)
        except TypeError:
            try:
                img_infos = page.get_image_info()
            except Exception:
                img_infos = []

        seen_xrefs = set()
        for info in img_infos:
            xref = info.get("xref", 0)
            if not xref or xref in smask_xrefs or xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            w_px = info.get("width",  0)
            h_px = info.get("height", 0)
            if w_px < 8 or h_px < 8:
                continue  # ignorer les images déco/pixel

            # Calculer la taille rendue via la matrice CTM (plus précis que get_image_rects)
            transform = info.get("transform")
            if transform:
                # transform peut être fitz.Matrix (attributs .a/.b) ou tuple (a,b,c,d,e,f)
                if hasattr(transform, 'a'):
                    a, b, c, d = transform.a, transform.b, transform.c, transform.d
                else:
                    a, b, c, d = transform[0], transform[1], transform[2], transform[3]
                w_pts = _math.sqrt(a*a + b*b)
                h_pts = _math.sqrt(c*c + d*d)
            else:
                bbox = info.get("bbox")
                if bbox:
                    w_pts = abs(bbox[2] - bbox[0])
                    h_pts = abs(bbox[3] - bbox[1])
                else:
                    continue

            if w_pts < 0.5 or h_pts < 0.5:
                continue

            dpi_x   = w_px / (w_pts / 72.0)
            dpi_y   = h_px / (h_pts / 72.0)
            dpi_eff = min(dpi_x, dpi_y)   # on retient le pire axe

            if not (10 < dpi_eff < 10000):
                continue

            # Info couleur via extract_image
            try:
                base    = doc.extract_image(xref)
                cs_name = base.get("cs-name", "")
                n_comp  = base.get("colorspace", 0)
            except Exception:
                cs_name, n_comp = "", 0

            label, comp = _cs_name_to_label(cs_name, n_comp)
            pages_dpi[page_num]["dpis"].append(dpi_eff)
            pages_dpi[page_num]["couleurs"].add(label)
            toutes_couleurs.add((label, comp))
            toutes_images.append({
                "page":    page_num,
                "color":   label,
                "comp":    comp,
                "x_ppi":   dpi_x,
                "y_ppi":   dpi_y,
                "dpi_moy": dpi_eff,
            })

    doc.close()

    # Résumer par page
    resultats_pages = {}
    for page_num, data in sorted(pages_dpi.items()):
        dpis = data["dpis"]
        resultats_pages[page_num] = {
            "dpi_min": min(dpis),
            "dpi_max": max(dpis),
            "dpi_moy": sum(dpis) / len(dpis),
            "conforme_300": min(dpis) >= 280,   # tolérance de calcul ±7%
            "couleurs": data["couleurs"],
        }

    return resultats_pages, toutes_images, toutes_couleurs


# ════════════════════════════════════════════════════════════
# ANALYSE COLORIMÉTRIQUE & TONS DIRECTS (via pikepdf)
# ════════════════════════════════════════════════════════════

def analyser_couleurs_et_tons_directs(pdf_path):
    """
    Retourne :
      - mode_global : "CMJN" / "RVB" / "Mixte" / "Vectoriel" / "Inconnu"
      - tons_directs : list de noms (ex: ["Pantone 485 C", "PANTONE Cool Gray 11 C"])
      - surimpression : list de dicts {page, gs_name, fill, stroke}
    """
    if not HAS_PIKEPDF:
        return "Inconnu", [], []

    tons_directs = set()
    surimpression_active = []

    try:
        with pikepdf.open(pdf_path) as pdf:
            nb_pages = len(pdf.pages)

            for page_num, page in enumerate(pdf.pages, start=1):
                if "/Resources" not in page:
                    continue
                res = page["/Resources"]

                # ── Tons directs ──────────────────────────────
                if "/ColorSpace" in res:
                    cs_dict = res["/ColorSpace"]
                    try:
                        for name in cs_dict.keys():
                            cs = cs_dict[name]
                            _extraire_ton_direct(cs, tons_directs)
                    except Exception:
                        pass

                # ── Tons directs dans les XObjects ────────────
                if "/XObject" in res:
                    xobjs = res["/XObject"]
                    try:
                        for xname in xobjs.keys():
                            xobj = xobjs[xname]
                            if xobj.get("/Subtype") == "/Form":
                                if "/Resources" in xobj:
                                    xres = xobj["/Resources"]
                                    if "/ColorSpace" in xres:
                                        for csn in xres["/ColorSpace"].keys():
                                            _extraire_ton_direct(xres["/ColorSpace"][csn], tons_directs)
                    except Exception:
                        pass

                # ── Surimpression (ExtGState) ──────────────────
                if "/ExtGState" in res:
                    try:
                        gstates = res["/ExtGState"]
                        for gs_name in gstates.keys():
                            gs = gstates[gs_name]
                            op_fill   = gs.get("/OP", False)
                            op_stroke = gs.get("/op", False)
                            opm       = gs.get("/OPM", 0)

                            # Convertir en bool (pikepdf renvoie pikepdf.Object)
                            try:
                                op_fill_bool   = bool(op_fill)
                                op_stroke_bool = bool(op_stroke)
                            except Exception:
                                continue

                            if op_fill_bool or op_stroke_bool:
                                surimpression_active.append({
                                    "page":   page_num,
                                    "gs":     str(gs_name),
                                    "fill":   op_fill_bool,
                                    "stroke": op_stroke_bool,
                                    "opm":    int(str(opm)) if str(opm).isdigit() else 0
                                })
                    except Exception:
                        pass

    except Exception as e:
        return "Erreur lecture PDF", [], []

    return list(tons_directs), surimpression_active


def _extraire_ton_direct(cs, ensemble_tons):
    """Extrait les noms de tons directs d'un objet colorspace pikepdf."""
    try:
        if not isinstance(cs, pikepdf.Array):
            return
        if len(cs) < 2:
            return
        cs_type = str(cs[0])

        if cs_type == "/Separation":
            # Structure: [/Separation /NomEncre /EspaceAlternate fonction]
            nom = str(cs[1]).lstrip("/")
            if nom not in ("None", "All"):
                ensemble_tons.add(nom)

        elif cs_type == "/DeviceN":
            # Structure: [/DeviceN [/Encre1 /Encre2 ...] /EspaceAlternate fonction]
            noms_array = cs[1]
            if isinstance(noms_array, pikepdf.Array):
                for n in noms_array:
                    nom = str(n).lstrip("/")
                    if nom not in ("None", "All", "Cyan", "Magenta", "Yellow", "Black",
                                   "Red", "Green", "Blue"):
                        ensemble_tons.add(nom)
    except Exception:
        pass


# ════════════════════════════════════════════════════════════
# MINIATURES TOUTES PAGES + DÉTECTION TYPE DOCUMENT
# ════════════════════════════════════════════════════════════

def _detecter_type_document(n_pages, formats):
    """Détermine le type de document selon nombre de pages et formats."""
    from collections import Counter
    fmt = Counter(formats).most_common(1)[0][0] if formats else "A4"
    grands = ("A0","A1","A2","A3","B0","B1","B2","Tabloid")
    est_grand = any(g in fmt for g in grands)
    if n_pages == 1:
        return "Affiche" if est_grand else "Flyer"
    elif n_pages == 2:
        return "Affiche recto-verso" if est_grand else "Flyer recto-verso"
    elif n_pages == 3:
        return "Dépliant 3 volets"
    elif n_pages == 4:
        return "Dépliant / Carte"
    elif n_pages <= 8:
        return "Plaquette"
    elif n_pages <= 24:
        return "Brochure"
    elif n_pages <= 64:
        return "Catalogue"
    else:
        return "Catalogue / Livre"

def generer_miniatures_fond_perdu(pdf_path, fond_perdu_data):
    """
    Génère des miniatures pour TOUTES les pages du document.
    Retourne (liste_miniatures, type_document).
    """
    import base64
    if not HAS_FITZ:
        return [], "inconnu"

    # Mapping page_num → infos bleed
    bleed_map = {}
    if fond_perdu_data.get('disponible'):
        for p in fond_perdu_data.get('pages', []):
            bleed_map[p['page']] = p

    thumbnails = []
    type_doc   = "inconnu"
    MAX_PAGES  = 24

    try:
        doc    = fitz.open(pdf_path)
        n      = len(doc)
        # Choisir la largeur de rendu selon le nombre de pages
        if   n <= 2:  render_w = 600
        elif n <= 4:  render_w = 560
        elif n <= 8:  render_w = 520
        elif n <= 16: render_w = 500
        else:         render_w = 480

        formats = []
        for page_idx in range(min(n, MAX_PAGES)):
            page  = doc[page_idx]
            pnum  = page_idx + 1
            w_mm  = round(page.rect.width  * 25.4 / 72, 1)
            h_mm  = round(page.rect.height * 25.4 / 72, 1)
            fmt   = _detecter_format(w_mm, h_mm)
            formats.append(fmt)

            scale = render_w / max(page.rect.width, 1)
            mat   = fitz.Matrix(scale, scale)
            pix   = page.get_pixmap(matrix=mat, alpha=False)
            b64   = base64.b64encode(pix.tobytes("png")).decode('ascii')

            pinfo = bleed_map.get(pnum, {})
            thumbnails.append({
                'page':          pnum,
                'img':           b64,
                'w':             pix.width,
                'h':             pix.height,
                'px_per_mm':     round(pix.width / w_mm, 4) if w_mm else 0,
                'bleed_left':    pinfo.get('bleed_left',   None),
                'bleed_right':   pinfo.get('bleed_right',  None),
                'bleed_top':     pinfo.get('bleed_top',    None),
                'bleed_bottom':  pinfo.get('bleed_bottom', None),
                'w_mm':          w_mm,
                'h_mm':          h_mm,
                'format':        fmt,
                'conforme':      pinfo.get('conforme', None),
                'has_bleed':     bool(pinfo),
            })

        if n > MAX_PAGES:
            thumbnails.append({'more': n - MAX_PAGES})

        type_doc = _detecter_type_document(n, formats)
        doc.close()
    except Exception:
        pass

    return thumbnails, type_doc


# ════════════════════════════════════════════════════════════
# TAILLE DES PAGES & DÉTECTION FORMAT
# ════════════════════════════════════════════════════════════

_FORMATS_STD = [
    ("A0",841,1189),("A1",594,841),("A2",420,594),("A3",297,420),
    ("A4",210,297),("A5",148,210),("A6",105,148),
    ("B0",1000,1414),("B1",707,1000),("B2",500,707),("B3",353,500),
    ("B4",250,353),("B5",176,250),
    ("Letter",216,279),("Legal",216,356),("Tabloid",279,432),
]

def _detecter_format(w_mm, h_mm, tol=2.5):
    pw, ph = min(w_mm,h_mm), max(w_mm,h_mm)
    for nom,fw,fh in _FORMATS_STD:
        if abs(pw-fw)<=tol and abs(ph-fh)<=tol:
            return f"{nom} {'portrait' if w_mm<=h_mm else 'paysage'}"
    return None

def analyser_tailles_pages(pdf_path):
    if not HAS_PIKEPDF:
        return {"disponible": False, "pages": []}
    pages_sizes = []
    try:
        with pikepdf.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                box = (page.get("/TrimBox") or page.get("/CropBox") or page.get("/MediaBox"))
                if box is None:
                    continue
                try:
                    coords = [float(str(v)) for v in box]
                    x0,y0,x1,y1 = coords
                    w_mm = round(abs(x1-x0)*_PT_TO_MM, 1)
                    h_mm = round(abs(y1-y0)*_PT_TO_MM, 1)
                    fmt  = _detecter_format(w_mm, h_mm)
                    pages_sizes.append({
                        "page": page_num, "w_mm": w_mm, "h_mm": h_mm,
                        "format": fmt or f"{w_mm}×{h_mm} mm",
                    })
                except Exception:
                    continue
    except Exception:
        return {"disponible": True, "pages": []}
    if not pages_sizes:
        return {"disponible": True, "pages": []}
    tailles = set((p["w_mm"],p["h_mm"]) for p in pages_sizes)
    formats = [p["format"] for p in pages_sizes]
    return {
        "disponible":        True,
        "pages":             pages_sizes,
        "toutes_identiques": len(tailles)==1,
        "format_principal":  max(set(formats), key=formats.count),
        "nb_formats":        len(tailles),
        "w_mm":              pages_sizes[0]["w_mm"],
        "h_mm":              pages_sizes[0]["h_mm"],
    }


# ════════════════════════════════════════════════════════════
# TRANSPARENCE (via pikepdf)
# ════════════════════════════════════════════════════════════

def analyser_transparence(pdf_path):
    """
    Détecte la transparence active dans le PDF :
    - Opacité partielle (ca/CA < 1 dans ExtGState)
    - Masques doux (SMask)
    - Modes de fusion non-Normal (BlendMode)
    - XObjects avec groupe de transparence
    Si aucun marqueur trouvé → probablement pas de transparence
    (ou transparence déjà aplatie/rasterisée).
    """
    if not HAS_PIKEPDF:
        return {"disponible": False, "a_transparence": False, "details": [], "aplatie_possible": False}

    details = []
    pages_concernees = set()

    def _check_extgstate(gs_dict, page_num):
        for gs_name in gs_dict.keys():
            try:
                gs = gs_dict[gs_name]
                ca   = float(str(gs.get("/ca",  "1")))
                CA   = float(str(gs.get("/CA",  "1")))
                bm   = str(gs.get("/BM",  "/Normal")).strip()
                smask = "/SMask" in gs and str(gs["/SMask"]) != "/None"

                types_found = []
                if ca < 0.999:
                    types_found.append(f"opacité fond {ca:.0%}")
                if CA < 0.999:
                    types_found.append(f"opacité contour {CA:.0%}")
                if smask:
                    types_found.append("masque doux (SMask)")
                if bm not in ("/Normal", "Normal", "/Compatible", "Compatible"):
                    types_found.append(f"fusion {bm.lstrip('/')}")

                if types_found:
                    pages_concernees.add(page_num)
                    details.append({
                        "page": page_num,
                        "gs": str(gs_name),
                        "types": types_found
                    })
            except Exception:
                continue

    try:
        with pikepdf.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                res = page.get("/Resources")
                if res is None:
                    continue

                # ExtGState de la page
                gs_dict = res.get("/ExtGState")
                if gs_dict:
                    _check_extgstate(gs_dict, page_num)

                # XObjects (Form XObjects peuvent contenir de la transparence)
                xobjs = res.get("/XObject")
                if xobjs:
                    for xname in xobjs.keys():
                        try:
                            xobj = xobjs[xname]
                            if str(xobj.get("/Subtype", "")) == "/Form":
                                # Groupe de transparence
                                grp = xobj.get("/Group")
                                if grp and str(grp.get("/S", "")) == "/Transparency":
                                    pages_concernees.add(page_num)
                                    details.append({
                                        "page": page_num,
                                        "gs": str(xname),
                                        "types": ["groupe de transparence (XObject)"]
                                    })
                                # ExtGState dans le XObject
                                xres = xobj.get("/Resources")
                                if xres:
                                    xgs = xres.get("/ExtGState")
                                    if xgs:
                                        _check_extgstate(xgs, page_num)
                        except Exception:
                            continue
    except Exception:
        return {"disponible": True, "a_transparence": False, "details": [], "aplatie_possible": False}

    a_transparence = len(details) > 0
    return {
        "disponible":      True,
        "a_transparence":  a_transparence,
        "pages":           sorted(pages_concernees),
        "details":         details,
        # Si aucune transparence détectée dans un PDF complexe → peut-être aplatie
        "aplatie_possible": not a_transparence
    }


# ════════════════════════════════════════════════════════════
# FOND PERDU (via pikepdf)
# ════════════════════════════════════════════════════════════

_PT_TO_MM = 0.352778  # 1 point = 0.352778 mm

def _box_to_list(box):
    """Convertit un pikepdf Array en liste de floats [x0, y0, x1, y1]."""
    try:
        return [float(str(v)) for v in box]
    except Exception:
        return None

def analyser_fond_perdu(pdf_path):
    """
    Analyse le fond perdu (bleed) page par page via les boxes PDF :
    - MediaBox  : taille totale de la page (avec fond perdu)
    - TrimBox   : taille de découpe finale
    - BleedBox  : zone de fond perdu définie explicitement
    Bleed minimum recommandé : 3 mm = 8.504 pts
    """
    if not HAS_PIKEPDF:
        return {"disponible": False, "pages": [], "global_ok": False}

    MIN_BLEED_MM = 3.0
    MIN_BLEED_PT = MIN_BLEED_MM / _PT_TO_MM  # ≈ 8.5 pts

    pages_info = []
    try:
        with pikepdf.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                # Récupérer les boxes (en cherchant aussi dans les parents)
                def get_box(key):
                    v = page.get(key)
                    if v is not None:
                        return _box_to_list(v)
                    return None

                media = get_box("/MediaBox")
                trim  = get_box("/TrimBox")
                bleed = get_box("/BleedBox")
                crop  = get_box("/CropBox")

                if media is None:
                    continue

                # Normaliser (certains PDF ont x0>x1 ou y0>y1)
                def norm(b):
                    if b is None: return None
                    x0,y0,x1,y1 = b
                    return [min(x0,x1), min(y0,y1), max(x0,x1), max(y0,y1)]

                media = norm(media)
                trim  = norm(trim)
                bleed = norm(bleed)
                crop  = norm(crop)

                # Référence de découpe
                ref = trim or crop or media

                # Taille de page en mm
                w_mm = (media[2] - media[0]) * _PT_TO_MM
                h_mm = (media[3] - media[1]) * _PT_TO_MM
                tw_mm = (ref[2] - ref[0]) * _PT_TO_MM
                th_mm = (ref[3] - ref[1]) * _PT_TO_MM

                # Calcul fond perdu
                if bleed:
                    # Utiliser le BleedBox
                    left   = (ref[0] - bleed[0]) * _PT_TO_MM
                    bottom = (ref[1] - bleed[1]) * _PT_TO_MM
                    right  = (bleed[2] - ref[2]) * _PT_TO_MM
                    top    = (bleed[3] - ref[3]) * _PT_TO_MM
                elif trim:
                    # Calculer depuis MediaBox vs TrimBox
                    left   = (trim[0] - media[0]) * _PT_TO_MM
                    bottom = (trim[1] - media[1]) * _PT_TO_MM
                    right  = (media[2] - trim[2]) * _PT_TO_MM
                    top    = (media[3] - trim[3]) * _PT_TO_MM
                else:
                    # Pas de TrimBox → on ne peut pas déterminer le fond perdu
                    left = bottom = right = top = 0.0

                # Arrondir
                left   = round(max(left,   0), 1)
                bottom = round(max(bottom, 0), 1)
                right  = round(max(right,  0), 1)
                top    = round(max(top,    0), 1)
                min_bleed = min(left, bottom, right, top)

                has_trim = trim is not None
                has_bleed_box = bleed is not None
                conforme = min_bleed >= MIN_BLEED_MM if has_trim or has_bleed_box else None

                pages_info.append({
                    "page":        page_num,
                    "w_mm":        round(tw_mm, 1),
                    "h_mm":        round(th_mm, 1),
                    "bleed_left":  left,
                    "bleed_right": right,
                    "bleed_top":   top,
                    "bleed_bottom":bottom,
                    "bleed_min":   min_bleed,
                    "has_trim":    has_trim,
                    "has_bleed_box": has_bleed_box,
                    "conforme":    conforme,
                })
    except Exception:
        return {"disponible": True, "pages": [], "global_ok": False}

    # Résumé global
    pages_avec_trim = [p for p in pages_info if p["has_trim"] or p["has_bleed_box"]]
    pages_ko = [p for p in pages_avec_trim if p["conforme"] is False]
    pages_sans_info = [p for p in pages_info if not p["has_trim"] and not p["has_bleed_box"]]

    global_ok = len(pages_avec_trim) > 0 and len(pages_ko) == 0

    return {
        "disponible":       True,
        "pages":            pages_info,
        "pages_ko":         pages_ko,
        "pages_sans_info":  pages_sans_info,
        "global_ok":        global_ok,
        "min_bleed_global": min((p["bleed_min"] for p in pages_avec_trim), default=0),
        "has_trim_box":     any(p["has_trim"] for p in pages_info),
    }


# ════════════════════════════════════════════════════════════
# DÉTERMINER LE MODE COULEUR GLOBAL
# ════════════════════════════════════════════════════════════

def determiner_mode_global(toutes_couleurs_images):
    """
    Détermine si le document est globalement RVB, CMJN ou mixte,
    à partir des couleurs des images raster.
    """
    if not toutes_couleurs_images:
        return "Vectoriel"

    a_rvb  = False
    a_cmjn = False

    for (couleur, comp) in toutes_couleurs_images:
        if "cmyk" in couleur or comp == 4:
            a_cmjn = True
        elif "rgb" in couleur or comp == 3:
            a_rvb = True
        elif "icc" in couleur:
            # ICC : 4 composantes = CMJN, 3 = RVB
            if comp == 4:
                a_cmjn = True
            elif comp == 3:
                a_rvb = True
        elif "gray" in couleur or "grey" in couleur:
            pass  # Niveaux de gris = neutre

    if a_cmjn and not a_rvb:
        return "CMJN"
    elif a_rvb and not a_cmjn:
        return "RVB"
    elif a_rvb and a_cmjn:
        return "Mixte RVB+CMJN"
    else:
        return "Niveaux de gris / Vectoriel"


# ════════════════════════════════════════════════════════════
# INFOS GÉNÉRALES (via PyMuPDF — sans outil système)
# ════════════════════════════════════════════════════════════

def infos_generales(pdf_path):
    info = {}
    if HAS_FITZ:
        try:
            doc = fitz.open(pdf_path)
            meta = doc.metadata or {}
            info["Pages"]    = str(len(doc.pages))
            info["Creator"]  = meta.get("creator", "?")
            info["Producer"] = meta.get("producer", "?")
            info["Title"]    = meta.get("title", "")
            doc.close()
        except Exception:
            pass
    return info


# ════════════════════════════════════════════════════════════
# ANALYSE PRINCIPALE
# ════════════════════════════════════════════════════════════

def analyser_pdf(pdf_path):
    if not os.path.exists(pdf_path):
        return {"erreur": f"Fichier introuvable : {pdf_path}"}

    if not HAS_FITZ:
        return {"erreur": "PyMuPDF (fitz) requis — pip3 install pymupdf"}

    nom = os.path.basename(pdf_path)
    res = {"fichier": nom, "chemin": pdf_path}

    # ── Infos générales ──────────────────────────────────────
    meta = infos_generales(pdf_path)
    res["pages_total"]    = int(meta.get("Pages", 0))
    res["createur"]       = meta.get("Creator", "?")
    res["producteur"]     = meta.get("Producer", "?")
    res["taille_fichier"] = os.path.getsize(pdf_path)

    # ── DPI par page (PyMuPDF) ───────────────────────────────
    pages_dpi, toutes_images, toutes_couleurs = analyser_dpi_par_page(pdf_path)

    if pages_dpi is None:
        res["erreur_fitz"] = "PyMuPDF introuvable — pip3 install pymupdf"
        pages_dpi = {}
        toutes_images = []
        toutes_couleurs = set()

    res["pages_dpi"]       = pages_dpi
    res["a_images_raster"] = len(toutes_images) > 0

    # Pages non conformes (< 300 DPI)
    pages_ko = {p: d for p, d in pages_dpi.items() if not d["conforme_300"]}
    pages_ok = {p: d for p, d in pages_dpi.items() if d["conforme_300"]}
    res["pages_ko"]  = pages_ko
    res["pages_ok"]  = pages_ok
    res["nb_pages_ko"] = len(pages_ko)
    res["nb_pages_ok"] = len(pages_ok)

    # DPI min global
    toutes_dpis = [img["dpi_moy"] for img in toutes_images]
    res["dpi_global_min"] = min(toutes_dpis) if toutes_dpis else None
    res["dpi_global_max"] = max(toutes_dpis) if toutes_dpis else None

    # ── Mode couleur global ──────────────────────────────────
    res["mode_couleur"] = determiner_mode_global(toutes_couleurs)

    # ── Tons directs & Surimpression (pikepdf) ───────────────
    if HAS_PIKEPDF:
        tons_directs, surimpression = analyser_couleurs_et_tons_directs(pdf_path)
        res["tons_directs"]   = tons_directs
        res["surimpression"]  = surimpression
        res["a_tons_directs"] = len(tons_directs) > 0
        res["a_surimpression"] = len(surimpression) > 0
    else:
        res["tons_directs"]    = []
        res["surimpression"]   = []
        res["a_tons_directs"]  = False
        res["a_surimpression"] = False

    # ── Transparence (pikepdf) ───────────────────────────────
    res["transparence"] = analyser_transparence(pdf_path)

    # ── Fond perdu / Bleed (pikepdf) ─────────────────────────
    res["fond_perdu"] = analyser_fond_perdu(pdf_path)

    # ── Miniatures fond perdu (PyMuPDF) ──────────────────────
    _miniatures, _type_doc = generer_miniatures_fond_perdu(pdf_path, res["fond_perdu"])
    res["miniatures_fp"]  = _miniatures
    res["type_document"]  = _type_doc

    # ── Tailles des pages ────────────────────────────────────
    res["tailles_pages"] = analyser_tailles_pages(pdf_path)

    # ── Verdicts ─────────────────────────────────────────────
    res["verdicts"] = construire_verdicts(res)
    return res


def construire_verdicts(res):
    v = {}

    # ─ Couleur ───────────────────────────────────────────────
    mode = res["mode_couleur"]
    if "CMJN" in mode and "RVB" not in mode:
        v["couleur"] = ("✅", "CMJN — Conforme pour l'impression offset")
    elif "RVB" in mode and "CMJN" not in mode:
        v["couleur"] = ("❌", "RVB — Non conforme, conversion CMJN nécessaire")
    elif "Mixte" in mode:
        v["couleur"] = ("⚠️", "Mixte RVB + CMJN — Vérification recommandée")
    elif "Vectoriel" in mode or "Gris" in mode:
        v["couleur"] = ("✅", f"{mode} — OK")
    else:
        v["couleur"] = ("⚠️", mode)

    # ─ DPI ───────────────────────────────────────────────────
    if not res["a_images_raster"]:
        v["dpi"] = ("✅", "PDF vectoriel — DPI non applicable")
    elif res["nb_pages_ko"] == 0:
        v["dpi"] = ("✅", f"Toutes les pages ≥ 300 DPI (min : {res['dpi_global_min']:.0f} DPI)")
    else:
        pages_ko_list = sorted(res["pages_ko"].keys())
        nb_total = res["pages_total"] or (res["nb_pages_ko"] + res["nb_pages_ok"])
        msg = (f"{res['nb_pages_ko']} page(s) sous 300 DPI sur {nb_total} — "
               f"Pages : {', '.join(str(p) for p in pages_ko_list[:10])}"
               + (" ..." if len(pages_ko_list) > 10 else ""))
        v["dpi"] = ("❌", msg)

    # ─ Tons directs ──────────────────────────────────────────
    if res["a_tons_directs"]:
        noms = ", ".join(sorted(res["tons_directs"])[:8])
        if len(res["tons_directs"]) > 8:
            noms += f" ... (+{len(res['tons_directs'])-8} autres)"
        v["tons_directs"] = ("⚠️", f"Tons directs détectés ({len(res['tons_directs'])}) : {noms}")
    else:
        v["tons_directs"] = ("✅", "Aucun ton direct — Quadrichromie pure")

    # ─ Surimpression ─────────────────────────────────────────
    if res["a_surimpression"]:
        pages_suri = sorted(set(s["page"] for s in res["surimpression"]))
        fill_count   = sum(1 for s in res["surimpression"] if s["fill"])
        stroke_count = sum(1 for s in res["surimpression"] if s["stroke"])
        details = []
        if fill_count:   details.append(f"fond ×{fill_count}")
        if stroke_count: details.append(f"contour ×{stroke_count}")
        msg = (f"Surimpression ACTIVE sur {len(pages_suri)} page(s) "
               f"({', '.join(details)}) — Pages : "
               f"{', '.join(str(p) for p in pages_suri[:10])}"
               + (" ..." if len(pages_suri) > 10 else ""))
        v["surimpression"] = ("⚠️", msg)
    else:
        if HAS_PIKEPDF:
            v["surimpression"] = ("✅", "Aucune surimpression détectée")
        else:
            v["surimpression"] = ("ℹ️", "Surimpression : analyse non disponible (pikepdf manquant)")

    # ─ Transparence ──────────────────────────────────────────
    tr = res.get("transparence", {})
    if not tr.get("disponible", False):
        v["transparence"] = ("ℹ️", "Analyse non disponible (pikepdf manquant)")
    elif tr.get("a_transparence"):
        pages_tr = tr.get("pages", [])
        nb = len(pages_tr)
        v["transparence"] = ("⚠️",
            f"Transparence ACTIVE sur {nb} page(s) — Pages : "
            + ", ".join(str(p) for p in pages_tr[:10])
            + (" ..." if nb > 10 else "")
            + " — À aplatir avant flashage")
    else:
        v["transparence"] = ("✅", "Aucune transparence active détectée (ou déjà aplatie)")

    # ─ Fond perdu ────────────────────────────────────────────
    fp = res.get("fond_perdu", {})
    if not fp.get("disponible", False):
        v["fond_perdu"] = ("ℹ️", "Analyse non disponible (pikepdf manquant)")
    elif not fp.get("has_trim_box", False):
        v["fond_perdu"] = ("⚠️", "Pas de TrimBox définie — fond perdu non vérifiable")
    elif fp.get("global_ok"):
        mb = fp.get("min_bleed_global", 0)
        v["fond_perdu"] = ("✅", f"Fond perdu conforme — min. {mb:.1f} mm (≥ 3 mm)")
    else:
        pages_ko = fp.get("pages_ko", [])
        nb = len(pages_ko)
        mins = [f"p.{p['page']}={p['bleed_min']:.1f}mm" for p in pages_ko[:5]]
        v["fond_perdu"] = ("❌",
            f"Fond perdu insuffisant sur {nb} page(s) — "
            + ", ".join(mins)
            + (" ..." if nb > 5 else "")
            + " (minimum requis : 3 mm)")

    # ─ Tailles pages ─────────────────────────────────────────
    tp = res.get("tailles_pages", {})
    if not tp.get("disponible"):
        v["tailles"] = ("ℹ️", "Analyse non disponible")
    elif not tp.get("pages"):
        v["tailles"] = ("ℹ️", "Aucune information de taille trouvée")
    elif tp.get("toutes_identiques"):
        v["tailles"] = ("✅", f"{tp['format_principal']} — {tp['w_mm']}×{tp['h_mm']} mm — Toutes les pages identiques")
    else:
        v["tailles"] = ("⚠️", f"{tp['nb_formats']} formats différents détectés — format principal : {tp['format_principal']}")

    # ─ Conformité globale ─────────────────────────────────────
    ok_couleur = v["couleur"][0] in ("✅",)
    ok_dpi     = v["dpi"][0]    in ("✅",)
    ok_fp      = v["fond_perdu"][0] in ("✅", "ℹ️")
    if ok_couleur and ok_dpi and ok_fp:
        v["global"] = ("✅", "CONFORME — Prêt pour l'impression")
    else:
        raisons = []
        if not ok_couleur: raisons.append("couleur")
        if not ok_dpi:     raisons.append("résolution")
        if not ok_fp:      raisons.append("fond perdu")
        v["global"] = ("❌", f"NON CONFORME — Problème(s) : {', '.join(raisons)}")

    return v


# ════════════════════════════════════════════════════════════
# FORMATAGE TEXTE (pour affichage dans Apple Mail / terminal)
# ════════════════════════════════════════════════════════════

def formater_rapport_texte(res):
    if "erreur" in res:
        return f"Erreur : {res['erreur']}"

    v = res.get("verdicts", {})
    taille_mo = res["taille_fichier"] / 1024 / 1024

    lignes = [
        f"📄 {res['fichier']}",
        f"   Pages : {res['pages_total']}  •  Taille : {taille_mo:.1f} Mo",
        f"   Créé avec : {res['createur']}",
        "",
        "─── Mode colorimétrique ───",
        f"{v.get('couleur', ('?','?'))[0]} {v.get('couleur', ('?','?'))[1]}",
        "",
        "─── Tons directs ───",
        f"{v.get('tons_directs', ('?','?'))[0]} {v.get('tons_directs', ('?','?'))[1]}",
    ]
    if res.get("a_tons_directs") and res["tons_directs"]:
        for t in sorted(res["tons_directs"])[:5]:
            lignes.append(f"   • {t}")
        if len(res["tons_directs"]) > 5:
            lignes.append(f"   ... +{len(res['tons_directs'])-5} autres")

    lignes += [
        "",
        "─── Résolution (DPI) ───",
        f"{v.get('dpi', ('?','?'))[0]} {v.get('dpi', ('?','?'))[1]}",
    ]

    # Détail pages sous 300 DPI
    if res.get("pages_ko"):
        lignes.append("   Détail pages non conformes :")
        for page_num in sorted(res["pages_ko"].keys())[:15]:
            d = res["pages_ko"][page_num]
            lignes.append(f"   • Page {page_num} : {d['dpi_min']:.0f} DPI (min)")

    lignes += [
        "",
        "─── Surimpression ───",
        f"{v.get('surimpression', ('?','?'))[0]} {v.get('surimpression', ('?','?'))[1]}",
        "",
        "════════════════════════",
        f"{v.get('global', ('?','?'))[0]} {v.get('global', ('?','?'))[1]}",
    ]

    return "\n".join(lignes)


# ════════════════════════════════════════════════════════════
# GÉNÉRATEUR RAPPORT HTML
# ════════════════════════════════════════════════════════════

def generer_rapport_html(resultats_liste, nom_projet, chemin_sortie):
    """
    Génère un rapport HTML multi-fichiers complet.
    resultats_liste : liste de dict retournés par analyser_pdf()
    """
    from datetime import datetime
    date_str = datetime.now().strftime("%d/%m/%Y à %H:%M")

    def badge(icone, texte, classe):
        return f'<span class="badge {classe}">{icone} {texte}</span>'

    def icone_to_class(icone):
        if icone == "✅": return "ok"
        if icone == "❌": return "ko"
        return "warn"

    # ── Tableau récapitulatif ─────────────────────────────────
    nb_total    = len(resultats_liste)
    nb_conformes = sum(1 for r in resultats_liste
                       if r.get("verdicts", {}).get("global", ("❌",))[0] == "✅")
    nb_ko       = nb_total - nb_conformes

    # ── Lignes du tableau ─────────────────────────────────────
    lignes_tableau = ""
    sections_detail = ""

    for i, res in enumerate(resultats_liste):
        v = res.get("verdicts", {})
        nom = res.get("fichier", "?")
        taille_mo = res.get("taille_fichier", 0) / 1024 / 1024
        conforme = v.get("global", ("❌",))[0] == "✅"
        row_class = "row-ok" if conforme else "row-ko"
        anchor = f"detail_{i}"

        # Badges pour le tableau récap
        bd_couleur = badge(*v.get("couleur", ("⚠️","?")), icone_to_class(v.get("couleur",("⚠️",))[0]))
        bd_dpi     = badge(*v.get("dpi",     ("⚠️","?")), icone_to_class(v.get("dpi",    ("⚠️",))[0]))
        bd_tons    = badge(*v.get("tons_directs",("ℹ️","?")), icone_to_class(v.get("tons_directs",("✅",))[0]))
        bd_suri    = badge(*v.get("surimpression",("ℹ️","?")), icone_to_class(v.get("surimpression",("✅",))[0]))
        bd_global  = badge(*v.get("global",  ("⚠️","?")), icone_to_class(v.get("global", ("⚠️",))[0]))

        lignes_tableau += f"""
        <tr class="{row_class}">
          <td><a href="#{anchor}" class="filename">📄 {nom}</a><br>
              <small style="color:#888">{res.get('pages_total','?')} p. • {taille_mo:.1f} Mo</small></td>
          <td>{bd_couleur}</td>
          <td>{bd_dpi}</td>
          <td>{bd_tons}</td>
          <td>{bd_suri}</td>
          <td>{bd_global}</td>
        </tr>"""

        # ── Section de détail par fichier ──────────────────────
        # Tableau DPI par page
        pages_dpi = res.get("pages_dpi", {})
        lignes_dpi = ""
        if pages_dpi:
            for page_num in sorted(pages_dpi.keys()):
                d = pages_dpi[page_num]
                ok = d["conforme_300"]
                cls = "dpi-ok" if ok else "dpi-ko"
                icn = "✅" if ok else "❌"
                lignes_dpi += f"""<tr class="{cls}">
                  <td>Page {page_num}</td>
                  <td>{d['dpi_min']:.0f}</td>
                  <td>{d['dpi_max']:.0f}</td>
                  <td>{icn} {'≥ 300' if ok else '< 300 ⚠️'}</td>
                  <td>{', '.join(d.get('couleurs', set()))}</td>
                </tr>"""

        # Tons directs
        tons_html = ""
        if res.get("a_tons_directs"):
            tons_html = "<ul class='tons-list'>" + "".join(
                f"<li>🎨 {t}</li>" for t in sorted(res["tons_directs"])
            ) + "</ul>"
        else:
            tons_html = "<p class='ok-msg'>✅ Aucun ton direct — Quadrichromie pure</p>"

        # Surimpression
        suri_html = ""
        surims = res.get("surimpression", [])
        if surims:
            pages_suri = sorted(set(s["page"] for s in surims))
            suri_html = f"""<div class='warn-box'>
              <p>⚠️ Surimpression active sur <strong>{len(pages_suri)} page(s)</strong></p>
              <p>Pages concernées : {', '.join(str(p) for p in pages_suri[:30])}{'…' if len(pages_suri)>30 else ''}</p>
              <table class='mini-table'><thead><tr><th>Page</th><th>État fond</th><th>État contour</th></tr></thead><tbody>"""
            seen = set()
            for s in surims[:20]:
                key = (s["page"], s["fill"], s["stroke"])
                if key not in seen:
                    seen.add(key)
                    suri_html += f"<tr><td>Page {s['page']}</td><td>{'🔴 Actif' if s['fill'] else '—'}</td><td>{'🔴 Actif' if s['stroke'] else '—'}</td></tr>"
            suri_html += "</tbody></table></div>"
        else:
            suri_html = "<p class='ok-msg'>✅ Aucune surimpression détectée</p>"

        # Badge global pour la section
        g_icn, g_txt = v.get("global", ("❌", "NON CONFORME"))
        g_cls = "ok" if g_icn == "✅" else "ko"

        sections_detail += f"""
      <section id="{anchor}" class="detail-section">
        <h2>📄 {nom}</h2>
        <div class="meta-bar">
          Pages : <strong>{res.get('pages_total','?')}</strong> &nbsp;|&nbsp;
          Taille : <strong>{taille_mo:.1f} Mo</strong> &nbsp;|&nbsp;
          Créé avec : <strong>{res.get('createur','?')}</strong> &nbsp;|&nbsp;
          <span class="badge {g_cls}">{g_icn} {g_txt}</span>
        </div>

        <div class="cards-row">
          <div class="info-card {'card-ok' if v.get('couleur',('❌',))[0]=='✅' else 'card-ko'}">
            <h3>🎨 Colorimétrie</h3>
            <p>{v.get('couleur',('',''))[0]} <strong>{res.get('mode_couleur','?')}</strong></p>
            <p class="detail-txt">{v.get('couleur',('',''))[1]}</p>
          </div>
          <div class="info-card {'card-ok' if v.get('dpi',('❌',))[0]=='✅' else 'card-ko'}">
            <h3>📐 Résolution</h3>
            {'<p>PDF vectoriel — DPI non applicable</p>' if not res.get('a_images_raster') else
             f"<p>Min global : <strong>{res.get('dpi_global_min',0):.0f} DPI</strong>"
             f" &nbsp;|&nbsp; Max : <strong>{res.get('dpi_global_max',0):.0f} DPI</strong></p>"
             f"<p class='detail-txt'>{res.get('nb_pages_ok',0)} page(s) OK · {res.get('nb_pages_ko',0)} page(s) sous 300 DPI</p>"}
          </div>
        </div>

        {'<div class="dpi-table-wrap"><h3>📊 Résolution par page</h3><table class="dpi-table"><thead><tr><th>Page</th><th>DPI min</th><th>DPI max</th><th>Statut</th><th>Couleur</th></tr></thead><tbody>' + lignes_dpi + '</tbody></table></div>' if lignes_dpi else ''}

        <div class="sub-section">
          <h3>🎨 Tons directs</h3>
          {tons_html}
        </div>

        <div class="sub-section">
          <h3>🖨️ Surimpression</h3>
          {suri_html}
        </div>
      </section>"""

    # ── HTML complet ──────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Rapport Prépresse — {nom_projet}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            background: #f5f6fa; color: #1a1a2e; font-size: 14px; }}
    a {{ color: inherit; text-decoration: none; }}

    /* ── Header ── */
    .header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
               color: white; padding: 36px 48px; }}
    .header h1 {{ font-size: 30px; font-weight: 700; letter-spacing: -0.5px; }}
    .header .sub {{ opacity: .65; font-size: 14px; margin-top: 4px; }}
    .header .meta {{ margin-top: 14px; font-size: 13px; opacity: .8; }}

    /* ── Summary cards ── */
    .summary {{ display: flex; gap: 16px; padding: 24px 48px; flex-wrap: wrap; }}
    .scard {{ flex: 1; min-width: 140px; background: white; border-radius: 14px;
              padding: 20px 24px; box-shadow: 0 2px 10px rgba(0,0,0,.07); }}
    .scard .num {{ font-size: 40px; font-weight: 800; line-height: 1; }}
    .scard .lbl {{ font-size: 12px; color: #777; margin-top: 4px; text-transform: uppercase; letter-spacing: .5px; }}
    .scard.blue .num {{ color: #3b82f6; }}
    .scard.green .num {{ color: #22c55e; }}
    .scard.red .num {{ color: #ef4444; }}

    /* ── Tableau récap ── */
    .recap-section {{ padding: 0 48px 32px; }}
    .recap-section h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; color: #333; }}
    table.recap {{ width: 100%; border-collapse: collapse; background: white;
                   border-radius: 14px; overflow: hidden;
                   box-shadow: 0 2px 10px rgba(0,0,0,.07); }}
    table.recap thead {{ background: #1a1a2e; color: white; }}
    table.recap th {{ padding: 13px 14px; text-align: left; font-size: 11px;
                      text-transform: uppercase; letter-spacing: .6px; font-weight: 500; }}
    table.recap td {{ padding: 13px 14px; border-bottom: 1px solid #f0f2f5; vertical-align: middle; }}
    table.recap tr:last-child td {{ border-bottom: none; }}
    .row-ok {{ background: #f0fdf4; }}
    .row-ko {{ background: #fff5f5; }}
    .row-ok:hover {{ background: #dcfce7; transition: .15s; }}
    .row-ko:hover {{ background: #fee2e2; transition: .15s; }}
    .filename {{ font-weight: 600; font-size: 13px; }}

    /* ── Badges ── */
    .badge {{ display: inline-flex; align-items: center; gap: 4px;
              padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 600;
              white-space: nowrap; }}
    .badge.ok   {{ background: #dcfce7; color: #16a34a; }}
    .badge.ko   {{ background: #fee2e2; color: #dc2626; }}
    .badge.warn {{ background: #fef9c3; color: #a16207; }}

    /* ── Sections de détail ── */
    .detail-section {{ background: white; margin: 0 48px 32px;
                       border-radius: 16px; overflow: hidden;
                       box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
    .detail-section h2 {{ background: #1a1a2e; color: white; padding: 16px 24px;
                          font-size: 16px; font-weight: 600; }}
    .meta-bar {{ background: #f8f9fb; padding: 12px 24px; font-size: 13px;
                 border-bottom: 1px solid #eee; }}
    .cards-row {{ display: flex; gap: 16px; padding: 20px 24px; flex-wrap: wrap; }}
    .info-card {{ flex: 1; min-width: 200px; border-radius: 12px; padding: 16px 20px;
                  border: 2px solid transparent; }}
    .card-ok {{ background: #f0fdf4; border-color: #86efac; }}
    .card-ko {{ background: #fff5f5; border-color: #fca5a5; }}
    .info-card h3 {{ font-size: 13px; color: #555; margin-bottom: 8px; font-weight: 600; }}
    .info-card p {{ font-size: 14px; margin-bottom: 4px; }}
    .detail-txt {{ font-size: 12px; color: #666; }}

    /* ── Tableau DPI ── */
    .dpi-table-wrap {{ padding: 0 24px 20px; overflow-x: auto; }}
    .dpi-table-wrap h3 {{ font-size: 14px; font-weight: 600; color: #444; margin-bottom: 10px; }}
    table.dpi-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    table.dpi-table thead tr {{ background: #334155; color: white; }}
    table.dpi-table th, table.dpi-table td {{ padding: 7px 12px; text-align: left; }}
    table.dpi-table tbody tr {{ border-bottom: 1px solid #f0f2f5; }}
    .dpi-ok {{ background: #f0fdf4; }}
    .dpi-ko {{ background: #fff5f5; font-weight: 600; }}

    /* ── Sous-sections ── */
    .sub-section {{ padding: 16px 24px; border-top: 1px solid #f0f2f5; }}
    .sub-section h3 {{ font-size: 14px; font-weight: 600; color: #444; margin-bottom: 10px; }}
    .tons-list {{ list-style: none; display: flex; flex-wrap: wrap; gap: 8px; }}
    .tons-list li {{ background: #f1f5f9; border-radius: 8px; padding: 4px 12px;
                     font-size: 12px; border: 1px solid #e2e8f0; }}
    .ok-msg {{ color: #16a34a; font-weight: 500; font-size: 13px; }}
    .warn-box {{ background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px;
                 padding: 14px 16px; }}
    .warn-box p {{ margin-bottom: 8px; font-size: 13px; }}
    table.mini-table {{ font-size: 12px; border-collapse: collapse; margin-top: 10px; width: auto; }}
    table.mini-table th, table.mini-table td {{ padding: 5px 14px; text-align: left;
                                                  border-bottom: 1px solid #fde68a; }}
    table.mini-table thead {{ background: #fef3c7; }}

    /* ── Footer ── */
    .footer {{ text-align: center; padding: 24px; font-size: 11px; color: #aaa; }}
  </style>
</head>
<body>

<div class="header">
  <h1>🖨️ Rapport de contrôle prépresse</h1>
  <div class="sub">Analyse colorimétrique, résolution, tons directs et surimpression</div>
  <div class="meta">
    📁 Projet : <strong>{nom_projet}</strong> &nbsp;|&nbsp;
    📅 {date_str} &nbsp;|&nbsp;
    📂 Dossier : Créa ou Source
  </div>
</div>

<div class="summary">
  <div class="scard blue">
    <div class="num">{nb_total}</div>
    <div class="lbl">Fichiers analysés</div>
  </div>
  <div class="scard green">
    <div class="num">{nb_conformes}</div>
    <div class="lbl">Conformes impression</div>
  </div>
  <div class="scard red">
    <div class="num">{nb_ko}</div>
    <div class="lbl">Non conformes</div>
  </div>
</div>

<div class="recap-section">
  <h2>Récapitulatif</h2>
  <table class="recap">
    <thead>
      <tr>
        <th>Fichier</th>
        <th>Colorimétrie</th>
        <th>Résolution</th>
        <th>Tons directs</th>
        <th>Surimpression</th>
        <th>Conformité</th>
      </tr>
    </thead>
    <tbody>{lignes_tableau}</tbody>
  </table>
</div>

{sections_detail}

<div class="footer">
  Rapport généré le {date_str} par AnalyseurPDF &nbsp;·&nbsp;
  Critères : CMJN + min. 300 DPI &nbsp;·&nbsp; Projet : {nom_projet}
</div>
</body>
</html>"""

    with open(chemin_sortie, "w", encoding="utf-8") as f:
        f.write(html)

    return chemin_sortie


# ════════════════════════════════════════════════════════════
# ANALYSE IMAGE BITMAP (PNG, JPG, TIFF, EPS)
# ════════════════════════════════════════════════════════════

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.eps', '.ai'}

def analyser_image(img_path):
    """Analyse une image bitmap et retourne les résultats au même format qu'analyser_pdf."""
    import os, base64, io
    ext = os.path.splitext(img_path)[-1].lower()
    res = {
        'fichier':        os.path.basename(img_path),
        'pages_total':    1,
        'taille_fichier': os.path.getsize(img_path),
        'type_document':  'Image',
        'miniatures_fp':  [],
        'tons_directs':   [],
        'surimpression':  [],
        'a_tons_directs': False,
        'a_surimpression':False,
        'transparence':   {'a_transparence': False, 'disponible': True},
        'fond_perdu':     {'disponible': False},
    }
    if not HAS_PIL:
        res['erreur'] = 'Pillow non disponible — pip3 install Pillow'
        res['mode_couleur'] = '?'
        res['verdicts'] = _verdicts_image(res)
        return res
    try:
        img = _PIL_Image.open(img_path)
        # Mode couleur
        mode_map = {'CMYK':'CMJN','RGB':'RVB','RGBA':'RVB','L':'Niveaux de gris','LA':'Niveaux de gris','1':'Niveaux de gris'}
        res['mode_couleur'] = mode_map.get(img.mode, img.mode)
        # DPI
        dpi_raw = img.info.get('dpi') or img.info.get('jfif_density')
        if dpi_raw and isinstance(dpi_raw,(tuple,list)) and len(dpi_raw)>=2:
            dpi_x, dpi_y = float(dpi_raw[0]) or 72.0, float(dpi_raw[1]) or 72.0
        else:
            dpi_x = dpi_y = 72.0
        w_px, h_px = img.size
        dpi_eff = min(dpi_x, dpi_y)
        w_mm = round(w_px / dpi_x * 25.4, 1) if dpi_x else 0
        h_mm = round(h_px / dpi_y * 25.4, 1) if dpi_y else 0
        fmt   = _detecter_format(w_mm, h_mm)
        res['dpi_global_min'] = dpi_eff
        res['dpi_global_max'] = dpi_eff
        res['a_images_raster'] = True
        res['nb_pages_ko'] = 0 if dpi_eff >= 280 else 1
        res['pages_ko']    = {} if dpi_eff >= 280 else {'1':{'dpi_min':dpi_eff,'dpi_moy':dpi_eff}}
        res['pages_ok']    = {'1':{'dpi_min':dpi_eff}} if dpi_eff >= 280 else {}
        res['tailles_pages'] = {'format_principal':fmt,'w_mm':w_mm,'h_mm':h_mm,'toutes_identiques':True,'nb_formats':1}
        # Miniature
        thumb = img.copy()
        thumb.thumbnail((500, 500))
        if thumb.mode not in ('RGB','L'):
            thumb = thumb.convert('RGB')
        buf = io.BytesIO()
        thumb.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode('ascii')
        ppm  = round(thumb.width / w_mm, 4) if w_mm else 0
        res['miniatures_fp'] = [{'page':1,'img':b64,'w':thumb.width,'h':thumb.height,
            'px_per_mm':ppm,'bleed_left':None,'bleed_right':None,'bleed_top':None,'bleed_bottom':None,
            'w_mm':w_mm,'h_mm':h_mm,'format':fmt,'conforme':None,'has_bleed':False}]
        img.close()
    except Exception as e:
        res['erreur'] = str(e)
        res['mode_couleur'] = '?'
    res['verdicts'] = _verdicts_image(res)
    return res

def _verdicts_image(res):
    v = {}
    mc = res.get('mode_couleur','?')
    if mc=='CMJN':   v['couleur'] = ('✅','CMJN conforme')
    elif mc=='RVB':  v['couleur'] = ('❌','RVB — conversion CMJN requise')
    elif 'gris' in mc.lower(): v['couleur'] = ('✅','Niveaux de gris')
    else:            v['couleur'] = ('⚠️', mc)
    dpi = res.get('dpi_global_min') or 0
    if dpi>=280:     v['dpi'] = ('✅', f'{dpi:.0f} DPI')
    elif dpi>0:      v['dpi'] = ('❌', f'{dpi:.0f} DPI — sous 300 DPI')
    else:            v['dpi'] = ('ℹ️', 'DPI non déterminé')
    v['tons_directs']  = ('✅','Non applicable')
    v['surimpression'] = ('✅','Non applicable')
    v['transparence']  = ('✅','Non applicable')
    v['fond_perdu']    = ('ℹ️','Non applicable aux images')
    v['tailles']       = ('✅', res.get('tailles_pages',{}).get('format_principal','?'))
    ok = v['couleur'][0]=='✅' and v['dpi'][0]=='✅'
    v['global'] = ('✅','Conforme') if ok else ('❌','Non conforme')
    return v

# ════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: python3 analyse_pdf_mail.py fichier.pdf [--json] [--html chemin_sortie.html] [--projet NomProjet]")
        sys.exit(1)

    # Récupérer les arguments
    pdf_path    = args[0]
    mode_json   = "--json" in args
    mode_html   = "--html" in args
    html_output = args[args.index("--html") + 1] if mode_html else None
    nom_projet  = args[args.index("--projet") + 1] if "--projet" in args else "Projet"

    res = analyser_pdf(pdf_path)

    if mode_json:
        def clean(obj):
            if isinstance(obj, set):
                return list(obj)
            if isinstance(obj, dict):
                return {k: clean(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [clean(i) for i in obj]
            return obj
        print(json.dumps(clean(res), ensure_ascii=False, indent=2))

    elif mode_html and html_output:
        chemin = generer_rapport_html([res], nom_projet, html_output)
        print(f"Rapport HTML généré : {chemin}")

    else:
        print(formater_rapport_texte(res))

    # Code de sortie : 0 = conforme, 1 = non conforme, 2 = erreur
    if "erreur" in res:
        sys.exit(2)
    v = res.get("verdicts", {})
    global_ok = v.get("global", ("❌",))[0] == "✅"
    sys.exit(0 if global_ok else 1)
