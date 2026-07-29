"""Colle entre le worker JavaScript et les moteurs d'analyse et d'outils.

Les résultats volumineux (miniatures base64, PDF produits) restent côté Python :
seul un résumé léger, ou les octets explicitement demandés, traversent la
frontière vers JavaScript.

`server_analyseur` est importé tel quel : son serveur HTTP ne démarre que via
`__main__`, et sa vérification de dépendances trouve PyMuPDF ainsi que le
pikepdf de remplacement, donc rien n'est installé au chargement.
"""

import sys

sys.path.insert(0, "/py")

import analyse_pdf_mail as A  # noqa: E402
import server_analyseur as S  # noqa: E402

RESULTATS = []

# PDF produits par les outils, gardés côté Python jusqu'au téléchargement.
_SORTIES = {}


# ════════════════════════════════════════════════════════════
# ANALYSE
# ════════════════════════════════════════════════════════════

def reset():
    RESULTATS.clear()


def analyser(chemin):
    res = A.analyser_pdf(chemin)
    RESULTATS.append(res)
    return resume(res)


def resume(res):
    """Extrait compact, sérialisable, pour l'affichage immédiat."""
    if res.get("erreur"):
        return {"erreur": res["erreur"], "fichier": res.get("fichier", "?")}

    fp = res.get("fond_perdu") or {}
    tr = res.get("transparence") or {}
    tp = res.get("tailles_pages") or {}

    verdicts = {}
    for cle, v in (res.get("verdicts") or {}).items():
        try:
            verdicts[cle] = [str(v[0]), str(v[1])]
        except Exception:
            continue

    return {
        "fichier": res.get("fichier"),
        "taille_fichier": res.get("taille_fichier"),
        "pages": len(res.get("pages_dpi") or {}) or res.get("pages_total"),
        "mode_couleur": res.get("mode_couleur"),
        "dpi_min": res.get("dpi_global_min"),
        "dpi_max": res.get("dpi_global_max"),
        "nb_pages_ko": res.get("nb_pages_ko"),
        "nb_pages_ok": res.get("nb_pages_ok"),
        "a_images_raster": res.get("a_images_raster"),
        "tons_directs": list(res.get("tons_directs") or []),
        "a_surimpression": bool(res.get("a_surimpression")),
        "a_transparence": bool(tr.get("a_transparence")),
        "fond_perdu_ok": fp.get("global_ok"),
        "fond_perdu_min": fp.get("min_bleed_global"),
        "has_trim_box": fp.get("has_trim_box"),
        "format_principal": tp.get("format_principal"),
        "formats_identiques": tp.get("toutes_identiques"),
        "type_document": res.get("type_document"),
        "verdicts": verdicts,
    }


def rapport_html(nom_projet):
    if not RESULTATS:
        return ""
    sortie = "/rapport.html"
    A.generer_rapport_html(RESULTATS, nom_projet, sortie)
    with open(sortie, encoding="utf-8") as f:
        return f.read()


def rapport_texte():
    return "\n\n".join(A.formater_rapport_texte(r) for r in RESULTATS)


# ════════════════════════════════════════════════════════════
# OUTILS (imposition, organisation, conversion)
# ════════════════════════════════════════════════════════════

def _garder(nom, octets):
    """Range un PDF produit et renvoie sa description, sans le transférer."""
    _SORTIES[nom] = octets
    return {"nom": nom, "taille": len(octets)}


def recuperer(nom):
    """Renvoie les octets d'un PDF produit, puis les oublie."""
    return _SORTIES.pop(nom, b"")


def miniatures(chemin, nom_fichier):
    """Vignettes de toutes les pages. Renvoie {key, total, thumbs:[b64]}."""
    with open(chemin, "rb") as f:
        octets = f.read()
    return S._get_page_thumbs(octets, nom_fichier)


def reorganiser(cle, ordre, nom_sortie):
    """Réordonne les pages du PDF mis en cache par miniatures()."""
    return _garder(nom_sortie, S._reorder_pages(cle, list(ordre)))


def imposer(chemin, nom_sortie, options):
    """Imposition 2-up. `options` reprend les paramètres de l'app native."""
    with open(chemin, "rb") as f:
        octets = f.read()
    o = dict(options)
    resultat = S._impose_pdf_pro(
        octets,
        mode=o.get("mode", "sequential"),
        inner_bleed=float(o.get("inner_bleed", 3)),
        outer_bleed=float(o.get("outer_bleed", 3)),
        creep=float(o.get("creep", 0)),
        mark_margin=float(o.get("mark_margin", 8)),
        crop_marks=bool(o.get("crop_marks", True)),
        reg_marks=bool(o.get("reg_marks", True)),
        fold_marks=bool(o.get("fold_marks", True)),
        color_bar=bool(o.get("color_bar", False)),
        sheet_size=o.get("sheet_size", "auto"),
    )
    return _garder(nom_sortie, resultat)


def apercu_cmjn(chemin, page):
    """Sépare une page en ses quatre plaques.

    Renvoie {width, height, total, raw_b64, spots} — raw_b64 contient 4 octets
    par pixel (C, M, J, N), décodés côté navigateur pour dessiner les plaques.
    """
    return S._render_cmyk_page(chemin, int(page))


def corriger(chemin, nom_sortie, fixups):
    """Corrections automatiques : conversion CMJN, fond perdu, métadonnées."""
    with open(chemin, "rb") as f:
        octets = f.read()
    return _garder(nom_sortie, S._apply_pitstop_fixups(octets, dict(fixups)))


def convertir_cmjn(chemin, nom_sortie):
    """Conversion quadrichromie.

    _convert_to_cmyk tente Ghostscript puis retombe sur la rastérisation
    PyMuPDF. Ghostscript n'existant pas ici, c'est toujours la seconde voie
    qui s'applique — celle que décrit déjà l'onglet de l'application.
    """
    with open(chemin, "rb") as f:
        octets = f.read()
    return _garder(nom_sortie, S._convert_to_cmyk(octets))
