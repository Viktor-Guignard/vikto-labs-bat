/* VIKTO LABS BAT — interface. Analyse et outils s'exécutent dans worker.js. */

const $ = (id) => document.getElementById(id);

let worker = null;
let pret = false;
let occupe = false;

/* ── état partagé ───────────────────────────────────────── */
const etat = {
  rapportHtml: "",
  rapportUrl: "",
  imposition: null,               // File
  conversion: null,               // File
  correction: null,               // File
  organisation: { fichier: null, cle: "", ordre: [], initial: [] },
  separation: { fichier: null, page: 0, total: 0 },
};

/* Encres de la quadrichromie, dans l'ordre des octets renvoyés par le moteur. */
const PLAQUES = [
  { nom: "Cyan", rvb: [0, 174, 239] },
  { nom: "Magenta", rvb: [236, 0, 140] },
  { nom: "Jaune", rvb: [255, 241, 0] },
  { nom: "Noir", rvb: [35, 31, 32] },
];

/* ── utilitaires d'état visuel ──────────────────────────── */
function statut(texte, mode, prefixe = "") {
  const s = $(prefixe + "status");
  const d = $(prefixe + "dot");
  if (s) s.textContent = texte;
  if (d) d.className = "dot" + (mode ? " " + mode : "");
}

function occupation(v, prefixe = "") {
  occupe = v;
  document.querySelectorAll(".drop").forEach((z) => z.classList.toggle("busy", v));
  majBoutons();
  if (v && prefixe) statut("Traitement en cours…", "work", prefixe);
}

function majBoutons() {
  const dispo = pret && !occupe;
  for (const b of ["an-pick", "imp-pick", "org-pick", "conv-pick", "sep-pick", "fix-pick"]) {
    $(b).disabled = !dispo;
  }
  $("imp-run").disabled = !dispo || !etat.imposition;
  $("conv-run").disabled = !dispo || !etat.conversion;
  $("fix-run").disabled = !dispo || !etat.correction;
  const sep = etat.separation;
  $("sep-prec").disabled = !dispo || sep.page <= 0;
  $("sep-suiv").disabled = !dispo || !sep.total || sep.page >= sep.total - 1;
  const org = etat.organisation;
  const modifie = org.ordre.join() !== org.initial.join();
  $("org-run").disabled = !dispo || !org.cle;
  $("org-reset").disabled = !dispo || !modifie;
}

/* ── onglets ────────────────────────────────────────────── */
document.querySelectorAll(".tab").forEach((onglet) => {
  onglet.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => {
      const actif = t === onglet;
      t.setAttribute("aria-selected", String(actif));
      $("p-" + t.dataset.panneau).hidden = !actif;
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
});

/* ── worker ─────────────────────────────────────────────── */
function demarrer() {
  worker = new Worker("worker.js", { type: "module" });
  worker.onmessage = (ev) => recevoir(ev.data);
  worker.onerror = (e) => {
    occupation(false);
    statut("Erreur du moteur : " + (e.message || "worker interrompu"), "err");
  };
  worker.postMessage({ type: "init" });
}

const PREFIXE_CONTEXTE = {
  impose: "imp-", convert: "conv-", thumbs: "org-",
  reorder: "org-", separate: "sep-", fix: "fix-",
};

function recevoir(m) {
  switch (m.type) {
    case "progress":
      statut(m.detail ? `${m.etape} — ${m.detail}` : m.etape, "work");
      break;

    case "ready":
      pret = true;
      occupation(false);
      statut(`Prêt — PyMuPDF ${m.versions.pymupdf}`, "ready");
      break;

    case "file-done":
      ajouterCarte(m.resume);
      break;

    case "done":
      terminerAnalyse(m);
      break;

    case "thumbs":
      afficherVignettes(m);
      break;

    case "separation":
      afficherPlaques(m);
      break;

    case "pdf":
      telechargerPdf(m);
      break;

    case "warn":
      console.warn(m.message);
      break;

    case "error": {
      const p = PREFIXE_CONTEXTE[m.contexte] || "";
      occupation(false);
      statut("Échec : " + m.message, "err", p);
      break;
    }
  }
}

/* ── analyse ────────────────────────────────────────────── */
function urlRapport() {
  if (!etat.rapportUrl && etat.rapportHtml) {
    etat.rapportUrl = URL.createObjectURL(new Blob([etat.rapportHtml], { type: "text/html" }));
  }
  return etat.rapportUrl;
}

function oublierRapport() {
  if (etat.rapportUrl) URL.revokeObjectURL(etat.rapportUrl);
  etat.rapportUrl = "";
  etat.rapportHtml = "";
}

async function analyser(listeFichiers) {
  const pdfs = filtrerPdf(listeFichiers);
  if (!pdfs.length) return statut("Aucun PDF dans la sélection.", "err");

  $("cards").innerHTML = "";
  $("report-bar").hidden = true;
  $("report-frame").style.display = "none";
  $("report-frame").removeAttribute("srcdoc");
  $("show-report").textContent = "Voir le rapport complet";
  oublierRapport();
  occupation(true);
  statut(`Lecture de ${pdfs.length} fichier${pdfs.length > 1 ? "s" : ""}…`, "work");

  const fichiers = [];
  for (const f of pdfs) fichiers.push({ nom: f.name, buffer: await f.arrayBuffer() });
  worker.postMessage({ type: "analyze", fichiers }, fichiers.map((f) => f.buffer));
}

function terminerAnalyse(m) {
  occupation(false);
  etat.rapportHtml = m.html || "";
  const n = m.resumes.length;
  const ko = m.resumes.filter((r) => r.erreur).length;
  statut(
    `Terminé — ${n} fichier${n > 1 ? "s" : ""} analysé${n > 1 ? "s" : ""}` + (ko ? `, ${ko} en erreur` : ""),
    ko === n ? "err" : "ready"
  );
  $("report-bar").hidden = !etat.rapportHtml;
}

const CLASSE_VERDICT = { "✅": "ok", "❌": "ko", "⚠️": "warn", "ℹ️": "info" };

function ajouterCarte(r) {
  const c = document.createElement("article");
  c.className = "card" + (r.erreur ? " err" : "");

  const titre = document.createElement("h3");
  titre.textContent = r.nom_affiche || r.fichier || "?";
  c.appendChild(titre);

  const meta = document.createElement("div");
  meta.className = "meta";
  if (r.erreur) {
    meta.textContent = "Analyse impossible";
    const p = document.createElement("div");
    p.className = "v ko";
    p.textContent = r.erreur;
    c.append(meta, p);
    return void $("cards").appendChild(c);
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
  if (r.tons_directs?.length) faits.push(["Tons directs", r.tons_directs.join(", ")]);
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
  $("cards").appendChild(c);
}

$("show-report").addEventListener("click", () => {
  if (!etat.rapportHtml) return;
  const frame = $("report-frame");
  const visible = frame.style.display === "block";
  frame.style.display = visible ? "none" : "block";
  $("show-report").textContent = visible ? "Voir le rapport complet" : "Masquer le rapport";
  if (!visible) {
    if (frame.srcdoc !== etat.rapportHtml) frame.srcdoc = etat.rapportHtml;
    frame.scrollIntoView({ behavior: "smooth", block: "start" });
  }
});

$("dl-report").addEventListener("click", () => {
  if (!etat.rapportHtml) return;
  declencher(urlRapport(), "rapport-vikto-labs-bat.html");
});

/* ── téléchargement des PDF produits ────────────────────── */
function declencher(url, nom) {
  const a = document.createElement("a");
  a.href = url;
  a.download = nom;
  a.click();
}

function telechargerPdf(m) {
  occupation(false);
  const url = URL.createObjectURL(new Blob([m.buffer], { type: "application/pdf" }));
  declencher(url, m.nom);
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  const mo = (m.buffer.byteLength / 1048576).toFixed(1);
  const p = m.nom.includes("_CMJN") ? "conv-"
    : m.nom.includes("_imposition") ? "imp-"
    : m.nom.includes("_corrige") ? "fix-" : "org-";
  statut(`${m.libelle} téléchargé — ${mo} Mo`, "ready", p);
}

/* ── aperçu CMJN ────────────────────────────────────────── */
async function separer(page) {
  const sep = etat.separation;
  if (!sep.fichier) return;
  sep.page = page;
  occupation(true, "sep-");
  worker.postMessage({
    type: "separate",
    fichier: { nom: sep.fichier.name, buffer: await sep.fichier.arrayBuffer() },
    page,
  });
}

function afficherPlaques(m) {
  occupation(false);
  const sep = etat.separation;
  sep.total = m.total;
  sep.page = m.page;

  const brut = Uint8Array.from(atob(m.raw_b64), (c) => c.charCodeAt(0));
  const conteneur = $("sep-plaques");
  conteneur.innerHTML = "";

  PLAQUES.forEach((plaque, canal) => {
    const bloc = document.createElement("div");
    bloc.className = "plaque";

    const titre = document.createElement("div");
    titre.className = "plaque-titre";
    const nom = document.createElement("span");
    nom.textContent = plaque.nom;
    const couv = document.createElement("b");
    titre.append(nom, couv);
    bloc.appendChild(titre);

    const toile = document.createElement("canvas");
    toile.width = m.width;
    toile.height = m.height;
    const ctx = toile.getContext("2d");
    const image = ctx.createImageData(m.width, m.height);

    let encre = 0;
    const [pr, pv, pb] = plaque.rvb;
    for (let i = 0, p = 0; i < m.width * m.height; i++, p += 4) {
      const v = brut[i * 4 + canal] / 255;   // taux d'encre du pixel
      if (v > 0.01) encre++;
      // fond blanc teinté vers la couleur de l'encre proportionnellement au taux
      image.data[p] = 255 - (255 - pr) * v;
      image.data[p + 1] = 255 - (255 - pv) * v;
      image.data[p + 2] = 255 - (255 - pb) * v;
      image.data[p + 3] = 255;
    }
    ctx.putImageData(image, 0, 0);
    couv.textContent = ((encre / (m.width * m.height)) * 100).toFixed(1) + " % encré";
    bloc.appendChild(toile);
    conteneur.appendChild(bloc);
  });

  const tons = $("sep-tons");
  if (m.spots?.length) {
    tons.hidden = false;
    tons.textContent = "Tons directs sur cette page : " + m.spots.join(", ")
      + " — ils apparaissent ici convertis en quadrichromie, pas sur leur propre plaque.";
  } else {
    tons.hidden = true;
  }

  $("sep-compteur").textContent = `page ${m.page + 1} / ${m.total}`;
  statut(`Page ${m.page + 1} séparée`, "ready", "sep-");
  majBoutons();
}

$("sep-prec").addEventListener("click", () => separer(etat.separation.page - 1));
$("sep-suiv").addEventListener("click", () => separer(etat.separation.page + 1));

/* ── corrections ────────────────────────────────────────── */
$("fix-run").addEventListener("click", async () => {
  if (!etat.correction) return;
  const fixups = {
    rgb_to_cmyk: $("fix-rgb").checked,
    spot_to_cmyk: $("fix-spot").checked,
    add_bleed: $("fix-bleed").checked,
    clean_meta: $("fix-meta").checked,
  };
  if (!Object.values(fixups).some(Boolean)) {
    return statut("Cochez au moins une correction.", "err", "fix-");
  }
  occupation(true, "fix-");
  worker.postMessage({
    type: "fix",
    fichier: { nom: etat.correction.name, buffer: await etat.correction.arrayBuffer() },
    fixups,
  });
});

/* ── imposition ─────────────────────────────────────────── */
$("imp-run").addEventListener("click", async () => {
  if (!etat.imposition) return;
  occupation(true, "imp-");
  worker.postMessage({
    type: "impose",
    fichier: { nom: etat.imposition.name, buffer: await etat.imposition.arrayBuffer() },
    options: {
      mode: $("imp-mode").value,
      sheet_size: $("imp-sheet").value,
      inner_bleed: parseFloat($("imp-inner").value) || 0,
      outer_bleed: parseFloat($("imp-outer").value) || 0,
      creep: parseFloat($("imp-creep").value) || 0,
      mark_margin: parseFloat($("imp-margin").value) || 8,
      crop_marks: $("imp-crop").checked,
      reg_marks: $("imp-reg").checked,
      fold_marks: $("imp-fold").checked,
      color_bar: $("imp-bar").checked,
    },
  });
});

/* ── conversion ─────────────────────────────────────────── */
$("conv-run").addEventListener("click", async () => {
  if (!etat.conversion) return;
  occupation(true, "conv-");
  worker.postMessage({
    type: "convert",
    fichier: { nom: etat.conversion.name, buffer: await etat.conversion.arrayBuffer() },
  });
});

/* ── organisation des pages ─────────────────────────────── */
async function chargerOrganisation(fichier) {
  etat.organisation = { fichier, cle: "", ordre: [], initial: [] };
  $("org-grille").innerHTML = '<div class="vide">Rendu des vignettes…</div>';
  occupation(true, "org-");
  worker.postMessage({
    type: "thumbs",
    fichier: { nom: fichier.name, buffer: await fichier.arrayBuffer() },
  });
}

function afficherVignettes(m) {
  occupation(false);
  const org = etat.organisation;
  org.cle = m.cle;
  org.ordre = m.thumbs.map((_, i) => i);
  org.initial = [...org.ordre];
  org.vignettes = m.thumbs;
  dessinerGrille();
  statut(`${m.total} page${m.total > 1 ? "s" : ""} — glissez pour réordonner`, "ready", "org-");
}

function dessinerGrille() {
  const org = etat.organisation;
  const grille = $("org-grille");
  grille.innerHTML = "";
  if (!org.ordre.length) {
    grille.innerHTML = '<div class="vide">Aucun PDF chargé</div>';
    return majBoutons();
  }
  org.ordre.forEach((indexPage, position) => {
    const v = document.createElement("div");
    v.className = "vignette";
    v.draggable = true;
    v.dataset.position = position;

    const img = document.createElement("img");
    img.src = "data:image/jpeg;base64," + org.vignettes[indexPage];
    img.alt = `Page ${indexPage + 1}`;
    const lg = document.createElement("span");
    lg.textContent = `p. ${indexPage + 1}`;
    v.append(img, lg);

    v.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", String(position));
      e.dataTransfer.effectAllowed = "move";
      v.classList.add("drag");
    });
    v.addEventListener("dragend", () => v.classList.remove("drag"));
    v.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      v.classList.add("cible");
    });
    v.addEventListener("dragleave", () => v.classList.remove("cible"));
    v.addEventListener("drop", (e) => {
      e.preventDefault();
      v.classList.remove("cible");
      const depuis = parseInt(e.dataTransfer.getData("text/plain"), 10);
      const vers = position;
      if (Number.isNaN(depuis) || depuis === vers) return;
      const [deplace] = org.ordre.splice(depuis, 1);
      org.ordre.splice(vers, 0, deplace);
      dessinerGrille();
      statut("Ordre modifié — pensez à télécharger", "warn", "org-");
    });

    grille.appendChild(v);
  });
  majBoutons();
}

$("org-run").addEventListener("click", () => {
  const org = etat.organisation;
  if (!org.cle) return;
  occupation(true, "org-");
  worker.postMessage({ type: "reorder", cle: org.cle, ordre: org.ordre, nom: org.fichier.name });
});

$("org-reset").addEventListener("click", () => {
  etat.organisation.ordre = [...etat.organisation.initial];
  dessinerGrille();
  statut("Ordre d'origine rétabli", "ready", "org-");
});

/* ── entrées fichiers ───────────────────────────────────── */
function filtrerPdf(liste) {
  return [...liste].filter((f) => f.type === "application/pdf" || /\.pdf$/i.test(f.name));
}

/* Relie une zone de dépôt, son bouton et son champ fichier à un traitement. */
function brancherZone({ zone, bouton, champ, multiple, surFichiers }) {
  const z = $(zone);
  $(bouton).addEventListener("click", () => $(champ).click());
  $(champ).addEventListener("change", () => {
    const pdfs = filtrerPdf($(champ).files);
    if (pdfs.length) surFichiers(multiple ? pdfs : pdfs[0]);
    $(champ).value = "";
  });

  for (const t of ["dragenter", "dragover"]) {
    z.addEventListener(t, (e) => {
      e.preventDefault();
      if (pret && !occupe) z.classList.add("over");
    });
  }
  for (const t of ["dragleave", "drop"]) {
    z.addEventListener(t, (e) => {
      e.preventDefault();
      z.classList.remove("over");
    });
  }
  z.addEventListener("drop", (e) => {
    if (!pret || occupe) return;
    const pdfs = filtrerPdf(e.dataTransfer?.files || []);
    if (pdfs.length) surFichiers(multiple ? pdfs : pdfs[0]);
  });
}

brancherZone({
  zone: "an-drop", bouton: "an-pick", champ: "an-file", multiple: true,
  surFichiers: (fs) => analyser(fs),
});

brancherZone({
  zone: "imp-drop", bouton: "imp-pick", champ: "imp-file", multiple: false,
  surFichiers: (f) => {
    etat.imposition = f;
    $("imp-nom").textContent = f.name;
    statut("Prêt à imposer", "ready", "imp-");
    majBoutons();
  },
});

brancherZone({
  zone: "conv-drop", bouton: "conv-pick", champ: "conv-file", multiple: false,
  surFichiers: (f) => {
    etat.conversion = f;
    $("conv-nom").textContent = f.name;
    statut("Prêt à convertir", "ready", "conv-");
    majBoutons();
  },
});

brancherZone({
  zone: "org-drop", bouton: "org-pick", champ: "org-file", multiple: false,
  surFichiers: (f) => {
    $("org-nom").textContent = f.name;
    chargerOrganisation(f);
  },
});

brancherZone({
  zone: "sep-drop", bouton: "sep-pick", champ: "sep-file", multiple: false,
  surFichiers: (f) => {
    etat.separation = { fichier: f, page: 0, total: 0 };
    $("sep-nom").textContent = f.name;
    separer(0);
  },
});

brancherZone({
  zone: "fix-drop", bouton: "fix-pick", champ: "fix-file", multiple: false,
  surFichiers: (f) => {
    etat.correction = f;
    $("fix-nom").textContent = f.name;
    statut("Prêt à corriger", "ready", "fix-");
    majBoutons();
  },
});

// Empêche le navigateur d'ouvrir un PDF lâché à côté d'une zone
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

demarrer();
