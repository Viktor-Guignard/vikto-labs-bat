/* Worker Pyodide — l'analyse tourne hors du thread principal
   pour que l'interface reste réactive pendant la rastérisation. */

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.3/full/";
const MODULES = ["pikepdf.py", "prepress_core.py", "analyse_pdf_mail.py", "run.py"];

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
  for (const nom of MODULES) {
    const src = await (await fetch("py/" + nom, { cache: "no-cache" })).text();
    pyodide.FS.writeFile("/py/" + nom, src);
  }

  pyodide.runPython('import sys; sys.path.insert(0, "/py")');
  run = pyodide.pyimport("run");
  postMessage({ type: "ready", versions: {
    pyodide: pyodide.version,
    pymupdf: pyodide.runPython("import pymupdf; pymupdf.__version__"),
  }});
}

/* Un nom de fichier PDF peut contenir n'importe quoi ; on ne garde qu'un nom
   sûr pour le système de fichiers virtuel, sans toucher au nom affiché
   (analyser_pdf lit le basename, donc on conserve l'extension et les accents
   sont translittérés par le remplacement ci-dessous). */
function cheminVirtuel(nom, index) {
  const sain = nom.replace(/[^\p{L}\p{N}._ -]/gu, "_").slice(-120);
  return `/in/${index}_${sain}`;
}

async function analyser(fichiers) {
  const resumes = [];
  pyodide.FS.mkdirTree("/in");
  run.reset();

  for (let i = 0; i < fichiers.length; i++) {
    const f = fichiers[i];
    say(`Analyse ${i + 1}/${fichiers.length}`, f.nom);
    const chemin = cheminVirtuel(f.nom, i);
    pyodide.FS.writeFile(chemin, new Uint8Array(f.buffer));
    let resume;
    try {
      const proxy = run.analyser(chemin);
      resume = proxy.toJs({ dict_converter: Object.fromEntries });
      proxy.destroy();
    } catch (e) {
      resume = { fichier: f.nom, erreur: String(e.message || e).split("\n").slice(-4).join(" ") };
    }
    resume.nom_affiche = f.nom;
    resumes.push(resume);
    postMessage({ type: "file-done", resume, index: i, total: fichiers.length });
    try { pyodide.FS.unlink(chemin); } catch (e) { /* déjà supprimé */ }
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

onmessage = async (ev) => {
  const { type } = ev.data;
  try {
    if (type === "init") await init();
    else if (type === "analyze") await analyser(ev.data.fichiers);
  } catch (e) {
    postMessage({ type: "error", message: String(e && e.message ? e.message : e) });
  }
};
