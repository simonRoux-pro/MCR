import os
from faster_whisper import WhisperModel, download_model
from config import CONFIG, chemin_modele_whisper

_model = None

# Silence a partir duquel on ouvre un nouveau paragraphe dans le texte final :
# un blanc de cette duree, dans une reunion, marque presque toujours un
# changement de sujet ou de personne qui parle.
PAUSE_PARAGRAPHE = 3.0   # secondes


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
            cpu_threads=CONFIG.cpu_threads,
        )
        print("[MeetingCT] Modele Whisper charge.", flush=True)
    return _model


def transcribe(audio_path: str, out_path: str, progress=None,
               vocabulaire: str = "") -> str:
    """Transcrit et ecrit le texte dans un fichier au fil de l'eau.
    Si le traitement plante, la partie deja transcrite est conservee.

    progress(secondes_traitees, duree_totale) est appele apres chaque segment.
    vocabulaire : mots propres a la reunion (noms, sigles) souffles au modele ;
    a defaut, celui de config.py est utilise.
    """
    mots = (vocabulaire or CONFIG.vocabulaire).strip()
    model = _get_model()
    segments, info = model.transcribe(
        audio_path,
        language=CONFIG.language,

        # Qualite du decodage : plusieurs hypotheses sont comparees plutot que
        # de garder aveuglement le premier mot venu (voir CONFIG.beam_size).
        beam_size=CONFIG.beam_size,

        # Ne PAS reinjecter le texte deja produit comme contexte. C'est le
        # reglage qui evite les boucles de repetition de Whisper : sur une
        # reunion (blancs, brouhaha, coupures), une erreur reinjectee se
        # propage sinon aux phrases suivantes et le texte part en vrille.
        condition_on_previous_text=False,

        # Vocabulaire maison souffle au modele avant chaque passage.
        hotwords=mots or None,

        # Ecarte les passages ou le modele n'entend en fait pas de parole :
        # sans cela, un silence ou un bruit de fond produit des phrases
        # inventees (le fameux "Sous-titres realises par...").
        no_speech_threshold=0.6,

        vad_filter=True,                   # coupe les silences, gros gain sur CPU
        vad_parameters={
            # Il faut un vrai blanc pour couper : trop court, une phrase se
            # trouve tranchee en plein milieu et le modele perd le fil.
            "min_silence_duration_ms": 1000,
            # Marge conservee de chaque cote d'un passage parle : evite de
            # manger le premier et le dernier mot.
            "speech_pad_ms": 400,
            # Micro-bruits isoles (clic de souris, toux) : ignores.
            "min_speech_duration_ms": 250,
        },
    )

    paragraphes = []
    fin_precedente = None
    with open(out_path, "w", encoding="utf-8") as f:
        for seg in segments:
            texte = seg.text.strip()
            if not texte:
                continue

            nouveau = (fin_precedente is not None
                       and seg.start - fin_precedente > PAUSE_PARAGRAPHE)
            if nouveau or fin_precedente is None:
                f.write(("\n\n" if nouveau else "") + texte)
                paragraphes.append(texte)
            else:
                # Meme paragraphe : on recolle a la suite, sans retour a la
                # ligne au milieu d'une phrase.
                f.write(" " + texte)
                paragraphes[-1] += " " + texte

            fin_precedente = seg.end
            f.flush()                      # ecrit vraiment sur disque
            os.fsync(f.fileno())
            if progress:
                progress(seg.end, info.duration)

        if paragraphes:
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

    return "\n\n".join(paragraphes)
