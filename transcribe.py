import os
from faster_whisper import WhisperModel, download_model
from config import CONFIG, chemin_modele_whisper

_model = None


def _trouver_modele() -> str:
    """Retourne le chemin local du modele Whisper, sans JAMAIS telecharger :
    un telechargement en pleine reunion peut bloquer toute la chaine sur un
    reseau instable. Le modele doit avoir ete recupere au prealable par
    telecharge_modele.py (fait automatiquement par setup.sh / setup.bat)."""
    local = chemin_modele_whisper()
    if os.path.isfile(os.path.join(local, "model.bin")):
        return local
    try:
        # Cache Hugging Face deja present sur la machine (ancienne installation)
        return download_model(CONFIG.whisper_model, local_files_only=True)
    except Exception:
        raise RuntimeError(
            f"Le modele Whisper '{CONFIG.whisper_model}' n'est pas installe sur cette machine. "
            "Lance d'abord : python telecharge_modele.py (telechargement avec reprise, "
            "a faire une seule fois), puis reessaie."
        )


def _get_model():
    global _model
    if _model is None:
        source = _trouver_modele()
        print(f"[MeetingCT] Chargement du modele Whisper depuis : {source}", flush=True)
        _model = WhisperModel(
            source,
            device=CONFIG.whisper_device,
            compute_type=CONFIG.whisper_compute,
        )
        print("[MeetingCT] Modele Whisper charge.", flush=True)
    return _model


def transcribe(audio_path: str, out_path: str, progress=None) -> str:
    """Transcrit et ecrit chaque segment dans un fichier au fil de l'eau.
    Si le traitement plante, la partie deja transcrite est conservee.

    progress(secondes_traitees, duree_totale) est appele apres chaque segment.
    """
    model = _get_model()
    segments, info = model.transcribe(
        audio_path,
        language=CONFIG.language,
        vad_filter=True,                   # coupe les silences, gros gain sur CPU
        vad_parameters={"min_silence_duration_ms": 500},
    )

    parts = []
    with open(out_path, "w", encoding="utf-8") as f:
        for seg in segments:
            text = seg.text.strip()
            parts.append(text)
            f.write(text + "\n")
            f.flush()                      # ecrit vraiment sur disque
            os.fsync(f.fileno())
            if progress:
                progress(seg.end, info.duration)

    return " ".join(parts)
