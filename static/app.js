// Capture l'audio dans le navigateur et l'envoie au serveur au fil de l'eau.
//
// Le micro seul ne capte pas les autres participants d'une visio (surtout au
// casque). Le navigateur ne peut pas lire le son du systeme comme une
// application de bureau : le seul moyen est getDisplayMedia, ou l'utilisateur
// partage un onglet/ecran en cochant "Partager l'audio". Les deux sources sont
// ensuite melangees puis enregistrees.

const DUREE_MORCEAU = 5000;   // envoi d'un morceau toutes les 5 s
const INTERVALLE_SUIVI = 1000;

const el = {
  demarrer: document.getElementById("demarrer"),
  arreter: document.getElementById("arreter"),
  sonSysteme: document.getElementById("sonSysteme"),
  etat: document.getElementById("etat"),
  jauge: document.getElementById("jauge"),
  texte: document.getElementById("texte"),
  copier: document.getElementById("copier"),
  telecharger: document.getElementById("telecharger"),
  effacer: document.getElementById("effacer"),
};

let sessionId = null;
let enregistreur = null;
let fluxAOuvrir = [];      // flux a fermer en fin d'enregistrement
let contexteAudio = null;
let debutEnregistrement = 0;
let minuterie = null;

function etat(message, genre = "") {
  el.etat.className = "etat" + (genre ? " " + genre : "");
  el.etat.innerHTML = message;
}

function jauge(pourcent) {
  el.jauge.style.width = Math.max(0, Math.min(100, pourcent)) + "%";
}

function duree(secondes) {
  const m = Math.floor(secondes / 60), s = Math.floor(secondes % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

async function api(chemin, options = {}) {
  const reponse = await fetch(chemin, options);
  if (!reponse.ok) {
    let detail = `Erreur ${reponse.status}`;
    try { detail = (await reponse.json()).erreur || detail; } catch (e) { /* reponse non JSON */ }
    throw new Error(detail);
  }
  return reponse.json();
}

/** Micro + (optionnel) son de l'ordinateur, melanges en une seule piste. */
async function ouvrirMicroEtSysteme(avecSonSysteme) {
  const micro = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true },
  });
  fluxAOuvrir.push(micro);

  if (!avecSonSysteme) return micro;

  let ecran;
  try {
    ecran = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
  } catch (e) {
    etat("Partage refuse : seul le micro sera enregistre.", "erreur");
    return micro;
  }
  fluxAOuvrir.push(ecran);

  if (ecran.getAudioTracks().length === 0) {
    // L'utilisateur a partage sans cocher "Partager l'audio"
    ecran.getTracks().forEach((p) => p.stop());
    etat("Aucun son partage (case « Partager l'audio » non cochee) : "
         + "seul le micro sera enregistre.", "erreur");
    return micro;
  }
  // La video n'est pas utilisee : on la coupe tout de suite.
  ecran.getVideoTracks().forEach((p) => p.stop());

  contexteAudio = new AudioContext();
  const melange = contexteAudio.createMediaStreamDestination();
  contexteAudio.createMediaStreamSource(micro).connect(melange);
  contexteAudio.createMediaStreamSource(ecran).connect(melange);
  return melange.stream;
}

function fermerFlux() {
  fluxAOuvrir.forEach((flux) => flux.getTracks().forEach((piste) => piste.stop()));
  fluxAOuvrir = [];
  if (contexteAudio) { contexteAudio.close(); contexteAudio = null; }
}

async function demarrer() {
  el.demarrer.disabled = true;
  etat("Autorisation du micro...");
  try {
    const flux = await ouvrirMicroEtSysteme(el.sonSysteme.checked);
    const session = await api("/api/sessions", { method: "POST" });
    sessionId = session.id;

    enregistreur = new MediaRecorder(flux, { mimeType: "audio/webm" });
    enregistreur.ondataavailable = async (evenement) => {
      if (evenement.data.size === 0 || !sessionId) return;
      try {
        await fetch(`/api/sessions/${sessionId}/morceau`, {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: evenement.data,
        });
      } catch (e) {
        etat("Envoi d'un morceau audio interrompu : " + e.message, "erreur");
      }
    };
    enregistreur.start(DUREE_MORCEAU);

    debutEnregistrement = Date.now();
    el.arreter.disabled = false;
    el.sonSysteme.disabled = true;
    minuterie = setInterval(() => {
      const secondes = (Date.now() - debutEnregistrement) / 1000;
      const source = el.sonSysteme.checked ? "micro + son de l'ordinateur" : "micro";
      etat(`<span class="point"></span>Enregistrement en cours (${source}) — ${duree(secondes)}`);
    }, 500);
  } catch (e) {
    etat("Impossible de demarrer : " + e.message, "erreur");
    fermerFlux();
    el.demarrer.disabled = false;
  }
}

async function arreter() {
  el.arreter.disabled = true;
  clearInterval(minuterie);
  etat("Finalisation de l'enregistrement...");

  // Recupere le dernier morceau avant de cloturer.
  await new Promise((resoudre) => {
    enregistreur.onstop = resoudre;
    enregistreur.stop();
  });
  fermerFlux();

  try {
    await api(`/api/sessions/${sessionId}/terminer`, { method: "POST" });
    suivre();
  } catch (e) {
    etat("Erreur : " + e.message, "erreur");
    el.demarrer.disabled = false;
    el.sonSysteme.disabled = false;
  }
}

/** Interroge le serveur jusqu'a la fin de la transcription. */
function suivre() {
  const identifiant = sessionId;
  const tic = setInterval(async () => {
    let session;
    try {
      session = await api(`/api/sessions/${identifiant}`);
    } catch (e) {
      clearInterval(tic);
      etat("Suivi interrompu : " + e.message, "erreur");
      return;
    }

    if (session.etat === "attente") {
      etat("En file d'attente (une autre transcription est en cours)...");
    } else if (session.etat === "transcription") {
      etat(`Transcription en cours... ${session.progression} %`);
      jauge(session.progression);
    } else if (session.etat === "termine") {
      clearInterval(tic);
      jauge(100);
      el.texte.value = session.texte;
      etat("Transcription terminee.", "succes");
      [el.copier, el.telecharger, el.effacer].forEach((b) => (b.disabled = false));
      el.demarrer.disabled = false;
      el.sonSysteme.disabled = false;
    } else if (session.etat === "echec") {
      clearInterval(tic);
      jauge(0);
      etat("Echec : " + session.erreur, "erreur");
      el.demarrer.disabled = false;
      el.sonSysteme.disabled = false;
    }
  }, INTERVALLE_SUIVI);
}

el.demarrer.addEventListener("click", demarrer);
el.arreter.addEventListener("click", arreter);

el.copier.addEventListener("click", async () => {
  await navigator.clipboard.writeText(el.texte.value);
  etat("Transcription copiee dans le presse-papiers.", "succes");
});

el.telecharger.addEventListener("click", () => {
  window.location = `/api/sessions/${sessionId}/transcription.txt`;
});

el.effacer.addEventListener("click", async () => {
  if (!confirm("Effacer l'audio et la transcription du serveur ?")) return;
  await api(`/api/sessions/${sessionId}`, { method: "DELETE" });
  sessionId = null;
  el.texte.value = "";
  jauge(0);
  [el.copier, el.telecharger, el.effacer].forEach((b) => (b.disabled = true));
  etat("Donnees effacees du serveur.", "succes");
});

// Avertit si le navigateur ne sait pas capter le son de l'ordinateur.
if (!navigator.mediaDevices?.getDisplayMedia) {
  el.sonSysteme.checked = false;
  el.sonSysteme.disabled = true;
  etat("Ce navigateur ne permet pas de capter le son de l'ordinateur : "
       + "utilise Chrome ou Edge pour enregistrer les autres participants.", "erreur");
}
