import os
from dataclasses import dataclass


@dataclass
class Config:
    # Transcription
    whisper_model: str = "small"        # base | small | medium (medium = plus lent, meilleur)
    whisper_device: str = "cpu"
    whisper_compute: str = "int8"       # quantification CPU
    language: str = "fr"

    # Serveur web
    host: str = "127.0.0.1"             # "0.0.0.0" pour ouvrir aux autres postes du reseau
    port: int = 8000

    # Nombre de transcriptions simultanees. 1 = les demandes s'enchainent :
    # sur CPU, lancer plusieurs transcriptions en parallele ralentit tout le
    # monde (et le modele Whisper n'est pas prevu pour un usage concurrent).
    transcriptions_simultanees: int = 1


CONFIG = Config()


def chemin_modele_whisper() -> str:
    """Dossier local ou telecharge_modele.py depose le modele Whisper.
    (dans models/, deja exclu de git par le .gitignore)"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "models", f"whisper-{CONFIG.whisper_model}")
