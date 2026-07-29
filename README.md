# VikBAT — Vikto Labs

Outil local de contrôle prépresse pour PDF (analyse BAT), sous macOS.

## Fonctionnalités

- **Mode colorimétrique global** : détection RVB / CMJN
- **Tons directs** : présence de couleurs Pantone, etc.
- **Résolution par page (DPI)** : pages conformes / non conformes
- **Surimpression (overprint)** : présence et état

## Contenu du dépôt

- `VikBAT.app/` — l'application macOS prête à l'emploi (applet AppleScript qui lance le serveur local)
- `src/` — les sources lisibles :
  - `server_analyseur.py` — serveur web local (port 5678) avec interface d'analyse
  - `analyse_pdf_mail.py` — analyse complète d'un PDF en ligne de commande (`--json` / `--html`)
  - `app.py`, `prepress_core.py`, `__main__.py` — contenu de `controle_prepresse.pyz`
  - `main.applescript` — source de l'applet de lancement

## Utilisation

### Application

Double-cliquer sur `VikBAT.app` : un Terminal s'ouvre, le serveur démarre et le navigateur s'ouvre sur <http://localhost:5678>.

### Ligne de commande

```bash
python3 src/analyse_pdf_mail.py /chemin/vers/fichier.pdf --html rapport.html
```

## Dépendances

Python 3 avec (installation automatique au premier lancement, ou manuellement) :

```bash
pip3 install --user pymupdf pikepdf
```

---
Créé par Viktor — Vikto Labs
