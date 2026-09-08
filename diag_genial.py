"""Verifie la liaison avec GenIAL, avant de brancher l'application dessus.

Trois inconnues quand on arrive sur un reseau ferme : le certificat est-il
verifiable, le jeton est-il accepte, et quel format audio le service avale.
Ce script les leve en une fois, avec un fichier son minuscule genere ici meme
(une seconde de silence, aucune donnee reelle envoyee) :

    export GENIAL_TOKEN="<ton jeton>"
    python diag_genial.py

Il affiche la reponse brute du service : c'est elle qui dit ce qui coince.
"""
import netfix  # noqa: F401  -- contournements reseau, DOIT rester le premier import (voir netfix.py)

import os
import sys
import tempfile
import wave

import requests

from config import CONFIG
from genial import TIMEOUT_CONNEXION, _verification_tls


def fichier_de_test() -> str:
    """Une seconde de silence en WAV 16 kHz mono, ecrite dans un fichier
    temporaire. Format le plus universellement accepte : si GenIAL refuse
    meme celui-la, le probleme n'est pas le format."""
    chemin = os.path.join(tempfile.mkdtemp(prefix="diag-genial-"), "test.wav")
    with wave.open(chemin, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b"\x00\x00" * 16000)
    return chemin


def main() -> int:
    print("== Diagnostic GenIAL ==")
    print(f"URL        : {CONFIG.genial_url}")
    print(f"Langue     : {CONFIG.genial_langue}")
    print(f"En-tete    : {CONFIG.genial_entete_token}: "
          f"{CONFIG.genial_prefixe_token}<jeton>")
    verification = _verification_tls()
    print(f"TLS        : {'bundle ' + str(verification) if isinstance(verification, str) else ('verifie' if verification else 'NON VERIFIE (depannage)')}")

    jeton = os.environ.get(CONFIG.genial_variable_token, "").strip()
    if not jeton:
        print(f"\nJeton absent : definis la variable {CONFIG.genial_variable_token}.")
        print(f'  Linux   : export {CONFIG.genial_variable_token}="<ton jeton>"')
        print(f'  Windows : set {CONFIG.genial_variable_token}=<ton jeton>')
        return 1
    print(f"Jeton      : present ({len(jeton)} caracteres)")

    chemin = fichier_de_test()
    print(f"\nEnvoi d'un fichier de test ({os.path.getsize(chemin)} octets)...")
    try:
        with open(chemin, "rb") as f:
            reponse = requests.post(
                CONFIG.genial_url,
                headers={CONFIG.genial_entete_token:
                         CONFIG.genial_prefixe_token + jeton},
                files={"file": ("test.wav", f, "audio/wav")},
                data={"language": CONFIG.genial_langue},
                timeout=(TIMEOUT_CONNEXION, 120),
                verify=verification,
            )
    except requests.exceptions.SSLError as e:
        print(f"\nECHEC TLS : {e}")
        print("Renseigne le bundle de l'autorite interne dans config.py "
              "(genial_ca), ou mets genial_verifier_tls a False pour depanner.")
        return 1
    except requests.exceptions.RequestException as e:
        print(f"\nECHEC RESEAU : {type(e).__name__}: {e}")
        return 1

    print(f"HTTP {reponse.status_code}")
    print("Reponse brute :")
    print((reponse.text or "")[:1000])

    if reponse.status_code != 200:
        print("\nLa liaison marche mais le service refuse la requete. "
              "Le message ci-dessus dit pourquoi (jeton, en-tete, format).")
        return 1

    try:
        texte = reponse.json()["result"]
    except Exception:
        print("\nLe champ « result » est absent : l'API ne repond pas la forme "
              "attendue. Colle la reponse ci-dessus, le code s'adaptera.")
        return 1

    print(f"\nSUCCES : GenIAL a repondu (result = {texte!r}).")
    print("Un silence peut tres bien donner un texte vide : c'est normal.")
    print("Tu peux passer moteur = \"genial\" dans config.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
