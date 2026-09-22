"""Serveur web de transcription de reunion.

Le navigateur capte l'audio (micro + son de l'ordinateur) et envoie des
morceaux au fil de l'eau ; le serveur les ecrit sur disque, puis transcrit
avec faster-whisper et renvoie le texte.

Lancement :
    python serveur.py
puis ouvrir http://127.0.0.1:8000

Aucune donnee ne sort de la machine qui heberge le serveur : la
transcription tourne en local, sans appel a un service externe.
"""
import netfix  # noqa: F401  -- contournements reseau, DOIT rester le premier import (voir netfix.py)

import datetime
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import CONFIG
from transcribe import transcribe

DOSSIER = Path(__file__).parent
STATIQUE = DOSSIER / "static"

# Une seule transcription a la fois par defaut : sur CPU, les lancer en
# parallele ralentit tout le monde (voir CONFIG.transcriptions_simultanees).
executeur = ThreadPoolExecutor(max_workers=CONFIG.transcriptions_simultanees)


# Nom du fichier qui conserve l'etat d'une session a cote de son audio.
FICHIER_ETAT = "session.json"

# Etats qui supposent un navigateur en train d'alimenter la session, ou une
# transcription en cours dans ce processus : aucun ne survit a un redemarrage.
ETATS_EN_COURS = {"enregistrement", "attente", "transcription", "finalisation"}


def _racine_sessions() -> Path | None:
    """Le dossier ou conserver les reunions, ou None si on travaille en
    temporaire (voir CONFIG.dossier_donnees)."""
    chemin = CONFIG.dossier_donnees.strip()
    if not chemin:
        return None
    racine = Path(chemin)
    racine.mkdir(parents=True, exist_ok=True)
    return racine


@dataclass
class Ligne:
    """Un segment transcrit : ce qui a ete dit, quand, et par quelle source."""
    debut: float                      # secondes depuis le debut de la reunion
    source: str                       # "micro" (moi) | "systeme" (les autres)
    texte: str


@dataclass
class Session:
    """Un enregistrement en cours ou termine."""
    identifiant: str
    dossier: Path
    etat: str = "enregistrement"      # enregistrement | attente | transcription | termine | echec
    # Pourcentage de la transcription, ou -1 tant qu'il est inconnu. GenIAL
    # rend le texte d'un bloc, sans avancement : mieux vaut une attente
    # explicite qu'un 0 % immobile, qui donne l'impression que rien ne tourne.
    progression: int = -1
    texte: str = ""
    erreur: str = ""
    octets_recus: int = 0
    vocabulaire: str = ""             # noms propres / sigles de cette reunion

    # Reference fournie par l'application appelante (Appian ou autre) dans
    # l'URL : ?ref=DOSSIER-2026-0412. C'est par elle qu'elle viendra recuperer
    # le resultat, sans avoir a connaitre l'identifiant interne de la session.
    reference: str = ""

    # Mode direct : les segments arrivent pendant la reunion et sont transcrits
    # au fil de l'eau. `en_attente` compte ceux dont on attend encore le texte,
    # pour ne declarer la session terminee qu'une fois le dernier revenu.
    lignes: list = field(default_factory=list)
    en_attente: int = 0
    segments_recus: int = 0

    # Compte rendu redige a partir de la transcription (moteur GenIAL).
    compte_rendu: str = ""
    cr_etat: str = "absent"           # absent | en_cours | pret | echec
    cr_erreur: str = ""
    debut: datetime.datetime = field(default_factory=datetime.datetime.now)
    verrou: threading.Lock = field(default_factory=threading.Lock)

    @property
    def audio(self) -> Path:
        return self.dossier / "reunion.webm"

    @property
    def dossier_segments(self) -> Path:
        return self.dossier / "segments"

    def nom_de_fichier(self, quoi: str, extension: str) -> str:
        """Nom propose au telechargement : date et heure de la reunion, pour
        que plusieurs comptes rendus ne se confondent pas dans un dossier."""
        return f"{quoi}-{self.debut:%Y-%m-%d-%Hh%M}.{extension}"

    def texte_assemble(self) -> str:
        """Le texte des segments, remis dans l'ordre et etiquete par locuteur.

        Les repliques consecutives d'une meme source sont regroupees : sans
        cela le texte serait hache d'une etiquette toutes les dix secondes."""
        if not self.lignes:
            return ""
        noms = {"micro": CONFIG.nom_micro, "systeme": CONFIG.nom_systeme}
        blocs = []
        for ligne in sorted(self.lignes, key=lambda l: l.debut):
            if not ligne.texte:
                continue
            if blocs and blocs[-1][0] == ligne.source:
                blocs[-1][1] += " " + ligne.texte
            else:
                blocs.append([ligne.source, ligne.texte])
        return "\n\n".join(f"{noms.get(source, source)} : {texte}"
                            for source, texte in blocs)

    # ----------------------------------------------------------------- #
    # Persistance
    #
    # Sans elle, un redemarrage du serveur perd toutes les reunions, y
    # compris celles qu'une application tierce n'est pas encore venue
    # chercher. Un fichier JSON par session suffit : il n'y a jamais assez de
    # reunions pour justifier une base de donnees.
    # ----------------------------------------------------------------- #
    def etat_a_conserver(self) -> dict:
        return {
            "identifiant": self.identifiant,
            "etat": self.etat,
            "progression": self.progression,
            "texte": self.texte,
            "erreur": self.erreur,
            "octets_recus": self.octets_recus,
            "vocabulaire": self.vocabulaire,
            "reference": self.reference,
            "lignes": [{"debut": l.debut, "source": l.source, "texte": l.texte}
                       for l in self.lignes],
            "segments_recus": self.segments_recus,
            "compte_rendu": self.compte_rendu,
            "cr_etat": self.cr_etat,
            "cr_erreur": self.cr_erreur,
            "debut": self.debut.isoformat(),
        }

    def enregistrer(self) -> None:
        """Ecrit l'etat de la session a cote de son audio.

        Silencieux en cas d'echec : ne pas pouvoir ecrire ce fichier ne doit
        jamais interrompre une reunion en cours. Le pire qu'on risque est de
        reperdre cette session au prochain redemarrage, ce qui est l'ancien
        comportement."""
        if _racine_sessions() is None:
            return
        try:
            # Ecriture puis remplacement : si le serveur s'arrete au milieu,
            # on garde l'ancien fichier entier plutot qu'un JSON tronque.
            provisoire = self.dossier / (FICHIER_ETAT + ".tmp")
            provisoire.write_text(
                json.dumps(self.etat_a_conserver(), ensure_ascii=False, indent=1),
                encoding="utf-8")
            provisoire.replace(self.dossier / FICHIER_ETAT)
        except OSError as e:
            print(f"[MeetingCT] Etat de la session {self.identifiant[:8]} "
                  f"non enregistre : {e}", flush=True)

    @classmethod
    def depuis_le_disque(cls, dossier: Path) -> "Session":
        donnees = json.loads((dossier / FICHIER_ETAT).read_text(encoding="utf-8"))
        session = cls(
            identifiant=donnees["identifiant"],
            dossier=dossier,
            etat=donnees["etat"],
            progression=donnees.get("progression", -1),
            texte=donnees.get("texte", ""),
            erreur=donnees.get("erreur", ""),
            octets_recus=donnees.get("octets_recus", 0),
            vocabulaire=donnees.get("vocabulaire", ""),
            reference=donnees.get("reference", ""),
            segments_recus=donnees.get("segments_recus", 0),
            compte_rendu=donnees.get("compte_rendu", ""),
            cr_etat=donnees.get("cr_etat", "absent"),
            cr_erreur=donnees.get("cr_erreur", ""),
            debut=datetime.datetime.fromisoformat(donnees["debut"]),
        )
        session.lignes = [Ligne(**l) for l in donnees.get("lignes", [])]

        # Une session qui n'etait pas terminee ne peut pas reprendre : le
        # navigateur qui l'alimentait a perdu le fil, et les transcriptions
        # en vol sont mortes avec le processus. Le dire franchement vaut
        # mieux qu'un etat "transcription" qui n'avancerait plus jamais.
        if session.etat in ETATS_EN_COURS:
            session.etat = "echec"
            session.erreur = ("Reunion interrompue par un redemarrage du "
                              "serveur. L'enregistrement n'a pas pu etre "
                              "transcrit.")
        if session.cr_etat == "en_cours":
            session.cr_etat = "echec"
            session.cr_erreur = "Interrompu par un redemarrage du serveur."
        return session

    def en_json(self) -> dict:
        return {
            "id": self.identifiant,
            "etat": self.etat,
            "progression": self.progression,
            "texte": self.texte_assemble() if self.lignes else self.texte,
            "erreur": self.erreur,
            "octetsRecus": self.octets_recus,
            "segmentsEnAttente": self.en_attente,
            "compteRendu": self.compte_rendu,
            "crEtat": self.cr_etat,
            "crErreur": self.cr_erreur,
        }


sessions: dict[str, Session] = {}
verrou_sessions = threading.Lock()

app = FastAPI(title="Transcription de reunion")


def origines_autorisees() -> list[str]:
    """Les domaines admis a appeler l'API depuis un navigateur."""
    return [o.strip() for o in CONFIG.origines.split(",") if o.strip()]


_origines = origines_autorisees()
if _origines:
    # Sans ce reglage, le navigateur refuse qu'une page servie par une autre
    # application appelle cette API. Les en-tetes X-Source et X-Debut doivent
    # etre nommes : le navigateur ne laisse passer que les en-tetes autorises.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origines,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Source", "X-Debut", "X-Cle-Api"],
    )


def mode_direct() -> bool:
    """Faut-il transcrire au fil de l'eau ? Voir CONFIG.mode."""
    if CONFIG.mode == "direct":
        return True
    if CONFIG.mode == "differe":
        return False
    # "auto" : seul un moteur qui rend la main plus vite que le temps reel peut
    # tenir la cadence d'une reunion.
    return CONFIG.moteur == "genial"


def _session(identifiant: str) -> Session:
    with verrou_sessions:
        session = sessions.get(identifiant)
    if session is None:
        raise HTTPException(status_code=404, detail="Session inconnue ou expiree.")
    return session


@app.post("/api/sessions")
async def creer_session(requete: Request):
    """Ouvre une session d'enregistrement et renvoie son identifiant.

    Corps facultatif : {"vocabulaire": "noms propres, sigles..."} — ces mots
    sont souffles au modele et evitent les orthographes fantaisistes."""
    try:
        donnees = await requete.json()
    except Exception:
        donnees = {}                   # aucun corps envoye : valeurs par defaut
    vocabulaire = str((donnees or {}).get("vocabulaire", "") or "")[:1000]
    reference = str((donnees or {}).get("reference", "") or "")[:200]

    identifiant = uuid.uuid4().hex
    racine = _racine_sessions()
    if racine is None:
        # Sans dossier de conservation, la reunion ne survit pas au processus.
        dossier = Path(tempfile.mkdtemp(prefix=f"reunion-{identifiant[:8]}-"))
    else:
        dossier = racine / identifiant
        dossier.mkdir(parents=True, exist_ok=True)
    session = Session(identifiant=identifiant, dossier=dossier,
                      vocabulaire=vocabulaire, reference=reference)
    with verrou_sessions:
        sessions[identifiant] = session
    session.enregistrer()
    print(f"[MeetingCT] Session {identifiant[:8]} ouverte"
          f"{' pour ' + reference if reference else ''} ({dossier})", flush=True)
    return session.en_json()


@app.post("/api/sessions/{identifiant}/morceau")
async def ajouter_morceau(identifiant: str, requete: Request):
    """Recoit un morceau d'audio et l'ajoute au fichier, au fil de l'eau :
    rien ne s'accumule en memoire, une reunion de 2 h passe sans probleme."""
    session = _session(identifiant)
    if session.etat != "enregistrement":
        raise HTTPException(status_code=409, detail="Cette session n'enregistre plus.")

    donnees = await requete.body()
    if donnees:
        with session.verrou:
            with open(session.audio, "ab") as f:
                f.write(donnees)
            session.octets_recus += len(donnees)
    return {"octetsRecus": session.octets_recus}


def _transcrire_segment(session: Session, fichier: Path, debut: float, source: str):
    """Transcrit un segment arrive pendant la reunion (mode direct).

    Un segment qui echoue ne fait pas tomber la reunion entiere : l'erreur est
    retenue et les suivants continuent d'arriver."""
    try:
        texte = transcribe(str(fichier), str(fichier.with_suffix(".txt")),
                           vocabulaire=session.vocabulaire)
        texte = texte.strip()
        if texte:
            session.lignes.append(Ligne(debut=debut, source=source, texte=texte))
        print(f"[MeetingCT] Session {session.identifiant[:8]} : {fichier.name} "
              f"-> {len(texte)} caracteres", flush=True)
    except Exception as e:
        session.erreur = str(e)
        print(f"[MeetingCT] Session {session.identifiant[:8]} : segment "
              f"{fichier.name} en echec - {e}", flush=True)
    finally:
        with session.verrou:
            session.en_attente -= 1


@app.post("/api/sessions/{identifiant}/segment")
async def ajouter_segment(identifiant: str, requete: Request):
    """Recoit un segment autonome (mode direct) et lance sa transcription.

    Le navigateur redemarre son enregistreur a chaque segment : chacun est donc
    un fichier webm complet, transcriptible seul — ce qu'un simple morceau du
    flux ne serait pas (seul le premier porte l'en-tete du format)."""
    session = _session(identifiant)
    if session.etat != "enregistrement":
        raise HTTPException(status_code=409, detail="Cette session n'enregistre plus.")

    donnees = await requete.body()
    if not donnees:
        return {"segmentsEnAttente": session.en_attente}

    source = requete.headers.get("x-source", "micro")
    if source not in ("micro", "systeme"):
        source = "micro"
    try:
        debut = float(requete.headers.get("x-debut", "0"))
    except ValueError:
        debut = 0.0

    session.dossier_segments.mkdir(exist_ok=True)
    with session.verrou:
        session.segments_recus += 1
        numero = session.segments_recus
        session.en_attente += 1

    fichier = session.dossier_segments / f"{numero:04d}-{source}.webm"
    fichier.write_bytes(donnees)
    print(f"[MeetingCT] Session {session.identifiant[:8]} : segment {numero} "
          f"({source}, {len(donnees) // 1024} Ko, a {debut:.0f} s) recu", flush=True)
    executeur.submit(_transcrire_segment, session, fichier, debut, source)
    return {"segmentsEnAttente": session.en_attente}


def _finaliser_si_pret(session: Session) -> Session:
    """Passe la session a l'etat final quand le dernier segment est revenu."""
    if session.etat == "finalisation" and session.en_attente == 0:
        if session.lignes:
            (session.dossier / "transcription.txt").write_text(
                session.texte_assemble() + "\n", encoding="utf-8")
            session.progression = 100
            session.etat = "termine"
            print(f"[MeetingCT] Session {session.identifiant[:8]} : terminee "
                  f"({len(session.lignes)} segments)", flush=True)
        else:
            session.etat = "echec"
            session.erreur = session.erreur or (
                "Aucun texte n'a pu etre obtenu. Verifie que le micro capte "
                "bien du son (les barres de niveau bougent pendant l'enregistrement).")
        session.enregistrer()
    return session


def _transcrire(session: Session):
    """Transcrit l'enregistrement (execute hors du thread web)."""
    session.etat = "transcription"
    try:
        def progression(secondes, duree):
            if duree:
                session.progression = min(int(secondes / duree * 100), 100)

        texte = transcribe(str(session.audio),
                           str(session.dossier / "transcription.txt"),
                           progress=progression,
                           vocabulaire=session.vocabulaire)
        session.texte = texte
        session.progression = 100
        session.etat = "termine"
        print(f"[MeetingCT] Session {session.identifiant[:8]} : transcription terminee "
              f"({len(texte)} caracteres)", flush=True)
    except Exception as e:
        session.erreur = str(e)
        session.etat = "echec"
        print(f"[MeetingCT] Session {session.identifiant[:8]} : echec - {e}", flush=True)
    session.enregistrer()


@app.post("/api/sessions/{identifiant}/terminer")
def terminer(identifiant: str):
    """Cloture l'enregistrement et lance la transcription en arriere-plan."""
    session = _session(identifiant)
    if session.etat != "enregistrement":
        return session.en_json()

    if session.segments_recus:
        # Mode direct : tout a deja ete envoye segment par segment pendant la
        # reunion, il ne reste qu'a attendre les dernieres reponses.
        session.etat = "finalisation"
        return _finaliser_si_pret(session).en_json()

    if not session.audio.exists() or session.octets_recus == 0:
        session.etat = "echec"
        session.erreur = ("Aucun son n'a ete recu. Verifie que le micro est autorise "
                          "dans le navigateur et qu'il capte bien du son.")
        session.enregistrer()
        return session.en_json()

    session.etat = "attente"   # devient "transcription" quand un creneau se libere
    executeur.submit(_transcrire, session)
    return session.en_json()


def _rediger(session: Session):
    """Demande le compte rendu a GenIAL (hors du thread web)."""
    try:
        # Importe ici : le moteur local n'a pas de modele de langue, et ne doit
        # pas dependre de ce module.
        from genial import rediger_cr
        texte = rediger_cr(session.texte_assemble() or session.texte)
        (session.dossier / "compte-rendu.md").write_text(texte + "\n",
                                                        encoding="utf-8")
        session.compte_rendu = texte
        session.cr_etat = "pret"
    except Exception as e:
        session.cr_erreur = str(e)
        session.cr_etat = "echec"
        print(f"[MeetingCT] Session {session.identifiant[:8]} : compte rendu "
              f"en echec - {e}", flush=True)
    session.enregistrer()


@app.post("/api/sessions/{identifiant}/compte-rendu")
def demander_compte_rendu(identifiant: str):
    """Lance la redaction du compte rendu a partir de la transcription."""
    session = _session(identifiant)
    if session.etat != "termine":
        raise HTTPException(status_code=409,
                            detail="La transcription n'est pas terminee.")
    if session.cr_etat == "en_cours":
        return session.en_json()

    session.cr_etat = "en_cours"
    session.cr_erreur = ""
    executeur.submit(_rediger, session)
    return session.en_json()


@app.get("/api/sessions/{identifiant}/compte-rendu.md")
def telecharger_compte_rendu(identifiant: str):
    """Telechargement du compte rendu, nomme avec la date de la reunion."""
    session = _session(identifiant)
    fichier = session.dossier / "compte-rendu.md"
    if session.cr_etat != "pret" or not fichier.exists():
        raise HTTPException(status_code=409,
                            detail="Le compte rendu n'est pas pret.")
    return FileResponse(fichier, media_type="text/markdown; charset=utf-8",
                        filename=session.nom_de_fichier("compte-rendu", "md"))


@app.get("/api/sessions/{identifiant}")
def etat_session(identifiant: str):
    """Interroge l'avancement (appele regulierement par le navigateur)."""
    return _finaliser_si_pret(_session(identifiant)).en_json()


@app.delete("/api/sessions/{identifiant}")
def supprimer_session(identifiant: str):
    """Efface l'audio et la transcription du serveur."""
    session = _session(identifiant)
    with verrou_sessions:
        sessions.pop(identifiant, None)
    shutil.rmtree(session.dossier, ignore_errors=True)
    print(f"[MeetingCT] Session {identifiant[:8]} supprimee", flush=True)
    return {"supprime": True}


@app.get("/api/sessions/{identifiant}/audio.webm")
def telecharger_audio(identifiant: str):
    """Audio brut recu par le serveur. Permet de VERIFIER par l'ecoute ce qui a
    reellement ete enregistre : si le son de l'ordinateur manque ici, le
    probleme est a la capture ; s'il y est, il est a la transcription."""
    session = _session(identifiant)
    if not session.audio.exists():
        raise HTTPException(status_code=404, detail="Aucun audio pour cette session.")
    return FileResponse(session.audio, media_type="audio/webm",
                        filename="enregistrement.webm")


@app.get("/api/sessions/{identifiant}/transcription.txt")
def telecharger(identifiant: str):
    """Telechargement du texte en .txt."""
    session = _session(identifiant)
    if session.etat != "termine":
        raise HTTPException(status_code=409, detail="La transcription n'est pas terminee.")
    return FileResponse(session.dossier / "transcription.txt",
                        media_type="text/plain; charset=utf-8",
                        filename=session.nom_de_fichier("transcription", "txt"))


def _verifier_cle(requete: Request) -> None:
    """Protege les routes d'integration par une cle partagee.

    Sans cle configuree, la route reste ouverte : c'est ce qui permet de
    travailler en local sans ceremonie. Des que le serveur ecoute ailleurs que
    sur cette machine, en configurer une (MEETING_CLE_API) — une transcription
    de reunion n'a pas a etre lisible par qui devine une reference."""
    attendue = os.environ.get("MEETING_CLE_API", "").strip()
    if not attendue:
        return
    fournie = requete.headers.get("x-cle-api", "")
    # compare_digest : comparaison a duree constante, pour qu'on ne puisse pas
    # deviner la cle caractere par caractere en mesurant le temps de reponse.
    if not secrets.compare_digest(fournie, attendue):
        raise HTTPException(status_code=401,
                            detail="Cle d'API absente ou invalide.")


def _derniere_par_reference(reference: str):
    """La session la plus recente portant cette reference, ou None.

    La plus recente et non la premiere : une reunion peut etre reenregistree
    apres un faux depart, c'est le dernier essai qui fait foi."""
    with verrou_sessions:
        candidates = [s for s in sessions.values() if s.reference == reference]
    return max(candidates, key=lambda s: s.debut) if candidates else None


@app.get("/api/reunions/{reference}")
def reunion_par_reference(reference: str, requete: Request):
    """Resultat d'une reunion, retrouve par la reference de l'appelant.

    C'est LE point d'entree d'integration : une application tierce ouvre
    l'outil avec ?ref=<sa reference>, puis vient lire ici. Elle n'a jamais
    besoin de connaitre l'identifiant interne de la session.

    Ce format est un contrat : il ne change pas sans preavis, contrairement a
    /api/sessions/{id} qui sert la page et suit ses besoins."""
    _verifier_cle(requete)
    session = _derniere_par_reference(reference)
    if session is None:
        raise HTTPException(status_code=404,
                            detail=f"Aucune reunion pour la reference {reference}.")
    _finaliser_si_pret(session)
    return {
        "ref": session.reference,
        "etat": session.etat,
        "debut": session.debut.isoformat(timespec="seconds"),
        "transcription": session.texte_assemble() or session.texte,
        "compteRendu": session.compte_rendu,
        "compteRenduEtat": session.cr_etat,
        "erreur": session.erreur,
    }


@app.get("/api/info")
def info():
    """Renseigne la page sur le moteur utilise : elle n'affiche pas les memes
    choses selon que l'audio reste sur le serveur ou part chez GenIAL."""
    return {
        "moteur": CONFIG.moteur,
        # Le vocabulaire personnalise n'existe que sur le moteur local.
        "vocabulaireDisponible": CONFIG.moteur == "local",
        "modeDirect": mode_direct(),
        "nomMicro": CONFIG.nom_micro,
        "nomSysteme": CONFIG.nom_systeme,
        # La redaction du compte rendu passe par le modele de langue de
        # GenIAL : elle n'existe pas avec le moteur local.
        "compteRenduDisponible": CONFIG.moteur == "genial",
    }


@app.get("/")
def accueil():
    return FileResponse(STATIQUE / "index.html")


@app.exception_handler(HTTPException)
def erreur_lisible(requete, exc):
    return JSONResponse(status_code=exc.status_code, content={"erreur": exc.detail})


# --------------------------------------------------------------------------- #
# Demarrage et entretien
# --------------------------------------------------------------------------- #

def charger_les_sessions() -> int:
    """Relit les reunions laissees sur le disque par le processus precedent.

    C'est ce qui rend les redemarrages inoffensifs : une application tierce
    qui vient chercher un compte rendu le retrouve, meme si le serveur a
    redemarre entre temps."""
    racine = _racine_sessions()
    if racine is None:
        return 0
    retrouvees = 0
    for dossier in sorted(racine.iterdir()):
        if not (dossier / FICHIER_ETAT).is_file():
            continue          # dossier incomplet ou etranger : on l'ignore
        try:
            session = Session.depuis_le_disque(dossier)
        except (OSError, ValueError, KeyError) as e:
            # Un fichier illisible ne doit pas empecher le serveur de
            # demarrer : on perd cette reunion, pas le service.
            print(f"[MeetingCT] Session illisible dans {dossier.name} : {e}",
                  flush=True)
            continue
        with verrou_sessions:
            sessions[session.identifiant] = session
        retrouvees += 1
    return retrouvees


def purger_les_anciennes() -> int:
    """Efface les reunions plus vieilles que CONFIG.retention_jours.

    Une transcription de reunion est une donnee sensible : elle ne doit pas
    rester sur un serveur parce que personne n'a pense a faire le menage."""
    if CONFIG.retention_jours <= 0:
        return 0
    limite = (datetime.datetime.now()
              - datetime.timedelta(days=CONFIG.retention_jours))
    effacees = 0
    with verrou_sessions:
        perimees = [s for s in sessions.values() if s.debut < limite]
        for session in perimees:
            sessions.pop(session.identifiant, None)
    for session in perimees:
        shutil.rmtree(session.dossier, ignore_errors=True)
        effacees += 1
    if effacees:
        print(f"[MeetingCT] {effacees} reunion(s) effacee(s) apres "
              f"{CONFIG.retention_jours} jours", flush=True)
    return effacees


def _entretien_periodique() -> None:
    """Repasse la purge une fois par jour : un serveur qui tourne des semaines
    ne peut pas compter sur son seul demarrage pour faire le menage."""
    while True:
        time.sleep(24 * 3600)
        try:
            purger_les_anciennes()
        except Exception as e:                       # jamais fatal
            print(f"[MeetingCT] Entretien : {e}", flush=True)


def demarrer(bruyant: bool = True) -> None:
    """Prepare le service : reprise des reunions conservees, puis menage."""
    retrouvees = charger_les_sessions()
    purger_les_anciennes()
    if bruyant and _racine_sessions() is not None:
        print(f"[MeetingCT] {retrouvees} reunion(s) reprise(s) depuis "
              f"{CONFIG.dossier_donnees}", flush=True)
    if _racine_sessions() is not None:
        threading.Thread(target=_entretien_periodique, daemon=True).start()


app.mount("/static", StaticFiles(directory=STATIQUE), name="static")


def options_tls() -> dict:
    """Les arguments TLS a passer a uvicorn, vides si on sert en HTTP.

    Refuse un certificat a moitie configure plutot que de demarrer en clair
    sans le dire : on croirait servir en HTTPS, et le micro serait refuse sans
    qu'on comprenne pourquoi."""
    cert, cle = CONFIG.ssl_cert.strip(), CONFIG.ssl_key.strip()
    if not cert and not cle:
        return {}
    if not cert or not cle:
        raise SystemExit("MEETING_SSL_CERT et MEETING_SSL_KEY vont par paire : "
                         "indiquer les deux, ou aucun des deux.")
    for chemin in (cert, cle):
        if not os.path.isfile(chemin):
            raise SystemExit(f"Fichier de certificat introuvable : {chemin}")
    return {"ssl_certfile": cert, "ssl_keyfile": cle}


if __name__ == "__main__":
    demarrer()
    tls = options_tls()
    protocole = "https" if tls else "http"
    print(f"Serveur de transcription : {protocole}://{CONFIG.host}:{CONFIG.port}")
    if CONFIG.host == "127.0.0.1":
        print("(accessible depuis ce poste uniquement ; mettre host = \"0.0.0.0\" "
              "dans config.py pour l'ouvrir aux autres postes du reseau)")
    elif not tls:
        # Sans HTTPS, le navigateur refuse le micro partout sauf sur localhost.
        # Autant le dire au demarrage plutot que de laisser chercher.
        print("ATTENTION : sans HTTPS, le navigateur refusera le micro aux "
              "postes distants. Voir MEETING_SSL_CERT dans .env.exemple.")
    uvicorn.run(app, host=CONFIG.host, port=CONFIG.port, **tls)
