/* Worker Pyodide — analyse et outils tournent hors du thread principal
   pour que l'interface reste réactive pendant la rastérisation. */

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.3/full/";
const MODULES = [
  "pikepdf.py",
  "prepress_core.py",
  "analyse_pdf_mail.py",
  "server_analyseur.py",
  "run.py",
];

let pyodide = null;
let run = null;

const say = (etape, detail) => postMessage({ type: "progress", etape, detail });

async function init() {
  // Worker de type module : import() gère le cross-origin là où importScripts échoue.
  const { loadPyodide } = await import(PYODIDE + "pyodide.mjs");

  say("Chargement de Python…");
  pyodide = await loadPyodide({ indexURL: PYODIDE });

  say("Chargement du moteur PDF…");
  await pyodide.loadPackage(["pymupdf", "pillow"]);

  say("Installation des modules d'analyse…");
  pyodide.FS.mkdirTree("/py");
  pyodide.FS.mkdirTree("/in");
  for (const nom of MODULES) {
    const src = await (await fetch("py/" + nom, { cache: "no-cache" })).text();
    pyodide.FS.writeFile("/py/" + nom, src);
  }

  pyodide.runPython('import sys; sys.path.insert(0, "/py")');
  run = pyodide.pyimport("run");
  postMessage({
    type: "ready",
    versions: {
      pyodide: pyodide.version,
      pymupdf: pyodide.runPython("import pymupdf; pymupdf.__version__"),
    },
  });
}

/* Un nom de fichier PDF peut contenir n'importe quoi ; on ne garde qu'un nom
   sûr pour le système de fichiers virtuel, sans toucher au nom affiché. */
function cheminVirtuel(nom, index) {
  const sain = String(nom).replace(/[^\p{L}\p{N}._ -]/gu, "_").slice(-120);
  return `/in/${index}_${sain}`;
}

function ecrire(fichier, index) {
  const chemin = cheminVirtuel(fichier.nom, index);
  pyodide.FS.writeFile(chemin, new Uint8Array(fichier.buffer));
  return chemin;
}

function effacer(chemin) {
  try {
    pyodide.FS.unlink(chemin);
  } catch (e) {
    /* déjà supprimé */
  }
}

function versJs(proxy) {
  const v = proxy.toJs({ dict_converter: Object.fromEntries });
  proxy.destroy();
  return v;
}

/* Récupère un PDF produit côté Python et le transfère sans copie. */
function livrer(nomSortie, libelle) {
  const proxy = run.recuperer(nomSortie);
  const octets = proxy.toJs();
  proxy.destroy();
  postMessage(
    { type: "pdf", nom: nomSortie, libelle, buffer: octets.buffer },
    [octets.buffer]
  );
}

/* ── analyse ─────────────────────────────────────────────── */
async function analyser(fichiers) {
  const resumes = [];
  run.reset();

  for (let i = 0; i < fichiers.length; i++) {
    const f = fichiers[i];
    say(`Analyse ${i + 1}/${fichiers.length}`, f.nom);
    const chemin = ecrire(f, i);
    let resume;
    try {
      resume = versJs(run.analyser(chemin));
    } catch (e) {
      resume = { fichier: f.nom, erreur: String(e.message || e).split("\n").slice(-4).join(" ") };
    }
    resume.nom_affiche = f.nom;
    resumes.push(resume);
    postMessage({ type: "file-done", resume, index: i, total: fichiers.length });
    effacer(chemin);
  }

  say("Génération du rapport…");
  let html = "";
  try {
    html = run.rapport_html(fichiers.length === 1 ? fichiers[0].nom : `${fichiers.length} fichiers`);
  } catch (e) {
    postMessage({ type: "warn", message: "Rapport HTML indisponible : " + (e.message || e) });
  }
  postMessage({ type: "done", resumes, html });
}

/* ── outils ──────────────────────────────────────────────── */
function sansExtension(nom) {
  return String(nom).replace(/\.pdf$/i, "");
}

async function miniatures(fichier) {
  say("Rendu des vignettes…", fichier.nom);
  const chemin = ecrire(fichier, "org");
  try {
    const r = versJs(run.miniatures(chemin, fichier.nom));
    if (r.error) throw new Error(r.error);
    postMessage({ type: "thumbs", cle: r.key, total: r.total, thumbs: r.thumbs, nom: fichier.nom });
  } finally {
    effacer(chemin);
  }
}

async function reorganiser(cle, ordre, nomSource) {
  say("Réécriture du PDF…");
  const sortie = sansExtension(nomSource) + "_reorganise.pdf";
  versJs(run.reorganiser(cle, ordre, sortie));
  livrer(sortie, "PDF réorganisé");
}

async function imposer(fichier, options) {
  say("Imposition en cours…", fichier.nom);
  const chemin = ecrire(fichier, "imp");
  const sortie = sansExtension(fichier.nom) + "_imposition.pdf";
  try {
    versJs(run.imposer(chemin, sortie, pyodide.toPy(options)));
    livrer(sortie, "Planche imposée");
  } finally {
    effacer(chemin);
  }
}

async function apercuCmjn(fichier, page) {
  say("Séparation des plaques…", `page ${page + 1}`);
  const chemin = ecrire(fichier, "sep");
  try {
    const r = versJs(run.apercu_cmjn(chemin, page));
    if (r.error) throw new Error(r.error);
    postMessage({ type: "separation", ...r, page });
  } finally {
    effacer(chemin);
  }
}

async function corriger(fichier, fixups) {
  say("Application des corrections…", fichier.nom);
  const chemin = ecrire(fichier, "fix");
  const sortie = sansExtension(fichier.nom) + "_corrige.pdf";
  try {
    versJs(run.corriger(chemin, sortie, pyodide.toPy(fixups)));
    livrer(sortie, "PDF corrigé");
  } finally {
    effacer(chemin);
  }
}

async function convertir(fichier) {
  say("Conversion en quadrichromie…", "rastérisation 300 dpi, cela peut être long");
  const chemin = ecrire(fichier, "conv");
  const sortie = sansExtension(fichier.nom) + "_CMJN.pdf";
  try {
    versJs(run.convertir_cmjn(chemin, sortie));
    livrer(sortie, "PDF quadrichromie");
  } finally {
    effacer(chemin);
  }
}

/* ── réception ───────────────────────────────────────────── */
const ACTIONS = {
  init,
  analyze: (d) => analyser(d.fichiers),
  thumbs: (d) => miniatures(d.fichier),
  reorder: (d) => reorganiser(d.cle, d.ordre, d.nom),
  impose: (d) => imposer(d.fichier, d.options),
  convert: (d) => convertir(d.fichier),
  separate: (d) => apercuCmjn(d.fichier, d.page),
  fix: (d) => corriger(d.fichier, d.fixups),
};

onmessage = async (ev) => {
  const action = ACTIONS[ev.data.type];
  if (!action) return;
  try {
    await action(ev.data);
  } catch (e) {
    postMessage({
      type: "error",
      contexte: ev.data.type,
      message: String(e && e.message ? e.message : e).split("\n").slice(-3).join(" "),
    });
  }
};
