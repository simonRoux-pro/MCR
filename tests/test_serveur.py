"""Tests de l'API du serveur de transcription. La transcription elle-meme est
simulee : ces tests verifient le parcours complet (session, envoi de morceaux
au fil de l'eau, suivi, telechargement, effacement) sans modele Whisper."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import serveur


@pytest.fixture
def client():
    serveur.sessions.clear()
    return TestClient(serveur.app)


def _transcription_simulee(texte="texte transcrit"):
    """Remplace transcribe() : ecrit le fichier attendu et renvoie le texte."""
    def faux_transcribe(audio, sortie, progress=None):
        if progress:
            progress(5.0, 10.0)
        with open(sortie, "w", encoding="utf-8") as f:
            f.write(texte)
        return texte
    return patch.object(serveur, "transcribe", side_effect=faux_transcribe)


def test_parcours_complet(client):
    session = client.post("/api/sessions").json()
    identifiant = session["id"]
    assert session["etat"] == "enregistrement"

    # Morceaux envoyes au fil de l'eau, comme le fait le navigateur
    for morceau in (b"aaaa", b"bbbbbb"):
        reponse = client.post(f"/api/sessions/{identifiant}/morceau", content=morceau)
        assert reponse.status_code == 200
    assert client.get(f"/api/sessions/{identifiant}").json()["octetsRecus"] == 10

    with _transcription_simulee("bonjour la reunion"):
        client.post(f"/api/sessions/{identifiant}/terminer")
        serveur.executeur.shutdown(wait=True)   # attend la fin de la transcription
        serveur.executeur = type(serveur.executeur)(max_workers=1)

    etat = client.get(f"/api/sessions/{identifiant}").json()
    assert etat["etat"] == "termine"
    assert etat["texte"] == "bonjour la reunion"
    assert etat["progression"] == 100

    fichier = client.get(f"/api/sessions/{identifiant}/transcription.txt")
    assert fichier.status_code == 200
    assert fichier.text == "bonjour la reunion"


def test_les_morceaux_sont_ajoutes_au_fil_de_l_eau(client):
    """Rien ne doit s'accumuler en memoire : chaque morceau est ecrit dans le
    fichier des sa reception (indispensable pour une reunion de 2 h)."""
    identifiant = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"debut-")
    session = serveur.sessions[identifiant]
    assert session.audio.read_bytes() == b"debut-"     # deja sur disque

    client.post(f"/api/sessions/{identifiant}/morceau", content=b"suite")
    assert session.audio.read_bytes() == b"debut-suite"


def test_terminer_sans_audio_donne_une_erreur_claire(client):
    identifiant = client.post("/api/sessions").json()["id"]
    etat = client.post(f"/api/sessions/{identifiant}/terminer").json()
    assert etat["etat"] == "echec"
    assert "micro" in etat["erreur"]


def test_echec_de_transcription_remonte_le_message(client):
    identifiant = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"audio")

    with patch.object(serveur, "transcribe", side_effect=RuntimeError("modele absent")):
        client.post(f"/api/sessions/{identifiant}/terminer")
        serveur.executeur.shutdown(wait=True)
        serveur.executeur = type(serveur.executeur)(max_workers=1)

    etat = client.get(f"/api/sessions/{identifiant}").json()
    assert etat["etat"] == "echec"
    assert etat["erreur"] == "modele absent"


def test_session_inconnue(client):
    assert client.get("/api/sessions/inexistante").status_code == 404


def test_morceau_refuse_apres_la_fin(client):
    identifiant = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"audio")

    with _transcription_simulee():
        client.post(f"/api/sessions/{identifiant}/terminer")
        serveur.executeur.shutdown(wait=True)
        serveur.executeur = type(serveur.executeur)(max_workers=1)

    reponse = client.post(f"/api/sessions/{identifiant}/morceau", content=b"encore")
    assert reponse.status_code == 409


def test_effacement_supprime_les_donnees_du_serveur(client):
    identifiant = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"audio")
    dossier = serveur.sessions[identifiant].dossier

    assert client.delete(f"/api/sessions/{identifiant}").json()["supprime"] is True
    assert not dossier.exists()                       # audio efface du disque
    assert identifiant not in serveur.sessions
    assert client.get(f"/api/sessions/{identifiant}").status_code == 404


def test_la_page_est_servie(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Transcription de reunion" in page.text
    assert client.get("/static/app.js").status_code == 200


def test_telechargement_de_l_audio_recu(client):
    """L'audio brut doit etre recuperable : c'est ce qui permet de verifier
    par l'ecoute si le son de l'ordinateur a bien ete enregistre."""
    identifiant = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"donnees-audio")

    reponse = client.get(f"/api/sessions/{identifiant}/audio.webm")
    assert reponse.status_code == 200
    assert reponse.content == b"donnees-audio"
    assert reponse.headers["content-type"] == "audio/webm"


def test_audio_absent_donne_404(client):
    identifiant = client.post("/api/sessions").json()["id"]
    assert client.get(f"/api/sessions/{identifiant}/audio.webm").status_code == 404
