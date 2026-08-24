"""Tests du mode "transcription seule" : arret de l'enregistrement suivi de
la seule transcription, sans appel au LLM (donc sans besoin d'Ollama)."""
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import main


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fenetre(app):
    return main.MainWindow()


def _worker_execute(generer_cr):
    """Execute run() du Worker avec transcription simulee, et renvoie
    (worker, summarize_simule) pour verifier les signaux emis."""
    worker = main.Worker("/tmp/reunion.wav", generer_cr=generer_cr)
    for signal in ("transcribed", "transcript_only_done", "done",
                   "failed", "summary_failed", "transcript_progress"):
        setattr(worker, signal, MagicMock())

    with patch.object(main, "transcribe", return_value="texte transcrit"), \
         patch.object(main, "summarize", return_value="## Resume\nCR") as resume:
        worker.run()
    return worker, resume


def test_transcription_seule_n_appelle_jamais_le_llm():
    worker, resume = _worker_execute(generer_cr=False)

    resume.assert_not_called()                      # aucun appel a Ollama
    worker.transcribed.emit.assert_called_once_with("texte transcrit")
    worker.transcript_only_done.emit.assert_called_once_with("texte transcrit")
    worker.done.emit.assert_not_called()
    worker.summary_failed.emit.assert_not_called()


def test_mode_normal_appelle_bien_le_llm():
    worker, resume = _worker_execute(generer_cr=True)

    resume.assert_called_once()
    worker.done.emit.assert_called_once_with("texte transcrit", "## Resume\nCR")
    worker.transcript_only_done.emit.assert_not_called()


def test_interface_apres_transcription_seule(fenetre):
    """La transcription est exportable, mais rien qui suppose un CR
    (envoi mail, exports du CR) ne doit etre propose."""
    fenetre.on_transcript_only_done("texte transcrit")

    assert fenetre.txt_transcript.toPlainText() == "texte transcrit"
    assert fenetre.btn_export_transcript.isEnabled()
    assert not fenetre.btn_send.isEnabled()
    assert not fenetre.btn_export_txt.isEnabled()
    assert not fenetre.btn_export_md.isEnabled()
    # Boutons d'enregistrement de nouveau disponibles
    assert fenetre.btn_rec.isEnabled()
    assert not fenetre.btn_stop_texte.isEnabled()


def test_les_deux_boutons_d_arret_sont_actifs_pendant_l_enregistrement(fenetre):
    with patch.object(fenetre.recorder, "start"):
        fenetre.recorder.system_audio_active = True
        fenetre.start_rec()

    assert fenetre.btn_stop.isEnabled()
    assert fenetre.btn_stop_texte.isEnabled()
    assert not fenetre.btn_rec.isEnabled()


def test_le_bouton_transcription_seule_lance_le_worker_sans_cr(fenetre):
    with patch.object(main, "Worker") as faux_worker:
        fenetre.stop_rec_transcription_seule()

    assert faux_worker.call_args.kwargs["generer_cr"] is False


def test_le_bouton_normal_lance_le_worker_avec_cr(fenetre):
    with patch.object(main, "Worker") as faux_worker:
        fenetre.stop_rec()

    assert faux_worker.call_args.kwargs["generer_cr"] is True


def test_export_de_la_transcription(fenetre, tmp_path):
    fenetre.txt_transcript.setPlainText("texte a reprendre ailleurs")
    cible = tmp_path / "transcription.txt"

    with patch.object(main.QFileDialog, "getSaveFileName", return_value=(str(cible), "")):
        fenetre.export_transcription()

    assert cible.read_text(encoding="utf-8") == "texte a reprendre ailleurs"
