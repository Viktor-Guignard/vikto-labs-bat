"""
Moteur d'analyse prépresse PDF — utilisé par l'app GUI.
Détecte : formats (avec/sans fond perdu), tons directs, plaques CMJN utilisées,
traits de coupe, imposition en planches vs page à page.
"""
import re
import fitz  # PyMuPDF

PT_TO_MM = 25.4 / 72.0

# Formats standards (mm) pour la détection de planches
STANDARD_FORMATS = {
    "A6": (105, 148), "A5": (148, 210), "A4": (210, 297), "A3": (297, 420),
    "A2": (420, 594), "A1": (594, 841),
    "10x15": (100, 150), "DL": (99, 210), "21x21": (210, 210),
    "Letter US": (216, 279), "Tabloid": (279, 432),
}
TOL = 2.5  # tolérance en mm


def _mm(v):
    return v * PT_TO_MM


def _rect_mm(rect):
    return (round(_mm(rect.width), 1), round(_mm(rect.height), 1))


def _match_format(w, h, tol=TOL):
    """Retourne le nom du format standard correspondant (peu importe l'orientation)."""
    for name, (fw, fh) in STANDARD_FORMATS.items():
        if (abs(w - fw) <= tol and abs(h - fh) <= tol) or \
           (abs(w - fh) <= tol and abs(h - fw) <= tol):
            return name
    return None


def find_spot_colors(doc):
    """Scanne tous les objets du PDF pour trouver les colorants /Separation et /DeviceN."""
    spots = set()
    deviceN = set()
    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=True)
        except Exception:
            continue
        if not obj or "/Separation" not in obj and "/DeviceN" not in obj:
            continue
        # /Separation /NomDuTon ...
        for m in re.finditer(r"/Separation\s*/([^\s/\]\[<>()]+)", obj):
            spots.add(_decode_pdf_name(m.group(1)))
        # /DeviceN [ /Nom1 /Nom2 ... ]
        for m in re.finditer(r"/DeviceN\s*\[((?:\s*/[^\s/\]\[<>()]+)+)\s*\]", obj):
            for n in re.findall(r"/([^\s/\]\[<>()]+)", m.group(1)):
                deviceN.add(_decode_pdf_name(n))
    process = {"Cyan", "Magenta", "Yellow", "Black", "None"}
    spots |= {n for n in deviceN if n not in process}
    registration = "All" in spots
    spots.discard("All")
    return sorted(spots), registration


def _decode_pdf_name(name):
    """Décode les #xx des noms PDF (ex: PANTONE#20485#20C -> PANTONE 485 C)."""
    return re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), name)


def cmyk_plates_used(doc, max_pages=20, dpi=72, threshold=0.02):
    """Rasterise les pages en CMJN et détecte quelles plaques sont réellement encrées.
    threshold : fraction d'encre minimale (2% sur au moins quelques pixels) pour
    considérer la plaque utilisée. Retourne dict {C,M,J,N: bool}."""
    used = [False] * 4
    n = min(len(doc), max_pages)
    step = max(1, len(doc) // n)
    for i in range(0, len(doc), step):
        page = doc[i]
        try:
            pix = page.get_pixmap(colorspace=fitz.csCMYK, dpi=dpi)
        except Exception:
            continue
        samples = pix.samples
        npx = pix.width * pix.height
        min_count = max(10, int(npx * 0.0005))  # ignore le bruit isolé
        for ch in range(4):
            if used[ch]:
                continue
            count = sum(1 for j in range(ch, len(samples), 4) if samples[j] > int(255 * threshold) + 2)
            if count >= min_count:
                used[ch] = True
        if all(used):
            break
    return dict(zip(["Cyan", "Magenta", "Jaune", "Noir"], used))


def detect_crop_marks(page):
    """Heuristique : traits courts dessinés hors de la TrimBox (si Media > Trim)."""
    trim = page.trimbox
    media = page.mediabox
    if abs(media.width - trim.width) < 2 and abs(media.height - trim.height) < 2:
        return False
    try:
        drawings = page.get_drawings()
    except Exception:
        return False
    marks = 0
    trim_r = fitz.Rect(trim)
    for d in drawings:
        r = d["rect"]
        # un trait de coupe est petit, fin, et entièrement hors de la zone rognée
        if (r.width < 30 or r.height < 30) and not fitz.Rect(r).intersects(trim_r):
            for item in d["items"]:
                if item[0] == "l":  # ligne
                    marks += 1
    return marks >= 4


def detect_spreads(trim_w, trim_h, n_pages=None):
    """Détecte si la page est une planche (2 pages côte à côte horizontalement).
    Retourne (is_spread, format_simple, format_planche, ambiguous).
    ambiguous=True quand le format complet est lui-même un format standard
    (ex: A3 paysage = 2×A4 : impossible de trancher sans contexte)."""
    full = _match_format(trim_w, trim_h)
    landscape = trim_w > trim_h

    if not landscape:
        return False, full, None, False

    hw, hh = trim_w / 2, trim_h
    half = _match_format(hw, hh)
    if half and hh > hw:  # chaque moitié en portrait : typique d'une brochure en planches
        ambiguous = full is not None  # le format entier existe aussi (A3 paysage…)
        # indice : une brochure en planches a un nb de pages finales multiple de 4
        if ambiguous and n_pages and (n_pages * 2) % 4 != 0:
            return False, full, None, True
        return True, half, full, ambiguous
    # paysage sans moitié standard : page à page paysage
    return False, full, None, False


def analyze(path, progress=None):
    """Analyse complète. Retourne un dict de résultats."""
    doc = fitz.open(path)
    res = {"path": path, "n_pdf_pages": len(doc)}

    page0 = doc[0]
    media = page0.mediabox
    trim = page0.trimbox      # = MediaBox si absent
    bleed = page0.bleedbox    # = MediaBox si absent
    crop = page0.cropbox

    trim_w, trim_h = _mm(trim.width), _mm(trim.height)
    res["media_mm"] = _rect_mm(media)
    res["trim_mm"] = (round(trim_w, 1), round(trim_h, 1))
    res["bleed_mm"] = _rect_mm(bleed)
    res["crop_mm"] = _rect_mm(crop)

    has_trim = (abs(media.width - trim.width) > 1 or abs(media.height - trim.height) > 1)
    has_bleedbox = (abs(bleed.width - trim.width) > 1 or abs(bleed.height - trim.height) > 1) and \
                   (bleed.width < media.width + 1)
    res["has_trimbox"] = has_trim
    if has_bleedbox and has_trim:
        b = max((bleed.width - trim.width) / 2, (bleed.height - trim.height) / 2)
        res["bleed_value_mm"] = round(_mm(b), 1)
    elif has_trim:
        b = max((media.width - trim.width) / 2, (media.height - trim.height) / 2)
        res["bleed_value_mm"] = round(_mm(b), 1) if b < 8 / PT_TO_MM else None
    else:
        res["bleed_value_mm"] = None

    if progress: progress("Détection des traits de coupe…")
    res["crop_marks"] = detect_crop_marks(page0)

    if progress: progress("Recherche des tons directs…")
    spots, registration = find_spot_colors(doc)
    res["spot_colors"] = spots
    res["registration"] = registration

    if progress: progress("Analyse des plaques CMJN (rastérisation)…")
    res["plates"] = cmyk_plates_used(doc)
    res["n_process"] = sum(res["plates"].values())
    res["n_colors_total"] = res["n_process"] + len(spots)

    if progress: progress("Détection planches / page à page…")
    is_spread, fmt_single, fmt_full, ambiguous = detect_spreads(trim_w, trim_h, len(doc))
    res["is_spread"] = is_spread
    res["spread_ambiguous"] = ambiguous
    res["format_name"] = fmt_full if is_spread else fmt_single
    res["format_single_name"] = fmt_single
    if is_spread:
        res["page_size_mm"] = (round(trim_w / 2, 1), round(trim_h, 1))
        res["n_final_pages"] = len(doc) * 2
    else:
        res["page_size_mm"] = res["trim_mm"]
        res["n_final_pages"] = len(doc)

    # uniformité des formats
    sizes = {(_rect_mm(p.mediabox)) for p in doc}
    res["uniform"] = len(sizes) == 1

    doc.close()
    return res


def report_text(res):
    """Rapport texte lisible."""
    L = []
    L.append(f"Fichier : {res['path'].split('/')[-1]}")
    L.append("")
    L.append("── FORMAT ──────────────────────────")
    tw, th = res["trim_mm"]
    fmt = f" ({res['format_name']})" if res.get("format_name") else ""
    L.append(f"Format fini (sans fond perdu) : {tw} × {th} mm{fmt}")
    if res["bleed_value_mm"]:
        bw, bh = tw + 2 * res["bleed_value_mm"], th + 2 * res["bleed_value_mm"]
        L.append(f"Format avec fond perdu : {bw:.1f} × {bh:.1f} mm (fond perdu {res['bleed_value_mm']} mm)")
    else:
        L.append("Fond perdu : NON DÉTECTÉ ⚠")
    L.append(f"Traits de coupe : {'OUI' if res['crop_marks'] else 'NON'}")
    if not res["uniform"]:
        L.append("⚠ Les pages n'ont pas toutes le même format")
    L.append("")
    L.append("── IMPOSITION ──────────────────────")
    if res["is_spread"]:
        pw, ph = res["page_size_mm"]
        L.append(f"Document EN PLANCHES ({res['n_pdf_pages']} planches)")
        L.append(f"Page simple : {pw} × {ph} mm ({res['format_single_name'] or '—'})")
        L.append(f"Nombre de pages finales : {res['n_final_pages']}")
        if res.get("spread_ambiguous"):
            L.append(f"⚠ Ambigu : peut aussi être {res['n_pdf_pages']} pages {res['format_name']} paysage")
    else:
        L.append(f"Document PAGE À PAGE : {res['n_final_pages']} pages")
        if res.get("spread_ambiguous"):
            L.append("⚠ Format paysage divisible en 2 pages standard : vérifier visuellement")
    L.append("")
    L.append("── COULEURS ────────────────────────")
    plates = [k for k, v in res["plates"].items() if v]
    L.append(f"Plaques quadri utilisées : {len(plates)} ({', '.join(plates) or 'aucune'})")
    if res["spot_colors"]:
        L.append(f"Tons directs : {len(res['spot_colors'])}")
        for s in res["spot_colors"]:
            L.append(f"   • {s}")
    else:
        L.append("Tons directs : aucun")
    if res.get("registration"):
        L.append("(couleur de repérage « All » présente — traits de coupe)")
    L.append(f"TOTAL COULEURS : {res['n_colors_total']}")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    r = analyze(sys.argv[1], progress=lambda m: print("…", m))
    print()
    print(report_text(r))
