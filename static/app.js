// Capture l'audio dans le navigateur et l'envoie au serveur au fil de l'eau.
//
// Le micro seul ne capte pas les autres participants d'une visio (surtout au
// casque). Le navigateur ne peut pas lire le son du systeme comme une
// application de bureau : le seul moyen est getDisplayMedia, ou l'utilisateur
// partage un onglet/ecran en cochant "Partager l'audio". Les deux sources sont
// ensuite melangees puis enregistrees.

const DUREE_MORCEAU = 5000;   // envoi d'un morceau toutes les 5 s
const INTERVALLE_SUIVI = 1000;
const SEUIL_SILENCE = 0.01;   // en dessous : considere comme du silence

const el = {
  demarrer: document.getElementById("demarrer"),
  arreter: document.getElementById("arreter"),
  sonSysteme: document.getElementById("sonSysteme"),
  etat: document.getElementById("etat"),
  jauge: document.getElementById("jauge"),
  texte: document.getElementById("texte"),
  copier: document.getElementById("copier"),
  telecharger: document.getElementById("telecharger"),
  audio: document.getElementById("audio"),
  effacer: document.getElementById("effacer"),
  niveaux: document.getElementById("niveaux"),
  niveauMicro: document.getElementById("niveauMicro"),
  niveauSysteme: document.getElementById("niveauSysteme"),
  ligneSysteme: document.getElementById("ligneSysteme"),
};

let sessionId = null;
let enregistreur = null;
let fluxAOuvrir = [];      // flux a fermer en fin d'enregistrement
let contexteAudio = null;
let debutEnregistrement = 0;
let minuterie = null;
let animation = null;

// Etat REEL de la capture (jamais deduit de la case a cocher : c'est ce qui
// masquait l'absence de son systeme dans la version precedente).
let sonSystemeActif = false;
const mesures = { micro: null, systeme: null };      // AnalyserNode par source

// Les noeuds Web Audio doivent rester references : un noeud dont plus aucune
// variable ne parle peut etre ramasse par le garbage collector, et le son
// s'arrete alors sans la moindre erreur. On les garde donc ici.
let noeuds = [];
let destination = null;

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

/** Branche un flux sur le melange, avec une mesure de niveau pour l'afficher. */
function brancher(flux, melange, nom) {
  const source = contexteAudio.createMediaStreamSource(flux);
  const mesure = contexteAudio.createAnalyser();
  mesure.fftSize = 512;
  source.connect(mesure);
  source.connect(melange);
  mesures[nom] = mesure;
  noeuds.push(source);   // garde une reference (voir commentaire sur `noeuds`)
}

/** Niveau sonore instantane d'une source, entre 0 et 1. */
function niveau(mesure) {
  if (!mesure) return 0;
  const donnees = new Float32Array(mesure.fftSize);
  mesure.getFloatTimeDomainData(donnees);
  let max = 0;
  for (const valeur of donnees) max = Math.max(max, Math.abs(valeur));
  return max;
}

function rafraichirNiveaux() {
  for (const nom of ["micro", "systeme"]) {
    const valeur = niveau(mesures[nom]);
    const barre = nom === "micro" ? el.niveauMicro : el.niveauSysteme;
    // Echelle non lineaire : les niveaux de parole normaux restent lisibles.
    barre.style.width = Math.min(100, Math.sqrt(valeur) * 130) + "%";
    barre.classList.toggle("actif", valeur > SEUIL_SILENCE);
  }
  animation = requestAnimationFrame(rafraichirNiveaux);
}

/** Micro + (optionnel) son de l'ordinateur, melanges en une seule piste. */
async function ouvrirSources(avecSonSysteme) {
  const micro = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true },
  });
  fluxAOuvrir.push(micro);

  contexteAudio = new AudioContext();
  // Un contexte suspendu ne traite AUCUN son : le melange serait silencieux.
  if (contexteAudio.state === "suspended") await contexteAudio.resume();
  const melange = contexteAudio.createMediaStreamDestination();
  destination = melange;   // garde une reference (voir commentaire sur `noeuds`)
  brancher(micro, melange, "micro");

  if (avecSonSysteme) {
    let ecran = null;
    try {
      ecran = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        // Pas de traitement sur le son de l'ordinateur : il est deja propre,
        // et le "nettoyer" degraderait les voix des autres participants.
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
    } catch (e) {
      etat("Partage refuse : seul le micro sera enregistre.", "erreur");
    }

    if (ecran) {
      fluxAOuvrir.push(ecran);
      if (ecran.getAudioTracks().length === 0) {
        // Partage accepte, mais sans cocher "Partager l'audio"
        ecran.getTracks().forEach((p) => p.stop());
        etat("Aucun son partage (case « Partager l'audio » non cochee) : "
             + "seul le micro sera enregistre.", "erreur");
      } else {
        // NE PAS arreter la piste video : dans Chrome, l'arreter met fin a
        // TOUTE la session de partage, et la piste audio meurt avec elle.
        // Elle est simplement laissee de cote (jamais enregistree).
        brancher(ecran, melange, "systeme");
        sonSystemeActif = true;
        // Si l'utilisateur arrete le partage via la barre de Chrome.
        ecran.getAudioTracks()[0].addEventListener("ended", () => {
          sonSystemeActif = false;
          mesures.systeme = null;
          etat("Partage du son interrompu : la suite est enregistree au micro seul.",
               "erreur");
        });
      }
    }
  }

  el.ligneSysteme.hidden = !sonSystemeActif;
  el.niveaux.hidden = false;
  return melange.stream;
}

function fermerFlux() {
  fluxAOuvrir.forEach((flux) => flux.getTracks().forEach((piste) => piste.stop()));
  fluxAOuvrir = [];
  if (contexteAudio) { contexteAudio.close(); contexteAudio = null; }
  noeuds = [];
  destination = null;
  mesures.micro = mesures.systeme = null;
  if (animation) { cancelAnimationFrame(animation); animation = null; }
}

async function demarrer() {
  el.demarrer.disabled = true;
  sonSystemeActif = false;
  noeuds = [];
  etat("Autorisation du micro...");
  try {
    const flux = await ouvrirSources(el.sonSysteme.checked);
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
    rafraichirNiveaux();
    minuterie = setInterval(() => {
      const secondes = (Date.now() - debutEnregistrement) / 1000;
      // Source reellement captee, pas la case cochee.
      const source = sonSystemeActif ? "micro + son de l'ordinateur" : "micro seul";
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
  el.niveaux.hidden = true;

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
      [el.copier, el.telecharger, el.audio, el.effacer].forEach((b) => (b.disabled = false));
      el.demarrer.disabled = false;
      el.sonSysteme.disabled = false;
    } else if (session.etat === "echec") {
      clearInterval(tic);
      jauge(0);
      etat("Echec : " + session.erreur, "erreur");
      el.audio.disabled = false;   // l'audio reste ecoutable pour diagnostiquer
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

// Ecouter l'enregistrement recu par le serveur : c'est LA verification qui
// distingue un probleme de capture (le son manque deja dans l'audio) d'un
// probleme de transcription (le son est present mais pas retranscrit).
el.audio.addEventListener("click", () => {
  window.open(`/api/sessions/${sessionId}/audio.webm`, "_blank");
});

el.effacer.addEventListener("click", async () => {
  if (!confirm("Effacer l'audio et la transcription du serveur ?")) return;
  await api(`/api/sessions/${sessionId}`, { method: "DELETE" });
  sessionId = null;
  el.texte.value = "";
  jauge(0);
  [el.copier, el.telecharger, el.audio, el.effacer].forEach((b) => (b.disabled = true));
  etat("Donnees effacees du serveur.", "succes");
});

// Avertit si le navigateur ne sait pas capter le son de l'ordinateur.
if (!navigator.mediaDevices?.getDisplayMedia) {
  el.sonSysteme.checked = false;
  el.sonSysteme.disabled = true;
  etat("Ce navigateur ne permet pas de capter le son de l'ordinateur : "
       + "utilise Chrome ou Edge pour enregistrer les autres participants.", "erreur");
}
