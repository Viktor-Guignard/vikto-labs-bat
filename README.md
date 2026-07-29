# VIKTO LABS BAT

Contrôle prépresse de PDF : analyse BAT, imposition, organisation des pages,
séparation CMJN, conversion quadrichromie et corrections automatiques.

## Version en ligne

**<https://viktor-guignard.github.io/vikto-labs-bat/>**

Rien à installer : déposez vos PDF dans la page.

Tout tourne **dans le navigateur** — le moteur Python d'origine est exécuté en
WebAssembly via [Pyodide](https://pyodide.org). Seul le code de l'outil est
téléchargé, une fois, au chargement : vos PDF, eux, ne sont jamais transmis.
La page continue de fonctionner connexion coupée. Comptez 5 secondes de
démarrage, puis quelques secondes par PDF (≈ 17 s pour un catalogue de
362 pages et 39 Mo).

## Fonctionnalités

Les six onglets de la version web reprennent les outils de l'application macOS.

**Analyse** — plusieurs PDF d'un coup, avec rapport HTML téléchargeable :

- **Mode colorimétrique global** : RVB / CMJN / mixte / vectoriel
- **Résolution par page (DPI)** : pages conformes / non conformes au seuil de 300
- **Tons directs** : Pantone, vernis, découpe, dorure…
- **Fond perdu** : mesuré sur les quatre bords, seuil de conformité à 3 mm
- **Surimpression** : détection des drapeaux `OP` / `op`
- **Transparence** : opacité partielle, masques doux, modes de fusion

**Imposition** — 2-up, séquentiel ou booklet (piqûre à cheval, dos carré collé),
avec traits de coupe, repères de repérage, repère de pliure, barre couleur,
fond perdu intérieur/extérieur et creep réglables.

**Organiser** — vignettes de toutes les pages, réordonnancement par
glisser-déposer, export du PDF réorganisé.

**Aperçu CMJN** — décomposition d'une page en ses quatre plaques, avec le taux
d'encrage de chacune.

**Convertir** — passage en quadrichromie par rastérisation CMJN à 300 dpi.

**Corriger** — conversion RVB/tons directs, ajout de 3 mm de fond perdu si
absent, nettoyage des métadonnées.

## Contenu du dépôt

- `docs/` — la version web publiée sur GitHub Pages
  - `index.html`, `app.js` — interface
  - `worker.js` — chargement de Pyodide et pilotage des traitements hors du thread principal
  - `py/pikepdf.py` — réimplémentation de l'API pikepdf sur PyMuPDF (voir plus bas)
  - `py/run.py` — colle entre JavaScript et les moteurs
  - `py/analyse_pdf_mail.py`, `py/prepress_core.py`, `py/server_analyseur.py` —
    copies **non modifiées** des modules de l'application. `server_analyseur.py`
    est importé pour ses outils (imposition, vignettes, réordonnancement,
    séparation CMJN, conversion, corrections) ; son serveur HTTP ne démarre que
    via `__main__` et reste donc inerte ici.
- `VikBAT.app/` — l'application macOS (applet AppleScript lançant le serveur local)
- `src/` — les sources lisibles de l'application macOS :
  - `server_analyseur.py` — serveur local (port 5678), interface complète
    (analyse, imposition, miniatures, réordonnancement, conversion CMJN)
  - `analyse_pdf_mail.py` — moteur d'analyse, utilisable en ligne de commande
  - `app.py`, `prepress_core.py`, `__main__.py` — contenu de `controle_prepresse.pyz`
  - `main.applescript` — source de l'applet de lancement

## Pourquoi un pikepdf maison

Le moteur s'appuie sur deux bibliothèques : PyMuPDF et pikepdf. PyMuPDF publie
une version WebAssembly, pas pikepdf — qui dépend de qpdf, écrit en C++.

`docs/py/pikepdf.py` réimplémente donc la portion de l'API réellement utilisée
(ouverture depuis un chemin ou des octets, parcours des pages, objets, tableaux,
noms, héritage des attributs `/Resources`, `/MediaBox`, `/CropBox`, `/Rotate`,
plus l'écriture des boîtes et l'enregistrement) au-dessus de PyMuPDF. Les
modules l'importent sans savoir que ce n'est pas le vrai pikepdf, ce qui permet
de les copier tels quels.

Fidélité vérifiée sur les 79 PDF d'un jeu de test réel — dont 12 avec tons
directs, 42 avec surimpression, 29 avec transparence : résultats identiques au
vrai pikepdf partout, sauf deux écarts, tous deux dus à des bogues du code
d'origine et non au remplacement :

- `format_principal` départage les ex æquo de façon non déterministe
  (`max(set(...), key=...)`), si bien que le vrai pikepdf donne lui aussi un
  résultat différent d'une exécution à l'autre ;
- la correction « ajouter le fond perdu » appelle `pikepdf.Real`, qui n'existe
  pas dans pikepdf 9.x ; l'`AttributeError` est avalée par un `except Exception`
  et la correction ne s'applique jamais. Le remplacement définit `Real`, donc la
  version web applique réellement les 3 mm.

## Application macOS

Double-cliquer sur `VikBAT.app` : un Terminal s'ouvre, le serveur démarre et le
navigateur s'ouvre sur <http://localhost:5678>.

Elle conserve deux avantages sur la version web : l'historique des analyses, et
une conversion quadrichromie **vectorielle** — mais uniquement si Ghostscript
est installé (`brew install ghostscript`). Sans lui, elle retombe sur la même
rastérisation 300 dpi que la version web.

L'application n'est pas signée par un compte développeur Apple : au premier
lancement après téléchargement, faire un clic droit puis « Ouvrir » pour passer
l'avertissement de macOS.

### Ligne de commande

```bash
python3 src/analyse_pdf_mail.py /chemin/vers/fichier.pdf --html rapport.html
```

### Dépendances

Python 3 avec (installation automatique au premier lancement, ou manuellement) :

```bash
pip3 install --user pymupdf pikepdf
```

---
Créé par Viktor — Vikto Labs
