"""Colle entre le worker JavaScript et le moteur d'analyse.

Les résultats complets (miniatures base64 comprises) restent côté Python :
seul un résumé léger traverse la frontière vers JavaScript.
"""

import sys

sys.path.insert(0, "/py")

import analyse_pdf_mail as A  # noqa: E402

RESULTATS = []


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
