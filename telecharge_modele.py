"""Pre-telecharge le modele Whisper configure dans config.py, avec un
diagnostic reseau complet : ce script ne peut PAS rester bloque en silence.

- Avant le telechargement, il affiche le proxy systeme vu par Python et teste
  la connexion aux serveurs concernes (avec timeout : reponse ou echec en
  quelques secondes, jamais d'attente infinie).
- Pendant le telechargement, chaque connexion HTTP est tracee, et si rien ne
  bouge pendant 60 s, la pile d'execution complete est imprimee : on voit la
  ligne exacte qui bloque.

Appele par setup.sh / setup.bat, et relançable a la main :

    python telecharge_modele.py
"""
import netfix  # noqa: F401  -- contournements reseau, DOIT rester le premier import (voir netfix.py)

import faulthandler
import logging
import sys
import urllib.request

# Si ca bloque, imprime la pile de tous les threads toutes les 60 s :
# fini les blocages muets, on voit exactement ou ca coince.
faulthandler.dump_traceback_later(60, repeat=True, exit=False)

# Trace chaque requete HTTP (connexions, redirections, codes de reponse).
logging.basicConfig(format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
logging.getLogger("urllib3").setLevel(logging.DEBUG)
logging.getLogger("huggingface_hub").setLevel(logging.DEBUG)

import requests
import huggingface_hub
from faster_whisper import download_model
from config import CONFIG

# Les fichiers de modeles ne sont pas servis par huggingface.co lui-meme mais
# par des domaines de stockage distincts : un pare-feu/proxy d'entreprise peut
# autoriser l'un et bloquer les autres.
SERVEURS_A_TESTER = (
    "https://huggingface.co",
    "https://cdn-lfs.hf.co",
    "https://cas-bridge.xethub.hf.co",
)


def diagnostic_reseau():
    print("== Diagnostic reseau ==")
    print(f"Python {sys.version.split()[0]} ; huggingface_hub {huggingface_hub.__version__}")
    proxies = urllib.request.getproxies()
    print(f"Proxy systeme vu par Python : {proxies if proxies else 'aucun'}")
    for url in SERVEURS_A_TESTER:
        try:
            r = requests.get(url, timeout=10)
            print(f"  {url} -> joignable (HTTP {r.status_code})")
        except Exception as e:
            print(f"  {url} -> ECHEC : {type(e).__name__}: {e}")
    print()


def main():
    diagnostic_reseau()
    print(
        f"Telechargement du modele Whisper '{CONFIG.whisper_model}' "
        "(plusieurs centaines de Mo, une seule fois)..."
    )
    try:
        chemin = download_model(CONFIG.whisper_model)
    except Exception as e:
        print(f"\nEchec du telechargement : {type(e).__name__}: {e}")
        print("Verifie ta connexion puis relance : python telecharge_modele.py")
        return 1
    finally:
        faulthandler.cancel_dump_traceback_later()
    print(f"\nModele pret : {chemin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
