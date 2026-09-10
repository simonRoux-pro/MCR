// Capte l'audio dans le navigateur et l'envoie au serveur au fil de l'eau.
//
// Le micro seul ne capte pas les autres participants d'une visio (surtout au
// casque). Le navigateur ne peut pas lire le son du systeme comme une
// application de bureau : le seul moyen est getDisplayMedia, ou l'utilisateur
// partage un onglet/ecran en cochant "Partager l'audio".
//
// Les deux sources sont gardees SEPAREES : c'est ce qui permet d'etiqueter le
// texte (le micro, c'est moi ; le son de l'ordinateur, ce sont les autres).
// Elles sont aussi melangees, mais seulement pour l'enregistrement d'archive
// que l'on peut reecouter.

// L'application n'est pas toujours servie a la racine d'un domaine : derriere
// un portail (Coder, reverse proxy...), elle vit sous un prefixe de chemin.
// Des URL absolues comme "/api/sessions" viseraient alors la racine du portail
// et non l'application. On deduit donc la racine de l'adresse de ce script
// lui-meme : c'est la seule information exacte quel que soit le prefixe.
const RACINE = document.currentScript.src.replace(/static\/app\.js(\?.*)?$/, "");

/** Adresse complete d'une ressource de l'application. */
function lien(chemin) {
  return RACINE + chemin.replace(/^\//, "");
}

const DUREE_MORCEAU = 5000;   // archive : un morceau toutes les 5 s
const INTERVALLE_SUIVI = 1000;
const SEUIL_SILENCE = 0.01;   // en dessous : considere comme du silence

// Debit de l'audio compresse. Le reglage par defaut des navigateurs vise la
// visio (voix compressee au maximum) ; ici l'enregistrement reste sur la
// machine, autant garder un son propre : le modele transcrit d'autant mieux.
const DEBIT_AUDIO = 128000;   // 128 kbit/s

// Chaque source est un peu attenuee avant le melange : additionner deux sons
// forts sature l'enregistrement, et une voix saturee devient illisible pour le
// modele.
const GAIN_SOURCE = 0.75;

// --- Decoupage en segments (mode direct) --------------------------------- //
// Les morceaux que produit MediaRecorder ne sont PAS decodables isolement :
// seul le premier porte l'en-tete du format. Pour transcrire pendant la
// reunion, on redemarre donc l'enregistreur a chaque segment, ce qui donne a
// chaque fois un fichier complet et autonome.
const SEGMENT_MIN = 6;        // s : duree avant d'envisager une coupure
const SEGMENT_MAX = 25;       // s : coupure forcee, meme si ca parle encore
const SILENCE_COUPURE = 700;  // ms de silence qui declenchent la coupure
const PERIODE_DECOUPE = 100;  // ms entre deux verifications

// Quand le plafond approche sans qu'un vrai blanc soit venu (un monologue),
// couper a l'instant pile trancherait un mot en deux. On se rabat alors sur un
// simple CREUX : meme un discours continu retombe entre deux mots, bien en
// dessous de son propre niveau de parole. Le seuil est relatif au pic du
// segment, donc valable pour une voix forte comme pour une voix posee.
const ZONE_SOUPLE = 5;        // s avant le plafond ou un creux suffit
const CREUX_RELATIF = 0.2;    // un creux = 20 % du pic du segment
const CREUX_DUREE = 120;      // ms de creux, l'ordre de grandeur d'un blanc
                              // entre deux mots
// Un segment dont le niveau n'a jamais depasse ce seuil n'est pas envoye :
// inutile de faire transcrire du silence, et cela evite un appel sur deux
// quand les interlocuteurs parlent chacun leur tour.
const SEUIL_PAROLE = 0.05;

const el = {
  demarrer: document.getElementById("demarrer"),
  arreter: document.getElementById("arreter"),
  rappel: document.getElementById("rappel"),
  vocabulaire: document.getElementById("vocabulaire"),
  mode: document.getElementById("mode"),
  avertissementMode: document.getElementById("avertissementMode"),
  champVocabulaire: document.getElementById("champVocabulaire"),
  sousTitre: document.getElementById("sousTitre"),
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

// Reglages annonces par le serveur (voir /api/info).
let moteur = "local";
let modeDirect = true;

let sessionId = null;
let enregistreurArchive = null;
let enregistrementEnCours = false;
let fluxAOuvrir = [];      // flux a fermer en fin d'enregistrement
let contexteAudio = null;
let debutEnregistrement = 0;
let minuterie = null;
let animation = null;
let decoupe = null;
let sondeDirect = null;
let envois = [];           // envois de segments encore en vol
let enAttente = 0;         // segments envoyes dont le texte n'est pas revenu

// Etat REEL de la capture (jamais deduit de la case a cocher : c'est ce qui
// masquait l'absence de son systeme dans la version precedente).
let sonSystemeActif = false;

// Une entree par source captee ("micro", "systeme") : sa mesure de niveau, son
// flux isole, son enregistreur de segments et l'etat du segment en cours.
let sources = {};

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
  // Avancement inconnu (-1) : barre animee plutot qu'un 0 % fige, qui laisse
  // croire que rien ne se passe.
  const inconnu = pourcent < 0;
  el.jauge.classList.toggle("indetermine", inconnu);
  el.jauge.style.width = inconnu ? "100%"
    : Math.max(0, Math.min(100, pourcent)) + "%";
}

function duree(secondes) {
  const m = Math.floor(secondes / 60), s = Math.floor(secondes % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

async function api(chemin, options = {}) {
  const reponse = await fetch(lien(chemin), options);
  if (!reponse.ok) {
    let detail = `Erreur ${reponse.status}`;
    try { detail = (await reponse.json()).erreur || detail; } catch (e) { /* reponse non JSON */ }
    throw new Error(detail);
  }
  return reponse.json();
}

/** Branche un flux : mesure de niveau, melange d'archive, et flux isole. */
function brancher(flux, melange, nom) {
  const source = contexteAudio.createMediaStreamSource(flux);
  const mesure = contexteAudio.createAnalyser();
  mesure.fftSize = 512;
  const gain = contexteAudio.createGain();
  gain.gain.value = GAIN_SOURCE;
  // Sortie propre a cette source : c'est elle qui part en transcription, et
  // c'est ce qui permet de savoir qui a parle.
  const isole = contexteAudio.createMediaStreamDestination();

  source.connect(mesure);        // la mesure affiche le niveau reel de la source
  source.connect(gain);
  gain.connect(melange);         // archive reecoutable
  gain.connect(isole);

  noeuds.push(source, gain, isole);   // garde une reference (voir `noeuds`)
  sources[nom] = {
    mesure,
    flux: isole.stream,
    enregistreur: null,
    debutSegment: 0,
    pic: 0,
    silenceDepuis: 0,
    creuxDepuis: 0,
  };
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

/** Releve le niveau d'une source et tient a jour son pic et son silence. */
function mesurer(nom) {
  const s = sources[nom];
  if (!s) return 0;
  const valeur = niveau(s.mesure);
  s.pic = Math.max(s.pic, valeur);

  // Vrai blanc : personne ne parle.
  if (valeur > SEUIL_SILENCE) s.silenceDepuis = 0;
  else if (!s.silenceDepuis) s.silenceDepuis = Date.now();

  // Creux : ca parle encore, mais on est entre deux mots.
  if (valeur > s.pic * CREUX_RELATIF) s.creuxDepuis = 0;
  else if (!s.creuxDepuis) s.creuxDepuis = Date.now();

  return valeur;
}

function rafraichirNiveaux() {
  for (const nom of ["micro", "systeme"]) {
    const valeur = mesurer(nom);
    const barre = nom === "micro" ? el.niveauMicro : el.niveauSysteme;
    // Echelle non lineaire : les niveaux de parole normaux restent lisibles.
    barre.style.width = Math.min(100, Math.sqrt(valeur) * 130) + "%";
    barre.classList.toggle("actif", valeur > SEUIL_SILENCE);
  }
  animation = requestAnimationFrame(rafraichirNiveaux);
}

/** Ouvre un nouveau segment pour une source. */
function demarrerSegment(nom) {
  const s = sources[nom];
  if (!s || !s.enregistreur || s.enregistreur.state !== "inactive") return;
  s.debutSegment = (Date.now() - debutEnregistrement) / 1000;
  s.pic = 0;
  s.silenceDepuis = 0;
  s.creuxDepuis = 0;
  s.enregistreur.start();
}

async function envoyerSegment(donnees, source, debut) {
  try {
    await fetch(lien(`/api/sessions/${sessionId}/segment`), {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Source": source,
        "X-Debut": debut.toFixed(2),
      },
      body: donnees,
    });
  } catch (e) {
    etat("Envoi d'un segment interrompu : " + e.message, "erreur");
  }
}

/** Enregistreur de segments d'une source : a chaque arret, il repart. */
function creerEnregistreurSegments(nom) {
  const s = sources[nom];
  const enregistreur = new MediaRecorder(s.flux, {
    mimeType: "audio/webm",
    audioBitsPerSecond: DEBIT_AUDIO,
  });

  // ondataavailable arrive AVANT onstop : les valeurs du segment qui vient de
  // se fermer sont encore celles-ci.
  enregistreur.ondataavailable = (evenement) => {
    if (evenement.data.size === 0 || !sessionId) return;
    if (s.pic < SEUIL_PAROLE) return;   // cette source n'a rien dit
    envois.push(envoyerSegment(evenement.data, nom, s.debutSegment));
  };
  enregistreur.onstop = () => {
    if (enregistrementEnCours) demarrerSegment(nom);
  };

  s.enregistreur = enregistreur;
  demarrerSegment(nom);
}

/** Ferme les segments assez longs, en cherchant le meilleur moment pour le
 *  faire : un blanc entre deux phrases, sinon un creux entre deux mots, et en
 *  dernier recours le plafond. */
function verifierDecoupe() {
  const maintenant = (Date.now() - debutEnregistrement) / 1000;
  for (const nom of Object.keys(sources)) {
    const s = sources[nom];
    if (!s.enregistreur || s.enregistreur.state !== "recording") continue;
    mesurer(nom);   // aussi mesure ici : requestAnimationFrame s'arrete si
                    // l'utilisateur passe sur une autre fenetre

    const duree = maintenant - s.debutSegment;
    if (duree < SEGMENT_MIN) continue;
    const depuis = (instant) => (instant ? Date.now() - instant : 0);

    // 1. Le cas courant : un vrai blanc, entre deux phrases.
    let couper = depuis(s.silenceDepuis) > SILENCE_COUPURE;

    // 2. Monologue : le plafond approche et personne ne s'est tu. Plutot que
    //    de trancher a l'instant pile, on attend le premier creux entre deux
    //    mots — quelques dizaines de millisecondes suffisent.
    if (!couper && duree >= SEGMENT_MAX - ZONE_SOUPLE) {
      couper = depuis(s.creuxDepuis) > CREUX_DUREE;
    }

    // 3. Plafond atteint sans le moindre creux : on coupe quand meme.
    if (couper || duree >= SEGMENT_MAX) {
      s.enregistreur.stop();   // le texte partira, puis un segment repart
    }
  }
}

/** Micro + (optionnel) son de l'ordinateur. */
// Le son de l'ordinateur est toujours demande : c'est la raison d'etre de
// l'outil (sans lui, on n'enregistre pas les autres participants). Si
// l'utilisateur refuse le partage, on continue au micro seul.
async function ouvrirSources() {
  const micro = await navigator.mediaDevices.getUserMedia({
    audio: {
      // L'annulation d'echo reste indispensable : sans elle, quelqu'un qui
      // ecoute la reunion sur haut-parleurs voit le son de l'ordinateur revenir
      // une seconde fois par le micro, en decale — deux voix superposees, que
      // le modele ne sait pas demeler. Elle garde aussi les deux sources
      // distinctes, ce dont depend l'etiquetage des locuteurs.
      echoCancellation: true,
      noiseSuppression: true,
      // Remonte automatiquement les voix trop faibles (micro loin, personne qui
      // parle bas) : c'est la premiere cause de mots avales a la transcription.
      autoGainControl: true,
      channelCount: 1,
    },
  });
  fluxAOuvrir.push(micro);

  contexteAudio = new AudioContext();
  // Un contexte suspendu ne traite AUCUN son : le melange serait silencieux.
  if (contexteAudio.state === "suspended") await contexteAudio.resume();
  const melange = contexteAudio.createMediaStreamDestination();
  destination = melange;   // garde une reference (voir commentaire sur `noeuds`)
  brancher(micro, melange, "micro");

  {
    let ecran = null;
    try {
      ecran = await navigator.mediaDevices.getDisplayMedia({
        // La video n'est JAMAIS enregistree : seul l'audio de ce partage nous
        // interesse. Mais Chrome refuse un partage audio seul, il faut donc
        // bien la demander. Une image par seconde suffit alors largement : la
        // capture d'ecran ne tourne pas a pleine vitesse pour rien. Une borne
        // haute est toujours satisfiable (il suffit d'ignorer des images),
        // donc elle ne peut pas faire echouer le partage.
        video: { frameRate: { max: 1 } },
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
  sources = {};
  if (animation) { cancelAnimationFrame(animation); animation = null; }
}

async function demarrer() {
  el.demarrer.disabled = true;
  sonSystemeActif = false;
  noeuds = [];
  sources = {};
  envois = [];
  el.texte.value = "";
  etat("Autorisation du micro...");
  try {
    const flux = await ouvrirSources();
    const session = await api("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vocabulaire: el.vocabulaire.value }),
    });
    sessionId = session.id;
    // Le mode est celui choisi dans la page au moment de demarrer : c'est le
    // navigateur qui decoupe ou non, le serveur s'adapte a ce qu'il recoit.
    modeDirect = el.mode.value === "direct";
    debutEnregistrement = Date.now();
    enregistrementEnCours = true;

    // Archive du melange : c'est elle que l'on peut reecouter pour verifier ce
    // qui a reellement ete capte.
    enregistreurArchive = new MediaRecorder(flux, {
      mimeType: "audio/webm",
      audioBitsPerSecond: DEBIT_AUDIO,
    });
    enregistreurArchive.ondataavailable = async (evenement) => {
      if (evenement.data.size === 0 || !sessionId) return;
      try {
        await fetch(lien(`/api/sessions/${sessionId}/morceau`), {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: evenement.data,
        });
      } catch (e) {
        etat("Envoi d'un morceau audio interrompu : " + e.message, "erreur");
      }
    };
    enregistreurArchive.start(DUREE_MORCEAU);

    if (modeDirect) {
      Object.keys(sources).forEach(creerEnregistreurSegments);
      decoupe = setInterval(verifierDecoupe, PERIODE_DECOUPE);
      sondeDirect = setInterval(rafraichirTexte, INTERVALLE_SUIVI * 2);
    }

    el.arreter.disabled = false;
    el.vocabulaire.disabled = true;
    el.mode.disabled = true;
    rafraichirNiveaux();
    minuterie = setInterval(() => {
      const secondes = (Date.now() - debutEnregistrement) / 1000;
      // Source reellement captee, pas la case cochee.
      const source = sonSystemeActif ? "micro + son de l'ordinateur" : "micro seul";
      // Si la file s'allonge, le dire tout de suite : mieux vaut le voir en
      // direct que de le decouvrir a l'arret avec cent segments en retard.
      const retard = enAttente > 2
        ? ` — <strong>${enAttente} segments en attente</strong>, la transcription ne suit pas`
        : "";
      etat(`<span class="point"></span>Enregistrement en cours (${source}) — `
           + `${duree(secondes)}${retard}`);
    }, 500);
  } catch (e) {
    etat("Impossible de demarrer : " + e.message, "erreur");
    enregistrementEnCours = false;
    fermerFlux();
    el.demarrer.disabled = false;
  }
}

/** Recupere le texte deja transcrit pendant que la reunion continue. */
async function rafraichirTexte() {
  if (!sessionId) return;
  try {
    const session = await api(`/api/sessions/${sessionId}`);
    if (session.texte) el.texte.value = session.texte;
    enAttente = session.segmentsEnAttente;
  } catch (e) { /* une sonde ratee n'a pas d'importance, la suivante reprend */ }
}

/** Ferme proprement un enregistreur et attend son dernier bloc. */
function arreterEnregistreur(enregistreur) {
  return new Promise((resoudre) => {
    if (!enregistreur || enregistreur.state === "inactive") return resoudre();
    enregistreur.onstop = resoudre;   // remplace le redemarrage automatique
    enregistreur.stop();
  });
}

async function arreter() {
  el.arreter.disabled = true;
  enregistrementEnCours = false;      // empeche les segments de repartir
  clearInterval(minuterie);
  clearInterval(decoupe);
  clearInterval(sondeDirect);
  etat("Finalisation de l'enregistrement...");

  // Dernier segment de chaque source, puis l'archive.
  await Promise.all(Object.keys(sources)
    .map((nom) => arreterEnregistreur(sources[nom].enregistreur)));
  await arreterEnregistreur(enregistreurArchive);
  await Promise.allSettled(envois);   // tous les segments sont bien partis

  fermerFlux();
  el.niveaux.hidden = true;

  try {
    await api(`/api/sessions/${sessionId}/terminer`, { method: "POST" });
    suivre();
  } catch (e) {
    etat("Erreur : " + e.message, "erreur");
    el.demarrer.disabled = false;
    el.vocabulaire.disabled = false;
    el.mode.disabled = false;
  }
}

function terminee(session) {
  el.texte.value = session.texte;
  jauge(100);
  etat("Transcription terminee.", "succes");
  [el.copier, el.telecharger, el.audio, el.effacer].forEach((b) => (b.disabled = false));
  el.demarrer.disabled = false;
  el.vocabulaire.disabled = false;
  el.mode.disabled = false;
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

    if (session.texte) el.texte.value = session.texte;

    if (session.etat === "attente") {
      etat("En file d'attente (une autre transcription est en cours)...");
    } else if (session.etat === "finalisation") {
      etat(`Derniers segments en cours (${session.segmentsEnAttente} restant`
           + `${session.segmentsEnAttente > 1 ? "s" : ""})...`);
      jauge(-1);
    } else if (session.etat === "transcription") {
      etat(session.progression < 0
        ? "Transcription en cours... cela peut prendre plusieurs minutes."
        : `Transcription en cours... ${session.progression} %`);
      jauge(session.progression);
    } else if (session.etat === "termine") {
      clearInterval(tic);
      terminee(session);
    } else if (session.etat === "echec") {
      clearInterval(tic);
      jauge(0);
      etat("Echec : " + session.erreur, "erreur");
      el.audio.disabled = false;   // l'audio reste ecoutable pour diagnostiquer
      el.demarrer.disabled = false;
      el.vocabulaire.disabled = false;
      el.mode.disabled = false;
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
  window.location = lien(`/api/sessions/${sessionId}/transcription.txt`);
});

// Ecouter l'enregistrement recu par le serveur : c'est LA verification qui
// distingue un probleme de capture (le son manque deja dans l'audio) d'un
// probleme de transcription (le son est present mais pas retranscrit).
el.audio.addEventListener("click", () => {
  window.open(lien(`/api/sessions/${sessionId}/audio.webm`), "_blank");
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

// Le vocabulaire est retenu d'une reunion a l'autre, dans le navigateur
// uniquement (localStorage) : ce sont souvent les memes noms chaque semaine.
const CLE_VOCABULAIRE = "meeting-ct.vocabulaire";
try {
  el.vocabulaire.value = localStorage.getItem(CLE_VOCABULAIRE) || "";
} catch (e) { /* stockage refuse (navigation privee) : sans importance */ }
el.vocabulaire.addEventListener("change", () => {
  try { localStorage.setItem(CLE_VOCABULAIRE, el.vocabulaire.value); }
  catch (e) { /* idem */ }
});

// Le mode est retenu d'une fois sur l'autre, et un avertissement s'affiche si
// le direct est demande a un serveur qui transcrit lui-meme : c'est la que la
// file d'attente se met a grandir.
const CLE_MODE = "meeting-ct.mode";

function rafraichirAvertissement() {
  el.avertissementMode.hidden =
    !(moteur === "local" && el.mode.value === "direct");
}

el.mode.addEventListener("change", () => {
  try { localStorage.setItem(CLE_MODE, el.mode.value); } catch (e) { /* idem */ }
  rafraichirAvertissement();
});

// Le serveur dit quel moteur il utilise et s'il transcrit au fil de l'eau :
// la page adapte son sous-titre, son bouton d'arret et le vocabulaire, qui
// n'existe que sur le moteur local.
(async () => {
  try {
    const infos = await api("/api/info");
    moteur = infos.moteur;
    modeDirect = infos.modeDirect;
    if (!infos.vocabulaireDisponible) el.champVocabulaire.hidden = true;
    if (moteur === "genial") {
      el.sousTitre.textContent = "L'audio est transcrit par GenIAL, le service "
        + "interne. L'enregistrement lui est envoye ; il ne sort pas du reseau.";
    }
    // Le reglage du serveur donne la valeur de depart ; un choix deja fait
    // dans ce navigateur l'emporte.
    el.mode.value = modeDirect ? "direct" : "differe";
    try {
      const retenu = localStorage.getItem(CLE_MODE);
      if (retenu) el.mode.value = retenu;
    } catch (e) { /* stockage refuse : on garde le reglage du serveur */ }
    rafraichirAvertissement();

    el.arreter.textContent = "Arreter";
    el.texte.placeholder = "Le texte apparaitra ici, etiquete "
      + `« ${infos.nomMicro} » et « ${infos.nomSysteme} ».`;
  } catch (e) { /* le serveur repondra de toute facon a la premiere action */ }
})();

// Avertit si le navigateur ne sait pas capter le son de l'ordinateur.
if (!navigator.mediaDevices?.getDisplayMedia) {
  el.rappel.hidden = true;
  etat("Ce navigateur ne permet pas de capter le son de l'ordinateur : "
       + "utilise Chrome ou Edge pour enregistrer les autres participants.", "erreur");
}
