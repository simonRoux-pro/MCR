"""Transcription par GenIAL, l'API interne.

Alternative au modele Whisper local : aucun modele a installer sur la machine,
mais l'audio de la reunion est envoye au service GenIAL. Le choix se fait dans
config.py (CONFIG.moteur).

Le jeton n'est JAMAIS ecrit dans le code ni dans config.py (qui sont
versionnes) : il est lu dans une variable d'environnement.
"""
import os

import requests

from config import CONFIG

# Type de contenu envoye selon l'extension du fichier. Le navigateur produit du
# webm ; les autres formats servent si un jour on rejoue un fichier existant.
TYPES = {
    ".webm": "audio/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
}

TIMEOUT_CONNEXION = 15   # secondes pour etablir la connexion


def _jeton() -> str:
    jeton = os.environ.get(CONFIG.genial_variable_token, "").strip()
    if not jeton:
        raise RuntimeError(
            f"Le jeton GenIAL est absent : la variable d'environnement "
            f"{CONFIG.genial_variable_token} n'est pas definie. "
            f"Sous Linux : export {CONFIG.genial_variable_token}=\"<ton jeton>\" "
            f"avant de lancer le serveur."
        )
    return jeton


def _verification_tls():
    """Ce que `requests` doit utiliser pour verifier le certificat du serveur.

    Un chemin de bundle CA si l'autorite interne est connue, True sinon.
    Mettre CONFIG.genial_verifier_tls a False desactive la verification : la
    liaison reste chiffree, mais plus rien ne garantit qu'on parle bien a
    GenIAL et non a un intermediaire. A n'utiliser qu'en depannage.
    """
    if CONFIG.genial_ca:
        return CONFIG.genial_ca
    return CONFIG.genial_verifier_tls


def _message_d_erreur(reponse) -> str:
    """Message lisible a partir de la reponse du service, en gardant son texte
    brut : c'est lui qui dit si le format audio ou le jeton est en cause."""
    detail = (reponse.text or "").strip()
    if len(detail) > 500:
        detail = detail[:500] + "..."
    if reponse.status_code in (401, 403):
        return (f"GenIAL a refuse le jeton (HTTP {reponse.status_code}). "
                f"Verifie la variable {CONFIG.genial_variable_token}. {detail}")
    if reponse.status_code == 413:
        return ("L'enregistrement est trop volumineux pour GenIAL "
                f"(HTTP 413). {detail}")
    return f"GenIAL a repondu HTTP {reponse.status_code} : {detail}"


def transcrire_genial(audio_path: str, out_path: str, progress=None,
                      vocabulaire: str = "") -> str:
    """Envoie l'enregistrement a GenIAL et ecrit le texte obtenu.

    Meme signature que la transcription locale, pour que le serveur n'ait pas
    a savoir quel moteur tourne. `vocabulaire` est ignore : l'API n'expose pas
    de vocabulaire personnalise (c'est une possibilite du moteur local seul).

    progress n'est pas appele : GenIAL rend le texte d'un bloc, il n'y a aucun
    avancement intermediaire a afficher (le serveur montre alors une attente
    sans pourcentage plutot qu'un 0 % trompeur).
    """
    entetes = {CONFIG.genial_entete_token: CONFIG.genial_prefixe_token + _jeton()}
    extension = os.path.splitext(audio_path)[1].lower()
    type_contenu = TYPES.get(extension, "application/octet-stream")
    taille = os.path.getsize(audio_path)

    print(f"[MeetingCT] GenIAL : envoi de {taille // 1024} Ko "
          f"({type_contenu}) vers {CONFIG.genial_url}", flush=True)

    try:
        with open(audio_path, "rb") as f:
            reponse = requests.post(
                CONFIG.genial_url,
                headers=entetes,
                files={"file": (os.path.basename(audio_path), f, type_contenu)},
                data={"language": CONFIG.genial_langue},
                timeout=(TIMEOUT_CONNEXION, CONFIG.genial_timeout),
                verify=_verification_tls(),
            )
    except requests.exceptions.SSLError as e:
        raise RuntimeError(
            "Le certificat de GenIAL n'a pas pu etre verifie. Renseigne le "
            "bundle de l'autorite interne dans config.py (genial_ca), ou, en "
            f"depannage, mets genial_verifier_tls a False. Detail : {e}")
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"GenIAL n'a pas repondu en {CONFIG.genial_timeout} s. Pour une "
            "reunion longue, augmente genial_timeout dans config.py.")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"GenIAL est injoignable : {type(e).__name__}: {e}")

    if reponse.status_code != 200:
        raise RuntimeError(_message_d_erreur(reponse))

    try:
        texte = reponse.json()["result"]
    except Exception:
        raise RuntimeError(
            "Reponse inattendue de GenIAL (le champ « result » est absent) : "
            + (reponse.text or "")[:500])

    texte = (texte or "").strip()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(texte + "\n")
        f.flush()
        os.fsync(f.fileno())

    print(f"[MeetingCT] GenIAL : {len(texte)} caracteres recus", flush=True)
    return texte
