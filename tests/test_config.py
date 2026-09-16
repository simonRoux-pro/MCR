"""Tests du chargement des reglages, notamment du fichier .env.

Ce fichier evite de reexporter le jeton a chaque terminal : s'il cesse d'etre
lu, la panne est silencieuse et ressemble a un probleme d'authentification."""
import os
from unittest.mock import patch

import config


def _ecrire_env(tmp_path, contenu):
    fichier = tmp_path / ".env"
    fichier.write_text(contenu, encoding="utf-8")
    return fichier


def test_le_fichier_env_fournit_les_variables(tmp_path):
    _ecrire_env(tmp_path, "GENIAL_TOKEN=jeton-du-fichier\n")
    with patch.object(config, "DOSSIER", str(tmp_path)):
        with patch.dict(os.environ, {}, clear=True):
            config.charger_env_local()
            assert os.environ["GENIAL_TOKEN"] == "jeton-du-fichier"


def test_l_environnement_l_emporte_sur_le_fichier(tmp_path):
    """Docker et le terminal posent des variables : elles doivent primer, sinon
    un vieux .env oublie sur la machine ecraserait le reglage voulu."""
    _ecrire_env(tmp_path, "GENIAL_TOKEN=jeton-du-fichier\n")
    with patch.object(config, "DOSSIER", str(tmp_path)):
        with patch.dict(os.environ, {"GENIAL_TOKEN": "jeton-du-terminal"}):
            config.charger_env_local()
            assert os.environ["GENIAL_TOKEN"] == "jeton-du-terminal"


def test_commentaires_lignes_vides_et_guillemets(tmp_path):
    _ecrire_env(tmp_path, """
# un commentaire
GENIAL_TOKEN="entre guillemets"

MEETING_MOTEUR=genial
ligne sans egal
""")
    with patch.object(config, "DOSSIER", str(tmp_path)):
        with patch.dict(os.environ, {}, clear=True):
            config.charger_env_local()
            assert os.environ["GENIAL_TOKEN"] == "entre guillemets"
            assert os.environ["MEETING_MOTEUR"] == "genial"


def test_l_absence_de_fichier_ne_fait_rien(tmp_path):
    with patch.object(config, "DOSSIER", str(tmp_path)):
        config.charger_env_local()          # ne doit pas lever


def test_les_reglages_de_deploiement_sont_surchargeables():
    """Changer d'adresse d'ecoute ou de moteur ne doit demander ni modification
    de config.py, ni reconstruction de l'image."""
    with patch.dict(os.environ, {"MEETING_HOST": "0.0.0.0",
                                 "MEETING_PORT": "9000",
                                 "MEETING_MOTEUR": "genial"}):
        assert config._reglage("MEETING_HOST", "127.0.0.1") == "0.0.0.0"
        assert int(config._reglage("MEETING_PORT", "8000")) == 9000
        assert config._reglage("MEETING_MOTEUR", "local") == "genial"

    assert config._reglage("MEETING_INEXISTANT", "defaut") == "defaut"
