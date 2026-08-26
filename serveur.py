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
class Session:
    """Un enregistrement en cours ou termine."""
    identifiant: str
    dossier: Path
    etat: str = "enregistrement"      # enregistrement | attente | transcription | termine | echec
    progression: int = 0              # pourcentage de la transcription
    texte: str = ""
    erreur: str = ""
    octets_recus: int = 0
    verrou: threading.Lock = field(default_factory=threading.Lock)

    @property
    def audio(self) -> Path:
        return self.dossier / "reunion.webm"

    def en_json(self) -> dict:
        return {
            "id": self.identifiant,
            "etat": self.etat,
            "progression": self.progression,
            "texte": self.texte,
            "erreur": self.erreur,
            "octetsRecus": self.octets_recus,
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
def creer_session():
    """Ouvre une session d'enregistrement et renvoie son identifiant."""
    identifiant = uuid.uuid4().hex
    dossier = Path(tempfile.mkdtemp(prefix=f"reunion-{identifiant[:8]}-"))
    session = Session(identifiant=identifiant, dossier=dossier)
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


def _transcrire(session: Session):
    """Transcrit l'enregistrement (execute hors du thread web)."""
    session.etat = "transcription"
    try:
        def progression(secondes, duree):
            if duree:
                session.progression = min(int(secondes / duree * 100), 100)

        texte = transcribe(str(session.audio),
                           str(session.dossier / "transcription.txt"),
                           progress=progression)
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
    return _session(identifiant).en_json()


@app.delete("/api/sessions/{identifiant}")
def supprimer_session(identifiant: str):
    """Efface l'audio et la transcription du serveur."""
    session = _session(identifiant)
    with verrou_sessions:
        sessions.pop(identifiant, None)
    shutil.rmtree(session.dossier, ignore_errors=True)
    print(f"[MeetingCT] Session {identifiant[:8]} supprimee", flush=True)
    return {"supprime": True}


@app.get("/api/sessions/{identifiant}/transcription.txt")
def telecharger(identifiant: str):
    """Telechargement du texte en .txt."""
    session = _session(identifiant)
    if session.etat != "termine":
        raise HTTPException(status_code=409, detail="La transcription n'est pas terminee.")
    return FileResponse(session.dossier / "transcription.txt",
                        media_type="text/plain; charset=utf-8",
                        filename="transcription.txt")


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
