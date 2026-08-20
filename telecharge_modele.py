"""Pre-telecharge le modele Whisper configure dans config.py.

Appele par setup.sh / setup.bat pour que le modele soit deja sur le disque
AVANT la premiere vraie reunion : le telechargement (~500 Mo pour `small`)
n'a rien a faire au moment ou on attend son compte-rendu.

Peut aussi etre lance a la main pour re-tenter un telechargement qui a
echoue, sans passer par l'application :

    python telecharge_modele.py
"""
import netfix  # noqa: F401  -- contournements reseau, DOIT rester le premier import (voir netfix.py)

import sys

from faster_whisper import download_model
from config import CONFIG


def main():
    print(
        f"Telechargement du modele Whisper '{CONFIG.whisper_model}' "
        "(plusieurs centaines de Mo, une seule fois ; la progression s'affiche ci-dessous)..."
    )
    try:
        chemin = download_model(CONFIG.whisper_model)
    except Exception as e:
        print(f"\nEchec du telechargement : {e}")
        print("Verifie ta connexion puis relance : python telecharge_modele.py")
        return 1
    print(f"\nModele pret : {chemin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
