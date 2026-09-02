"""Telecharge le modele Whisper avec REPRISE automatique sur coupure.

Pourquoi un telechargeur maison : sur certains reseaux, les gros transferts
"calent" en cours de route (la connexion reste ouverte mais plus aucune
donnee n'arrive). Le telechargeur de huggingface_hub attend alors
indefiniment, sans timeout ni message (constate en conditions reelles :
pile bloquee dans ssl.read). Ici :

- chaque lecture a un timeout de 30 s : un reseau qui cale est detecte en
  30 s maximum, jamais de blocage silencieux ;
- la reprise repart de l'octet exact ou ca s'est arrete (en-tete HTTP
  Range) : chaque tentative conserve ce qui est deja recu, meme une
  connexion tres instable finit par aboutir ;
- la progression s'affiche en continu (Mo recus / total).

Appele par setup.sh / setup.bat, et relançable a la main :

    python telecharge_modele.py
"""
import netfix  # noqa: F401  -- contournements reseau, DOIT rester le premier import (voir netfix.py)

import fnmatch
import os
import sys
import time
import urllib.request

import requests

from config import CONFIG, chemin_modele_whisper

# Correspondance nom court -> depot Hugging Face (voir faster_whisper/utils.py)
DEPOTS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    # Turbo : qualite proche de large-v3 pour un decodeur bien plus leger,
    # c'est le modele par defaut du projet (voir config.py).
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3": "Systran/faster-whisper-large-v3",
}

# Fichiers necessaires a faster-whisper (memes motifs que faster_whisper.utils)
MOTIFS_FICHIERS = ["config.json", "preprocessor_config.json", "model.bin",
                   "tokenizer.json", "vocabulary.*"]

TIMEOUT_CONNEXION = 15   # secondes pour etablir la connexion
TIMEOUT_LECTURE = 30     # secondes sans recevoir de donnees avant reprise
MAX_TENTATIVES = 60      # par fichier ; chaque tentative conserve l'acquis
TAILLE_BLOC = 1024 * 1024          # lecture par blocs de 1 Mo
AFFICHAGE_TOUS_LES = 10 * 1024 * 1024  # une ligne de progression tous les 10 Mo


def diagnostic_reseau():
    print("== Diagnostic reseau ==")
    proxies = urllib.request.getproxies()
    print(f"Proxy systeme vu par Python : {proxies if proxies else 'aucun'}")
    try:
        r = requests.get("https://huggingface.co", timeout=10)
        print(f"huggingface.co : joignable (HTTP {r.status_code})\n")
        return True
    except Exception as e:
        print(f"huggingface.co : INJOIGNABLE ({type(e).__name__}: {e})")
        print("Verifie ta connexion puis relance ce script.\n")
        return False


def lister_fichiers(repo: str) -> list:
    """Interroge l'API Hugging Face pour la liste des fichiers du depot,
    filtree sur ceux dont faster-whisper a besoin."""
    r = requests.get(f"https://huggingface.co/api/models/{repo}",
                     timeout=(TIMEOUT_CONNEXION, TIMEOUT_LECTURE))
    r.raise_for_status()
    tous = [s["rfilename"] for s in r.json().get("siblings", [])]
    return [f for f in tous
            if any(fnmatch.fnmatch(f, motif) for motif in MOTIFS_FICHIERS)]


def telecharger_avec_reprise(url: str, destination: str, session=None) -> None:
    """Telecharge `url` vers `destination`, en reprenant la ou ca s'est
    arrete a chaque coupure ou blocage reseau (jamais de retour a zero)."""
    http = session or requests
    temporaire = destination + ".part"
    nom = os.path.basename(destination)

    for tentative in range(1, MAX_TENTATIVES + 1):
        recu = os.path.getsize(temporaire) if os.path.exists(temporaire) else 0
        entetes = {"Range": f"bytes={recu}-"} if recu else {}
        try:
            with http.get(url, headers=entetes, stream=True,
                          timeout=(TIMEOUT_CONNEXION, TIMEOUT_LECTURE)) as r:
                if recu and r.status_code == 200:
                    # Le serveur ignore la reprise : on repart de zero
                    recu = 0
                elif recu and r.status_code == 416:
                    # Plage invalide : le fichier est en fait deja complet
                    break
                else:
                    r.raise_for_status()

                if r.status_code == 206:
                    # "bytes debut-fin/total"
                    total = int(r.headers["Content-Range"].split("/")[-1])
                else:
                    total = int(r.headers.get("Content-Length", 0))

                mode = "ab" if recu else "wb"
                prochain_affichage = recu + AFFICHAGE_TOUS_LES
                with open(temporaire, mode) as f:
                    for bloc in r.iter_content(chunk_size=TAILLE_BLOC):
                        f.write(bloc)
                        recu += len(bloc)
                        if recu >= prochain_affichage or recu == total:
                            pct = f" ({recu * 100 // total}%)" if total else ""
                            print(f"  {nom} : {recu // (1024 * 1024)} Mo"
                                  f" / {total // (1024 * 1024)} Mo{pct}", flush=True)
                            prochain_affichage = recu + AFFICHAGE_TOUS_LES

            if total and recu < total:
                raise IOError(f"transfert incomplet ({recu}/{total} octets)")
            break   # fichier complet

        except (requests.exceptions.RequestException, IOError) as e:
            print(f"  {nom} : coupure a {recu // (1024 * 1024)} Mo"
                  f" ({type(e).__name__}), reprise dans 3 s"
                  f" [tentative {tentative}/{MAX_TENTATIVES}]...", flush=True)
            time.sleep(3)
    else:
        raise RuntimeError(
            f"Impossible de telecharger {nom} apres {MAX_TENTATIVES} tentatives. "
            "Relance ce script : il reprendra ou il s'est arrete."
        )

    os.replace(temporaire, destination)


def main():
    if not diagnostic_reseau():
        return 1

    repo = DEPOTS.get(CONFIG.whisper_model, CONFIG.whisper_model)
    dossier = chemin_modele_whisper()
    os.makedirs(dossier, exist_ok=True)

    print(f"Modele Whisper '{CONFIG.whisper_model}' ({repo}) -> {dossier}")
    try:
        fichiers = lister_fichiers(repo)
    except Exception as e:
        print(f"Impossible de lister les fichiers du modele : {type(e).__name__}: {e}")
        return 1

    # Garde-fou : sans model.bin, le dossier serait cree mais inutilisable, et
    # l'erreur n'apparaitrait qu'au moment de transcrire.
    if "model.bin" not in fichiers:
        print(f"Le depot {repo} ne contient pas de model.bin : ce n'est pas un "
              "modele au format faster-whisper (CTranslate2).")
        print("Verifie le nom du modele dans config.py (whisper_model).")
        return 1

    for fichier in fichiers:
        destination = os.path.join(dossier, fichier)
        if os.path.exists(destination):
            print(f"  {fichier} : deja present, ignore")
            continue
        url = f"https://huggingface.co/{repo}/resolve/main/{fichier}"
        print(f"  {fichier} : telechargement...")
        telecharger_avec_reprise(url, destination)
        print(f"  {fichier} : termine")

    print(f"\nModele pret : {dossier}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
