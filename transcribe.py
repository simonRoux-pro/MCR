import os
from faster_whisper import WhisperModel
from config import CONFIG

_model = None


def _get_model():
    global _model
    if _model is None:
        print(
            f"[MeetingCT] Chargement du modele Whisper '{CONFIG.whisper_model}' "
            "(telecharge depuis Hugging Face au premier lancement, mis en cache ensuite)...",
            flush=True,
        )
        _model = WhisperModel(
            CONFIG.whisper_model,
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
