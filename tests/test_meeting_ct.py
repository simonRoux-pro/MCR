"""Tests ne necessitant ni micro ni Ollama : decoupage map-reduce, gestion
d'erreur Ollama absent, validation du mode fichier, export .txt/.md."""
import pytest

from summarize import _chunk_text, summarize
from pipeline import process_from_file
from export import save_txt, save_md
from config import CONFIG


def test_chunk_text_decoupe_un_texte_long_sans_perte():
    lignes = [f"Ligne {i} : contenu de discussion factice." for i in range(500)]
    texte = "\n".join(lignes)

    chunks = _chunk_text(texte, max_chars=6000)

    assert len(chunks) > 1
    assert "\n".join(chunks) == texte          # aucune perte de contenu
    for c in chunks[:-1]:
        assert len(c) <= 6000 + 200            # chaque morceau reste proche de la limite


def test_chunk_text_texte_court_ne_produit_qu_un_seul_morceau():
    texte = "Une reunion courte.\nDeux phrases seulement."
    chunks = _chunk_text(texte, max_chars=6000)
    assert chunks == [texte]


def test_summarize_leve_une_erreur_claire_si_ollama_indisponible():
    ancien_host = CONFIG.ollama_host
    CONFIG.ollama_host = "http://localhost:19999"   # port sur lequel rien n'ecoute
    try:
        with pytest.raises(RuntimeError, match="Ollama"):
            summarize("Un petit texte de test.")
    finally:
        CONFIG.ollama_host = ancien_host


def test_process_from_file_fichier_introuvable():
    with pytest.raises(FileNotFoundError):
        process_from_file("/chemin/inexistant.wav")


def test_process_from_file_extension_non_supportee(tmp_path):
    f = tmp_path / "audio.ogg"
    f.write_bytes(b"\x00")
    with pytest.raises(ValueError, match="non supporte"):
        process_from_file(str(f))


def test_export_txt_et_md(tmp_path):
    rapport = "## Resume\nTest de compte-rendu."

    txt_path = tmp_path / "cr.txt"
    save_txt(str(txt_path), rapport)
    assert txt_path.read_text(encoding="utf-8") == rapport

    md_path = tmp_path / "cr.md"
    save_md(str(md_path), rapport)
    contenu_md = md_path.read_text(encoding="utf-8")
    assert contenu_md.startswith("# Compte-rendu de reunion")
    assert rapport in contenu_md
