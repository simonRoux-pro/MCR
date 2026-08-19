import os
import tempfile
from transcribe import transcribe
from summarize import summarize


EXTENSIONS_SUPPORTEES = (".wav", ".mp3", ".m4a")


def validate_audio_file(audio_path: str):
    """Verifie qu'un fichier audio existe et a un format supporte.
    Utilise par le mode "fichier" (charger un WAV/MP3 au lieu d'enregistrer le micro)."""
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Fichier audio introuvable : {audio_path}")
    ext = os.path.splitext(audio_path)[1].lower()
    if ext not in EXTENSIONS_SUPPORTEES:
        raise ValueError(
            f"Format non supporte : {ext or '(aucune extension)'} "
            f"(formats attendus : {', '.join(EXTENSIONS_SUPPORTEES)})"
        )


def process(audio_path: str, transcript_progress=None, summary_progress=None):
    """Chaine complete : audio -> transcription -> compte-rendu. Tout en local."""
    transcript_file = os.path.join(tempfile.gettempdir(), "transcript.txt")
    transcript = transcribe(audio_path, transcript_file, progress=transcript_progress)
    report = summarize(transcript, progress=summary_progress)
    return transcript, report


def process_from_file(audio_path: str, transcript_progress=None, summary_progress=None):
    """Meme chaine que process(), mais pour un fichier audio deja existant
    (mode "fichier"). Utile pour tester la chaine sans materiel audio."""
    validate_audio_file(audio_path)
    return process(audio_path, transcript_progress, summary_progress)
