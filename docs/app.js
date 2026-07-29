/* VikBAT web — interface. Toute l'analyse se fait dans worker.js. */

const $ = (id) => document.getElementById(id);
const elDrop = $("drop"), elPick = $("pick"), elFile = $("file");
const elDot = $("dot"), elStatus = $("status"), elCards = $("cards");
const elBar = $("report-bar"), elFrame = $("report-frame");

let worker = null, pret = false, occupe = false, rapportHtml = "", rapportUrl = "";

/* L'aperçu passe par srcdoc : l'iframe est en bac à sable sans allow-same-origin,
   or une URL blob appartient à l'origine parente et s'y voit refusée sur
   certains navigateurs. Le blob ne sert donc qu'au téléchargement. */
function urlRapport() {
  if (!rapportUrl && rapportHtml) {
    rapportUrl = URL.createObjectURL(new Blob([rapportHtml], { type: "text/html" }));
  }
  return rapportUrl;
}

function oublierRapport() {
  if (rapportUrl) URL.revokeObjectURL(rapportUrl);
  rapportUrl = "";
  rapportHtml = "";
}

/* ── état visuel ────────────────────────────────────────── */
function statut(texte, etat) {
  elStatus.textContent = texte;
  elDot.className = "dot" + (etat ? " " + etat : "");
}

function occupation(v) {
  occupe = v;
  elDrop.classList.toggle("busy", v);
  elPick.disabled = v || !pret;
}

/* ── démarrage du worker ────────────────────────────────── */
function demarrer() {
  worker = new Worker("worker.js", { type: "module" });
  worker.onmessage = (ev) => {
    const m = ev.data;
    if (m.type === "progress") statut(m.detail ? `${m.etape} — ${m.detail}` : m.etape, "work");
    else if (m.type === "ready") {
      pret = true;
      occupation(false);
      statut(`Prêt — PyMuPDF ${m.versions.pymupdf}`, "ready");
    }
    else if (m.type === "file-done") ajouterCarte(m.resume);
    else if (m.type === "warn") console.warn(m.message);
    else if (m.type === "done") terminer(m);
    else if (m.type === "error") {
      occupation(false);
      statut("Erreur : " + m.message, "err");
    }
  };
  worker.onerror = (e) => {
    occupation(false);
    statut("Erreur du moteur : " + (e.message || "worker interrompu"), "err");
  };
  worker.postMessage({ type: "init" });
}

/* ── analyse ────────────────────────────────────────────── */
async function analyser(listeFichiers) {
  const pdfs = [...listeFichiers].filter(
    (f) => f.type === "application/pdf" || /\.pdf$/i.test(f.name)
  );
  if (!pdfs.length) {
    statut("Aucun PDF dans la sélection.", "err");
    return;
  }

  elCards.innerHTML = "";
  elBar.hidden = true;
  elFrame.style.display = "none";
  elFrame.removeAttribute("srcdoc");
  $("show-report").textContent = "Voir le rapport complet";
  oublierRapport();
  occupation(true);
  statut(`Lecture de ${pdfs.length} fichier${pdfs.length > 1 ? "s" : ""}…`, "work");

  const fichiers = [];
  for (const f of pdfs) fichiers.push({ nom: f.name, buffer: await f.arrayBuffer() });

  worker.postMessage(
    { type: "analyze", fichiers },
    fichiers.map((f) => f.buffer) // transfert sans copie
  );
}

function terminer(m) {
  occupation(false);
  rapportHtml = m.html || "";
  const n = m.resumes.length;
  const ko = m.resumes.filter((r) => r.erreur).length;
  statut(
    `Terminé — ${n} fichier${n > 1 ? "s" : ""} analysé${n > 1 ? "s" : ""}` +
      (ko ? `, ${ko} en erreur` : ""),
    ko === n ? "err" : "ready"
  );
  elBar.hidden = !rapportHtml;
}

/* ── rendu d'une fiche ──────────────────────────────────── */
const CLASSE_VERDICT = { "✅": "ok", "❌": "ko", "⚠️": "warn", "ℹ️": "info" };

function ajouterCarte(r) {
  const c = document.createElement("article");
  c.className = "card" + (r.erreur ? " err" : "");

  const titre = document.createElement("h2");
  titre.textContent = r.nom_affiche || r.fichier || "?";
  c.appendChild(titre);

  const meta = document.createElement("div");
  meta.className = "meta";
  if (r.erreur) {
    meta.textContent = "Analyse impossible";
    c.appendChild(meta);
    const p = document.createElement("div");
    p.className = "v ko";
    p.textContent = r.erreur;
    c.appendChild(p);
    elCards.appendChild(c);
    return;
  }
  meta.textContent = [
    r.pages ? `${r.pages} page${r.pages > 1 ? "s" : ""}` : null,
    r.format_principal,
    r.taille_fichier ? (r.taille_fichier / 1048576).toFixed(1) + " Mo" : null,
  ].filter(Boolean).join(" · ");
  c.appendChild(meta);

  const vs = document.createElement("div");
  vs.className = "verdicts";
  for (const cle of Object.keys(r.verdicts || {})) {
    const [icone, texte] = r.verdicts[cle];
    const ligne = document.createElement("div");
    ligne.className = "v " + (CLASSE_VERDICT[icone] || "info");
    const i = document.createElement("span"); i.textContent = icone;
    const t = document.createElement("span"); t.textContent = texte;
    ligne.append(i, t);
    vs.appendChild(ligne);
  }
  if (vs.children.length) c.appendChild(vs);

  const faits = [];
  if (r.mode_couleur) faits.push(["Mode", r.mode_couleur]);
  if (r.dpi_min != null) faits.push(["DPI min", Math.round(r.dpi_min)]);
  if (r.tons_directs && r.tons_directs.length) faits.push(["Tons directs", r.tons_directs.join(", ")]);
  if (r.fond_perdu_min != null && r.has_trim_box) faits.push(["Fond perdu", r.fond_perdu_min + " mm"]);
  if (r.type_document) faits.push(["Type", r.type_document]);
  if (faits.length) {
    const box = document.createElement("div");
    box.className = "facts";
    for (const [k, v] of faits) {
      const f = document.createElement("span");
      f.className = "fact";
      const b = document.createElement("b");
      b.textContent = v;
      f.append(k + " ", b);
      box.appendChild(f);
    }
    c.appendChild(box);
  }

  elCards.appendChild(c);
}

/* ── rapport complet ────────────────────────────────────── */
$("show-report").addEventListener("click", () => {
  if (!rapportHtml) return;
  const visible = elFrame.style.display === "block";
  elFrame.style.display = visible ? "none" : "block";
  $("show-report").textContent = visible ? "Voir le rapport complet" : "Masquer le rapport";
  if (!visible) {
    if (elFrame.srcdoc !== rapportHtml) elFrame.srcdoc = rapportHtml;
    elFrame.scrollIntoView({ behavior: "smooth", block: "start" });
  }
});

$("dl-report").addEventListener("click", () => {
  if (!rapportHtml) return;
  const a = document.createElement("a");
  a.href = urlRapport();
  a.download = "rapport-vikbat.html";
  a.click();
});

/* ── entrées fichiers ───────────────────────────────────── */
elPick.addEventListener("click", () => elFile.click());
elFile.addEventListener("change", () => {
  if (elFile.files.length) analyser(elFile.files);
  elFile.value = "";
});

for (const type of ["dragenter", "dragover"]) {
  elDrop.addEventListener(type, (e) => {
    e.preventDefault();
    if (pret && !occupe) elDrop.classList.add("over");
  });
}
for (const type of ["dragleave", "drop"]) {
  elDrop.addEventListener(type, (e) => {
    e.preventDefault();
    elDrop.classList.remove("over");
  });
}
elDrop.addEventListener("drop", (e) => {
  if (!pret || occupe) return;
  if (e.dataTransfer?.files?.length) analyser(e.dataTransfer.files);
});
// Empêche le navigateur d'ouvrir un PDF lâché à côté de la zone
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

demarrer();
