# VikBAT — Vikto Labs

Contrôle prépresse de PDF : résolution, colorimétrie, tons directs, fond perdu,
surimpression, transparence.

## Version en ligne

**<https://viktor-guignard.github.io/vikto-labs-bat/>**

Rien à installer : déposez vos PDF dans la page et le rapport s'affiche.

L'analyse tourne **entièrement dans le navigateur** — le moteur Python d'origine
est exécuté en WebAssembly via [Pyodide](https://pyodide.org). Aucun fichier
n'est envoyé sur un serveur ; la page fonctionne même connexion coupée une fois
chargée. Comptez 5 secondes de démarrage, puis quelques secondes par PDF
(≈ 17 s pour un catalogue de 362 pages et 39 Mo).

## Fonctionnalités

- **Mode colorimétrique global** : RVB / CMJN / mixte / vectoriel
- **Résolution par page (DPI)** : pages conformes / non conformes au seuil de 300
- **Tons directs** : Pantone, vernis, découpe, dorure…
- **Fond perdu** : mesuré sur les quatre bords, seuil de conformité à 3 mm
- **Surimpression** : détection des drapeaux `OP` / `op`
- **Transparence** : opacité partielle, masques doux, modes de fusion
- **Rapport HTML** consultable et téléchargeable

## Contenu du dépôt

- `docs/` — la version web publiée sur GitHub Pages
  - `index.html`, `app.js` — interface
  - `worker.js` — chargement de Pyodide et pilotage de l'analyse hors du thread principal
  - `py/pikepdf.py` — réimplémentation de l'API pikepdf sur PyMuPDF (voir plus bas)
  - `py/run.py` — colle entre JavaScript et le moteur
  - `py/analyse_pdf_mail.py`, `py/prepress_core.py` — copies **non modifiées** du moteur
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
(ouverture, parcours des pages, objets, tableaux, noms, héritage des attributs
`/Resources`, `/MediaBox`, `/CropBox`, `/Rotate`) au-dessus de PyMuPDF. Le
moteur l'importe sans savoir que ce n'est pas le vrai pikepdf, ce qui permet de
copier `analyse_pdf_mail.py` tel quel.

Fidélité vérifiée sur les 79 PDF d'un jeu de test réel — dont 12 avec tons
directs, 42 avec surimpression, 29 avec transparence : résultats identiques au
vrai pikepdf partout, sauf sur le champ `format_principal` de deux fichiers, où
l'écart vient d'un départage d'ex æquo non déterministe dans le moteur lui-même
(le vrai pikepdf donne aussi un résultat différent à chaque exécution).

## Application macOS

Double-cliquer sur `VikBAT.app` : un Terminal s'ouvre, le serveur démarre et le
navigateur s'ouvre sur <http://localhost:5678>. Elle offre davantage que la
version web (imposition, conversion CMJN via Ghostscript, historique).

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
