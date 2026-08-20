"""Tests du telechargeur avec reprise (telecharge_modele.py) : c'est la piece
qui rend l'installation possible sur un reseau instable, elle doit etre
verifiee sans dependre du reseau (requests est simule)."""
from unittest.mock import MagicMock

import pytest
import requests

import telecharge_modele as tm


CONTENU = b"0123456789" * 100   # 1000 octets de "modele"


class FausseReponse:
    """Simule une reponse requests en streaming, avec coupure optionnelle."""

    def __init__(self, donnees, status=200, total=None, debut=0, couper_apres=None):
        self.status_code = status
        self._donnees = donnees
        self._couper_apres = couper_apres
        self.headers = {}
        if status == 206:
            fin = debut + len(donnees) - 1
            self.headers["Content-Range"] = f"bytes {debut}-{fin}/{total}"
        else:
            self.headers["Content-Length"] = str(len(donnees))

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        envoye = 0
        for i in range(0, len(self._donnees), chunk_size):
            bloc = self._donnees[i:i + chunk_size]
            yield bloc
            envoye += len(bloc)
            if self._couper_apres is not None and envoye >= self._couper_apres:
                raise requests.exceptions.ConnectionError("coupure simulee")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_telechargement_complet_sans_coupure(tmp_path, monkeypatch):
    monkeypatch.setattr(tm.time, "sleep", lambda s: None)
    session = MagicMock()
    session.get.return_value = FausseReponse(CONTENU)

    dest = tmp_path / "model.bin"
    tm.telecharger_avec_reprise("http://x/model.bin", str(dest), session=session)

    assert dest.read_bytes() == CONTENU
    assert not (tmp_path / "model.bin.part").exists()


def test_reprise_apres_coupure_reprend_a_l_octet_exact(tmp_path, monkeypatch):
    monkeypatch.setattr(tm.time, "sleep", lambda s: None)
    monkeypatch.setattr(tm, "TAILLE_BLOC", 100)

    session = MagicMock()
    appels = []

    def get(url, headers=None, stream=True, timeout=None):
        appels.append(headers or {})
        if len(appels) == 1:
            # Premiere tentative : coupure apres 300 octets
            return FausseReponse(CONTENU, couper_apres=300)
        # Reprise : le serveur sert la suite (206) a partir de l'octet demande
        debut = int(headers["Range"].split("=")[1].rstrip("-"))
        return FausseReponse(CONTENU[debut:], status=206,
                             total=len(CONTENU), debut=debut)

    session.get.side_effect = get

    dest = tmp_path / "model.bin"
    tm.telecharger_avec_reprise("http://x/model.bin", str(dest), session=session)

    assert dest.read_bytes() == CONTENU          # aucun octet perdu ni duplique
    assert appels[1] == {"Range": "bytes=300-"}  # reprise a l'octet exact


def test_serveur_sans_reprise_repart_de_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(tm.time, "sleep", lambda s: None)
    monkeypatch.setattr(tm, "TAILLE_BLOC", 100)

    session = MagicMock()
    reponses = iter([
        FausseReponse(CONTENU, couper_apres=300),
        FausseReponse(CONTENU),   # 200 malgre le Range : repartir de zero
    ])
    session.get.side_effect = lambda *a, **k: next(reponses)

    dest = tmp_path / "model.bin"
    tm.telecharger_avec_reprise("http://x/model.bin", str(dest), session=session)

    assert dest.read_bytes() == CONTENU


def test_abandon_apres_le_maximum_de_tentatives(tmp_path, monkeypatch):
    monkeypatch.setattr(tm.time, "sleep", lambda s: None)
    monkeypatch.setattr(tm, "MAX_TENTATIVES", 3)

    session = MagicMock()
    session.get.side_effect = requests.exceptions.ConnectionError("reseau mort")

    with pytest.raises(RuntimeError, match="3 tentatives"):
        tm.telecharger_avec_reprise("http://x/model.bin",
                                    str(tmp_path / "model.bin"), session=session)


def test_filtrage_des_fichiers_du_depot(monkeypatch):
    reponse = MagicMock()
    reponse.status_code = 200
    reponse.raise_for_status = lambda: None
    reponse.json = lambda: {"siblings": [
        {"rfilename": "model.bin"},
        {"rfilename": "config.json"},
        {"rfilename": "vocabulary.txt"},
        {"rfilename": "README.md"},          # inutile, doit etre exclu
        {"rfilename": ".gitattributes"},     # idem
    ]}
    monkeypatch.setattr(tm.requests, "get", lambda *a, **k: reponse)

    fichiers = tm.lister_fichiers("Systran/faster-whisper-small")
    assert sorted(fichiers) == ["config.json", "model.bin", "vocabulary.txt"]
