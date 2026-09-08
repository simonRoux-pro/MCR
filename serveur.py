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

import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import CONFIG
from transcribe import transcribe

DOSSIER = Path(__file__).parent
STATIQUE = DOSSIER / "static"

# Une seule transcription a la fois par defaut : sur CPU, les lancer en
# parallele ralentit tout le monde (voir CONFIG.transcriptions_simultanees).
executeur = ThreadPoolExecutor(max_workers=CONFIG.transcriptions_simultanees)


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

    # Mode direct : les segments arrivent pendant la reunion et sont transcrits
    # au fil de l'eau. `en_attente` compte ceux dont on attend encore le texte,
    # pour ne declarer la session terminee qu'une fois le dernier revenu.
    lignes: list = field(default_factory=list)
    en_attente: int = 0
    segments_recus: int = 0
    verrou: threading.Lock = field(default_factory=threading.Lock)

    @property
    def audio(self) -> Path:
        return self.dossier / "reunion.webm"

    @property
    def dossier_segments(self) -> Path:
        return self.dossier / "segments"

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

    def en_json(self) -> dict:
        return {
            "id": self.identifiant,
            "etat": self.etat,
            "progression": self.progression,
            "texte": self.texte_assemble() if self.lignes else self.texte,
            "erreur": self.erreur,
            "octetsRecus": self.octets_recus,
            "segmentsEnAttente": self.en_attente,
        }


sessions: dict[str, Session] = {}
verrou_sessions = threading.Lock()

app = FastAPI(title="Transcription de reunion")


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

    identifiant = uuid.uuid4().hex
    dossier = Path(tempfile.mkdtemp(prefix=f"reunion-{identifiant[:8]}-"))
    session = Session(identifiant=identifiant, dossier=dossier,
                      vocabulaire=vocabulaire)
    with verrou_sessions:
        sessions[identifiant] = session
    print(f"[MeetingCT] Session {identifiant[:8]} ouverte ({dossier})", flush=True)
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
        return session.en_json()

    session.etat = "attente"   # devient "transcription" quand un creneau se libere
    executeur.submit(_transcrire, session)
    return session.en_json()


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
                        filename="transcription.txt")


@app.get("/api/info")
def info():
    """Renseigne la page sur le moteur utilise : elle n'affiche pas les memes
    choses selon que l'audio reste sur le serveur ou part chez GenIAL."""
    return {
        "moteur": CONFIG.moteur,
        # Le vocabulaire personnalise n'existe que sur le moteur local.
        "vocabulaireDisponible": CONFIG.moteur == "local",
        "modeDirect": CONFIG.mode_direct,
        "nomMicro": CONFIG.nom_micro,
        "nomSysteme": CONFIG.nom_systeme,
    }


@app.get("/")
def accueil():
    return FileResponse(STATIQUE / "index.html")


@app.exception_handler(HTTPException)
def erreur_lisible(requete, exc):
    return JSONResponse(status_code=exc.status_code, content={"erreur": exc.detail})


app.mount("/static", StaticFiles(directory=STATIQUE), name="static")


if __name__ == "__main__":
    print(f"Serveur de transcription : http://{CONFIG.host}:{CONFIG.port}")
    if CONFIG.host == "127.0.0.1":
        print("(accessible depuis ce poste uniquement ; mettre host = \"0.0.0.0\" "
              "dans config.py pour l'ouvrir aux autres postes du reseau)")
    uvicorn.run(app, host=CONFIG.host, port=CONFIG.port)
