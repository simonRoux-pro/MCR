"""Tests du moteur GenIAL. Aucun appel reseau : requests.post est simule.

Ces tests verifient ce qui nous appartient — la requete envoyee, la lecture de
la reponse, et surtout la clarte des messages d'erreur, puisque c'est tout ce
dont on dispose pour diagnostiquer depuis un reseau ferme."""
import os
from unittest.mock import patch

import pytest
import requests

import genial
import transcribe


class FausseReponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text or (str(json_data) if json_data else "")

    def json(self):
        if self._json is None:
            raise ValueError("pas du JSON")
        return self._json


@pytest.fixture
def audio(tmp_path):
    chemin = tmp_path / "reunion.webm"
    chemin.write_bytes(b"des octets audio")
    return str(chemin)


@pytest.fixture
def sortie(tmp_path):
    return str(tmp_path / "transcription.txt")


@pytest.fixture(autouse=True)
def jeton():
    with patch.dict(os.environ, {"GENIAL_TOKEN": "jeton-de-test"}):
        yield


def _envoyer(audio, sortie, reponse, **kwargs):
    with patch.object(genial.requests, "post", return_value=reponse) as post:
        texte = genial.transcrire_genial(audio, sortie, **kwargs)
    return texte, post.call_args


def test_la_transcription_est_ecrite_et_renvoyee(audio, sortie):
    texte, _ = _envoyer(audio, sortie,
                        FausseReponse(json_data={"result": "  bonjour la reunion  "}))
    assert texte == "bonjour la reunion"
    assert open(sortie, encoding="utf-8").read() == "bonjour la reunion\n"


def test_la_requete_porte_le_jeton_la_langue_et_le_bon_type(audio, sortie):
    _, appel = _envoyer(audio, sortie, FausseReponse(json_data={"result": "ok"}))

    assert appel.args[0] == genial.CONFIG.genial_url
    assert appel.kwargs["headers"]["Authorization"] == "Bearer jeton-de-test"
    assert appel.kwargs["data"]["language"] == genial.CONFIG.genial_langue
    nom, _flux, type_contenu = appel.kwargs["files"]["file"]
    assert nom == "reunion.webm"
    assert type_contenu == "audio/webm"      # ce que produit le navigateur


def test_le_jeton_absent_donne_une_consigne_claire(audio, sortie):
    with patch.dict(os.environ, {"GENIAL_TOKEN": ""}):
        with pytest.raises(RuntimeError, match="GENIAL_TOKEN"):
            genial.transcrire_genial(audio, sortie)


def test_un_jeton_refuse_est_annonce_comme_tel(audio, sortie):
    with patch.object(genial.requests, "post",
                      return_value=FausseReponse(401, text="invalid token")):
        with pytest.raises(RuntimeError, match="refuse le jeton"):
            genial.transcrire_genial(audio, sortie)


def test_une_erreur_du_service_remonte_son_message(audio, sortie):
    """Le texte brut de la reponse est conserve : sur un reseau ferme, c'est la
    seule piste pour comprendre (format audio refuse, quota, ...)."""
    with patch.object(genial.requests, "post",
                      return_value=FausseReponse(415, text="unsupported media type")):
        with pytest.raises(RuntimeError, match="unsupported media type"):
            genial.transcrire_genial(audio, sortie)


def test_un_certificat_non_verifiable_explique_la_marche_a_suivre(audio, sortie):
    with patch.object(genial.requests, "post",
                      side_effect=requests.exceptions.SSLError("certificat inconnu")):
        with pytest.raises(RuntimeError, match="genial_ca"):
            genial.transcrire_genial(audio, sortie)


def test_un_delai_depasse_renvoie_vers_le_reglage(audio, sortie):
    with patch.object(genial.requests, "post",
                      side_effect=requests.exceptions.Timeout()):
        with pytest.raises(RuntimeError, match="genial_timeout"):
            genial.transcrire_genial(audio, sortie)


def test_une_reponse_inattendue_est_signalee(audio, sortie):
    with patch.object(genial.requests, "post",
                      return_value=FausseReponse(200, text="<html>portail</html>")):
        with pytest.raises(RuntimeError, match="result"):
            genial.transcrire_genial(audio, sortie)


def test_le_serveur_route_vers_genial_selon_la_config(audio, sortie):
    """Le serveur appelle toujours transcribe() : c'est config.moteur qui
    decide du moteur, sans que le reste du code ait a le savoir."""
    with patch.object(transcribe.CONFIG, "moteur", "genial"):
        with patch.object(genial.requests, "post",
                          return_value=FausseReponse(json_data={"result": "via genial"})):
            assert transcribe.transcribe(audio, sortie) == "via genial"


def test_un_moteur_inconnu_est_refuse_avec_les_valeurs_attendues(audio, sortie):
    with patch.object(transcribe.CONFIG, "moteur", "chatgpt"):
        with pytest.raises(RuntimeError, match="local.*genial"):
            transcribe.transcribe(audio, sortie)
