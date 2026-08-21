"""Tests de l'envoi mail : messages d'erreur exploitables plutot que les
erreurs brutes de smtplib (ex. "run connect() first" quand rien n'est configure)."""
import smtplib
from unittest.mock import MagicMock, patch

import pytest

from config import CONFIG
from mailer import send_report


def test_smtp_non_configure_message_clair():
    """Sans SMTP configure, smtplib echouait sur un cryptique
    'run connect() first' : on veut un message qui dit quoi faire."""
    with pytest.raises(RuntimeError) as err:
        send_report("qui@exemple.fr", "Sujet", "Corps")
    message = str(err.value)
    assert "smtp_host" in message
    assert "config.py" in message
    assert ".txt" in message   # rappelle l'alternative sans configuration


def test_envoi_nominal(monkeypatch):
    monkeypatch.setattr(CONFIG, "smtp_host", "smtp.exemple.fr")
    monkeypatch.setattr(CONFIG, "smtp_user", "moi@exemple.fr")
    monkeypatch.setattr(CONFIG, "smtp_password", "secret")

    serveur = MagicMock()
    with patch("mailer.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = serveur
        send_report("qui@exemple.fr", "Sujet", "Corps")

    serveur.starttls.assert_called_once()
    serveur.login.assert_called_once_with("moi@exemple.fr", "secret")
    serveur.send_message.assert_called_once()


def test_identifiants_refuses_message_explicite(monkeypatch):
    monkeypatch.setattr(CONFIG, "smtp_host", "smtp.exemple.fr")
    monkeypatch.setattr(CONFIG, "smtp_user", "moi@exemple.fr")
    monkeypatch.setattr(CONFIG, "smtp_password", "secret")

    with patch("mailer.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value.login.side_effect = \
            smtplib.SMTPAuthenticationError(535, b"refuse")
        with pytest.raises(RuntimeError, match="mot de passe d'application"):
            send_report("qui@exemple.fr", "Sujet", "Corps")


def test_serveur_injoignable_message_explicite(monkeypatch):
    monkeypatch.setattr(CONFIG, "smtp_host", "smtp.exemple.fr")
    monkeypatch.setattr(CONFIG, "smtp_user", "moi@exemple.fr")
    monkeypatch.setattr(CONFIG, "smtp_password", "secret")

    with patch("mailer.smtplib.SMTP", side_effect=OSError("injoignable")):
        with pytest.raises(RuntimeError, match="Echec de l'envoi"):
            send_report("qui@exemple.fr", "Sujet", "Corps")
