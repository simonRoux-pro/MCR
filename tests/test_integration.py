"""Tests du contrat d'integration : une application tierce (Appian ou autre)
ouvre l'outil avec sa propre reference, puis vient lire le resultat par cette
meme reference. Ce format est un contrat : ces tests le verrouillent."""
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import serveur
from tests.test_serveur import _transcription_simulee, _attendre_les_segments


@pytest.fixture
def client():
    serveur.sessions.clear()
    return TestClient(serveur.app)


def _reunion_transcrite(client, reference, texte="le budget a ete valide"):
    identifiant = client.post("/api/sessions",
                              json={"reference": reference}).json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"audio")
    with _transcription_simulee(texte):
        client.post(f"/api/sessions/{identifiant}/terminer")
        _attendre_les_segments()
    return identifiant


def test_la_reunion_se_retrouve_par_la_reference_de_l_appelant(client):
    """L'appelant n'a jamais besoin de connaitre l'identifiant interne : il
    ouvre l'outil avec sa reference, il relit avec la meme."""
    _reunion_transcrite(client, "DOSSIER-2026-0412")

    reponse = client.get("/api/reunions/DOSSIER-2026-0412")
    assert reponse.status_code == 200
    donnees = reponse.json()
    assert donnees["ref"] == "DOSSIER-2026-0412"
    assert donnees["etat"] == "termine"
    assert donnees["transcription"] == "le budget a ete valide"
    assert donnees["debut"]          # horodatage present


def test_une_reference_inconnue_donne_404(client):
    assert client.get("/api/reunions/JAMAIS-VU").status_code == 404


def test_le_dernier_enregistrement_fait_foi(client):
    """Une reunion peut etre reenregistree apres un faux depart."""
    _reunion_transcrite(client, "DOSSIER-1", "premier essai rate")
    _reunion_transcrite(client, "DOSSIER-1", "le bon enregistrement")

    donnees = client.get("/api/reunions/DOSSIER-1").json()
    assert donnees["transcription"] == "le bon enregistrement"


def test_la_reunion_est_consultable_avant_la_fin(client):
    """L'appelant peut interroger pendant la reunion : il lit l'etat et
    decide d'attendre, plutot que de tomber sur une erreur."""
    client.post("/api/sessions", json={"reference": "EN-COURS"})
    donnees = client.get("/api/reunions/EN-COURS").json()
    assert donnees["etat"] == "enregistrement"
    assert donnees["transcription"] == ""


def test_le_compte_rendu_accompagne_la_transcription(client):
    _reunion_transcrite(client, "DOSSIER-CR")
    identifiant = [s.identifiant for s in serveur.sessions.values()
                   if s.reference == "DOSSIER-CR"][0]
    with patch("genial.rediger_cr", return_value="# Compte rendu\n\nValide."):
        client.post(f"/api/sessions/{identifiant}/compte-rendu")
        _attendre_les_segments()

    donnees = client.get("/api/reunions/DOSSIER-CR").json()
    assert donnees["compteRenduEtat"] == "pret"
    assert donnees["compteRendu"].startswith("# Compte rendu")


# ----------------------------------------------------------------------- #
# Cle d'API
# ----------------------------------------------------------------------- #

def test_sans_cle_configuree_la_route_reste_ouverte(client):
    """Pour travailler en local sans ceremonie."""
    _reunion_transcrite(client, "LOCAL")
    with patch.dict(os.environ, {}, clear=True):
        assert client.get("/api/reunions/LOCAL").status_code == 200


def test_une_cle_configuree_est_exigee(client):
    _reunion_transcrite(client, "PROTEGE")
    with patch.dict(os.environ, {"MEETING_CLE_API": "cle-secrete"}):
        assert client.get("/api/reunions/PROTEGE").status_code == 401
        assert client.get("/api/reunions/PROTEGE",
                          headers={"X-Cle-Api": "mauvaise"}).status_code == 401
        assert client.get("/api/reunions/PROTEGE",
                          headers={"X-Cle-Api": "cle-secrete"}).status_code == 200


def test_la_reference_est_memorisee_a_la_creation(client):
    session = client.post("/api/sessions", json={"reference": "REF-42"}).json()
    assert serveur.sessions[session["id"]].reference == "REF-42"


def test_une_session_sans_reference_reste_possible(client):
    """L'outil s'utilise aussi seul, sans application appelante."""
    session = client.post("/api/sessions").json()
    assert serveur.sessions[session["id"]].reference == ""
