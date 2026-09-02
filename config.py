import os
from dataclasses import dataclass


@dataclass
class Config:
    # ------------------------------------------------------------------ #
    # Transcription
    # ------------------------------------------------------------------ #
    # Modele Whisper, du plus rapide au plus precis :
    #   small          : rapide, mais confond les mots des que le son est moyen
    #   medium         : lent, un peu meilleur que small
    #   large-v3-turbo : nettement plus fidele, et pourtant PLUS RAPIDE que
    #                    medium (son decodeur est allege) -> choix par defaut
    #   large-v3       : le plus precis, mais tres lent sur un CPU
    # Apres avoir change cette valeur : relancer `python telecharge_modele.py`.
    whisper_model: str = "large-v3-turbo"

    whisper_device: str = "cpu"

    # Quantification du calcul. "int8" est rapide et suffit dans la plupart
    # des cas ; "int8_float32" est un cran plus fidele (~20 % plus lent),
    # "float32" encore un peu plus mais deux a trois fois plus lent.
    whisper_compute: str = "int8"

    language: str = "fr"

    # Nombre d'hypotheses explorees en parallele par le decodeur : c'est le
    # reglage "qualite contre vitesse" le plus direct. 5 = valeur de reference
    # de Whisper ; 1 va plus vite mais fait sensiblement plus de fautes.
    beam_size: int = 5

    # Mots que le modele ne peut pas deviner : noms de l'equipe, du produit,
    # sigles metier... Ils lui sont souffles avant chaque passage, ce qui evite
    # les orthographes fantaisistes sur le vocabulaire maison.
    # Exemple : "Sopra Steria, Kubernetes, RGPD, Jira, Simon Roux"
    vocabulaire: str = ""

    # Coeurs CPU utilises pour la transcription. 0 = tous ceux de la machine.
    cpu_threads: int = 0

    # ------------------------------------------------------------------ #
    # Serveur web
    # ------------------------------------------------------------------ #
    host: str = "127.0.0.1"             # "0.0.0.0" pour ouvrir aux autres postes du reseau
    port: int = 8000

    # Nombre de transcriptions simultanees. 1 = les demandes s'enchainent :
    # sur CPU, lancer plusieurs transcriptions en parallele ralentit tout le
    # monde (et le modele Whisper n'est pas prevu pour un usage concurrent).
    transcriptions_simultanees: int = 1


CONFIG = Config()


def chemin_modele_whisper() -> str:
    """Dossier local ou telecharge_modele.py depose le modele Whisper.
    (dans models/, deja exclu de git par le .gitignore)"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "models", f"whisper-{CONFIG.whisper_model}")
