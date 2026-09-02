"""Tests de la mise en forme et des reglages de transcription.

Le modele Whisper n'est jamais charge : il est remplace par un faux modele qui
renvoie des segments choisis a la main. Ces tests verifient donc ce qui nous
appartient (regroupement en paragraphes, vocabulaire souffle au modele), pas la
qualite du modele lui-meme."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import transcribe as module


class FauxModele:
    """Modele Whisper simule : memorise les options recues."""

    def __init__(self, segments):
        self.segments = segments
        self.options = None

    def transcribe(self, audio, **options):
        self.options = options
        info = SimpleNamespace(duration=self.segments[-1].end if self.segments else 0)
        return iter(self.segments), info


def segment(texte, debut, fin):
    return SimpleNamespace(text=texte, start=debut, end=fin)


@pytest.fixture
def sortie(tmp_path):
    return str(tmp_path / "transcription.txt")


def _transcrire(segments, sortie, **kwargs):
    faux = FauxModele(segments)
    with patch.object(module, "_get_model", return_value=faux):
        texte = module.transcribe("reunion.webm", sortie, **kwargs)
    return texte, faux


def test_les_phrases_proches_forment_un_seul_paragraphe(sortie):
    texte, _ = _transcrire([
        segment(" Bonjour a tous.", 0.0, 2.0),
        segment(" On commence par le budget.", 2.3, 5.0),
    ], sortie)

    assert texte == "Bonjour a tous. On commence par le budget."
    assert open(sortie, encoding="utf-8").read() == \
        "Bonjour a tous. On commence par le budget.\n"


def test_un_long_silence_ouvre_un_paragraphe(sortie):
    """Un blanc marque un changement de sujet ou de personne : le texte doit
    rester lisible, pas former un bloc unique."""
    texte, _ = _transcrire([
        segment(" Premier point.", 0.0, 2.0),
        segment(" Deuxieme point.", 30.0, 32.0),      # 28 s de silence
    ], sortie)

    assert texte == "Premier point.\n\nDeuxieme point."
    assert "\n\n" in open(sortie, encoding="utf-8").read()


def test_les_segments_vides_sont_ignores(sortie):
    texte, _ = _transcrire([
        segment("  ", 0.0, 1.0),
        segment(" Une phrase.", 1.0, 2.0),
    ], sortie)
    assert texte == "Une phrase."


def test_la_progression_suit_les_segments(sortie):
    avancement = []
    _transcrire([segment(" A.", 0.0, 5.0), segment(" B.", 5.0, 10.0)],
                sortie, progress=lambda s, d: avancement.append((s, d)))
    assert avancement == [(5.0, 10.0), (10.0, 10.0)]


def test_le_vocabulaire_de_la_reunion_est_souffle_au_modele(sortie):
    _, faux = _transcrire([segment(" Bonjour.", 0.0, 1.0)], sortie,
                          vocabulaire="Dupont, Kubernetes")
    assert faux.options["hotwords"] == "Dupont, Kubernetes"


def test_sans_vocabulaire_de_reunion_celui_de_la_config_sert(sortie):
    with patch.object(module.CONFIG, "vocabulaire", "RGPD"):
        _, faux = _transcrire([segment(" Bonjour.", 0.0, 1.0)], sortie)
    assert faux.options["hotwords"] == "RGPD"


def test_sans_aucun_vocabulaire_rien_n_est_impose(sortie):
    with patch.object(module.CONFIG, "vocabulaire", ""):
        _, faux = _transcrire([segment(" Bonjour.", 0.0, 1.0)], sortie)
    assert faux.options["hotwords"] is None


def test_les_reglages_qui_evitent_les_derapages_sont_actifs(sortie):
    """condition_on_previous_text=False empeche les boucles de repetition,
    le filtre VAD et no_speech_threshold evitent les phrases inventees sur
    du silence. Ces trois reglages sont la raison d'etre du reglage fin."""
    _, faux = _transcrire([segment(" Bonjour.", 0.0, 1.0)], sortie)
    assert faux.options["condition_on_previous_text"] is False
    assert faux.options["vad_filter"] is True
    assert faux.options["no_speech_threshold"] == 0.6
    assert faux.options["beam_size"] == module.CONFIG.beam_size
