#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VikBAT 1.4 — Serveur local d'analyse prépresse
Créé par Viktor
"""

import http.server
import socketserver
import json
import os
import sys
import re
import threading
import webbrowser
import tempfile
import subprocess
import glob

# ─── Ajouter TOUS les user site-packages Python 3.x au sys.path ─────────────
# (Fait EN PREMIER pour que _ensure_deps() et les imports fonctionnent)
def _add_all_user_sites():
    v = sys.version_info
    # Chemin exact de la version courante en premier
    exact = os.path.expanduser(f'~/Library/Python/{v.major}.{v.minor}/lib/python/site-packages')
    # Toutes les versions 3.x trouvées (reverse = version la plus récente d'abord)
    all_sites = sorted(
        glob.glob(os.path.expanduser('~/Library/Python/3.*/lib/python/site-packages')),
        reverse=True
    )
    for p in ([exact] + all_sites):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)

_add_all_user_sites()

# ─── Auto-installation des dépendances ───────────────────────────────────────

def _ensure_deps():
    deps = [("pymupdf", "fitz"), ("pikepdf", "pikepdf")]
    for pkg, imp in deps:
        try:
            __import__(imp)
        except ImportError:
            for flags in [["--user"], ["--break-system-packages"], []]:
                try:
                    subprocess.run(
                        [sys.executable, "-m", "pip", "install", pkg, "-q"] + flags,
                        capture_output=True, timeout=120
                    )
                    # Recharger les chemins après installation
                    _add_all_user_sites()
                    __import__(imp)
                    break
                except Exception:
                    continue

_ensure_deps()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import analyse_pdf_mail
import hashlib
import io
import base64

PORT = 5678

# ─── Cache fichiers PDF (pour /download-preview) ──────────────────────────────
_file_cache = {}   # cache_key → {'path': str, 'fp_pages': list, 'filename': str}

# ─── Interface HTML ───────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VikBAT 1.4</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;cursor:none!important}
/* Curseur normal dans le viewer fond perdu */
#fp-modal,#fp-modal *{cursor:default!important}
#fp-viewer-stage img{cursor:crosshair!important}
/* Loupe */
#fp-loupe{position:fixed;width:180px;height:180px;border-radius:50%;border:2px solid var(--accent);box-shadow:0 0 20px rgba(0,245,255,.3),0 4px 30px rgba(0,0,0,.8);pointer-events:none;overflow:hidden;display:none;z-index:9000;background:#000;}
:root{
  --bg:#020608;
  --s1:rgba(0,245,255,0.03);
  --s2:rgba(0,245,255,0.05);
  --s3:rgba(0,245,255,0.08);
  --border:rgba(0,245,255,0.12);
  --border2:rgba(0,245,255,0.22);
  --accent:#00f5ff;
  --accent2:#ff00aa;
  --accent3:#9d00ff;
  --glow:rgba(0,245,255,0.4);
  --glow2:rgba(255,0,170,0.4);
  --text:#e0f7fa;
  --muted:rgba(0,245,255,0.4);
  --faint:rgba(0,245,255,0.08);
  --ok:#00ff9d;    --ok-g:rgba(0,255,157,.08);   --ok-b:rgba(0,255,157,.25);
  --ko:#ff003c;    --ko-g:rgba(255,0,60,.08);    --ko-b:rgba(255,0,60,.25);
  --warn:#ffb700;  --warn-g:rgba(255,183,0,.08); --warn-b:rgba(255,183,0,.25);
}
html{scroll-behavior:smooth}
body{
  font-family:'SF Mono','Menlo','Monaco','Courier New',monospace;
  background:var(--bg);color:var(--text);
  min-height:100vh;overflow-x:hidden;
  -webkit-font-smoothing:antialiased;
  background-image:
    linear-gradient(rgba(0,245,255,0.03) 1px,transparent 1px),
    linear-gradient(90deg,rgba(0,245,255,0.03) 1px,transparent 1px);
  background-size:44px 44px;
}

/* ─── SCANLINES ─── */
body::before{
  content:'';position:fixed;inset:0;z-index:1;pointer-events:none;
  background:repeating-linear-gradient(
    0deg,transparent,transparent 2px,
    rgba(0,0,0,0.06) 2px,rgba(0,0,0,0.06) 4px
  );
}
body::after{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(ellipse 80% 50% at 50% -10%,rgba(0,245,255,0.06),transparent),
    radial-gradient(ellipse 40% 30% at 90% 80%,rgba(157,0,255,0.05),transparent),
    radial-gradient(ellipse 40% 30% at 10% 80%,rgba(255,0,170,0.04),transparent);
}

/* ─── CURSEUR CYBER ─── */
#cur{
  position:fixed;z-index:99999;pointer-events:none;
  width:5px;height:5px;
  background:var(--accent);
  transform:translate(-50%,-50%);
  clip-path:polygon(50% 0%,100% 50%,50% 100%,0% 50%);
  box-shadow:0 0 8px var(--accent),0 0 16px var(--accent);
  transition:transform .1s,width .15s,height .15s;
}
#cur-ring{
  position:fixed;z-index:99998;pointer-events:none;
  width:24px;height:24px;
  border:1px solid rgba(0,245,255,0.7);
  transform:translate(-50%,-50%) rotate(45deg);
  transition:left .06s,top .06s,width .2s,height .2s,border-color .2s,box-shadow .2s;
  box-shadow:0 0 8px rgba(0,245,255,0.3),inset 0 0 6px rgba(0,245,255,0.1);
}
body.cur-hover #cur{width:4px;height:4px}
body.cur-hover #cur-ring{
  width:32px;height:32px;
  border-color:var(--accent2);
  box-shadow:0 0 14px rgba(255,0,170,0.5),inset 0 0 8px rgba(255,0,170,0.1);
}
body.cur-click #cur-ring{width:16px;height:16px;border-color:#fff}

/* ─── HEADER ─── */
header{
  position:sticky;top:0;z-index:200;
  height:58px;padding:0 48px;
  display:flex;align-items:center;justify-content:space-between;
  background:rgba(2,6,8,0.85);
  backdrop-filter:blur(24px) saturate(200%);
  border-bottom:1px solid var(--border);
  box-shadow:0 1px 0 rgba(0,245,255,0.08),0 4px 30px rgba(0,0,0,0.5);
}
.logo{display:flex;align-items:center;gap:12px}
.logo-mark{
  width:32px;height:32px;
  background:transparent;
  border:1px solid var(--accent);
  display:flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:900;color:var(--accent);
  clip-path:polygon(10% 0%,90% 0%,100% 10%,100% 90%,90% 100%,10% 100%,0% 90%,0% 10%);
  box-shadow:0 0 16px rgba(0,245,255,0.3),inset 0 0 10px rgba(0,245,255,0.1);
  text-shadow:0 0 8px var(--accent);
}
.logo-name{
  font-size:15px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
  color:var(--text);text-shadow:0 0 12px rgba(0,245,255,0.4);
}
.logo-name em{font-style:normal;color:var(--accent);text-shadow:0 0 10px var(--accent)}
.logo-sub{font-size:9px;color:var(--muted);letter-spacing:2px;text-transform:uppercase;margin-top:2px}
.hdr-right{display:flex;align-items:center;gap:14px}
.bat-chip{
  font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
  color:var(--accent);border:1px solid rgba(0,245,255,0.3);
  padding:3px 10px;background:rgba(0,245,255,0.05);
  box-shadow:0 0 8px rgba(0,245,255,0.15);
}
.credit{font-size:10px;color:var(--muted);letter-spacing:1px}
.btn-hist{
  font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
  color:var(--muted);border:1px solid var(--border);
  padding:4px 12px;background:transparent;
  transition:color .15s,border-color .15s,box-shadow .15s;
}
.btn-hist:hover{
  color:var(--accent2);border-color:rgba(255,0,170,0.5);
  box-shadow:0 0 12px rgba(255,0,170,0.2);
}

/* ─── PANNEAU HISTORIQUE ─── */
#hist-panel{
  position:fixed;top:0;right:0;bottom:0;width:340px;
  background:rgba(2,6,8,0.95);
  border-left:1px solid var(--border);
  backdrop-filter:blur(20px);
  z-index:500;transform:translateX(100%);
  transition:transform .3s cubic-bezier(.16,1,.3,1);
  display:flex;flex-direction:column;
  box-shadow:-4px 0 30px rgba(0,0,0,0.5),-1px 0 0 rgba(0,245,255,0.1);
}
#hist-panel.open{transform:none}
.hist-head{
  padding:18px 20px 14px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;flex-shrink:0;
}
.hist-title{font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--accent);text-shadow:0 0 8px var(--accent)}
.hist-actions{display:flex;gap:8px;align-items:center}
.btn-clear{font-size:9px;color:var(--muted);background:none;border:none;text-decoration:underline;letter-spacing:1px;text-transform:uppercase;}
.btn-close{font-size:16px;color:var(--muted);background:none;border:none;line-height:1;}
.hist-list{overflow-y:auto;flex:1;padding:10px}
.hist-empty{text-align:center;padding:40px 20px;font-size:11px;color:var(--muted);letter-spacing:1px}
.hitem{
  border:1px solid var(--border);padding:12px 14px;margin-bottom:8px;
  background:var(--s1);
  transition:border-color .15s,box-shadow .15s;
}
.hitem:hover{border-color:rgba(0,245,255,0.3);box-shadow:0 0 12px rgba(0,245,255,0.08)}
.hitem-top{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:5px}
.hitem-name{font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0;color:var(--text)}
.hbadge{flex-shrink:0;font-size:8px;font-weight:700;padding:2px 8px;letter-spacing:.5px;text-transform:uppercase}
.hok {background:rgba(0,255,157,.08);color:var(--ok);border:1px solid rgba(0,255,157,.3)}
.hko {background:rgba(255,0,60,.08);color:#ff5577;border:1px solid rgba(255,0,60,.3)}
.hitem-meta{font-size:9px;color:var(--muted);display:flex;flex-wrap:wrap;gap:5px}
.htag{background:var(--s2);padding:1px 6px;letter-spacing:.5px}

/* ─── HERO ─── */
.hero{
  padding:80px 24px 52px;text-align:center;
  position:relative;z-index:2;
  background:radial-gradient(ellipse 60% 40% at 50% 0%,rgba(0,245,255,0.04),transparent);
}
.eyebrow{
  display:inline-flex;align-items:center;gap:10px;
  font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;
  color:var(--accent);margin-bottom:20px;
  text-shadow:0 0 10px var(--accent);
}
.eyebrow::before,.eyebrow::after{
  content:'';display:block;width:24px;height:1px;
  background:linear-gradient(90deg,transparent,var(--accent));
}
.eyebrow::after{transform:scaleX(-1)}
h1{
  font-size:52px;font-weight:900;letter-spacing:-1px;line-height:1.05;
  margin-bottom:18px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
}
h1 .grd{
  background:linear-gradient(135deg,var(--accent) 0%,var(--accent2) 50%,var(--accent3) 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  filter:drop-shadow(0 0 20px rgba(0,245,255,0.3));
}
.sub{color:var(--muted);font-size:14px;line-height:1.7;max-width:400px;margin:0 auto 44px;letter-spacing:.5px}
.pills{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-bottom:60px}
.pill{
  font-size:10px;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);
  background:var(--s1);border:1px solid var(--border);
  padding:5px 14px;
  transition:border-color .2s,color .2s,box-shadow .2s;
}
.pill:hover{border-color:rgba(0,245,255,0.4);color:var(--accent);box-shadow:0 0 10px rgba(0,245,255,0.1)}

/* ─── DROP ZONE ─── */
.drop-wrap{max-width:620px;margin:0 auto 80px;padding:0 24px;position:relative;z-index:2}
.drop-zone{
  border:1px solid rgba(0,245,255,0.2);
  padding:64px 40px;text-align:center;
  background:rgba(0,245,255,0.02);
  position:relative;overflow:hidden;
  transition:border-color .2s,box-shadow .2s;
  backdrop-filter:blur(10px);
}
.drop-zone::before,.drop-zone::after{
  content:'';position:absolute;width:12px;height:12px;border-color:var(--accent);border-style:solid;
}
.drop-zone::before{top:10px;left:10px;border-width:1px 0 0 1px}
.drop-zone::after{bottom:10px;right:10px;border-width:0 1px 1px 0}
.drop-zone .spotlight{
  position:absolute;width:400px;height:400px;border-radius:50%;
  background:radial-gradient(circle,rgba(0,245,255,0.07) 0%,transparent 70%);
  transform:translate(-50%,-50%);pointer-events:none;opacity:0;transition:opacity .3s;
}
.drop-zone.drag-over{
  border-color:var(--accent);
  box-shadow:0 0 0 1px rgba(0,245,255,0.3),0 0 60px rgba(0,245,255,0.1),inset 0 0 40px rgba(0,245,255,0.03);
}
.drop-zone.drag-over .spotlight{opacity:1}
.drop-zone:hover .spotlight{opacity:1}
.drop-zone.drag-over .dz-icon{transform:scale(1.1) translateY(-4px)}
.dz-icon{font-size:48px;display:block;margin-bottom:20px;transition:transform .25s;filter:drop-shadow(0 0 20px rgba(0,245,255,0.5))}
.dz-title{font-size:17px;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;color:var(--text)}
.dz-sub{color:var(--muted);font-size:11px;line-height:1.7;margin-bottom:28px;letter-spacing:.8px}
.btn-pick{
  display:inline-flex;align-items:center;gap:8px;
  padding:11px 28px;border:1px solid var(--accent);background:rgba(0,245,255,0.08);color:var(--accent);
  font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
  box-shadow:0 0 20px rgba(0,245,255,0.2),inset 0 0 10px rgba(0,245,255,0.05);
  transition:background .15s,box-shadow .15s,transform .1s;
}
.btn-pick:hover{background:rgba(0,245,255,0.15);box-shadow:0 0 30px rgba(0,245,255,0.35),inset 0 0 15px rgba(0,245,255,0.08);transform:translateY(-1px)}
.btn-pick:active{transform:none}
input[type=file]{display:none}

/* ─── LOADING ─── */
#loading{display:none;text-align:center;padding:80px 24px;position:relative;z-index:2}
.spinner{
  width:48px;height:48px;margin:0 auto 18px;
  border:2px solid rgba(0,245,255,0.1);border-top-color:var(--accent);border-right-color:var(--accent2);
  border-radius:50%;animation:spin .8s linear infinite;
  box-shadow:0 0 20px rgba(0,245,255,0.2);
}
@keyframes spin{to{transform:rotate(360deg)}}
.loading-txt{color:var(--muted);font-size:11px;letter-spacing:2px;text-transform:uppercase}
.loading-names{margin-top:8px;font-size:11px;color:var(--accent);text-shadow:0 0 8px var(--accent)}

/* ─── RESULTS ─── */
#results{max-width:840px;margin:0 auto;padding:0 24px 80px;position:relative;z-index:2}

.rcard{
  background:rgba(0,245,255,0.02);
  border:1px solid var(--border);
  overflow:hidden;margin-bottom:20px;
  box-shadow:0 4px 30px rgba(0,0,0,.5),0 0 0 0 rgba(0,245,255,0);
  animation:fadeUp .4s cubic-bezier(.16,1,.3,1) both;
  backdrop-filter:blur(20px);
  transition:box-shadow .3s,border-color .3s;
}
.rcard:hover{border-color:rgba(0,245,255,0.22);box-shadow:0 4px 40px rgba(0,0,0,.6),0 0 20px rgba(0,245,255,0.05)}
@keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}

.card-head{
  padding:16px 24px;
  background:rgba(0,245,255,0.04);
  display:flex;align-items:center;justify-content:space-between;
  border-bottom:1px solid var(--border);gap:14px;flex-wrap:wrap;
}
.card-info{display:flex;flex-direction:column;gap:3px;min-width:0}
.card-name{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;letter-spacing:.5px}
.card-meta{font-size:10px;color:var(--muted);letter-spacing:.5px}
.vbadge{
  flex-shrink:0;padding:4px 14px;
  font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
}
.vok {background:rgba(0,255,157,.06);color:var(--ok);border:1px solid rgba(0,255,157,.3);box-shadow:0 0 10px rgba(0,255,157,.15)}
.vko {background:rgba(255,0,60,.06);color:#ff5577;border:1px solid rgba(255,0,60,.3);box-shadow:0 0 10px rgba(255,0,60,.15)}
.vwarn{background:rgba(255,183,0,.06);color:var(--warn);border:1px solid rgba(255,183,0,.3);box-shadow:0 0 10px rgba(255,183,0,.15)}

.card-body{padding:20px 24px;display:flex;flex-direction:column;gap:12px}
.crit-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:560px){.crit-grid{grid-template-columns:1fr}}

.crit{
  border:1px solid rgba(0,245,255,0.08);
  padding:14px 16px;background:rgba(0,245,255,0.015);
  transition:border-color .15s;position:relative;overflow:hidden;
}
.crit::before{
  content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(0,245,255,0.1),transparent);
}
.cok {border-color:rgba(0,255,157,.25)!important;background:rgba(0,255,157,.04)!important}
.cko {border-color:rgba(255,0,60,.25)!important;background:rgba(255,0,60,.04)!important}
.cwarn{border-color:rgba(255,183,0,.25)!important;background:rgba(255,183,0,.04)!important}

.crit-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.clabel{font-size:9px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted)}
.cok  .clabel{color:rgba(0,255,157,.6)}
.cko  .clabel{color:rgba(255,85,119,.6)}
.cwarn .clabel{color:rgba(255,183,0,.6)}
.cbadge{
  width:16px;height:16px;
  display:flex;align-items:center;justify-content:center;
  font-size:8px;font-weight:700;flex-shrink:0;
  clip-path:polygon(50% 0%,100% 50%,50% 100%,0% 50%);
}
.cok  .cbadge{background:var(--ok);color:#000}
.cko  .cbadge{background:var(--ko);color:#fff}
.cwarn .cbadge{background:var(--warn);color:#000}
.cneu .cbadge{background:var(--faint);color:var(--muted)}

.cmain{font-size:15px;font-weight:700;letter-spacing:.5px;margin-bottom:3px}
.cok  .cmain{color:var(--ok);text-shadow:0 0 10px rgba(0,255,157,.4)}
.cko  .cmain{color:#ff5577;text-shadow:0 0 10px rgba(255,0,60,.4)}
.cwarn .cmain{color:var(--warn);text-shadow:0 0 10px rgba(255,183,0,.4)}
.cneu .cmain{color:var(--text)}

.cdetail{font-size:10px;line-height:1.5;color:var(--muted);letter-spacing:.3px}
.cok  .cdetail{color:rgba(0,255,157,.55)}
.cko  .cdetail{color:rgba(255,85,119,.55)}
.cwarn .cdetail{color:rgba(255,183,0,.55)}

/* Tons tags */
.tons{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}
.ton{
  font-size:9px;font-weight:600;letter-spacing:.5px;
  background:rgba(255,183,0,.06);border:1px solid rgba(255,183,0,.25);
  padding:2px 8px;color:var(--warn);
}
/* Pages KO */
.pko-box{
  background:rgba(255,0,60,.04);border:1px solid rgba(255,0,60,.2);
  padding:12px 16px;
}
.pko-title{
  font-size:9px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
  color:#ff5577;margin-bottom:10px;
}
.pchips{display:flex;flex-wrap:wrap;gap:5px}
.pchip{
  font-size:10px;
  background:rgba(255,0,60,.06);border:1px solid rgba(255,0,60,.2);
  padding:3px 9px;color:#ff8899;letter-spacing:.3px;
}
/* Erreur */
.cerr{padding:18px 24px;display:flex;gap:12px;align-items:flex-start}
.cerr-icon{font-size:20px;flex-shrink:0;margin-top:1px}
.cerr-msg{font-size:12px;color:var(--muted);line-height:1.5;letter-spacing:.3px}
.cerr-hint{margin-top:5px;font-size:10px;color:var(--accent);letter-spacing:.5px}

/* ─── FOOTER ─── */
footer{
  text-align:center;padding:28px 24px;
  border-top:1px solid var(--border);
  font-size:10px;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase;
  position:relative;z-index:2;
}
footer b{color:rgba(0,245,255,0.3)}

/* ─── MINIATURES FOND PERDU ─── */
/* ── Hero vignette (card) ── */
.fp-visual-wrap{margin-top:8px;display:flex;flex-direction:column;gap:8px}
.fp-hero{display:inline-flex;flex-direction:column;align-items:center;gap:5px;cursor:pointer;}
.fp-hero-img{position:relative;overflow:hidden;border:1px solid var(--border);box-shadow:0 2px 20px rgba(0,0,0,.4),0 0 10px rgba(0,245,255,0.05);transition:transform .18s,box-shadow .18s;}
.fp-hero-img:hover{transform:scale(1.04);box-shadow:0 0 24px rgba(0,245,255,0.4);}
.fp-hero-img img{display:block;max-width:130px;height:auto}
.fp-hero-lbl{font-size:8px;color:var(--muted);letter-spacing:.5px;text-align:center}
.fp-hero-cta{font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:rgba(0,245,255,.65);}
.fp-thumb-store{display:none}
.fp-visual-header{display:flex;align-items:baseline;gap:8px;margin-bottom:6px}
.fp-visual-type{font-size:10px;font-weight:700;letter-spacing:1px;color:var(--accent);text-transform:uppercase}
.fp-visual-hint{font-size:8px;color:rgba(0,245,255,.4);letter-spacing:.5px}
/* fp-thumb hidden (data store only) */
.fp-badge-page{position:absolute;top:3px;left:3px;font-size:7px;font-weight:700;background:rgba(0,0,0,.85);color:var(--accent);padding:1px 5px;letter-spacing:1px;border:1px solid rgba(0,245,255,0.3);}
.fp-status{position:absolute;top:3px;right:3px;font-size:8px;font-weight:900;width:14px;height:14px;display:flex;align-items:center;justify-content:center;}
.fp-status.ok{background:rgba(0,200,80,.85);color:#000}
.fp-status.ko{background:rgba(255,0,50,.85);color:#fff}
/* ── VIEWER MODAL ── */
#fp-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.92);backdrop-filter:blur(12px);z-index:8000;align-items:center;justify-content:center;}
#fp-modal.open{display:flex}
.fp-viewer{display:flex;flex-direction:column;background:rgba(2,10,18,.97);border:1px solid rgba(0,245,255,.2);box-shadow:0 0 80px rgba(0,245,255,.06),0 0 200px rgba(0,245,255,.03);padding:22px 28px 18px;width:min(98vw,1500px);height:95vh;}
.fp-viewer-header{display:flex;align-items:center;gap:14px;margin-bottom:12px;flex-shrink:0;}
.fp-viewer-type{font-size:10px;font-weight:700;letter-spacing:1.5px;color:var(--accent);text-transform:uppercase;flex:1;}
.fp-viewer-info{font-size:9px;color:var(--muted);letter-spacing:.5px;}
.fp-modal-close{font-size:18px;cursor:pointer;color:var(--muted);transition:color .2s;line-height:1;background:none;border:none;padding:0;}
.fp-modal-close:hover{color:var(--accent2)}
.fp-viewer-stage{flex:1;display:flex;align-items:center;justify-content:center;gap:12px;overflow:auto;min-height:0;scroll-behavior:smooth;padding:12px 0;}
.fp-page-slot{position:relative;display:inline-block;line-height:0;flex-shrink:0;outline:1px solid rgba(0,245,255,0.3);box-shadow:0 0 18px rgba(0,245,255,0.1);}.fp-page-slot+.fp-page-slot img{max-width:min(43vw,520px)}
.fp-page-slot img{display:block;max-height:min(80vh,950px);max-width:min(85vw,1050px);width:min(80vw,900px);height:auto;object-fit:contain;}
.fp-band{position:absolute;pointer-events:none;display:flex;align-items:center;justify-content:center;}
/* Traits de coupe : remplacés par fp-trim-frame */
.fp-trim-h,.fp-trim-v{display:none}
/* Cadre TrimBox (bord de découpe) */
.fp-trim-frame{
  position:absolute;pointer-events:none;z-index:15;
  border:2px solid rgba(255,255,255,0.95);
  box-shadow:0 0 0 1px rgba(0,0,0,0.7),inset 0 0 0 1px rgba(0,0,0,0.5);
}
/* Repères de coupe aux coins */
.fp-trim-frame::before,.fp-trim-frame::after{
  content:'';position:absolute;background:rgba(255,255,255,0.9);
}
.fp-trim-frame::before{width:1px;height:8px;top:-10px;left:-1px;box-shadow:calc(100% + 1px) 0 0 rgba(255,255,255,0.9);}
.fp-trim-frame::after{width:8px;height:1px;left:-10px;top:-1px;box-shadow:0 calc(100% + 1px) 0 rgba(255,255,255,0.9);}
/* Étiquette de mesure dans la bande */
.fp-bleed-lbl{
  position:absolute;pointer-events:none;z-index:16;
  font-family:'SF Mono','Menlo',monospace;
  font-size:9px;font-weight:700;letter-spacing:.5px;
  color:rgba(255,255,255,0.95);text-shadow:0 1px 3px rgba(0,0,0,0.9);
  white-space:nowrap;
}
/* Pilules format en haut du slot */
.fp-format-pills{
  position:absolute;top:-28px;left:0;right:0;
  display:flex;justify-content:center;gap:8px;pointer-events:none;z-index:20;
}
.fp-format-pill{
  font-size:8px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;
  padding:2px 8px;border:1px solid;white-space:nowrap;
}
.fp-pill-media{color:rgba(0,245,255,0.8);border-color:rgba(0,245,255,0.4);background:rgba(0,245,255,0.1);}
.fp-pill-trim{color:rgba(255,255,255,0.9);border-color:rgba(255,255,255,0.5);background:rgba(0,0,0,0.7);}
.fp-viewer-nav{flex-shrink:0;display:flex;align-items:center;justify-content:center;gap:12px;margin-top:12px;}
.fp-nav-btn{background:rgba(0,245,255,.08);border:1px solid rgba(0,245,255,.3);color:var(--accent);font-size:14px;width:32px;height:32px;cursor:pointer;transition:background .2s;clip-path:polygon(5px 0%,100% 0%,calc(100% - 5px) 100%,0% 100%);display:flex;align-items:center;justify-content:center;}
.fp-nav-btn:hover:not(:disabled){background:rgba(0,245,255,.2)}
.fp-nav-btn:disabled{opacity:.25;cursor:default}
.fp-nav-ctr{font-size:10px;color:var(--muted);letter-spacing:1px;min-width:52px;text-align:center;}
.fp-nav-dots{display:flex;gap:5px;flex-wrap:wrap;justify-content:center;max-width:250px;}
.fp-nav-dot{width:5px;height:5px;border-radius:50%;background:rgba(255,255,255,.2);cursor:pointer;transition:background .15s,transform .15s;}
.fp-nav-dot:hover{background:rgba(0,245,255,.5)}
.fp-nav-dot.active{background:var(--accent);transform:scale(1.6)}
.fp-nav-dot.has-ko{background:rgba(255,50,60,.55)}
.fp-nav-dot.active.has-ko{background:rgba(255,80,70,1)}
.fp-modal-footer{flex-shrink:0;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-top:10px;}
.fp-modal-legend{font-size:8px;display:flex;gap:16px;color:rgba(255,255,255,.4);letter-spacing:.5px;}
.fp-legend-ok{color:rgba(0,230,80,.8)}
.fp-legend-ko{color:rgba(255,50,60,.8)}
.btn-dl-preview{background:rgba(0,245,255,.1);border:1px solid rgba(0,245,255,.35);color:var(--accent);padding:5px 14px;font-size:9px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;cursor:pointer;transition:background .2s,box-shadow .2s;clip-path:polygon(6px 0%,100% 0%,calc(100% - 6px) 100%,0% 100%);}
.btn-dl-preview:hover{background:rgba(0,245,255,.2);box-shadow:0 0 14px rgba(0,245,255,.25);}
/* ─── CMJN VIEWER ─── */
#cmjn-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.93);backdrop-filter:blur(12px);z-index:8001;align-items:center;justify-content:center;}
#cmjn-modal.open{display:flex}
.cmjn-viewer{display:flex;flex-direction:column;background:rgba(2,6,14,.97);border:1px solid rgba(255,0,170,.2);box-shadow:0 0 80px rgba(255,0,170,.06),0 0 200px rgba(255,0,170,.02);padding:18px 22px 14px;width:min(98vw,1200px);height:95vh;}
.cmjn-header{display:flex;align-items:center;gap:12px;flex-shrink:0;margin-bottom:12px;flex-wrap:wrap;}
.cmjn-title{font-size:10px;font-weight:700;letter-spacing:1.5px;color:var(--accent2);text-transform:uppercase;flex:1;}
.cmjn-plates{display:flex;gap:5px;}
.cmjn-plate-btn{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.18);color:rgba(255,255,255,.35);font-size:10px;font-weight:800;width:30px;height:30px;cursor:pointer;transition:all .15s;letter-spacing:.5px;clip-path:polygon(4px 0%,100% 0%,calc(100% - 4px) 100%,0% 100%);}
.cmjn-plate-btn.inactive{background:rgba(0,0,0,.3);border-color:rgba(255,255,255,.08);color:rgba(255,255,255,.2);}
#cmjn-btn-C.active{background:rgba(0,200,255,.18);border-color:rgba(0,200,255,.7);color:#00c8ff;box-shadow:0 0 8px rgba(0,200,255,.3);}
#cmjn-btn-M.active{background:rgba(255,0,170,.18);border-color:rgba(255,0,170,.7);color:#ff00aa;box-shadow:0 0 8px rgba(255,0,170,.3);}
#cmjn-btn-Y.active{background:rgba(255,220,0,.18);border-color:rgba(255,220,0,.7);color:#ffdc00;box-shadow:0 0 8px rgba(255,220,0,.3);}
#cmjn-btn-K.active{background:rgba(220,220,220,.12);border-color:rgba(220,220,220,.5);color:rgba(255,255,255,.8);box-shadow:0 0 8px rgba(255,255,255,.15);}
.cmjn-readout{display:flex;align-items:center;gap:6px;font-size:10px;font-family:'SF Mono','Menlo',monospace;background:rgba(0,0,0,.4);padding:4px 10px;border:1px solid rgba(255,255,255,.06);}
.cmjn-ch{font-weight:800;letter-spacing:.5px;min-width:10px;}
.cmjn-c-lbl{color:#00c8ff}.cmjn-m-lbl{color:#ff00aa}.cmjn-y-lbl{color:#ffdc00}.cmjn-k-lbl{color:rgba(255,255,255,.55)}
.cmjn-val{color:rgba(255,255,255,.85);min-width:36px;margin-right:4px;}
.cmjn-stage{flex:1;overflow:auto;display:flex;align-items:center;justify-content:center;min-height:0;padding:8px 0;}
#cmjn-canvas{max-width:100%;max-height:100%;object-fit:contain;cursor:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='32' height='32' viewBox='0 0 32 32'%3E%3Ccircle cx='13' cy='13' r='9' fill='none' stroke='%2300f5ff' stroke-width='1.8'/%3E%3Cline x1='13' y1='1' x2='13' y2='7' stroke='%2300f5ff' stroke-width='1.4'/%3E%3Cline x1='13' y1='19' x2='13' y2='25' stroke='%2300f5ff' stroke-width='1.4'/%3E%3Cline x1='1' y1='13' x2='7' y2='13' stroke='%2300f5ff' stroke-width='1.4'/%3E%3Cline x1='19' y1='13' x2='25' y2='13' stroke='%2300f5ff' stroke-width='1.4'/%3E%3Cline x1='20' y1='20' x2='30' y2='30' stroke='%2300f5ff' stroke-width='2.2' stroke-linecap='round'/%3E%3C/svg%3E") 13 13, zoom-in!important;display:block;image-rendering:auto;}
.cmjn-footer{flex-shrink:0;display:flex;align-items:center;justify-content:center;gap:12px;margin-top:10px;}
.btn-cmyk-open{background:rgba(255,0,170,.1);border:1px solid rgba(255,0,170,.4);color:rgba(255,0,170,.9);padding:4px 10px;font-size:9px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;cursor:pointer;transition:background .2s,box-shadow .2s;clip-path:polygon(5px 0%,100% 0%,calc(100% - 5px) 100%,0% 100%);}
.btn-cmyk-open:hover{background:rgba(255,0,170,.22);box-shadow:0 0 12px rgba(255,0,170,.25);}

/* ── Barre résultats ── */
.results-bar{
  display:flex;align-items:center;justify-content:flex-end;
  margin-bottom:18px;gap:10px;
}
.btn-rapport{
  background:rgba(255,35,55,.12);
  border:1px solid rgba(255,35,55,.4);
  color:rgba(255,100,110,1);
  padding:7px 18px;font-size:10px;font-weight:700;
  letter-spacing:1.2px;text-transform:uppercase;
  cursor:pointer;transition:background .2s,box-shadow .2s;
  clip-path:polygon(6px 0%,100% 0%,calc(100% - 6px) 100%,0% 100%);
}
.btn-rapport:hover{
  background:rgba(255,35,55,.25);
  box-shadow:0 0 16px rgba(255,35,55,.3);
}
.results-ok-chip{
  font-size:10px;font-weight:600;letter-spacing:1px;
  color:rgba(0,230,80,.7);text-transform:uppercase;
}
/* Scrollbar */
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(0,245,255,0.2);}
::-webkit-scrollbar-thumb:hover{background:rgba(0,245,255,0.4);}

/* ─── OVERLAY PLEINE PAGE ─── */
#page-drop-overlay{
  position:fixed;inset:0;z-index:9999;
  pointer-events:none;opacity:0;
  transition:opacity .2s;
  display:flex;align-items:center;justify-content:center;
  background:rgba(2,6,8,0.92);
  backdrop-filter:blur(12px);
}
#page-drop-overlay.active{opacity:1;pointer-events:all}
.overlay-inner{
  border:1px solid rgba(0,245,255,0.6);
  padding:60px 80px;text-align:center;
  background:rgba(0,245,255,0.03);
  box-shadow:0 0 80px rgba(0,245,255,0.15),0 0 160px rgba(0,245,255,0.05),inset 0 0 60px rgba(0,245,255,0.03);
  animation:pulseOverlay 1.5s ease-in-out infinite;
  position:relative;
}
.overlay-inner::before,.overlay-inner::after{
  content:'';position:absolute;width:20px;height:20px;border-color:var(--accent);border-style:solid;
}
.overlay-inner::before{top:-1px;left:-1px;border-width:2px 0 0 2px}
.overlay-inner::after{bottom:-1px;right:-1px;border-width:0 2px 2px 0}
@keyframes pulseOverlay{
  0%,100%{box-shadow:0 0 60px rgba(0,245,255,0.1),inset 0 0 40px rgba(0,245,255,0.02)}
  50%    {box-shadow:0 0 100px rgba(0,245,255,0.25),inset 0 0 60px rgba(0,245,255,0.06)}
}
.overlay-icon{font-size:64px;display:block;margin-bottom:24px;
  filter:drop-shadow(0 0 30px rgba(0,245,255,0.7));
  animation:floatIcon 2s ease-in-out infinite;
}
@keyframes floatIcon{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}
.overlay-title{
  font-size:26px;font-weight:900;letter-spacing:4px;text-transform:uppercase;margin-bottom:10px;
  color:var(--accent);text-shadow:0 0 20px var(--accent),0 0 40px rgba(0,245,255,0.4);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
}
.overlay-sub{font-size:11px;color:var(--muted);letter-spacing:2px;text-transform:uppercase}

/* ─── NAV TABS ─── */
.nav-tabs{
  position:sticky;top:58px;z-index:190;
  display:flex;gap:0;
  background:rgba(2,6,8,0.9);
  border-bottom:1px solid var(--border);
  backdrop-filter:blur(20px);
  padding:0 48px;
}
.nav-tab{
  font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
  color:var(--muted);background:transparent;border:none;
  padding:14px 22px;position:relative;
  transition:color .2s;
  border-bottom:2px solid transparent;
  margin-bottom:-1px;
}
.nav-tab:hover{color:var(--text)}
.nav-tab.active{color:var(--accent);border-bottom-color:var(--accent);text-shadow:0 0 10px var(--accent)}

/* ─── TOOL SECTIONS ─── */
.tool-section{padding:60px 48px 80px;position:relative;z-index:2;max-width:900px;margin:0 auto}
.tool-title{font-size:22px;font-weight:900;letter-spacing:-.5px;margin-bottom:8px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.tool-title .grd{background:linear-gradient(135deg,var(--accent) 0%,var(--accent2) 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.tool-desc{font-size:12px;color:var(--muted);letter-spacing:.5px;line-height:1.7;margin-bottom:36px}
.tool-upload{
  border:1px solid rgba(0,245,255,0.2);padding:36px;text-align:center;
  background:rgba(0,245,255,0.02);
  transition:border-color .2s,box-shadow .2s;margin-bottom:20px;
}
.tool-upload:hover,.tool-upload.drag-over{border-color:var(--accent);box-shadow:0 0 30px rgba(0,245,255,0.08)}
.tool-upload-icon{font-size:32px;display:block;margin-bottom:10px;filter:drop-shadow(0 0 10px rgba(0,245,255,0.4))}
.tool-upload-title{font-size:13px;font-weight:700;letter-spacing:1px;color:var(--text);margin-bottom:5px}
.tool-upload-sub{font-size:11px;color:var(--muted);letter-spacing:.5px}
.tool-input{display:none}
.tool-btn-row{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:20px}
.btn-tool{
  font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
  color:var(--bg);background:var(--accent);border:none;padding:11px 28px;
  transition:box-shadow .2s,transform .1s;
  box-shadow:0 0 20px rgba(0,245,255,0.3);
}
.btn-tool:hover{box-shadow:0 0 32px rgba(0,245,255,0.5);transform:translateY(-1px)}
.btn-tool:disabled{opacity:.4;transform:none}
.tool-status{font-size:11px;letter-spacing:.5px;padding:10px 14px;background:var(--s1);border:1px solid var(--border);display:none}
.tool-status.visible{display:inline-block}
.tool-status.ok{border-color:rgba(0,255,157,.3);color:var(--ok)}
.tool-status.ko{border-color:rgba(255,0,60,.3);color:#ff5577}
.tool-status.running{color:var(--accent)}
/* Options imposition */
.tool-options{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:24px}
.tool-option{
  flex:1;min-width:180px;border:1px solid var(--border);padding:14px 18px;
  background:var(--s1);transition:border-color .2s,box-shadow .2s;position:relative;
}
.tool-option.selected{border-color:var(--accent);box-shadow:0 0 14px rgba(0,245,255,0.1);background:rgba(0,245,255,0.04)}
.tool-option input[type=radio]{position:absolute;opacity:0;width:0;height:0}
.tool-option-title{font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--text);margin-bottom:4px}
.tool-option-desc{font-size:10px;color:var(--muted);letter-spacing:.4px;line-height:1.5}
.tool-option-check{position:absolute;top:10px;right:12px;width:13px;height:13px;border:1px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:9px;color:transparent}
.tool-option.selected .tool-option-check{border-color:var(--accent);color:var(--accent)}
/* Organiser grid */
.pages-grid{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:14px;
  padding:18px;border:1px solid var(--border);background:var(--s1);min-height:140px;margin-bottom:20px;
}
.page-thumb{
  position:relative;background:var(--s2);border:1px solid var(--border);
  padding:6px 6px 24px;cursor:grab;
  transition:border-color .2s,box-shadow .2s,transform .15s,opacity .15s;user-select:none;
}
.page-thumb:hover{border-color:rgba(0,245,255,0.4);box-shadow:0 0 14px rgba(0,245,255,0.1);transform:translateY(-2px)}
.page-thumb.dragging{opacity:.35;transform:scale(.94)}
.page-thumb.drag-over-thumb{border-color:var(--accent2);box-shadow:0 0 18px rgba(255,0,170,0.2)}
.page-thumb img{width:100%;display:block;background:#111;min-height:70px}
.page-thumb-num{position:absolute;bottom:5px;left:0;right:0;text-align:center;font-size:9px;font-weight:700;letter-spacing:1px;color:var(--muted);text-transform:uppercase}
.pages-grid-empty{text-align:center;padding:36px;font-size:11px;color:var(--muted);letter-spacing:1px;grid-column:1/-1}
/* Convertir */
.convert-info{border:1px solid rgba(0,245,255,0.1);padding:18px 20px;background:var(--s1);font-size:11px;color:var(--muted);letter-spacing:.4px;line-height:1.8;margin-bottom:24px}
.convert-info strong{color:var(--text)}
/* Fix drag organiser: l'image ne doit pas être la source de drag */
.page-thumb img{-webkit-user-drag:none;user-select:none;pointer-events:none}
.page-thumb{-webkit-user-drag:element}

/* ─── IMPOSITION PRO ─── */
.imp-settings{display:grid;grid-template-columns:1fr 1fr;gap:12px 20px;margin-bottom:20px;background:var(--s1);border:1px solid var(--border);padding:18px 20px}
.imp-settings-title{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--accent);margin-bottom:4px;grid-column:1/-1;text-shadow:0 0 8px var(--accent)}
.imp-row{display:flex;flex-direction:column;gap:4px}
.imp-label{font-size:9px;color:var(--muted);letter-spacing:.5px;text-transform:uppercase}
.imp-input,.imp-select{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 10px;font-family:inherit;font-size:11px;width:100%;outline:none;-webkit-appearance:none}
.imp-input:focus,.imp-select:focus{border-color:var(--accent)}
.imp-checks{display:flex;flex-wrap:wrap;gap:10px 18px;grid-column:1/-1;padding-top:4px;border-top:1px solid var(--border);margin-top:4px}
.imp-chk-lbl{display:flex;align-items:center;gap:6px;font-size:10px;color:var(--muted);letter-spacing:.5px}
.imp-chk-lbl input[type=checkbox]{width:11px;height:11px;accent-color:var(--accent)}
.imp-preview-wrap{margin-bottom:20px;background:var(--s1);border:1px solid var(--border);padding:14px}
.imp-preview-hdr{font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:10px;display:flex;align-items:center;justify-content:space-between}
#imp-canvas{max-width:100%;display:block;margin:0 auto;background:#0a0e10;border:1px solid rgba(0,245,255,.06)}
.imp-spread-nav{display:flex;align-items:center;justify-content:center;gap:14px;margin-top:10px}
.imp-spread-ctr{font-size:11px;color:var(--muted);letter-spacing:1px;min-width:60px;text-align:center}

/* ─── PITSTOP PRO ─── */
.pit-options{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:24px}
.pit-group{border:1px solid var(--border);padding:16px 18px;background:var(--s1)}
.pit-group-title{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--accent);margin-bottom:12px;text-shadow:0 0 6px var(--accent)}
.pit-check{display:flex;align-items:flex-start;gap:9px;margin-bottom:10px;font-size:11px;color:var(--text);line-height:1.4}
.pit-check input[type=checkbox]{width:11px;height:11px;flex-shrink:0;margin-top:2px;accent-color:var(--accent)}
.pit-check-sub{font-size:9px;color:var(--muted);letter-spacing:.4px;margin-top:2px}
.pit-check.na{opacity:.35}

/* CMJN spots */
.cmjn-spots{display:flex;flex-wrap:wrap;gap:4px;padding:6px 12px;border-top:1px solid rgba(0,245,255,.08);min-height:0}
.cmjn-spot-chip{font-size:9px;font-weight:700;letter-spacing:.5px;padding:2px 8px;border:1px solid rgba(255,255,255,.2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:130px}

/* ─── BOUTON INFO FIXE ─── */
#btn-info-fixed{
  position:fixed;bottom:24px;right:24px;z-index:1000;
  width:38px;height:38px;border-radius:50%;
  background:rgba(2,6,8,0.85);border:1px solid rgba(0,245,255,0.3);
  color:var(--accent);font-size:15px;font-weight:700;
  display:flex;align-items:center;justify-content:center;
  box-shadow:0 0 14px rgba(0,245,255,0.12),0 2px 10px rgba(0,0,0,0.4);
  transition:box-shadow .2s,border-color .2s,transform .1s;
  backdrop-filter:blur(10px);text-decoration:none;
}
#btn-info-fixed:hover{border-color:var(--accent);box-shadow:0 0 26px rgba(0,245,255,0.32),0 2px 10px rgba(0,0,0,0.4);transform:scale(1.1)}
</style>
</head>
<body>

<!-- Curseur custom -->
<div id="cur"></div>
<div id="cur-ring"></div>

<!-- Viewer fond perdu -->
<div id="fp-loupe"></div>

<div id="fp-modal" onclick="closeFpModal(event)">
  <div class="fp-viewer">
    <div class="fp-viewer-header">
      <span class="fp-viewer-type" id="fp-viewer-type"></span>
      <span class="fp-viewer-info" id="fp-viewer-info"></span>
      <button class="fp-modal-close" onclick="closeFpModal(null,true)">✕</button>
    </div>
    <div class="fp-viewer-stage" id="fp-viewer-stage"></div>
    <div class="fp-viewer-nav">
      <button class="fp-nav-btn" id="fp-nav-prev" onclick="fpNavStep(-1)">&#8592;</button>
      <div class="fp-nav-dots" id="fp-nav-dots"></div>
      <span class="fp-nav-ctr" id="fp-nav-ctr"></span>
      <button class="fp-nav-btn" id="fp-nav-next" onclick="fpNavStep(1)">&#8594;</button>
    </div>
    <div class="fp-modal-footer">
      <div class="fp-modal-legend">
        <span><span class="fp-legend-ok">■</span> Fond perdu ≥ 3mm (OK)</span>
        <span><span class="fp-legend-ko">■</span> Fond perdu &lt; 3mm (KO)</span>
        <span style="color:rgba(255,255,255,.7)">□ Cadre de découpe (TrimBox)</span>
      </div>
      <button class="btn-dl-preview" onclick="downloadFpPreview()">⬇ Télécharger l'aperçu PDF</button>
    </div>
  </div>
</div>

<!-- Viewer CMJN -->
<div id="cmjn-modal" onclick="closeCmykModal(event)">
  <div class="cmjn-viewer">
    <div class="cmjn-header">
      <span class="cmjn-title">◎ Aperçu CMJN</span>
      <div class="cmjn-plates">
        <button id="cmjn-btn-C" class="cmjn-plate-btn active" onclick="toggleCmykPlate('C')">C</button>
        <button id="cmjn-btn-M" class="cmjn-plate-btn active" onclick="toggleCmykPlate('M')">M</button>
        <button id="cmjn-btn-Y" class="cmjn-plate-btn active" onclick="toggleCmykPlate('Y')">J</button>
        <button id="cmjn-btn-K" class="cmjn-plate-btn active" onclick="toggleCmykPlate('K')">N</button>
      </div>
      <div class="cmjn-readout">
        <span class="cmjn-ch cmjn-c-lbl">C</span><span id="cmjn-c" class="cmjn-val">—%</span>
        <span class="cmjn-ch cmjn-m-lbl">M</span><span id="cmjn-m" class="cmjn-val">—%</span>
        <span class="cmjn-ch cmjn-y-lbl">J</span><span id="cmjn-y" class="cmjn-val">—%</span>
        <span class="cmjn-ch cmjn-k-lbl">N</span><span id="cmjn-k" class="cmjn-val">—%</span>
      </div>
      <button class="fp-modal-close" onclick="closeCmykModal(null,true)">✕</button>
    </div>
    <div id="cmjn-spots" class="cmjn-spots" style="display:none"></div>
    <div class="cmjn-stage">
      <canvas id="cmjn-canvas" onmousemove="_cmykMouseMove(event)"></canvas>
    </div>
    <div class="cmjn-footer">
      <button class="fp-nav-btn" onclick="_cmykStep(-1)">&#8592;</button>
      <span id="cmjn-page-ctr" class="fp-nav-ctr">— / —</span>
      <button class="fp-nav-btn" onclick="_cmykStep(1)">&#8594;</button>
    </div>
  </div>
</div>

<!-- Overlay pleine page drag & drop -->
<div id="page-drop-overlay">
  <div class="overlay-inner">
    <span class="overlay-icon">🖨</span>
    <div class="overlay-title">Déposez vos PDF</div>
    <div class="overlay-sub">PDF · PNG · JPG · TIFF · EPS</div>
  </div>
</div>

<header>
  <div class="logo">
    <div class="logo-mark">V</div>
    <div>
      <div class="logo-name">Vik <em>BAT</em> <span style="font-size:10px;font-weight:500;color:var(--muted);letter-spacing:.5px">1.4</span></div>
      <div class="logo-sub">Contrôle prépresse</div>
    </div>
  </div>
  <div class="hdr-right">
    <span class="bat-chip">Bon à Tirer</span>
    <button class="btn-hist" id="btnHist" onclick="toggleHist()">⏱ Historique</button>
    <span class="credit">Créé par Viktor</span>
  </div>
</header>

<!-- Nav tabs -->
<nav class="nav-tabs" id="mainNav">
  <button class="nav-tab active" onclick="switchTab('analyse',this)">Analyse</button>
  <button class="nav-tab" onclick="switchTab('imposition',this)">Imposition</button>
  <button class="nav-tab" onclick="switchTab('organiser',this)">Organiser</button>
  <button class="nav-tab" onclick="switchTab('convertir',this)">Convertir</button>
</nav>

<!-- Panneau historique -->
<div id="hist-panel">
  <div class="hist-head">
    <div class="hist-title">⏱ Historique</div>
    <div class="hist-actions">
      <button class="btn-clear" onclick="clearHist()">Effacer</button>
      <button class="btn-close" onclick="toggleHist()">✕</button>
    </div>
  </div>
  <div class="hist-list" id="histList"><div class="hist-empty">Aucun fichier analysé</div></div>
</div>

<div id="app">
  <div class="hero">
    <div class="eyebrow">Analyse prépresse</div>
    <h1>Vos PDF <span class="grd">prêts<br>à l'impression</span></h1>
    <p class="sub">Vérifiez colorimétrie, résolution, tons directs et surimpression avant impression.</p>
    <div class="pills">
      <span class="pill">CMJN / RVB</span>
      <span class="pill">Tons directs</span>
      <span class="pill">Résolution DPI</span>
      <span class="pill">Surimpression</span>
      <span class="pill">Multi-fichiers</span>
    </div>
  </div>

  <div class="drop-wrap">
    <div class="drop-zone" id="dropZone">
      <div class="spotlight" id="spotlight"></div>
      <span class="dz-icon">🖨</span>
      <div class="dz-title">Glissez vos PDF n'importe où</div>
      <div class="dz-sub">Sur toute la page · Un ou plusieurs fichiers · Analyse instantanée</div>
      <button class="btn-pick" id="btnPick">＋ Choisir des fichiers</button>
      <input type="file" id="fileInput" multiple accept=".pdf,.PDF,.png,.PNG,.jpg,.JPG,.jpeg,.JPEG,.tif,.tiff,.TIFF,.eps,.ai">
    </div>
  </div>
</div>

<div id="loading">
  <div class="spinner"></div>
  <div class="loading-txt">Analyse en cours…</div>
  <div class="loading-names" id="loadingNames"></div>
</div>

<div id="results"></div>

<!-- ─── ONGLET IMPOSITION ─── -->
<div id="tab-imposition" class="tool-section" style="display:none">
  <div class="tool-title">Imposition <span class="grd">Professionnelle</span></div>
  <div class="tool-desc">Imposition 2-up automatique avec traits de coupe, repères de repérage et contrôle fond perdu — comme sur les systèmes d'imprimerie (Preps, Metrix).</div>

  <div class="tool-upload" id="imp-drop" onclick="document.getElementById('imp-input').click()">
    <input type="file" id="imp-input" class="tool-input" accept=".pdf,.PDF">
    <span class="tool-upload-icon">📄</span>
    <div class="tool-upload-title">Déposer le PDF page à page</div>
    <div class="tool-upload-sub" id="imp-filename">Cliquez ou glissez un PDF ici</div>
  </div>

  <div class="imp-settings">
    <div class="imp-settings-title">⚙ Paramètres d'imposition</div>
    <div class="imp-row">
      <span class="imp-label">Format de la planche de sortie</span>
      <select class="imp-select" id="imp-sheet-size" onchange="impSettingChanged()">
        <option value="auto" selected>Auto — 2 × format page + marques</option>
        <option value="a3l">A3 Paysage 420 × 297 mm</option>
        <option value="a3p">A3 Portrait 297 × 420 mm</option>
        <option value="a4l">A4 Paysage 297 × 210 mm</option>
        <option value="tabloid">Tabloid 432 × 279 mm</option>
      </select>
    </div>
    <div class="imp-row">
      <span class="imp-label">Mode d'imposition</span>
      <select class="imp-select" id="imp-mode-sel" onchange="impSettingChanged()">
        <option value="sequential">Séquentiel (1-2, 3-4, 5-6…)</option>
        <option value="booklet">Booklet — piqûre à cheval</option>
        <option value="booklet_pb">Booklet — dos carré collé</option>
      </select>
    </div>
    <div class="imp-row">
      <span class="imp-label">Fond perdu spine/intérieur (mm)</span>
      <input class="imp-input" id="imp-inner-bleed" type="number" value="3" min="0" max="20" step="0.5" oninput="impSettingChanged()">
    </div>
    <div class="imp-row">
      <span class="imp-label">Fond perdu extérieur (mm)</span>
      <input class="imp-input" id="imp-outer-bleed" type="number" value="3" min="0" max="20" step="0.5" oninput="impSettingChanged()">
    </div>
    <div class="imp-row">
      <span class="imp-label">Blanc tournant / Creep (mm)</span>
      <input class="imp-input" id="imp-creep" type="number" value="0" min="0" max="5" step="0.1" oninput="impSettingChanged()">
    </div>
    <div class="imp-row">
      <span class="imp-label">Marge marques (mm)</span>
      <input class="imp-input" id="imp-mark-margin" type="number" value="8" min="5" max="25" step="1" oninput="impSettingChanged()">
    </div>
    <div class="imp-checks">
      <label class="imp-chk-lbl"><input type="checkbox" id="imp-crop-marks" checked onchange="impSettingChanged()"> Traits de coupe</label>
      <label class="imp-chk-lbl"><input type="checkbox" id="imp-reg-marks" checked onchange="impSettingChanged()"> Repères de repérage</label>
      <label class="imp-chk-lbl"><input type="checkbox" id="imp-fold-marks" checked onchange="impSettingChanged()"> Repère de pliure</label>
      <label class="imp-chk-lbl"><input type="checkbox" id="imp-color-bar" onchange="impSettingChanged()"> Barre couleur CMJN</label>
    </div>
  </div>

  <div class="imp-preview-wrap">
    <div class="imp-preview-hdr">
      <span>📐 Prévisualisation planche</span>
      <span id="imp-preview-info" style="color:var(--muted);font-weight:400">Chargez un PDF pour prévisualiser</span>
    </div>
    <canvas id="imp-canvas" width="680" height="260"></canvas>
    <div class="imp-spread-nav">
      <button class="fp-nav-btn" onclick="_impSpreadStep(-1)">←</button>
      <span class="imp-spread-ctr" id="imp-spread-ctr">— / —</span>
      <button class="fp-nav-btn" onclick="_impSpreadStep(1)">→</button>
    </div>
  </div>

  <div class="tool-btn-row">
    <button class="btn-tool" id="imp-btn" onclick="runImposition()" disabled>▶ Générer l'imposition PDF</button>
    <span id="imp-status" class="tool-status"></span>
  </div>
</div>

<!-- ─── ONGLET ORGANISER ─── -->
<div id="tab-organiser" class="tool-section" style="display:none">
  <div class="tool-title">Organiser <span class="grd">les pages</span></div>
  <div class="tool-desc">Glissez-déposez les vignettes pour réordonner les pages, puis téléchargez le PDF réorganisé.</div>
  <div class="tool-upload" id="org-drop" onclick="document.getElementById('org-input').click()">
    <input type="file" id="org-input" class="tool-input" accept=".pdf,.PDF">
    <span class="tool-upload-icon">🗂</span>
    <div class="tool-upload-title">Ouvrir un PDF</div>
    <div class="tool-upload-sub" id="org-filename">Cliquez ou glissez un PDF ici</div>
  </div>
  <div class="pages-grid" id="org-pages-grid">
    <div class="pages-grid-empty">Aucun PDF chargé</div>
  </div>
  <div class="tool-btn-row">
    <button class="btn-tool" id="org-btn" onclick="runOrganiser()" disabled>⬇ Télécharger PDF réordonné</button>
    <span id="org-status" class="tool-status"></span>
  </div>
</div>

<!-- ─── ONGLET CONVERTIR ─── -->
<div id="tab-convertir" class="tool-section" style="display:none">
  <div class="tool-title">Convertir en <span class="grd">Quadrichromie</span></div>
  <div class="tool-desc">Convertit les couleurs Pantone / tons directs en CMJN procédé sans perte de qualité visuelle.</div>
  <div class="convert-info">
    <strong>Comment ça fonctionne :</strong> VikBAT re-rastérise chaque page via PyMuPDF en espace colorimétrique CMYK natif,
    éliminant automatiquement tous les tons directs et espaces RVB. La résolution de sortie est de 300 dpi.
    Résultat : un PDF 100 % CMJN compatible avec tous les flux prépresse.
  </div>
  <div class="tool-upload" id="conv-drop" onclick="document.getElementById('conv-input').click()">
    <input type="file" id="conv-input" class="tool-input" accept=".pdf,.PDF">
    <span class="tool-upload-icon">🎨</span>
    <div class="tool-upload-title">PDF avec Pantone / tons directs</div>
    <div class="tool-upload-sub" id="conv-filename">Cliquez ou glissez un PDF ici</div>
  </div>
  <div class="tool-btn-row">
    <button class="btn-tool" id="conv-btn" onclick="runConvertir()" disabled>🔄 Convertir en CMJN</button>
    <span id="conv-status" class="tool-status"></span>
  </div>
</div>

<!-- ─── ONGLET PITSTOP PRO ─── -->

<footer>
  <b>VikBAT 1.4</b> · Outil de contrôle prépresse · Créé par <b>Viktor</b>
</footer>

<!-- Bouton info fixe -->
<a id="btn-info-fixed" href="/info" target="_blank" title="Protocoles &amp; aide">ℹ</a>

<script>
/* ─── GLOBAUX ─── */
let _lastResults  = [];
let _fpModalData  = null;

/* ─── CURSEUR CUSTOM ─── */
const cur     = document.getElementById('cur');
const curRing = document.getElementById('cur-ring');
let mx = -200, my = -200, rx = -200, ry = -200;

document.addEventListener('mousemove', e => { mx = e.clientX; my = e.clientY; });
function animCursor() {
  rx += (mx - rx) * 0.14;
  ry += (my - ry) * 0.14;
  cur.style.left     = mx + 'px';
  cur.style.top      = my + 'px';
  curRing.style.left = rx + 'px';
  curRing.style.top  = ry + 'px';
  requestAnimationFrame(animCursor);
}
animCursor();

const hoverEls = () => document.querySelectorAll('a,button,.pill,.drop-zone,input');
function addHover(){
  hoverEls().forEach(el => {
    el.addEventListener('mouseenter', () => document.body.classList.add('cur-hover'));
    el.addEventListener('mouseleave', () => document.body.classList.remove('cur-hover'));
  });
}
addHover();
document.addEventListener('mousedown', () => document.body.classList.add('cur-click'));
document.addEventListener('mouseup',   () => document.body.classList.remove('cur-click'));
document.addEventListener('keydown', e => {
  const modal = document.getElementById('fp-modal');
  const cmjnModal = document.getElementById('cmjn-modal');
  if(cmjnModal.classList.contains('open')){
    if(e.key==='ArrowLeft')  _cmykStep(-1);
    if(e.key==='ArrowRight') _cmykStep(1);
    if(e.key==='Escape') closeCmykModal(null,true);
    return;
  }
  if(modal.classList.contains('open')){
    if(e.key==='ArrowLeft')  fpNavStep(-1);
    if(e.key==='ArrowRight') fpNavStep(1);
  }
  if(e.key==='Escape') closeFpModal(null,true);
});

/* ─── VIEWER FOND PERDU ─── */
let _fpThumbs  = [];
let _fpIdx     = 0;
let _fpTwoUp   = false;

function openFpViewer(heroEl){
  const wrap   = heroEl.closest('.fp-visual-wrap');
  const store  = wrap.querySelector('.fp-thumb-store');
  _fpThumbs    = [...store.querySelectorAll('.fp-thumb[data-page]')];
  _fpTwoUp     = wrap.dataset.twoup === 'true';
  _fpCacheKey  = wrap.dataset.cachekey || '';
  const typeDoc = wrap.dataset.typedoc || '';
  _fpIdx = 0;
  document.getElementById('fp-viewer-type').textContent = typeDoc;
  /* Points de navigation */
  const dotsEl = document.getElementById('fp-nav-dots');
  if(_fpThumbs.length <= 24){
    dotsEl.innerHTML = _fpThumbs.map((t,i)=>{
      const ko = t.dataset.conforme === 'false';
      return `<div class="fp-nav-dot ${ko?'has-ko':''}" onclick="fpNavTo(${i})" title="p.${t.dataset.page}"></div>`;
    }).join('');
  } else { dotsEl.innerHTML=''; }
  /* Ouvrir le modal EN PREMIER pour que offsetWidth soit calculé */
  document.getElementById('fp-modal').classList.add('open');
  requestAnimationFrame(() => { _fpRender(); });
}

/* Rendre les page(s) courante(s) avec bandeaux */
function _fpRender(){
  const stage = document.getElementById('fp-viewer-stage');
  stage.innerHTML = '';
  if(!_fpThumbs.length) return;
  const t = _fpThumbs[_fpIdx];
  /* 2-up : brochure → page gauche + page droite en regard */
  /* p0 = couverture seule, p1+p2 = cahier 1, etc. */
  const showTwo = _fpTwoUp && _fpIdx > 0 && (_fpIdx+1) < _fpThumbs.length;
  const slots = showTwo ? [_fpThumbs[_fpIdx], _fpThumbs[_fpIdx+1]] : [t];
  slots.forEach((pageEl, si)=>{
    const slot = document.createElement('div');
    slot.className = 'fp-page-slot';
    const img = document.createElement('img');
    img.alt = 'p.' + pageEl.dataset.page;
    if(si===0) _fpModalData = {wmm:+pageEl.dataset.wmm,hmm:+pageEl.dataset.hmm,bt:+pageEl.dataset.bt,bb:+pageEl.dataset.bb,bl:+pageEl.dataset.bl,br:+pageEl.dataset.br,page:pageEl.dataset.page,img:pageEl.dataset.img};
    /* IMPORTANT: attacher onload AVANT de set src, mais appendre le slot au DOM
       AVANT de set src pour que offsetWidth soit > 0 quand onload s'exécute */
    img.onload = ()=>{ _fpApplyBands(slot, img, pageEl); };
    slot.appendChild(img);
    stage.appendChild(slot);           /* ← dans le DOM AVANT src */
    img.src = 'data:image/png;base64,' + pageEl.dataset.img;
    /* Fallback : si l'image est déjà en cache, onload peut ne pas se déclencher */
    if(img.complete && img.naturalWidth > 0){
      _fpApplyBands(slot, img, pageEl);
    }
  });
  /* Compteur */
  const total = _fpThumbs.length;
  const pNum = +t.dataset.page;
  const ctrEl = document.getElementById('fp-nav-ctr');
  if(showTwo) ctrEl.textContent=`${pNum}–${+_fpThumbs[_fpIdx+1].dataset.page} / ${total}`;
  else        ctrEl.textContent=`${pNum} / ${total}`;
  /* Info page (format + bleed) */
  const wmm=+t.dataset.wmm, hmm=+t.dataset.hmm;
  const bt=+t.dataset.bt,bb=+t.dataset.bb,bl=+t.dataset.bl,br=+t.dataset.br;
  const hasBl = t.dataset.hasBl==='True';
  const trimW = hasBl ? (wmm-bl-br).toFixed(1) : wmm;
  const trimH = hasBl ? (hmm-bt-bb).toFixed(1) : hmm;
  {
    const infoEl = document.getElementById('fp-viewer-info');
    if(hasBl){
      infoEl.innerHTML =
        `<span style="color:rgba(0,210,80,.9);font-weight:700">${trimW}×${trimH} mm</span>` +
        `<span style="color:rgba(0,245,255,.35);margin:0 6px">|</span>` +
        `<span style="color:rgba(0,245,255,.55)">Feuille&nbsp;${wmm}×${hmm}&nbsp;mm</span>` +
        `<span style="color:rgba(0,245,255,.35);margin:0 6px">·</span>` +
        `<span style="color:rgba(255,255,255,.4)">` +
        `FP&nbsp;H${bt.toFixed(1)}&nbsp;B${bb.toFixed(1)}&nbsp;G${bl.toFixed(1)}&nbsp;D${br.toFixed(1)}&nbsp;mm</span>`;
    } else {
      infoEl.textContent = `${wmm}×${hmm} mm`;
    }
  }
  /* Dots actifs */
  document.querySelectorAll('.fp-nav-dot').forEach((d,i)=>{
    d.classList.toggle('active', i===_fpIdx||(showTwo&&i===_fpIdx+1));
  });
  /* Boutons nav */
  document.getElementById('fp-nav-prev').disabled = _fpIdx<=0;
  const atEnd = showTwo ? (_fpIdx+2)>=total : (_fpIdx+1)>=total;
  document.getElementById('fp-nav-next').disabled = atEnd;
}

function fpNavTo(idx){
  _fpIdx = Math.max(0, Math.min(idx, _fpThumbs.length-1));
  /* En mode 2-up aligner sur pair (sauf page 0) */
  if(_fpTwoUp && _fpIdx>0 && _fpIdx%2===0) _fpIdx--;
  _fpRender();
}
function fpNavStep(dir){
  if(_fpTwoUp && _fpIdx>0){ fpNavTo(_fpIdx + dir*2); }
  else { fpNavTo(_fpIdx + dir); }
}

function closeFpModal(event, force){
  if(force || (event && event.target===document.getElementById('fp-modal'))){
    document.getElementById('fp-modal').classList.remove('open');
    document.getElementById('fp-loupe').style.display = 'none';
  }
}

/* ─── LOUPE sur l'aperçu fond perdu ─── */
(function(){
  const loupe = document.getElementById('fp-loupe');
  const ZOOM  = 3;        // facteur de grossissement
  const R     = 90;       // rayon loupe px

  document.getElementById('fp-modal').addEventListener('mousemove', e => {
    const img = e.target.closest('.fp-page-slot img');
    if(!img){ loupe.style.display='none'; return; }
    const r   = img.getBoundingClientRect();
    const cx  = e.clientX - r.left;
    const cy  = e.clientY - r.top;
    if(cx<0||cy<0||cx>r.width||cy>r.height){ loupe.style.display='none'; return; }

    // Position de la loupe (centrée sur le curseur)
    loupe.style.display = 'block';
    loupe.style.left    = (e.clientX - R) + 'px';
    loupe.style.top     = (e.clientY - R - 10) + 'px';

    // Coordonnées % dans l'image native
    const pctX = cx / r.width;
    const pctY = cy / r.height;

    // background-size = taille affichée × zoom
    const bsw = r.width  * ZOOM;
    const bsh = r.height * ZOOM;
    const bpx = pctX * bsw - R;
    const bpy = pctY * bsh - R;

    loupe.style.backgroundImage    = `url('${img.src}')`;
    loupe.style.backgroundSize     = `${bsw}px ${bsh}px`;
    loupe.style.backgroundPosition = `-${bpx}px -${bpy}px`;
    loupe.style.backgroundRepeat   = 'no-repeat';
  });

  document.getElementById('fp-modal').addEventListener('mouseleave', () => {
    loupe.style.display = 'none';
  });
})();

/* ─── CMJN VIEWER ─── */
let _cmykKey   = '';
let _cmykPage  = 1;
let _cmykTotal = 1;
let _cmykW     = 0;
let _cmykH     = 0;
let _cmykRaw   = null;  /* Uint8Array: CMYK 4 bytes/pixel (C,M,Y,K each 0–255) */
let _cmykPlates = {C:true, M:true, Y:true, K:true};

function openCmykViewer(key, totalPages){
  _cmykKey   = key;
  _cmykPage  = 1;
  _cmykTotal = totalPages || 1;
  _cmykRaw   = null;
  _cmykPlates = {C:true, M:true, Y:true, K:true};
  ['C','M','Y','K'].forEach(ch => {
    const b = document.getElementById('cmjn-btn-'+ch);
    if(b){ b.classList.add('active'); b.classList.remove('inactive'); }
  });
  document.getElementById('cmjn-c').textContent = '—%';
  document.getElementById('cmjn-m').textContent = '—%';
  document.getElementById('cmjn-y').textContent = '—%';
  document.getElementById('cmjn-k').textContent = '—%';
  document.getElementById('cmjn-modal').classList.add('open');
  _cmykLoadPage(1);
}

async function _cmykLoadPage(page){
  _cmykPage = page;
  document.getElementById('cmjn-page-ctr').textContent = page + ' / ' + _cmykTotal;
  try {
    const res  = await fetch('/cmyk-page?key=' + encodeURIComponent(_cmykKey) + '&page=' + page);
    const data = await res.json();
    if(data.error){ console.error('CMJN error:', data.error); return; }
    _cmykW = data.width;
    _cmykH = data.height;
    _cmykTotal = data.total || _cmykTotal;
    document.getElementById('cmjn-page-ctr').textContent = page + ' / ' + _cmykTotal;
    /* Update spot color chips */
    _cmykUpdateSpots(data.spots || []);
    /* Decode base64 → Uint8Array */
    const binary = atob(data.raw_b64);
    _cmykRaw = new Uint8Array(binary.length);
    for(let i = 0; i < binary.length; i++) _cmykRaw[i] = binary.charCodeAt(i);
    const canvas = document.getElementById('cmjn-canvas');
    canvas.width  = _cmykW;
    canvas.height = _cmykH;
    _cmykRender();
  } catch(e){ console.error('CMJN load error:', e); }
}

function _cmykRender(){
  if(!_cmykRaw) return;
  const canvas = document.getElementById('cmjn-canvas');
  const ctx    = canvas.getContext('2d');
  const imgData = ctx.createImageData(_cmykW, _cmykH);
  const d = imgData.data;
  const pC = _cmykPlates.C, pM = _cmykPlates.M, pY = _cmykPlates.Y, pK = _cmykPlates.K;
  const n = _cmykW * _cmykH;
  for(let i = 0; i < n; i++){
    const c = pC ? _cmykRaw[i*4]   / 255.0 : 0;
    const m = pM ? _cmykRaw[i*4+1] / 255.0 : 0;
    const y = pY ? _cmykRaw[i*4+2] / 255.0 : 0;
    const k = pK ? _cmykRaw[i*4+3] / 255.0 : 0;
    d[i*4]   = Math.round(255 * (1-c) * (1-k));
    d[i*4+1] = Math.round(255 * (1-m) * (1-k));
    d[i*4+2] = Math.round(255 * (1-y) * (1-k));
    d[i*4+3] = 255;
  }
  ctx.putImageData(imgData, 0, 0);
}

function _cmykMouseMove(e){
  if(!_cmykRaw) return;
  const canvas = document.getElementById('cmjn-canvas');
  const rect   = canvas.getBoundingClientRect();
  const sx = _cmykW / rect.width;
  const sy = _cmykH / rect.height;
  const px = Math.floor((e.clientX - rect.left) * sx);
  const py = Math.floor((e.clientY - rect.top)  * sy);
  if(px < 0 || py < 0 || px >= _cmykW || py >= _cmykH) return;
  const idx = (py * _cmykW + px) * 4;
  const C = Math.round(_cmykRaw[idx]   / 255 * 100);
  const M = Math.round(_cmykRaw[idx+1] / 255 * 100);
  const Y = Math.round(_cmykRaw[idx+2] / 255 * 100);
  const K = Math.round(_cmykRaw[idx+3] / 255 * 100);
  document.getElementById('cmjn-c').textContent = C + '%';
  document.getElementById('cmjn-m').textContent = M + '%';
  document.getElementById('cmjn-y').textContent = Y + '%';
  document.getElementById('cmjn-k').textContent = K + '%';
}

function toggleCmykPlate(ch){
  _cmykPlates[ch] = !_cmykPlates[ch];
  const btn = document.getElementById('cmjn-btn-'+ch);
  if(btn){
    btn.classList.toggle('active', _cmykPlates[ch]);
    btn.classList.toggle('inactive', !_cmykPlates[ch]);
  }
  _cmykRender();
}

function _cmykStep(dir){
  const next = _cmykPage + dir;
  if(next < 1 || next > _cmykTotal) return;
  _cmykLoadPage(next);
}

function closeCmykModal(e, force){
  if(force || (e && e.target === document.getElementById('cmjn-modal'))){
    document.getElementById('cmjn-modal').classList.remove('open');
    _cmykRaw = null;
  }
}

/* ─── SPOTLIGHT DROP ZONE ─── */
const dz         = document.getElementById('dropZone');
const spotlight  = document.getElementById('spotlight');
dz.addEventListener('mousemove', e => {
  const r = dz.getBoundingClientRect();
  spotlight.style.left = (e.clientX - r.left) + 'px';
  spotlight.style.top  = (e.clientY - r.top)  + 'px';
});

/* ─── DRAG & DROP PLEINE PAGE ─── */
const overlay = document.getElementById('page-drop-overlay');
let dragDepth = 0;
// Flag mis à true pendant un drag interne (organiser pages)
let _internalDrag = false;

document.addEventListener('dragenter', e => {
  if(_internalDrag) return;
  e.preventDefault();
  dragDepth++;
  if (dragDepth === 1) {
    overlay.classList.add('active');
    dz.classList.add('drag-over');
  }
});
document.addEventListener('dragleave', e => {
  if(_internalDrag) return;
  dragDepth--;
  if (dragDepth <= 0) {
    dragDepth = 0;
    overlay.classList.remove('active');
    dz.classList.remove('drag-over');
  }
});
document.addEventListener('dragover', e => { e.preventDefault(); });
document.addEventListener('drop', e => {
  if(_internalDrag) return;
  e.preventDefault();
  dragDepth = 0;
  overlay.classList.remove('active');
  dz.classList.remove('drag-over');
  const files = [...(e.dataTransfer.files||[])].filter(f => /\.(pdf|png|jpg|jpeg|tif|tiff|eps|ai)$/i.test(f.name));
  if (files.length) run(files);
  else if (e.dataTransfer.files.length > 0) showErr('Format non supporté — déposez des PDF, PNG, JPG, TIFF ou EPS');
});

/* ─── INPUT FILE ─── */
const fileInput = document.getElementById('fileInput');
const btnPick   = document.getElementById('btnPick');

btnPick.addEventListener('click', e => {
  e.stopPropagation();
  fileInput.click();
});
fileInput.addEventListener('change', () => {
  if (fileInput.files && fileInput.files.length > 0) {
    run([...fileInput.files]);
  }
});

/* ─── HELPERS ─── */
const app          = document.getElementById('app');
const loading      = document.getElementById('loading');
const results      = document.getElementById('results');
const loadingNames = document.getElementById('loadingNames');

function showErr(msg) {
  results.innerHTML = `<div style="text-align:center;padding:48px 24px;color:#f87171;font-size:14px">${msg}</div>`;
}

/* ─── ANALYSE ─── */
async function run(files) {
  app.style.display    = 'none';
  results.innerHTML    = '';
  loading.style.display = 'block';
  loadingNames.textContent = files.map(f => f.name).join(' · ');

  const fd = new FormData();
  files.forEach((f, i) => fd.append('file_' + i, f));

  try {
    const res = await fetch('/analyze', { method: 'POST', body: fd });
    if (!res.ok) throw new Error('Serveur : ' + res.status);
    const data = await res.json();
    _lastResults = data;
    loading.style.display = 'none';
    app.style.display     = '';
    if (!data.length) {
      showErr('Aucun résultat — vérifiez que les fichiers sont des PDF valides.');
    } else {
      const errCount = data.filter(r=>r.verdicts&&r.verdicts.global&&r.verdicts.global[0]!=='✅').length;
      const reportBtn = errCount > 0
        ? `<button class="btn-rapport" onclick="downloadRapport()">⬇ Rapport d'erreurs (${errCount} fichier${errCount>1?'s':''})</button>`
        : `<div class="results-ok-chip">✓ Tous les fichiers sont conformes</div>`;
      results.innerHTML = `<div class="results-bar">${reportBtn}</div>` + data.map((r, i) => card(r, i)).join('');
      // Rafraîchir l'historique si le panneau est ouvert
      if (document.getElementById('hist-panel').classList.contains('open')) loadHist();
    }
  } catch(e) {
    loading.style.display = 'none';
    app.style.display     = '';
    showErr('Erreur de connexion au serveur : ' + e.message);
  }
  fileInput.value = '';
  addHover(); // ré-attacher les hover listeners aux nouvelles cards
}

/* ─── CARD ─── */
function card(r, idx) {
  const nom   = r.original_name || r.fichier || '—';
  const mo    = r.taille_fichier ? (r.taille_fichier/1024/1024).toFixed(1)+' Mo' : '';
  const pages = r.pages_total   ? r.pages_total+' p.' : '';
  const meta  = [pages, mo].filter(Boolean).join(' · ');
  const v     = r.verdicts || {};

  /* ── Erreur ── */
  if (r.erreur && !v.couleur) {
    const hint = (r.erreur.includes('fitz')||r.erreur.includes('pymupdf'))
      ? 'pip3 install pymupdf pikepdf' : '';
    return `<div class="rcard" style="animation-delay:${idx*.06}s">
  <div class="card-head">
    <div class="card-info">
      <div class="card-name">📄 ${nom}</div>
      ${meta?`<div class="card-meta">${meta}</div>`:''}
    </div>
    <span class="vbadge vwarn">⚠ Erreur</span>
  </div>
  <div class="cerr">
    <div class="cerr-icon">⚠️</div>
    <div>
      <div class="cerr-msg">${r.erreur}</div>
      ${hint?`<div class="cerr-hint">${hint}</div>`:''}
    </div>
  </div>
</div>`;
  }

  /* ── Global ── */
  const gv  = v.global || ['⚠','?'];
  const gOk = gv[0] === '✅';
  const vbc = gOk ? 'vok' : 'vko';
  const vbl = gOk ? '✓ Conforme' : '✗ Non conforme';

  /* ── Colorimétrie ── */
  const mc = r.mode_couleur || '';
  const cv = v.couleur;
  let cMain,cDet,cCls;
  if      (mc==='CMJN')           { cMain='CMJN';       cDet='Conforme'; cCls='cok'; }
  else if (mc==='RVB')            { cMain='RVB';         cDet='Non conforme — CMJN requis';   cCls='cko'; }
  else if (mc.includes('Mixte'))  { cMain='Mixte';       cDet='RVB + CMJN — à vérifier';     cCls='cwarn'; }
  else if (mc&&(mc.includes('Vectoriel')||mc.includes('gris')||mc.includes('Gris')))
                                  { cMain=mc;            cDet='Vectoriel / niveaux de gris';  cCls='cok'; }
  else if (cv)                    { cMain=cv[1]||mc||'?'; cDet=''; cCls=cv[0]==='✅'?'cok':cv[0]==='⚠️'?'cwarn':'cko'; }
  else                            { cMain=mc||'?';        cDet=''; cCls='cneu'; }
  const cBdg = cCls==='cok'?'✓':cCls==='cko'?'✗':'!';

  /* ── Résolution ── */
  const dv    = v.dpi;
  const nbKo  = typeof r.nb_pages_ko==='number'?r.nb_pages_ko:null;
  const dpiMin= r.dpi_global_min;
  let dMain,dDet,dCls;
  if (r.a_images_raster===false||(dv&&dv[1]&&dv[1].includes('vectoriel'))) {
    dMain='Vectoriel'; dDet='PDF vectoriel — DPI non applicable'; dCls='cok';
  } else if (nbKo===0&&r.a_images_raster) {
    dMain='≥ 300 DPI'; dDet=dpiMin?`Min constaté : ${Math.round(dpiMin)} DPI`:'Toutes pages conformes'; dCls='cok';
  } else if (nbKo!==null&&nbKo>0) {
    dMain=`${nbKo} page${nbKo>1?'s':''} sous 300 DPI`;
    dDet=r.pages_total?`Sur ${r.pages_total} pages au total`:'';
    dCls='cko';
  } else if (dv) {
    const ok=dv[0]==='✅';
    dMain=ok?'≥ 300 DPI':'Sous 300 DPI'; dDet=dv[1]||''; dCls=ok?'cok':'cko';
  } else { dMain='?'; dDet='Analyse indisponible'; dCls='cneu'; }
  const dBdg = dCls==='cok'?'✓':dCls==='cko'?'✗':'!';

  /* ── Tons directs ── */
  const tv = v.tons_directs||['✅',''];
  const tOk= tv[0]==='✅';
  const tN = (r.tons_directs||[]).length;
  let tonsHtml='';
  if(!tOk&&r.tons_directs&&r.tons_directs.length)
    tonsHtml='<div class="tons">'+r.tons_directs.map(t=>`<span class="ton">${t}</span>`).join('')+'</div>';

  /* ── Surimpression ── */
  const sv  = v.surimpression||['✅',''];
  const sOk = sv[0]==='✅';
  const sInf= sv[0]==='ℹ️';
  const sCls= sOk?'cok':sInf?'cneu':'cwarn';
  const sMn = sOk?'Aucune':sInf?'—':'Active';
  const sDt = sOk?'Pas de surimpression':sInf?'pikepdf non disponible':sv[1]||'';

  /* ── Transparence ── */
  const trv  = v.transparence||['✅',''];
  const trOk = trv[0]==='✅';
  const trInf= trv[0]==='ℹ️';
  const trCls= trOk?'cok':trInf?'cneu':'cwarn';
  const trData = r.transparence||{};
  const trPages = trData.pages||[];
  let trMain, trDet;
  if(trInf){ trMain='—'; trDet='Analyse non disponible'; }
  else if(trData.a_transparence){
    trMain=`${trPages.length} page${trPages.length>1?'s':''}`; trDet='Transparence active — à aplatir';
  } else {
    trMain='Aucune'; trDet=trData.aplatie_possible?'Aucune transparence active (ou déjà aplatie)':'Pas de transparence';
  }

  /* ── Fond perdu ── */
  const fpv  = v.fond_perdu||['✅',''];
  const fpOk = fpv[0]==='✅';
  const fpInf= fpv[0]==='ℹ️';
  const fpWarn = fpv[0]==='⚠️';
  const fpCls= fpOk?'cok':fpInf||fpWarn?'cwarn':'cko';
  const fpData = r.fond_perdu||{};
  const fpKo   = fpData.pages_ko||[];
  let fpMain, fpDet;
  if(!fpData.has_trim_box && fpData.disponible){
    fpMain='Non défini'; fpDet='Pas de TrimBox dans le PDF';
  } else if(fpOk){
    fpMain=`${fpData.min_bleed_global!=null?fpData.min_bleed_global.toFixed(1)+' mm min':'OK'}`;
    fpDet='Fond perdu conforme (≥ 3 mm)';
  } else if(fpKo.length){
    fpMain=`${fpKo.length} page${fpKo.length>1?'s':''} KO`;
    fpDet=`Min : ${Math.min(...fpKo.map(p=>p.bleed_min)).toFixed(1)} mm (requis : 3 mm)`;
  } else { fpMain='?'; fpDet=fpv[1]||''; }

  /* ── Format en 2 cases : Zone de recadrage + Feuille ── */
  const tpv  = v.tailles||['✅',''];
  const tpOk = tpv[0]==='✅';
  const tpW  = tpv[0]==='⚠️';
  const tpData = r.tailles_pages||{};
  const fp0 = (fpData.pages||[])[0];
  /* Formater un mm sans ,0 inutile : 125.0→"125", 115.5→"115.5" */
  function fmm(v){ const n=Math.round(+v*10)/10; return n===Math.round(n)?String(Math.round(n)):n.toFixed(1); }

  let tbMain, tbDet, tbCls='cneu';   // Format final (TrimBox)
  let mbMain, mbDet, mbCls='cneu';   // Format feuille avec fond perdu (MediaBox)
  if(fp0 && fp0.bleed_left!=null){
    /* bT/bB/bL/bR = fond perdu réel lu dans le PDF (pas estimé) */
    const bT=+(fp0.bleed_top||0), bB=+(fp0.bleed_bottom||0);
    const bL=+(fp0.bleed_left||0), bR=+(fp0.bleed_right||0);
    /* TrimBox = w_mm × h_mm tels que lus par pikepdf */
    tbMain = `${fmm(fp0.w_mm)}×${fmm(fp0.h_mm)} mm`;
    tbDet  = `Format après découpe (TrimBox)`;
    tbCls  = 'cneu';
    /* MediaBox = TrimBox + fond perdu sur chaque côté */
    const mW = fp0.w_mm + bL + bR;
    const mH = fp0.h_mm + bT + bB;
    const bMin = Math.min(bT, bB, bL, bR);
    mbMain = `${fmm(mW)}×${fmm(mH)} mm`;
    mbDet  = bMin>0
      ? `FP — H:+${fmm(bT)} B:+${fmm(bB)} G:+${fmm(bL)} D:+${fmm(bR)} mm`
      : `Feuille = format final (pas de fond perdu)`;
    mbCls  = bMin>=3 ? 'cok' : bMin>0 ? 'cwarn' : 'cneu';
  } else {
    const wStr = tpData.w_mm ? `${fmm(tpData.w_mm)}×${fmm(tpData.h_mm)} mm` : '?';
    tbMain = tpData.format_principal || wStr;
    tbDet  = tpData.toutes_identiques ? `${wStr} (TrimBox non définie)` : `${tpData.nb_formats||'?'} formats différents`;
    tbCls  = tpOk?'cok':tpW?'cwarn':'cneu';
    mbMain = wStr;
    mbDet  = `Feuille totale — pas de fond perdu détecté`;
    mbCls  = 'cneu';
  }

  /* ── Aperçu : hero page 1 + store données toutes pages ── */
  let fpVisualHtml = '';
  const thumbs     = r.miniatures_fp||[];
  const typeDoc    = r.type_document||'';
  const realThumbs = thumbs.filter(t=>t.page);
  const moreCount  = (thumbs.find(t=>t.more)||{}).more||0;
  if(realThumbs.length){
    /* Hero = page 1 */
    const hero = realThumbs[0];
    const heroConf = hero.conforme;
    const heroBadge = hero.has_bleed
      ? (heroConf===true ? '<div class="fp-status ok">✓</div>' : heroConf===false ? '<div class="fp-status ko">✗</div>' : '')
      : '';
    const totalPages = realThumbs.length + moreCount;
    const twoUp = totalPages > 4 && (typeDoc.includes('Brochure')||typeDoc.includes('Catalogue')||typeDoc.includes('Livre'));
    const heroHtml = `<div class="fp-hero" onclick="openFpViewer(this)">
        <div class="fp-hero-img">
          <img src="data:image/png;base64,${hero.img}" alt="p.1">
          ${heroBadge}
        </div>
        <div class="fp-hero-lbl">${typeDoc} · ${hero.w_mm}×${hero.h_mm} mm</div>
        <div class="fp-hero-cta">▶ Voir les ${totalPages} pages${twoUp?' (doubles)':''}</div>
      </div>`;
    /* Store données de TOUTES les pages (hidden) */
    const storeHtml = realThumbs.map(t=>{
      const da=`data-page="${t.page}" data-img="${t.img}" data-wmm="${t.w_mm}" data-hmm="${t.h_mm}" data-bt="${t.bleed_top??0}" data-bb="${t.bleed_bottom??0}" data-bl="${t.bleed_left??0}" data-br="${t.bleed_right??0}" data-conforme="${t.conforme}" data-hasBl="${t.has_bleed}"`;
      return `<div class="fp-thumb" ${da}></div>`;
    }).join('');
    fpVisualHtml=`<div class="fp-visual-wrap" data-typedoc="${typeDoc}" data-twoup="${twoUp}" data-cachekey="${r.cache_key||''}">
      ${heroHtml}
      <div class="fp-thumb-store">${storeHtml}</div>
    </div>`;
  }

  /* ── Pages KO DPI ── */
  let pkoHtml='';
  const pko=r.pages_ko||{};
  const pkoK=Object.keys(pko).sort((a,b)=>+a-+b);
  if(pkoK.length){
    const chips=pkoK.map(p=>{
      const d=pko[p]; const dv2=d.dpi_min!==undefined?Math.round(d.dpi_min):d.dpi_moy!==undefined?Math.round(d.dpi_moy):'?';
      return `<div class="pchip">p.${p} — ${dv2} DPI</div>`;
    }).join('');
    pkoHtml=`<div class="pko-box"><div class="pko-title">Pages sous 300 DPI (${pkoK.length})</div><div class="pchips">${chips}</div></div>`;
  }

  return `<div class="rcard" style="animation-delay:${idx*.06}s">
  <div class="card-head">
    <div class="card-info">
      <div class="card-name">📄 ${nom}</div>
      ${meta?`<div class="card-meta">${meta}</div>`:''}
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-shrink:0">
      ${r.cache_key?`<button class="btn-cmyk-open" onclick="openCmykViewer('${r.cache_key}',${r.pages_total||1})">◎ CMJN</button>`:''}
      <span class="vbadge ${vbc}">${vbl}</span>
    </div>
  </div>
  <div class="card-body">
    <div class="crit-grid">
      <div class="crit ${cCls}">
        <div class="crit-top"><span class="clabel">Colorimétrie</span><div class="cbadge">${cBdg}</div></div>
        <div class="cmain">${cMain}</div>
        ${cDet?`<div class="cdetail">${cDet}</div>`:''}
      </div>
      <div class="crit ${dCls}">
        <div class="crit-top"><span class="clabel">Résolution</span><div class="cbadge">${dBdg}</div></div>
        <div class="cmain">${dMain}</div>
        ${dDet?`<div class="cdetail">${dDet}</div>`:''}
      </div>
      <div class="crit ${tOk?'cok':'cwarn'}">
        <div class="crit-top"><span class="clabel">Tons directs</span><div class="cbadge">${tOk?'✓':'!'}</div></div>
        <div class="cmain">${tOk?'Aucun':tN+' ton'+(tN>1?'s':'')}</div>
        <div class="cdetail">${tOk?'Quadrichromie pure':'Tons directs détectés'}</div>
        ${tonsHtml}
      </div>
      <div class="crit ${sCls}">
        <div class="crit-top"><span class="clabel">Surimpression</span><div class="cbadge">${sOk?'✓':sInf?'—':'!'}</div></div>
        <div class="cmain">${sMn}</div>
        <div class="cdetail">${sDt}</div>
      </div>
      <div class="crit ${trCls}">
        <div class="crit-top"><span class="clabel">Transparence</span><div class="cbadge">${trOk?'✓':trInf?'—':'!'}</div></div>
        <div class="cmain">${trMain}</div>
        <div class="cdetail">${trDet}</div>
      </div>
      <div class="crit ${tbCls}">
        <div class="crit-top"><span class="clabel">Format final</span><div class="cbadge">—</div></div>
        <div class="cmain">${tbMain}</div>
        <div class="cdetail">${tbDet}</div>
      </div>
      <div class="crit ${mbCls}">
        <div class="crit-top"><span class="clabel">Format + fond perdu</span><div class="cbadge">${mbCls==='cok'?'✓':mbCls==='cwarn'?'!':'—'}</div></div>
        <div class="cmain">${mbMain}</div>
        <div class="cdetail">${mbDet}</div>
      </div>
      <div class="crit ${fpCls}">
        <div class="crit-top"><span class="clabel">Fond perdu</span><div class="cbadge">${fpOk?'✓':fpInf||fpWarn?'!':'✗'}</div></div>
        <div class="cmain">${fpMain}</div>
        <div class="cdetail">${fpDet}</div>
      </div>
    </div>
    ${pkoHtml}
    ${fpVisualHtml}
  </div>
</div>`;
}

/* ─── HISTORIQUE ─── */
async function toggleHist() {
  const panel = document.getElementById('hist-panel');
  panel.classList.toggle('open');
  if (panel.classList.contains('open')) await loadHist();
}

async function loadHist() {
  const list = document.getElementById('histList');
  try {
    const res = await fetch('/history');
    const data = await res.json();
    if (!data.length) {
      list.innerHTML = '<div class="hist-empty">Aucun fichier analysé pour l\'instant</div>';
      return;
    }
    list.innerHTML = data.map(h => {
      const ok = h.conforme;
      const tags = [];
      if (h.couleur && h.couleur !== '?') tags.push(h.couleur);
      if (h.pages) tags.push(h.pages + ' p.');
      if (h.dpi_min) tags.push(Math.round(h.dpi_min) + ' DPI min');
      if (h.tons > 0) tags.push(h.tons + ' ton' + (h.tons > 1 ? 's directs' : ' direct'));
      if (h.transp) tags.push('transparence');
      if (h.fp_ok === false) tags.push('⚠ fond perdu');
      return `<div class="hitem">
        <div class="hitem-top">
          <div class="hitem-name" title="${h.fichier}">📄 ${h.fichier}</div>
          <span class="hbadge ${ok ? 'hok' : 'hko'}">${ok ? '✓ OK' : '✗ KO'}</span>
        </div>
        <div class="hitem-meta">
          <span class="htag">${h.date}</span>
          ${tags.map(t => `<span class="htag">${t}</span>`).join('')}
        </div>
      </div>`;
    }).join('');
  } catch(e) {
    list.innerHTML = '<div class="hist-empty">Erreur de chargement</div>';
  }
}

async function clearHist() {
  await fetch('/history/clear');
  document.getElementById('histList').innerHTML = '<div class="hist-empty">Historique effacé</div>';
}

// Recharger historique après chaque analyse
const _origRun = run;
window.addEventListener('load', () => {});

/* ─── BANDES FOND PERDU + CADRE TRIMBOX ─── */
function _fpBand(){ /* conservé pour compatibilité */ }

function _fpApplyBands(slot, img, pageEl){
  /* Garde anti-double : appelé parfois via onload ET via img.complete */
  if(slot._fpDone) return;
  slot._fpDone = true;

  const wmm = +pageEl.dataset.wmm || 1;
  const hmm = +pageEl.dataset.hmm || 1;
  const BT  = +pageEl.dataset.bt  || 0;
  const BB  = +pageEl.dataset.bb  || 0;
  const BL  = +pageEl.dataset.bl  || 0;
  const BR  = +pageEl.dataset.br  || 0;
  const hasAny = BT>0 || BB>0 || BL>0 || BR>0;
  const REQ = 3;

  /* ─ Pilules format (au-dessus de l'image) ─ */
  const pills = document.createElement('div');
  pills.className = 'fp-format-pills';
  const trimW = (wmm - BL - BR).toFixed(1);
  const trimH = (hmm - BT - BB).toFixed(1);
  pills.innerHTML =
    `<span class="fp-format-pill fp-pill-media">Feuille&nbsp;${wmm}×${hmm}&nbsp;mm</span>` +
    (hasAny ? `<span class="fp-format-pill fp-pill-trim">Recadrage&nbsp;${trimW}×${trimH}&nbsp;mm</span>` : '');
  slot.appendChild(pills);

  if(!hasAny) return;

  /* ─ Positionnement % — indépendant de la taille d'affichage réelle ─ */
  const pBT = (BT / hmm * 100);
  const pBB = (BB / hmm * 100);
  const pBL = (BL / wmm * 100);
  const pBR = (BR / wmm * 100);

  function bandCol(v)  { return v >= REQ-0.1 ? 'rgba(0,210,80,0.32)' : 'rgba(255,0,55,0.40)'; }
  function strokeCol(v){ return v >= REQ-0.1 ? 'rgba(0,210,80,0.80)' : 'rgba(255,0,55,0.85)'; }
  function lbl(v){ return v.toFixed(1)+' mm'; }

  function addBand(css, val, lblCss){
    if(val < 0.1) return;
    const d = document.createElement('div');
    d.className = 'fp-band';
    d.style.cssText = css + `;background:${bandCol(val)};outline:1px solid ${strokeCol(val)};`;
    slot.appendChild(d);
    const l = document.createElement('div');
    l.className = 'fp-bleed-lbl';
    l.textContent = lbl(val);
    l.style.cssText = 'position:absolute;pointer-events:none;z-index:16;' + lblCss;
    slot.appendChild(l);
  }

  /* Bandes en % de la taille du slot → correctes quelle que soit la résolution */
  addBand(
    `position:absolute;top:0;left:0;right:0;height:${pBT.toFixed(4)}%`, BT,
    `top:${Math.max(0.2, pBT/2-1).toFixed(3)}%;left:0;right:0;text-align:center;`
  );
  addBand(
    `position:absolute;bottom:0;left:0;right:0;height:${pBB.toFixed(4)}%`, BB,
    `bottom:${Math.max(0.2, pBB/2-1).toFixed(3)}%;left:0;right:0;text-align:center;`
  );
  addBand(
    `position:absolute;left:0;top:0;bottom:0;width:${pBL.toFixed(4)}%`, BL,
    `left:${Math.max(0.1, pBL/2-2).toFixed(3)}%;top:50%;transform:translateY(-50%) rotate(-90deg);white-space:nowrap;`
  );
  addBand(
    `position:absolute;right:0;top:0;bottom:0;width:${pBR.toFixed(4)}%`, BR,
    `right:${Math.max(0.1, pBR/2-2).toFixed(3)}%;top:50%;transform:translateY(-50%) rotate(90deg);white-space:nowrap;`
  );

  /* ─ Cadre TrimBox en % ─ */
  const frame = document.createElement('div');
  frame.className = 'fp-trim-frame';
  frame.style.cssText =
    `left:${pBL.toFixed(4)}%;top:${pBT.toFixed(4)}%;` +
    `width:${(100-pBL-pBR).toFixed(4)}%;height:${(100-pBT-pBB).toFixed(4)}%;`;
  slot.appendChild(frame);
}

/* ─── TÉLÉCHARGER LE RAPPORT D'ERREURS (.txt) ─── */
function downloadRapport(){
  const lines = [];
  let hasErr = false;
  for(const r of _lastResults){
    const v  = r.verdicts||{};
    const gv = v.global||['?','?'];
    if(gv[0]==='✅') continue;
    hasErr = true;
    lines.push('───────────────────────────────────────────────────');
    lines.push('Fichier  : ' + (r.original_name||r.fichier||'?'));
    lines.push('Verdict  : ' + (gv[1]||'Non conforme'));
    lines.push('');
    const mc = r.mode_couleur||'';
    if(mc && mc!=='CMJN' && !mc.includes('Vectoriel') && !mc.includes('gris')){
      lines.push('• Colorimétrie : ' + mc + ' — CMJN requis');
    }
    const nbKo = r.nb_pages_ko;
    if(typeof nbKo==='number' && nbKo>0){
      lines.push('• Résolution : ' + nbKo + ' page(s) sous 300 DPI');
      const pko = r.pages_ko||{};
      Object.keys(pko).sort((a,b)=>+a-+b).forEach(p=>{
        const d = pko[p];
        const dv = Math.round(d.dpi_min!==undefined?d.dpi_min:d.dpi_moy||0);
        lines.push('    – Page ' + p + ' : ' + dv + ' DPI');
      });
    }
    if(r.tons_directs && r.tons_directs.length){
      lines.push('• Tons directs : ' + r.tons_directs.join(', '));
    }
    const fp = r.fond_perdu||{};
    if(fp.pages_ko && fp.pages_ko.length){
      lines.push('• Fond perdu : ' + fp.pages_ko.length + ' page(s) insuffisant(es)');
      fp.pages_ko.forEach(p=>{
        lines.push('    – Page ' + p.page + ' : ' + (p.bleed_min||0).toFixed(1) + ' mm (min requis : 3 mm)');
      });
    }
    const tr = r.transparence||{};
    if(tr.a_transparence){
      lines.push('• Transparence : active sur ' + (tr.pages||[]).length + ' page(s) — à aplatir');
    }
    lines.push('');
  }
  if(!hasErr){
    lines.push('Aucune erreur détectée — tous les fichiers sont conformes.');
  }
  const blob = new Blob([lines.join('\n')], {type:'text/plain;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'rapport_erreurs_vikbat.txt';
  a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href), 2000);
}

/* ─── NAVIGATION TABS ─── */
function switchTab(name, el){
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  const isAnalyse = (name === 'analyse');
  document.getElementById('app').style.display     = isAnalyse ? '' : 'none';
  document.getElementById('loading').style.display = isAnalyse ? '' : 'none';
  document.getElementById('results').style.display = isAnalyse ? '' : 'none';
  ['imposition','organiser','convertir','pitstop'].forEach(t => {
    const s = document.getElementById('tab-'+t);
    if(s) s.style.display = (t === name) ? '' : 'none';
  });
  addHover();
}

/* ─── ONGLET IMPOSITION PRO ─── */
let _impFile   = null;
let _impThumbs = [];   // base64 jpeg per page
let _impTotal  = 0;
let _impSpread = 0;    // current spread index (0-based)
let _impPairs  = [];   // [[l,r], ...] page pairs

function _impGetSettings(){
  return {
    sheet  : document.getElementById('imp-sheet-size').value,
    mode   : document.getElementById('imp-mode-sel').value,
    inner  : parseFloat(document.getElementById('imp-inner-bleed').value) || 0,
    outer  : parseFloat(document.getElementById('imp-outer-bleed').value) || 0,
    creep  : parseFloat(document.getElementById('imp-creep').value) || 0,
    markMm : parseFloat(document.getElementById('imp-mark-margin').value) || 8,
    crop   : document.getElementById('imp-crop-marks').checked,
    reg    : document.getElementById('imp-reg-marks').checked,
    fold   : document.getElementById('imp-fold-marks').checked,
    cbar   : document.getElementById('imp-color-bar').checked,
  };
}

function _impBuildPairs(n, mode){
  if(mode === 'booklet' || mode === 'booklet_pb'){
    const total = n + ((-n) % 4 + 4) % 4;
    const pages = Array.from({length:total}, (_,i) => i < n ? i : null);
    const pairs = [];
    let lo = 0, hi = pages.length - 1;
    while(lo < hi){
      pairs.push([pages[hi], pages[lo]]); lo++; hi--;
      if(lo < hi){ pairs.push([pages[lo], pages[hi]]); lo++; hi--; }
    }
    return pairs;
  } else {
    const padded = Array.from({length: n + (n%2)}, (_,i) => i < n ? i : null);
    return Array.from({length: Math.ceil(padded.length/2)}, (_,i) => [padded[i*2], padded[i*2+1]]);
  }
}

function impSettingChanged(){
  if(_impThumbs.length === 0) return;
  const s = _impGetSettings();
  _impPairs = _impBuildPairs(_impTotal, s.mode);
  _impSpread = Math.min(_impSpread, _impPairs.length - 1);
  _impDrawPreview();
}

function _impSpreadStep(d){
  if(_impPairs.length === 0) return;
  _impSpread = Math.max(0, Math.min(_impPairs.length - 1, _impSpread + d));
  _impDrawPreview();
}

function _impDrawPreview(){
  const canvas = document.getElementById('imp-canvas');
  const ctx = canvas.getContext('2d');
  const s = _impGetSettings();
  const pair = _impPairs[_impSpread] || [null, null];
  const [li, ri] = pair;

  const CW = canvas.width, CH = canvas.height;
  ctx.clearRect(0, 0, CW, CH);
  ctx.fillStyle = '#0a0e10';
  ctx.fillRect(0, 0, CW, CH);

  // Sheet simulation (2-up with margin)
  const MARG = 24;   // pixels for mark area in preview
  const pageW = (CW - MARG * 3) / 2;
  const pageH = CH - MARG * 2;

  const lx = MARG, rx = MARG * 2 + pageW;
  const py = MARG;

  // Draw page slots (background)
  ctx.fillStyle = '#fff';
  ctx.fillRect(lx, py, pageW, pageH);
  ctx.fillRect(rx, py, pageW, pageH);

  let pending = 2;
  function done(){
    pending--;
    if(pending <= 0){
      _impOverlayMarks(ctx, lx, rx, py, pageW, pageH, MARG, s);
      _impUpdateNav();
    }
  }

  function drawThumb(idx, x, y, w, h){
    if(idx === null || idx === undefined || !_impThumbs[idx]){
      ctx.fillStyle = '#1a1a1a';
      ctx.fillRect(x, y, w, h);
      ctx.fillStyle = 'rgba(0,245,255,.2)';
      ctx.font = '11px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Blanc', x + w/2, y + h/2);
      done(); return;
    }
    const img = new Image();
    img.onload = () => { ctx.drawImage(img, x, y, w, h); done(); };
    img.onerror = () => done();
    img.src = 'data:image/jpeg;base64,' + _impThumbs[idx];
  }

  drawThumb(li, lx, py, pageW, pageH);
  drawThumb(ri, rx, py, pageW, pageH);
}

function _impOverlayMarks(ctx, lx, rx, py, pageW, pageH, marg, s){
  const MARK_LEN = marg * 0.6;
  const MARK_OFF = marg * 0.1;
  ctx.strokeStyle = '#000';
  ctx.lineWidth = 0.7;

  if(s.crop){
    // Outer corners of left page
    _ctxMarkCorner(ctx, lx,          py,           -1, -1, MARK_LEN, MARK_OFF);
    _ctxMarkCorner(ctx, lx,          py + pageH,   -1,  1, MARK_LEN, MARK_OFF);
    // Outer corners of right page
    _ctxMarkCorner(ctx, rx + pageW,  py,             1, -1, MARK_LEN, MARK_OFF);
    _ctxMarkCorner(ctx, rx + pageW,  py + pageH,     1,  1, MARK_LEN, MARK_OFF);
    // Spine / inner corners
    _ctxMarkCorner(ctx, lx + pageW,  py,             1, -1, MARK_LEN, MARK_OFF);
    _ctxMarkCorner(ctx, lx + pageW,  py + pageH,     1,  1, MARK_LEN, MARK_OFF);
    _ctxMarkCorner(ctx, rx,          py,            -1, -1, MARK_LEN, MARK_OFF);
    _ctxMarkCorner(ctx, rx,          py + pageH,    -1,  1, MARK_LEN, MARK_OFF);
  }

  if(s.fold){
    // Fold guides at spine
    const sx = (lx + pageW + rx) / 2;
    ctx.save();
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = 'rgba(0,100,255,0.7)';
    ctx.beginPath();
    ctx.moveTo(sx, 0); ctx.lineTo(sx, py - MARK_OFF);
    ctx.moveTo(sx, py + pageH + MARK_OFF); ctx.lineTo(sx, ctx.canvas.height);
    ctx.stroke();
    ctx.restore();
  }

  if(s.reg){
    // Registration marks (crosshair+circle) at sheet sides
    const midY = py + pageH / 2;
    _ctxRegMark(ctx, lx - marg * 0.6, midY);
    _ctxRegMark(ctx, rx + pageW + marg * 0.6, midY);
  }

  // Bleed shading
  if(s.inner > 0){
    const innerPx = s.inner / (210 / pageW);  // rough scale
    ctx.fillStyle = 'rgba(255,50,100,.12)';
    ctx.fillRect(lx + pageW - innerPx, py, innerPx, pageH);
    ctx.fillRect(rx, py, innerPx, pageH);
  }
}

function _ctxMarkCorner(ctx, x, y, dx, dy, len, off){
  ctx.beginPath();
  ctx.moveTo(x + dx * off, y); ctx.lineTo(x + dx * (off + len), y);
  ctx.moveTo(x, y + dy * off); ctx.lineTo(x, y + dy * (off + len));
  ctx.stroke();
}

function _ctxRegMark(ctx, cx, cy){
  const R = 5, CL = 9;
  ctx.beginPath();
  ctx.arc(cx, cy, R, 0, Math.PI*2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(cx - CL, cy); ctx.lineTo(cx + CL, cy);
  ctx.moveTo(cx, cy - CL); ctx.lineTo(cx, cy + CL);
  ctx.stroke();
}

function _impUpdateNav(){
  document.getElementById('imp-spread-ctr').textContent =
    _impPairs.length ? `Planche ${_impSpread+1} / ${_impPairs.length}` : '— / —';
}

document.getElementById('imp-input').addEventListener('change', e => {
  const f = e.target.files[0]; if(!f) return;
  _impFile = f;
  document.getElementById('imp-filename').textContent = f.name;
  _impSetStatus('','');
  _impLoadThumbs();
});
(function(){
  const dz = document.getElementById('imp-drop');
  dz.addEventListener('dragover',  e => { e.preventDefault(); dz.classList.add('drag-over'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
  dz.addEventListener('drop', e => {
    e.preventDefault(); dz.classList.remove('drag-over');
    const f = e.dataTransfer.files[0]; if(!f) return;
    _impFile = f;
    document.getElementById('imp-filename').textContent = f.name;
    _impSetStatus('','');
    _impLoadThumbs();
  });
})();

function _impSetStatus(msg, cls){
  const s = document.getElementById('imp-status');
  s.textContent = msg;
  s.className = 'tool-status' + (msg ? ' visible ' + cls : '');
}

async function _impLoadThumbs(){
  _impSetStatus('⏳ Chargement aperçu…','running');
  document.getElementById('imp-btn').disabled = true;
  try {
    const fd = new FormData(); fd.append('file', _impFile);
    const resp = await fetch('/page-thumbs', {method:'POST', body:fd});
    if(!resp.ok) throw new Error('Erreur ' + resp.status);
    const data = await resp.json();
    if(data.error) throw new Error(data.error);
    _impThumbs = data.thumbs;
    _impTotal  = data.total;
    const s = _impGetSettings();
    _impPairs = _impBuildPairs(_impTotal, s.mode);
    _impSpread = 0;
    _impDrawPreview();
    document.getElementById('imp-preview-info').textContent =
      `${_impTotal} pages · ${_impPairs.length} planches`;
    document.getElementById('imp-btn').disabled = false;
    _impSetStatus('','');
  } catch(e){
    _impSetStatus('✗ ' + e.message, 'ko');
  }
}

async function runImposition(){
  if(!_impFile) return;
  const btn = document.getElementById('imp-btn');
  btn.disabled = true;
  _impSetStatus('⏳ Imposition en cours…', 'running');
  const s = _impGetSettings();
  try {
    const fd = new FormData();
    fd.append('file', _impFile);
    fd.append('mode',         s.mode);
    fd.append('inner_bleed',  s.inner);
    fd.append('outer_bleed',  s.outer);
    fd.append('creep',        s.creep);
    fd.append('mark_margin',  s.markMm);
    fd.append('crop_marks',   s.crop  ? '1' : '0');
    fd.append('reg_marks',    s.reg   ? '1' : '0');
    fd.append('fold_marks',   s.fold  ? '1' : '0');
    fd.append('color_bar',    s.cbar  ? '1' : '0');
    fd.append('sheet_size',   s.sheet);
    const resp = await fetch('/impose', {method:'POST', body:fd});
    if(!resp.ok){ const j = await resp.json().catch(()=>({error:'Erreur '+resp.status})); throw new Error(j.error); }
    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = _impFile.name.replace(/\.pdf$/i,'') + '_imposition.pdf'; a.click();
    setTimeout(()=>URL.revokeObjectURL(url), 3000);
    _impSetStatus('✓ PDF d\'imposition généré', 'ok');
  } catch(e){ _impSetStatus('✗ ' + e.message, 'ko'); }
  finally { btn.disabled = false; }
}

/* ─── ONGLET ORGANISER ─── */
let _orgFile  = null;
let _orgKey   = '';
let _orgOrder = [];

document.getElementById('org-input').addEventListener('change', e => {
  const f = e.target.files[0]; if(!f) return;
  _orgFile = f;
  document.getElementById('org-filename').textContent = f.name;
  _orgLoadThumbs();
});
(function(){
  const dz = document.getElementById('org-drop');
  dz.addEventListener('dragover',  e => { e.preventDefault(); e.stopPropagation(); dz.classList.add('drag-over'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
  dz.addEventListener('drop', e => {
    e.preventDefault(); e.stopPropagation(); dz.classList.remove('drag-over');
    const f = e.dataTransfer.files[0]; if(!f || !f.name.match(/\.pdf$/i)) return;
    _orgFile = f;
    document.getElementById('org-filename').textContent = f.name;
    _orgLoadThumbs();
  });
})();
function _orgSetStatus(msg, cls){
  const s = document.getElementById('org-status');
  s.textContent = msg;
  s.className = 'tool-status' + (msg ? ' visible ' + cls : '');
}
async function _orgLoadThumbs(){
  const grid = document.getElementById('org-pages-grid');
  grid.innerHTML = '<div class="pages-grid-empty">⏳ Chargement des vignettes…</div>';
  document.getElementById('org-btn').disabled = true;
  _orgSetStatus('','');
  try {
    const fd = new FormData();
    fd.append('file', _orgFile);
    const resp = await fetch('/page-thumbs', {method:'POST', body:fd});
    if(!resp.ok) throw new Error('Erreur serveur ' + resp.status);
    const data = await resp.json();
    if(data.error) throw new Error(data.error);
    _orgKey   = data.key;
    _orgOrder = data.thumbs.map((_,i) => i);
    _orgRenderGrid(data.thumbs);
    document.getElementById('org-btn').disabled = false;
    addHover();
  } catch(e){
    grid.innerHTML = `<div class="pages-grid-empty" style="color:var(--ko)">✗ ${e.message}</div>`;
  }
}
function _orgRenderGrid(thumbs){
  const grid = document.getElementById('org-pages-grid');
  grid.innerHTML = '';
  thumbs.forEach((b64, i) => {
    const div = document.createElement('div');
    div.className = 'page-thumb'; div.draggable = true; div.dataset.origIdx = i;
    const img = document.createElement('img');
    img.src = 'data:image/jpeg;base64,' + b64; img.alt = 'Page '+(i+1);
    // Prevent image from intercepting drag events (key fix for macOS Safari/Chrome)
    img.draggable = false;
    img.setAttribute('draggable','false');
    img.style.pointerEvents = 'none';
    img.style.userSelect = 'none';
    const num = document.createElement('div');
    num.className = 'page-thumb-num'; num.textContent = 'Page '+(i+1);
    div.appendChild(img); div.appendChild(num);
    div.addEventListener('dragstart', _orgDragStart);
    div.addEventListener('dragover',  _orgDragOver);
    div.addEventListener('dragleave', _orgDragLeave);
    div.addEventListener('drop',      _orgDrop);
    div.addEventListener('dragend',   _orgDragEnd);
    grid.appendChild(div);
  });
}
let _orgDragSrc = null;
function _orgDragStart(e){ _internalDrag = true; _orgDragSrc = this; this.classList.add('dragging'); e.dataTransfer.effectAllowed='move'; e.dataTransfer.setData('text/plain', this.dataset.origIdx); }
function _orgDragOver(e){ e.preventDefault(); e.dataTransfer.dropEffect='move'; if(this!==_orgDragSrc) this.classList.add('drag-over-thumb'); }
function _orgDragLeave(){ this.classList.remove('drag-over-thumb'); }
function _orgDragEnd(){ _internalDrag = false; dragDepth = 0; overlay.classList.remove('active'); dz.classList.remove('drag-over'); this.classList.remove('dragging'); document.querySelectorAll('.page-thumb').forEach(t=>t.classList.remove('drag-over-thumb','dragging')); }
function _orgDrop(e){
  e.preventDefault(); this.classList.remove('drag-over-thumb');
  if(!_orgDragSrc || _orgDragSrc===this) return;
  const grid   = document.getElementById('org-pages-grid');
  const thumbs = [...grid.querySelectorAll('.page-thumb')];
  const fi = thumbs.indexOf(_orgDragSrc), ti = thumbs.indexOf(this);
  if(fi<0||ti<0) return;
  grid.insertBefore(_orgDragSrc, fi<ti ? this.nextSibling : this);
  [...grid.querySelectorAll('.page-thumb')].forEach((t,i) => t.querySelector('.page-thumb-num').textContent = 'Page '+(i+1));
  _orgOrder = [...grid.querySelectorAll('.page-thumb')].map(t => +t.dataset.origIdx);
}
async function runOrganiser(){
  if(!_orgKey) return;
  const btn = document.getElementById('org-btn');
  btn.disabled = true;
  _orgSetStatus('⏳ Réorganisation en cours…', 'running');
  try {
    const resp = await fetch('/reorder', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({key:_orgKey, order:_orgOrder})
    });
    if(!resp.ok){ const j = await resp.json().catch(()=>({error:'Erreur '+resp.status})); throw new Error(j.error); }
    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = _orgFile.name.replace(/\.pdf$/i,'') + '_reorganise.pdf'; a.click();
    setTimeout(()=>URL.revokeObjectURL(url), 3000);
    _orgSetStatus('✓ PDF réorganisé — téléchargement lancé', 'ok');
  } catch(e){ _orgSetStatus('✗ ' + e.message, 'ko'); }
  finally { btn.disabled = false; }
}

/* ─── ONGLET CONVERTIR ─── */
let _convFile = null;
document.getElementById('conv-input').addEventListener('change', e => {
  const f = e.target.files[0]; if(!f) return;
  _convFile = f;
  document.getElementById('conv-filename').textContent = f.name;
  document.getElementById('conv-btn').disabled = false;
  _convSetStatus('','');
});
(function(){
  const dz = document.getElementById('conv-drop');
  dz.addEventListener('dragover',  e => { e.preventDefault(); dz.classList.add('drag-over'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
  dz.addEventListener('drop', e => {
    e.preventDefault(); dz.classList.remove('drag-over');
    const f = e.dataTransfer.files[0]; if(!f) return;
    _convFile = f;
    document.getElementById('conv-filename').textContent = f.name;
    document.getElementById('conv-btn').disabled = false;
    _convSetStatus('','');
  });
})();
function _convSetStatus(msg, cls){
  const s = document.getElementById('conv-status');
  s.textContent = msg;
  s.className = 'tool-status' + (msg ? ' visible ' + cls : '');
}
async function runConvertir(){
  if(!_convFile) return;
  const btn = document.getElementById('conv-btn');
  btn.disabled = true;
  _convSetStatus('⏳ Conversion en cours… (quelques secondes selon la taille)', 'running');
  try {
    const fd = new FormData();
    fd.append('file', _convFile);
    const resp = await fetch('/convert-cmyk', {method:'POST', body:fd});
    if(!resp.ok){ const j = await resp.json().catch(()=>({error:'Erreur '+resp.status})); throw new Error(j.error); }
    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = _convFile.name.replace(/\.pdf$/i,'') + '_CMJN.pdf'; a.click();
    setTimeout(()=>URL.revokeObjectURL(url), 3000);
    _convSetStatus('✓ PDF converti en CMJN — téléchargement lancé', 'ok');
  } catch(e){ _convSetStatus('✗ ' + e.message, 'ko'); }
  finally { btn.disabled = false; }
}


/* ─── CMJN SPOTS UPDATE ─── */
function _cmykUpdateSpots(spots){
  const container = document.getElementById('cmjn-spots');
  if(!spots || spots.length === 0){
    container.style.display = 'none';
    container.innerHTML = '';
    return;
  }
  container.style.display = 'flex';
  container.innerHTML = '<span style="font-size:9px;color:rgba(0,245,255,.4);letter-spacing:1px;margin-right:4px;text-transform:uppercase">Tons directs :</span>';
  spots.forEach(name => {
    const chip = document.createElement('span');
    chip.className = 'cmjn-spot-chip';
    chip.textContent = name;
    // Assign a color based on name
    chip.style.background = _spotNameToColor(name);
    chip.style.color = '#fff';
    chip.title = name;
    container.appendChild(chip);
  });
}
function _spotNameToColor(name){
  const n = name.toLowerCase();
  if(n.includes('black') || n.includes('noir') || n.includes('k')) return '#222';
  if(n.includes('cyan') || n.includes('c'))   return '#009fbb';
  if(n.includes('magenta') || n.includes('m') || n.includes('pink')) return '#cc0077';
  if(n.includes('yellow') || n.includes('jaune') || n.includes('y')) return '#c9a700';
  if(n.includes('red') || n.includes('rouge') || n.includes('485')) return '#c8002a';
  if(n.includes('blue') || n.includes('bleu')  || n.includes('287')) return '#003da5';
  if(n.includes('green') || n.includes('vert') || n.includes('348')) return '#007a53';
  if(n.includes('orange') || n.includes('021')) return '#f04e00';
  if(n.includes('gold') || n.includes('or')   || n.includes('871')) return '#9b7d3e';
  if(n.includes('silver') || n.includes('argent') || n.includes('877')) return '#8a8d8f';
  if(n.includes('white') || n.includes('blanc')) return '#555';
  // Generic fallback — derive from string hash
  let h = 0; for(let c of name){ h = (h * 31 + c.charCodeAt(0)) & 0xffffff; }
  return '#' + ((h & 0xFFFFFF) | 0x404040).toString(16).padStart(6,'0');
}

/* ─── TÉLÉCHARGER L'APERÇU PDF ANNOTÉ (bleed bands) ─── */
let _fpCacheKey = '';

async function downloadFpPreview(){
  if(!_fpCacheKey){
    alert('Aperçu non disponible — analysez à nouveau le fichier.');
    return;
  }
  const btn = document.querySelector('.btn-dl-preview');
  if(btn){ btn.textContent='⏳ Génération…'; btn.disabled=true; }
  try {
    const resp = await fetch('/download-preview?key=' + encodeURIComponent(_fpCacheKey));
    if(!resp.ok) throw new Error('Erreur serveur ' + resp.status);
    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url;
    a.download = 'apercu_fond_perdu.pdf';
    a.click();
    setTimeout(()=>URL.revokeObjectURL(url), 3000);
  } catch(e){
    alert('Impossible de générer le PDF annoté : ' + e.message);
  } finally {
    if(btn){ btn.textContent='⬇ Télécharger l\'aperçu PDF'; btn.disabled=false; }
  }
}

</script>
</body>
</html>"""


# ─── Historique ───────────────────────────────────────────────────────────────

HISTORY_FILE = os.path.expanduser('~/.vikbat_history.json')
MAX_HISTORY  = 50

def _load_history():
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def _save_to_history(results):
    from datetime import datetime
    history = _load_history()
    for r in results:
        v = r.get('verdicts', {})
        gv = v.get('global', ['?','?'])
        entry = {
            'fichier':   r.get('original_name') or r.get('fichier', '?'),
            'date':      datetime.now().strftime('%d/%m/%Y %H:%M'),
            'conforme':  gv[0] == '✅',
            'verdict':   gv[1] if len(gv) > 1 else '?',
            'couleur':   r.get('mode_couleur', '?'),
            'pages':     r.get('pages_total', 0),
            'dpi_min':   r.get('dpi_global_min'),
            'tons':      len(r.get('tons_directs', [])),
            'fp_ok':     r.get('fond_perdu', {}).get('global_ok', None),
            'transp':    r.get('transparence', {}).get('a_transparence', False),
        }
        history.insert(0, entry)
    history = history[:MAX_HISTORY]
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ─── Parseur multipart robuste ────────────────────────────────────────────────

def _parse_multipart(raw_body: bytes, content_type: str):
    ct = content_type.encode() if isinstance(content_type, str) else content_type
    m = re.search(rb'boundary=([^\s;,"]+|"[^"]+")', ct)
    if not m:
        return {}
    boundary = m.group(1).strip(b'"')
    delimiter = b'--' + boundary
    parts = raw_body.split(delimiter)
    result = {}
    for part in parts:
        if part in (b'', b'--', b'--\r\n', b'\r\n') or not part.strip():
            continue
        part = part.lstrip(b'\r\n')
        if b'\r\n\r\n' in part:
            head, body = part.split(b'\r\n\r\n', 1)
        elif b'\n\n' in part:
            head, body = part.split(b'\n\n', 1)
        else:
            continue
        if body.endswith(b'\r\n'):
            body = body[:-2]
        nm = re.search(rb'[Nn]ame="([^"]*)"', head)
        fn = re.search(rb'[Ff]ilename="([^"]*)"', head)
        if nm and fn:
            field = nm.group(1).decode('utf-8', errors='replace')
            fname = fn.group(1).decode('utf-8', errors='replace')
            result[field] = (fname, body)
    return result



# ─── Génération PDF annoté avec bandes fond perdu ─────────────────────────────

def _generate_annotated_pdf(cache_path, fp_pages):
    """Ouvre le PDF source, dessine les bandes fond perdu roses + traits de coupe,
       retourne les bytes du PDF annoté.
       Les bandes sont positionnées depuis la MediaBox = TrimBox + bleed sur chaque côté."""
    try:
        import fitz
    except ImportError:
        return None

    # Rose / magenta avec opacité — tous les côtés identiques
    COLOR_ROSE  = (0.95, 0.25, 0.55)   # rose vif
    ALPHA_BAND  = 0.35
    TRIM_COLOR  = (0.95, 0.25, 0.55)   # trait de coupe rose
    MM_TO_PTS   = 72.0 / 25.4

    doc = fitz.open(cache_path)
    for i, page in enumerate(doc):
        pd = next((p for p in (fp_pages or []) if p.get('page') == i + 1), None)
        if not pd:
            continue

        bt_mm = float(pd.get('bleed_top',    0) or 0)
        bb_mm = float(pd.get('bleed_bottom', 0) or 0)
        bl_mm = float(pd.get('bleed_left',   0) or 0)
        br_mm = float(pd.get('bleed_right',  0) or 0)

        # Vérifier qu'il y a au moins un côté avec du fond perdu
        if bt_mm + bb_mm + bl_mm + br_mm < 0.1:
            continue

        # Dimensions de la page telles que rendues par fitz (MediaBox, Y-down, origine (0,0))
        # La MediaBox = TrimBox + fond perdu → les bandes sont aux bords de la page
        w = page.rect.width
        h = page.rect.height
        bt = bt_mm * MM_TO_PTS
        bb = bb_mm * MM_TO_PTS
        bl = bl_mm * MM_TO_PTS
        br = br_mm * MM_TO_PTS

        def draw_band(rect):
            """Dessine un rectangle rose semi-transparent."""
            r = rect & page.rect   # clamp dans la page
            if r.is_empty: return
            shape = page.new_shape()
            shape.draw_rect(r)
            shape.finish(color=COLOR_ROSE, fill=COLOR_ROSE,
                         fill_opacity=ALPHA_BAND, width=0)
            shape.commit()

        # Bandes aux 4 côtés (bords de la MediaBox = zones de fond perdu)
        if bt > 0.2: draw_band(fitz.Rect(0,      0,      w,      bt))
        if bb > 0.2: draw_band(fitz.Rect(0,      h - bb, w,      h))
        if bl > 0.2: draw_band(fitz.Rect(0,      bt,     bl,     h - bb))
        if br > 0.2: draw_band(fitz.Rect(w - br, bt,     w,      h - bb))

        # Trait de découpe (TrimBox) en pointillés roses
        shape = page.new_shape()
        if bt > 0.2: shape.draw_line(fitz.Point(0,  bt),     fitz.Point(w,     bt))
        if bb > 0.2: shape.draw_line(fitz.Point(0,  h - bb), fitz.Point(w,     h - bb))
        if bl > 0.2: shape.draw_line(fitz.Point(bl, 0),      fitz.Point(bl,    h))
        if br > 0.2: shape.draw_line(fitz.Point(w - br, 0),  fitz.Point(w - br, h))
        shape.finish(color=TRIM_COLOR, width=0.6, dashes="[4 3]")
        shape.commit()

        # Légende discrète
        try:
            legend = (f"VikBAT 1.4  —  FP: H+{bt_mm:.1f} B+{bb_mm:.1f} "
                      f"G+{bl_mm:.1f} D+{br_mm:.1f} mm  —  trait = bord découpe")
            page.insert_text(
                fitz.Point(bl + 3, h - bb - 5),
                legend, fontsize=5,
                color=(0.7, 0.2, 0.45), overlay=True
            )
        except Exception:
            pass

    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()

# ─── Rendu CMJN page (raw CMYK bytes) ────────────────────────────────────────

def _render_cmyk_page(pdf_path: str, page_num: int) -> dict:
    """Render a PDF page as raw CMYK bytes (4 bytes/pixel: C,M,Y,K each 0–255).
    Returns dict {width, height, total, raw_b64} or {error}."""
    RENDER_W = 700
    try:
        import fitz
    except ImportError:
        return {'error': 'PyMuPDF non disponible'}
    doc = None
    try:
        doc   = fitz.open(pdf_path)
        total = len(doc)
        page_num = max(1, min(page_num, total))
        page  = doc[page_num - 1]
        scale = RENDER_W / max(page.rect.width, 1)
        mat   = fitz.Matrix(scale, scale)
        raw_cmyk = None
        w = h = 0
        # 1. Try native CMYK colorspace
        try:
            cs   = getattr(fitz, 'csCMYK', None)
            if cs is None:
                cs = fitz.Colorspace(fitz.CS_CMYK)
            pix = page.get_pixmap(matrix=mat, colorspace=cs, alpha=False)
            if pix.n == 4:
                raw_cmyk = bytes(pix.samples)
                w, h = pix.width, pix.height
        except Exception:
            raw_cmyk = None
        if raw_cmyk is None:
            # 2. Render RGB then convert to CMYK
            pix = page.get_pixmap(matrix=mat, alpha=False)
            w, h = pix.width, pix.height
            rgb  = bytes(pix.samples)
            n    = w * h
            try:
                import numpy as np
                arr = np.frombuffer(rgb, dtype=np.uint8).reshape(n, 3).astype(np.float32) / 255.0
                R, G, B = arr[:,0], arr[:,1], arr[:,2]
                K = 1.0 - np.maximum(R, np.maximum(G, B))
                denom = np.where(K < 1.0, 1.0 - K, 1.0)
                C = np.clip((1.0 - R - K) / denom, 0.0, 1.0)
                M = np.clip((1.0 - G - K) / denom, 0.0, 1.0)
                Y = np.clip((1.0 - B - K) / denom, 0.0, 1.0)
                cmyk_arr = np.stack([C, M, Y, K], axis=1)
                raw_cmyk = (np.clip(cmyk_arr, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes()
            except ImportError:
                out = bytearray(n * 4)
                for i in range(n):
                    r = rgb[i*3]   / 255.0
                    g = rgb[i*3+1] / 255.0
                    b = rgb[i*3+2] / 255.0
                    k = 1.0 - max(r, g, b)
                    inv = (1.0 / (1.0 - k)) if k < 1.0 else 1.0
                    out[i*4]   = int(max(0, min(255, (1.0 - r - k) * inv * 255 + 0.5)))
                    out[i*4+1] = int(max(0, min(255, (1.0 - g - k) * inv * 255 + 0.5)))
                    out[i*4+2] = int(max(0, min(255, (1.0 - b - k) * inv * 255 + 0.5)))
                    out[i*4+3] = int(max(0, min(255, k * 255 + 0.5)))
                raw_cmyk = bytes(out)
        doc.close()

        # Extract spot colors from this page via pikepdf
        spot_colors = []
        try:
            import pikepdf
            pp = pikepdf.open(pdf_path)
            if 1 <= page_num <= len(pp.pages):
                pp_page = pp.pages[page_num - 1]
                def _scan_spots(obj, depth=0, seen=None):
                    if seen is None: seen = set()
                    oid = id(obj)
                    if oid in seen or depth > 6: return
                    seen.add(oid)
                    if isinstance(obj, pikepdf.Array):
                        if len(obj) >= 2 and str(obj[0]) == '/Separation':
                            name = str(obj[1]).lstrip('/')
                            if name not in ('None', 'All') and name not in spot_colors:
                                spot_colors.append(name)
                    elif isinstance(obj, pikepdf.Dictionary):
                        for _, v in obj.items():
                            _scan_spots(v, depth+1, seen)
                res = pp_page.get('/Resources', pikepdf.Dictionary())
                _scan_spots(res)
                # Also scan XObject resources
                xobjs = res.get('/XObject', pikepdf.Dictionary())
                for _, xo in xobjs.items():
                    try:
                        _scan_spots(xo.get('/Resources', pikepdf.Dictionary()), 1)
                    except Exception:
                        pass
            pp.close()
        except Exception:
            pass

        return {
            'width':   w,
            'height':  h,
            'total':   total,
            'raw_b64': base64.b64encode(raw_cmyk).decode('ascii'),
            'spots':   spot_colors,
        }
    except Exception as e:
        if doc:
            try: doc.close()
            except Exception: pass
        return {'error': str(e)}


# ─── Parseur multipart étendu (fichiers + champs texte) ──────────────────────

def _parse_multipart_fields(raw_body: bytes, content_type: str):
    """Returns (files: {field:(fname,bytes)}, fields: {field:str})"""
    ct = content_type.encode() if isinstance(content_type, str) else content_type
    m = re.search(rb'boundary=([^\s;,"]+|"[^"]+")', ct)
    if not m:
        return {}, {}
    boundary = m.group(1).strip(b'"')
    delimiter = b'--' + boundary
    parts = raw_body.split(delimiter)
    files = {}
    fields = {}
    for part in parts:
        if part in (b'', b'--', b'--\r\n', b'\r\n') or not part.strip():
            continue
        part = part.lstrip(b'\r\n')
        if b'\r\n\r\n' in part:
            head, body = part.split(b'\r\n\r\n', 1)
        elif b'\n\n' in part:
            head, body = part.split(b'\n\n', 1)
        else:
            continue
        if body.endswith(b'\r\n'):
            body = body[:-2]
        nm = re.search(rb'[Nn]ame="([^"]*)"', head)
        fn = re.search(rb'[Ff]ilename="([^"]*)"', head)
        if nm and fn:
            field = nm.group(1).decode('utf-8', errors='replace')
            fname = fn.group(1).decode('utf-8', errors='replace')
            files[field] = (fname, body)
        elif nm:
            field = nm.group(1).decode('utf-8', errors='replace')
            fields[field] = body.decode('utf-8', errors='replace').strip()
    return files, fields


# ─── Imposition brochure ─────────────────────────────────────────────────────

def _impose_pdf(pdf_bytes: bytes, mode: str = 'sequential') -> bytes:
    """Combine pages 2-up (side by side).
    mode='sequential': (1,2),(3,4),...
    mode='booklet':    booklet imposition order."""
    try:
        import fitz
    except ImportError:
        raise RuntimeError('PyMuPDF non disponible')

    src = fitz.open(stream=pdf_bytes, filetype='pdf')
    n   = len(src)
    if n == 0:
        raise RuntimeError('PDF vide')

    ref = src[0].rect
    pw, ph = ref.width, ref.height

    if mode == 'booklet':
        total = n + (-n % 4)
        pages = list(range(n)) + [None] * (total - n)
        pairs = []
        lo, hi = 0, len(pages) - 1
        while lo < hi:
            pairs.append((pages[hi], pages[lo]))
            lo += 1; hi -= 1
            if lo < hi:
                pairs.append((pages[lo], pages[hi]))
                lo += 1; hi -= 1
    else:
        padded = list(range(n)) + ([None] if n % 2 else [])
        pairs = [(padded[i], padded[i+1]) for i in range(0, len(padded), 2)]

    out = fitz.open()
    for (l, r) in pairs:
        page = out.new_page(width=pw * 2, height=ph)
        if l is not None:
            page.show_pdf_page(fitz.Rect(0,  0, pw,    ph), src, l)
        if r is not None:
            page.show_pdf_page(fitz.Rect(pw, 0, pw*2,  ph), src, r)

    buf = io.BytesIO()
    out.save(buf)
    src.close(); out.close()
    return buf.getvalue()


# ─── Vignettes de pages ───────────────────────────────────────────────────────

_thumb_cache = {}   # key → {'path': str, 'total': int}

def _get_page_thumbs(pdf_bytes: bytes, filename: str) -> dict:
    """Render small thumbnails for each page. Returns {key, total, thumbs:[b64_jpeg]}."""
    try:
        import fitz
    except ImportError:
        return {'error': 'PyMuPDF non disponible'}

    THUMB_W = 180
    key = hashlib.md5((filename + str(len(pdf_bytes))).encode()).hexdigest()[:14]

    try:
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        total = len(doc)
        thumbs = []
        for i in range(total):
            page  = doc[i]
            scale = THUMB_W / max(page.rect.width, 1)
            mat   = fitz.Matrix(scale, scale)
            pix   = page.get_pixmap(matrix=mat, alpha=False)
            png_bytes = pix.tobytes('png')
            try:
                from PIL import Image as PILImage
                img = PILImage.frombytes('RGB', (pix.width, pix.height), pix.samples)
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=72)
                thumbs.append(base64.b64encode(buf.getvalue()).decode('ascii'))
            except ImportError:
                thumbs.append(base64.b64encode(png_bytes).decode('ascii'))
        doc.close()

        cache_path = os.path.join(tempfile.gettempdir(), f'vikbat_org_{key}.pdf')
        with open(cache_path, 'wb') as f_:
            f_.write(pdf_bytes)
        _thumb_cache[key] = {'path': cache_path, 'total': total}

        return {'key': key, 'total': total, 'thumbs': thumbs}
    except Exception as e:
        return {'error': str(e)}


# ─── Réorganisation de pages ─────────────────────────────────────────────────

def _reorder_pages(key: str, order: list) -> bytes:
    """Reorder pages of cached PDF by order (0-based indices). Returns bytes."""
    try:
        import fitz
    except ImportError:
        raise RuntimeError('PyMuPDF non disponible')

    entry = _thumb_cache.get(key)
    if not entry or not os.path.exists(entry.get('path', '')):
        raise RuntimeError('Cache expiré — rechargez le PDF.')

    doc = fitz.open(entry['path'])
    out = fitz.open()
    for idx in order:
        if 0 <= int(idx) < len(doc):
            out.insert_pdf(doc, from_page=int(idx), to_page=int(idx))

    buf = io.BytesIO()
    out.save(buf)
    doc.close(); out.close()
    return buf.getvalue()


# ─── Conversion CMJN ─────────────────────────────────────────────────────────

def _convert_to_cmyk(pdf_bytes: bytes) -> bytes:
    """Convert all spot/RGB colors to CMYK process.
    Stratégie 1 : GhostScript (préserve vecteurs, texte, qualité native).
    Stratégie 2 : PyMuPDF rastérisation 600 dpi (fallback)."""
    import tempfile, subprocess, os

    # --- Stratégie 1 : GhostScript ---
    tmp_in = None
    tmp_out = None
    try:
        tmp_in  = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        tmp_in.write(pdf_bytes); tmp_in.close()
        tmp_out = tmp_in.name.replace('.pdf', '_cmyk.pdf')
        cmd = [
            'gs', '-dBATCH', '-dNOPAUSE', '-dQUIET',
            '-sDEVICE=pdfwrite',
            '-sProcessColorModel=DeviceCMYK',
            '-sColorConversionStrategy=CMYK',
            '-dOverrideICC=true',
            f'-sOutputFile={tmp_out}',
            tmp_in.name
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=180)
        if result.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 200:
            with open(tmp_out, 'rb') as f:
                out_bytes = f.read()
            return out_bytes
    except Exception:
        pass
    finally:
        for p in (tmp_in.name if tmp_in else None, tmp_out):
            try:
                if p and os.path.exists(p): os.unlink(p)
            except Exception:
                pass

    # --- Stratégie 2 : PyMuPDF 600 dpi ---
    try:
        import fitz
    except ImportError:
        raise RuntimeError('Ni GhostScript ni PyMuPDF disponibles')

    DPI   = 600
    SCALE = DPI / 72.0

    src = fitz.open(stream=pdf_bytes, filetype='pdf')
    out = fitz.open()

    for i in range(len(src)):
        page = src[i]
        w_pt = page.rect.width
        h_pt = page.rect.height
        mat  = fitz.Matrix(SCALE, SCALE)

        try:
            cs  = getattr(fitz, 'csCMYK', None) or fitz.Colorspace(fitz.CS_CMYK)
            pix = page.get_pixmap(matrix=mat, colorspace=cs, alpha=False)
        except Exception:
            pix = page.get_pixmap(matrix=mat, alpha=False)

        img_data = None
        try:
            from PIL import Image as PILImage
            if pix.n == 4:
                img = PILImage.frombytes('CMYK', (pix.width, pix.height), bytes(pix.samples))
                buf_img = io.BytesIO()
                img.save(buf_img, format='JPEG', quality=98)
                img_data = buf_img.getvalue()
            else:
                img = PILImage.frombytes('RGB', (pix.width, pix.height), bytes(pix.samples))
                buf_img = io.BytesIO()
                img.save(buf_img, format='JPEG', quality=98)
                img_data = buf_img.getvalue()
        except ImportError:
            pass

        if img_data is None:
            if pix.n == 4:
                try: pix = fitz.Pixmap(fitz.csRGB, pix)
                except Exception: pass
            img_data = pix.tobytes('png')

        new_page = out.new_page(width=w_pt, height=h_pt)
        new_page.insert_image(new_page.rect, stream=img_data)

    buf = io.BytesIO()
    out.save(buf, deflate=True)
    src.close(); out.close()
    return buf.getvalue()


# ─── Imposition professionnelle avec marques ─────────────────────────────────

def _impose_pdf_pro(pdf_bytes, mode='sequential', inner_bleed=3, outer_bleed=3,
                    creep=0, mark_margin=8, crop_marks=True, reg_marks=True,
                    fold_marks=True, color_bar=False, sheet_size='auto'):
    """Professional 2-up imposition with crop marks, registration marks, fold marks."""
    try:
        import fitz
    except ImportError:
        raise RuntimeError('PyMuPDF non disponible')

    MM = 72.0 / 25.4

    src = fitz.open(stream=pdf_bytes, filetype='pdf')
    n = len(src)
    if n == 0:
        raise RuntimeError('PDF vide')

    ref = src[0].rect
    pw, ph = ref.width, ref.height

    MARG = mark_margin * MM

    # Sheet size
    SHEET_SIZES = {
        'a3l':    (420 * MM, 297 * MM),
        'a3p':    (297 * MM, 420 * MM),
        'a4l':    (297 * MM, 210 * MM),
        'a4p':    (210 * MM, 297 * MM),
        'tabloid': (432 * MM, 279 * MM),
    }
    if sheet_size in SHEET_SIZES:
        sw, sh = SHEET_SIZES[sheet_size]
        # Place pages centered on sheet
        lx = (sw / 2 - pw) / 2
        rx = sw / 2 + (sw / 2 - pw) / 2
        py = (sh - ph) / 2
    else:
        sw = pw * 2 + MARG * 2
        sh = ph + MARG * 2
        lx = MARG
        rx = MARG + pw
        py = MARG

    ib = inner_bleed * MM
    ob = outer_bleed * MM

    # Build page pairs
    if mode in ('booklet', 'booklet_pb'):
        total = n + ((-n) % 4 + 4) % 4
        pages = list(range(n)) + [None] * (total - n)
        pairs = []
        lo, hi = 0, len(pages) - 1
        while lo < hi:
            pairs.append((pages[hi], pages[lo])); lo += 1; hi -= 1
            if lo < hi:
                pairs.append((pages[lo], pages[hi])); lo += 1; hi -= 1
    else:
        padded = list(range(n)) + ([None] if n % 2 else [])
        pairs = [(padded[i], padded[i+1]) for i in range(0, len(padded), 2)]

    out = fitz.open()

    MARK_LEN  = 6 * MM
    MARK_OFF  = 2 * MM
    MARK_W    = 0.25
    BLACK     = (0, 0, 0)

    for pi, (l, r) in enumerate(pairs):
        sheet = out.new_page(width=sw, height=sh)

        # Place pages (inner bleed shifts pages slightly outward from spine)
        if l is not None:
            rect_l = fitz.Rect(lx - ib, py, lx + pw - ib, py + ph)
            sheet.show_pdf_page(rect_l, src, l)
        if r is not None:
            rect_r = fitz.Rect(rx + ib, py, rx + pw + ib, py + ph)
            sheet.show_pdf_page(rect_r, src, r)

        def mark_h(x1, y, x2):
            sh2 = sheet.new_shape()
            sh2.draw_line(fitz.Point(x1, y), fitz.Point(x2, y))
            sh2.finish(color=BLACK, width=MARK_W)
            sh2.commit()

        def mark_v(x, y1, y2):
            sh2 = sheet.new_shape()
            sh2.draw_line(fitz.Point(x, y1), fitz.Point(x, y2))
            sh2.finish(color=BLACK, width=MARK_W)
            sh2.commit()

        if crop_marks:
            # Top-left outer
            mark_h(lx - MARK_OFF - MARK_LEN, py,       lx - MARK_OFF)
            mark_v(lx,                        py - MARK_OFF - MARK_LEN, py - MARK_OFF)
            # Bottom-left outer
            mark_h(lx - MARK_OFF - MARK_LEN, py + ph,  lx - MARK_OFF)
            mark_v(lx,                        py + ph + MARK_OFF, py + ph + MARK_OFF + MARK_LEN)
            # Top-right outer
            mark_h(rx + pw + MARK_OFF, py,      rx + pw + MARK_OFF + MARK_LEN)
            mark_v(rx + pw,            py - MARK_OFF - MARK_LEN, py - MARK_OFF)
            # Bottom-right outer
            mark_h(rx + pw + MARK_OFF, py + ph, rx + pw + MARK_OFF + MARK_LEN)
            mark_v(rx + pw,            py + ph + MARK_OFF, py + ph + MARK_OFF + MARK_LEN)
            # Spine marks (both pages inner edge)
            mark_v(lx + pw, py - MARK_OFF - MARK_LEN, py - MARK_OFF)
            mark_v(lx + pw, py + ph + MARK_OFF, py + ph + MARK_OFF + MARK_LEN)
            mark_v(rx,      py - MARK_OFF - MARK_LEN, py - MARK_OFF)
            mark_v(rx,      py + ph + MARK_OFF, py + ph + MARK_OFF + MARK_LEN)

        if fold_marks:
            spine_x = (lx + pw + rx) / 2
            sh2 = sheet.new_shape()
            sh2.draw_line(fitz.Point(spine_x, 0), fitz.Point(spine_x, py - MARK_OFF))
            sh2.draw_line(fitz.Point(spine_x, py + ph + MARK_OFF), fitz.Point(spine_x, sh))
            sh2.finish(color=BLACK, width=0.2, dashes="[4 3]")
            sh2.commit()

        if reg_marks:
            R = 3.5 * MM
            CL = 7 * MM
            MID_Y = py + ph / 2
            for cx in [lx - MARG * 0.55, rx + pw + MARG * 0.55]:
                sh2 = sheet.new_shape()
                sh2.draw_circle(fitz.Point(cx, MID_Y), R)
                sh2.finish(color=BLACK, width=MARK_W)
                sh2.commit()
                sh2 = sheet.new_shape()
                sh2.draw_line(fitz.Point(cx - CL, MID_Y), fitz.Point(cx + CL, MID_Y))
                sh2.draw_line(fitz.Point(cx, MID_Y - CL), fitz.Point(cx, MID_Y + CL))
                sh2.finish(color=BLACK, width=MARK_W)
                sh2.commit()

        if color_bar:
            bar_h = 4 * MM
            bar_w = pw * 0.5
            bar_x = lx + (pw - bar_w) / 2
            bar_y = py + ph + MARK_OFF + MARK_LEN + 2 * MM
            cmyk_colors = [(1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1),
                           (0,0,0,0.5),(0,0,0,0.25)]
            slw = bar_w / len(cmyk_colors)
            for ci, cmyk in enumerate(cmyk_colors):
                rgb = (round((1-cmyk[0])*(1-cmyk[3]),3),
                       round((1-cmyk[1])*(1-cmyk[3]),3),
                       round((1-cmyk[2])*(1-cmyk[3]),3))
                sh2 = sheet.new_shape()
                sh2.draw_rect(fitz.Rect(bar_x + ci*slw, bar_y, bar_x + (ci+1)*slw, bar_y + bar_h))
                sh2.finish(color=rgb, fill=rgb, width=0)
                sh2.commit()

        # Label
        try:
            lbl = f"VikBAT 1.4 · Planche {pi+1}/{len(pairs)}"
            if l is not None: lbl += f" · G:{l+1}"
            if r is not None: lbl += f" D:{r+1}"
            sheet.insert_text(fitz.Point(lx, sh - MARG/2 + 4), lbl, fontsize=5,
                              color=(0.4,0.4,0.4))
        except Exception:
            pass

    buf = io.BytesIO()
    out.save(buf)
    src.close(); out.close()
    return buf.getvalue()


# ─── Fixups PitStop Pro ───────────────────────────────────────────────────────

def _apply_pitstop_fixups(pdf_bytes, fixups):
    """Apply selected corrections. fixups = dict."""
    try:
        import fitz
    except ImportError:
        raise RuntimeError('PyMuPDF non disponible')

    do_color = fixups.get('rgb_to_cmyk') or fixups.get('spot_to_cmyk')
    do_bleed = fixups.get('add_bleed')
    do_meta  = fixups.get('clean_meta')

    result = pdf_bytes

    # 1. Color conversion (re-render in CMYK)
    if do_color:
        result = _convert_to_cmyk(result)

    # 2. Add bleed (extend MediaBox by 3mm on each side if it equals TrimBox)
    if do_bleed:
        BLEED = 3 * 72 / 25.4
        try:
            import pikepdf
            pp = pikepdf.open(io.BytesIO(result))
            for page in pp.pages:
                tb = page.get('/TrimBox') or page.get('/MediaBox')
                mb = page.get('/MediaBox')
                if tb and mb:
                    tb = [float(x) for x in tb]
                    mb = [float(x) for x in mb]
                    if abs(tb[0]-mb[0]) < 1 and abs(tb[1]-mb[1]) < 1:
                        # Extend MediaBox by bleed
                        new_mb = pikepdf.Array([
                            pikepdf.Real(mb[0] - BLEED),
                            pikepdf.Real(mb[1] - BLEED),
                            pikepdf.Real(mb[2] + BLEED),
                            pikepdf.Real(mb[3] + BLEED),
                        ])
                        page['/MediaBox'] = new_mb
                        if '/TrimBox' not in page:
                            page['/TrimBox'] = pikepdf.Array([pikepdf.Real(x) for x in tb])
            buf = io.BytesIO()
            pp.save(buf)
            pp.close()
            result = buf.getvalue()
        except Exception:
            pass

    # 3. Clean metadata
    if do_meta:
        try:
            doc = fitz.open(stream=result, filetype='pdf')
            doc.set_metadata({})
            buf = io.BytesIO()
            doc.save(buf, deflate=True)
            doc.close()
            result = buf.getvalue()
        except Exception:
            pass

    return result


# ─── Page d'information / protocoles ─────────────────────────────────────────

INFO_HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VikBAT 1.4 — Protocoles</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'SF Mono','Menlo',monospace;background:#020608;color:#e0f7fa;min-height:100vh;padding:48px 24px 80px;
  background-image:linear-gradient(rgba(0,245,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(0,245,255,.03) 1px,transparent 1px);
  background-size:44px 44px;}
.wrap{max-width:760px;margin:0 auto}
h1{font-size:28px;font-weight:900;letter-spacing:-1px;margin-bottom:6px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:linear-gradient(135deg,#00f5ff,#ff00aa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sub{font-size:11px;color:rgba(0,245,255,.5);letter-spacing:2px;text-transform:uppercase;margin-bottom:48px}
.section{border:1px solid rgba(0,245,255,.12);padding:24px 28px;margin-bottom:20px;background:rgba(0,245,255,.02)}
.section h2{font-size:13px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#00f5ff;
  text-shadow:0 0 10px #00f5ff;margin-bottom:14px;display:flex;align-items:center;gap:10px}
.section h2 .ico{font-size:16px}
.section p,.section li{font-size:11px;color:rgba(224,247,250,.75);letter-spacing:.4px;line-height:1.8;margin-bottom:8px}
.section ul{padding-left:18px}
.tag{display:inline-block;font-size:9px;font-weight:700;letter-spacing:1px;padding:2px 8px;
  background:rgba(0,245,255,.06);border:1px solid rgba(0,245,255,.2);color:#00f5ff;margin:2px 2px 2px 0;vertical-align:middle}
.tag.pink{background:rgba(255,0,170,.06);border-color:rgba(255,0,170,.2);color:#ff00aa}
.back{display:inline-block;margin-bottom:32px;font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
  color:rgba(0,245,255,.6);text-decoration:none;border:1px solid rgba(0,245,255,.2);padding:6px 16px}
.back:hover{color:#00f5ff;border-color:#00f5ff}
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="/" onclick="window.close()">← Fermer</a>
  <h1>Protocoles VikBAT 1.4</h1>
  <p class="sub">Documentation des méthodes et algorithmes utilisés</p>

  <div class="section">
    <h2><span class="ico">🎨</span> Analyse colorimétrique</h2>
    <p>Chaque page est analysée pixel par pixel via <span class="tag">PyMuPDF</span>. Les objets sont inspectés dans leur espace colorimétrique natif.</p>
    <ul>
      <li>Détection RVB : présence de couleurs hors gamme CMJN (<span class="tag">sRGB, Display P3, AdobeRGB</span>)</li>
      <li>Tons directs : lecture des ressources PDF (<span class="tag">Separation, DeviceN</span>) via <span class="tag">pikepdf</span></li>
      <li>Surimpression : détection des flags <span class="tag">OP / op</span> dans les flux graphiques</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="ico">🔍</span> Résolution DPI</h2>
    <p>Les images embarquées sont extraites via <span class="tag">PyMuPDF page.get_images()</span>. La résolution effective est calculée :</p>
    <ul>
      <li>Résolution = (pixels natifs de l'image) ÷ (taille affichée en pouces sur la page)</li>
      <li>Seuil BAT : <span class="tag">≥ 300 dpi</span> = OK · <span class="tag">200–299 dpi</span> = Attention · <span class="tag">&lt; 200 dpi</span> = KO</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="ico">📐</span> Fond perdu &amp; format</h2>
    <p>Les boîtes de page sont lues directement via <span class="tag">pikepdf</span> (lecture PDF bas niveau, aucune estimation) :</p>
    <ul>
      <li><span class="tag">TrimBox</span> = format final après découpe</li>
      <li><span class="tag">MediaBox</span> = TrimBox + fond perdu sur chaque côté</li>
      <li>Fond perdu conforme : <span class="tag">≥ 3 mm</span> sur tous les côtés</li>
      <li>L'aperçu visuel des bandes est calculé en pourcentage de la page pour rester précis quelle que soit la taille d'affichage</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="ico">◎</span> Aperçu CMJN</h2>
    <p>Rendu pixel par pixel en espace CMJN natif :</p>
    <ul>
      <li>Tentative 1 : rendu natif <span class="tag">fitz.csCMYK</span> (PyMuPDF)</li>
      <li>Tentative 2 : rendu RGB → conversion CMJN via formule vectorisée <span class="tag">NumPy</span> (ou boucle Python de secours)</li>
      <li>Les données CMJN brutes (4 octets/pixel) sont transférées en <span class="tag">base64</span> et composées en canvas HTML</li>
      <li>Désactivation de plaques C/M/J/N en temps réel sans nouveau rendu serveur</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="ico">📄</span> Imposition brochure</h2>
    <p>Combinaison 2-up (double page côte à côte) via <span class="tag">PyMuPDF page.show_pdf_page()</span> :</p>
    <ul>
      <li><span class="tag">Séquentiel</span> : (1,2), (3,4)… pour agrafage dos carré</li>
      <li><span class="tag">Booklet</span> : ordre d'imposition pour brochure pliée piqûre à cheval (dernière+1ère, 2e+avant-dernière…)</li>
      <li>Le PDF source reste vectoriel — aucune rastérisation</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="ico">🗂</span> Organiser les pages</h2>
    <p>Réorganisation drag &amp; drop dans le navigateur :</p>
    <ul>
      <li>Vignettes générées côté serveur via <span class="tag">PyMuPDF</span> (180 px de large, JPEG 72 %)</li>
      <li>L'ordre final est envoyé au serveur qui reconstruit le PDF avec <span class="tag">fitz.insert_pdf()</span> dans le bon ordre</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="ico">🔄</span> Conversion Quadrichromie</h2>
    <p>Double stratégie pour préserver la qualité au maximum :</p>
    <ul>
      <li><span class="tag">Stratégie 1 — GhostScript</span> : conversion vectorielle native. Texte, vecteurs et images restent intacts, seule la colorimétrie change. Résultat = qualité identique au fichier source.</li>
      <li><span class="tag">Stratégie 2 — PyMuPDF 600 dpi</span> : fallback automatique si GhostScript absent. Rastérisation haute résolution + JPEG qualité 98.</li>
      <li>Tous les tons directs (Pantone, HKS, Separation) et espaces RVB sont convertis en CMJN procédé.</li>
      <li>Le PDF résultant est 100 % CMJN, compatible RIP offset et flux prépresse.</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="ico">📋</span> Rapport d'erreurs</h2>
    <ul>
      <li>Format <span class="tag">.txt</span> structuré, une ligne par critère non conforme</li>
      <li>Inclut : colorimétrie, résolution, tons directs, surimpression, transparence, format, fond perdu</li>
      <li>Compatible copier-coller pour email client ou archivage BAT</li>
    </ul>
  </div>

  <p style="margin-top:32px;font-size:10px;color:rgba(0,245,255,.3);letter-spacing:1px">VikBAT 1.4 — Créé par Viktor · Tous droits réservés</p>
</div>
</body>
</html>"""


# ─── Serveur HTTP ─────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            body = HTML.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/history':
            body = json.dumps(_load_history(), ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith('/download-preview'):
            from urllib.parse import urlparse, parse_qs
            params   = parse_qs(urlparse(self.path).query)
            key      = (params.get('key', [''])[0]).strip()
            entry    = _file_cache.get(key)
            if not entry or not os.path.exists(entry.get('path', '')):
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write('Cache expiré — relancez une analyse.'.encode('ascii', 'replace'))
                return
            pdf_bytes = _generate_annotated_pdf(entry['path'], entry.get('fp_pages', []))
            if pdf_bytes is None:
                # Fallback : retourner le PDF original sans annotations
                with open(entry['path'], 'rb') as _f:
                    pdf_bytes = _f.read()
            safe_name = os.path.splitext(entry.get('filename','apercu'))[0]
            safe_name = safe_name.replace(' ', '_').replace('/','_')[:60]
            dl_name   = f'apercu_fond_perdu_{safe_name}.pdf'
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Disposition', f'attachment; filename="{dl_name}"')
            self.send_header('Content-Length', str(len(pdf_bytes)))
            self.end_headers()
            self.wfile.write(pdf_bytes)
        elif self.path.startswith('/cmyk-page'):
            from urllib.parse import urlparse, parse_qs
            params   = parse_qs(urlparse(self.path).query)
            key      = (params.get('key', [''])[0]).strip()
            try:
                page = int(params.get('page', ['1'])[0])
            except ValueError:
                page = 1
            entry = _file_cache.get(key)
            if not entry or not os.path.exists(entry.get('path', '')):
                body = json.dumps({'error': 'Cache expiré — relancez l\'analyse.'}).encode('utf-8')
                self.send_response(404)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            result = _render_cmyk_page(entry['path'], page)
            body   = json.dumps(result, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/history/clear':
            try:
                os.remove(HISTORY_FILE)
            except Exception:
                pass
            body = b'[]'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/info':
            body = INFO_HTML.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json_error(self, status, msg):
        body = json.dumps({'error': msg}, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_pdf(self, pdf_bytes, filename):
        self.send_response(200)
        self.send_header('Content-Type', 'application/pdf')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Content-Length', str(len(pdf_bytes)))
        self.end_headers()
        self.wfile.write(pdf_bytes)

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', '0') or '0')
        try:
            raw_body = self.rfile.read(content_length)
        except Exception:
            raw_body = b''
        content_type = self.headers.get('Content-Type', '')

        # ── /impose ──────────────────────────────────────────────────────────
        if self.path == '/impose':
            try:
                files_map, tf = _parse_multipart_fields(raw_body, content_type)
                pdf_bytes = None
                orig_name = 'imposition'
                for _, (fname, data) in files_map.items():
                    if fname.lower().endswith('.pdf'):
                        pdf_bytes = data; orig_name = fname
                if not pdf_bytes:
                    self._send_json_error(400, 'Aucun fichier PDF fourni'); return
                def _flt(k, default=0):
                    try: return float(tf.get(k, default))
                    except: return float(default)
                def _bool(k): return tf.get(k,'0') not in ('0','false','')
                result = _impose_pdf_pro(
                    pdf_bytes,
                    mode         = tf.get('mode', 'sequential'),
                    inner_bleed  = _flt('inner_bleed', 3),
                    outer_bleed  = _flt('outer_bleed', 3),
                    creep        = _flt('creep', 0),
                    mark_margin  = _flt('mark_margin', 8),
                    crop_marks   = _bool('crop_marks'),
                    reg_marks    = _bool('reg_marks'),
                    fold_marks   = _bool('fold_marks'),
                    color_bar    = _bool('color_bar'),
                    sheet_size   = tf.get('sheet_size', 'auto'),
                )
                self._send_pdf(result, orig_name.replace('.pdf','_imposition.pdf').replace('.PDF','_imposition.pdf'))
            except Exception as e:
                self._send_json_error(500, str(e))
            return

        # ── /pitstop ──────────────────────────────────────────────────────────
        if self.path == '/pitstop':
            try:
                files_map, tf = _parse_multipart_fields(raw_body, content_type)
                pdf_bytes = None
                orig_name = 'document.pdf'
                for _, (fname, data) in files_map.items():
                    if fname.lower().endswith('.pdf'):
                        pdf_bytes = data; orig_name = fname
                if not pdf_bytes:
                    self._send_json_error(400, 'Aucun fichier PDF fourni'); return
                fixups_str = tf.get('fixups', '{}')
                try:
                    import json as _json
                    fixups = _json.loads(fixups_str)
                except Exception:
                    fixups = {}
                result = _apply_pitstop_fixups(pdf_bytes, fixups)
                safe = orig_name.replace('.pdf','_corrige.pdf').replace('.PDF','_corrige.pdf')
                self._send_pdf(result, safe)
            except Exception as e:
                self._send_json_error(500, str(e))
            return

        # ── /page-thumbs ──────────────────────────────────────────────────────
        if self.path == '/page-thumbs':
            try:
                files_map, _ = _parse_multipart_fields(raw_body, content_type)
                pdf_bytes = None
                orig_name = 'document.pdf'
                for _, (fname, data) in files_map.items():
                    if fname.lower().endswith('.pdf'):
                        pdf_bytes = data; orig_name = fname
                if not pdf_bytes:
                    self._send_json_error(400, 'Aucun fichier PDF fourni'); return
                result = _get_page_thumbs(pdf_bytes, orig_name)
                body = json.dumps(result, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._send_json_error(500, str(e))
            return

        # ── /reorder ──────────────────────────────────────────────────────────
        if self.path == '/reorder':
            try:
                data  = json.loads(raw_body.decode('utf-8'))
                key   = data.get('key', '')
                order = [int(x) for x in data.get('order', [])]
                result = _reorder_pages(key, order)
                self._send_pdf(result, 'reorganise.pdf')
            except Exception as e:
                self._send_json_error(500, str(e))
            return

        # ── /convert-cmyk ─────────────────────────────────────────────────────
        if self.path == '/convert-cmyk':
            try:
                files_map, _ = _parse_multipart_fields(raw_body, content_type)
                pdf_bytes = None
                orig_name = 'document.pdf'
                for _, (fname, data) in files_map.items():
                    if fname.lower().endswith('.pdf'):
                        pdf_bytes = data; orig_name = fname
                if not pdf_bytes:
                    self._send_json_error(400, 'Aucun fichier PDF fourni'); return
                result = _convert_to_cmyk(pdf_bytes)
                safe = orig_name.replace('.pdf', '_CMJN.pdf')
                self._send_pdf(result, safe)
            except Exception as e:
                self._send_json_error(500, str(e))
            return

        # ── /analyze ──────────────────────────────────────────────────────────
        if self.path != '/analyze':
            self.send_response(404)
            self.end_headers()
            return

        try:
            files_map = _parse_multipart(raw_body, content_type)
        except Exception:
            files_map = {}

        analysis_results = []
        for key, (original_name, data) in files_map.items():
            suffix = os.path.splitext(original_name)[-1] or '.pdf'
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            try:
                ext = os.path.splitext(original_name)[-1].lower()
                if ext in analyse_pdf_mail.IMAGE_EXTENSIONS:
                    result = analyse_pdf_mail.analyser_image(tmp_path)
                else:
                    result = analyse_pdf_mail.analyser_pdf(tmp_path)
                    # Mettre en cache le PDF pour /download-preview
                    try:
                        cache_key = hashlib.md5(
                            (original_name + str(len(data))).encode()
                        ).hexdigest()[:14]
                        cache_path = os.path.join(
                            tempfile.gettempdir(), f'vikbat_cache_{cache_key}.pdf'
                        )
                        with open(cache_path, 'wb') as _fc:
                            _fc.write(data)
                        _file_cache[cache_key] = {
                            'path':     cache_path,
                            'fp_pages': result.get('fond_perdu', {}).get('pages', []),
                            'filename': original_name,
                        }
                        result['cache_key'] = cache_key
                    except Exception:
                        pass
                result['original_name'] = original_name
                result = json.loads(
                    json.dumps(result,
                               default=lambda o: list(o) if isinstance(o, (set, frozenset)) else str(o))
                )
            except Exception as e:
                result = {
                    'erreur': str(e),
                    'original_name': original_name,
                    'fichier': original_name,
                    'verdicts': {}
                }
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

            analysis_results.append(result)

        # Sauvegarder dans l'historique
        try:
            _save_to_history(analysis_results)
        except Exception:
            pass

        body = json.dumps(analysis_results, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)


# ─── Point d'entrée ───────────────────────────────────────────────────────────

def main():
    port = PORT
    server = None
    for p in range(PORT, PORT + 20):
        try:
            server = socketserver.TCPServer(('127.0.0.1', p), Handler)
            server.allow_reuse_address = True
            port = p
            break
        except OSError:
            continue

    if server is None:
        print("Impossible de démarrer le serveur.")
        sys.exit(1)

    def open_browser():
        import time; time.sleep(0.9)
        webbrowser.open(f'http://localhost:{port}')

    threading.Thread(target=open_browser, daemon=True).start()
    print(f"VikBAT 1.4 — http://localhost:{port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
