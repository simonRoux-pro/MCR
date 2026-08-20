"""Verifie les contournements reseau de netfix.py : IPv4 force et
telechargeur hf_xet desactive (voir netfix.py pour le pourquoi)."""
import os
import socket

import netfix  # noqa: F401  -- l'import applique les contournements


def test_getaddrinfo_ne_renvoie_que_de_l_ipv4():
    resultats = socket.getaddrinfo("localhost", 80)
    familles = {r[0] for r in resultats}
    assert familles == {socket.AF_INET}


def test_variables_environnement_hugging_face():
    assert os.environ["HF_HUB_DISABLE_XET"] == "1"
    assert os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] == "1"


def test_huggingface_hub_voit_bien_xet_desactive():
    # C'est le point critique : le telechargement doit passer par le HTTP
    # classique (sockets Python, IPv4 force) et non par le binaire hf_xet
    # qui fait ses propres connexions reseau. Les constantes etant figees a
    # l'import de huggingface_hub, ce test verifie aussi que netfix a ete
    # importe suffisamment tot.
    from huggingface_hub import constants
    assert constants.HF_HUB_DISABLE_XET is True
