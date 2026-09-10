import os
from dataclasses import dataclass


@dataclass
class Config:
    # ------------------------------------------------------------------ #
    # Moteur de transcription
    # ------------------------------------------------------------------ #
    # "local"  : Whisper sur cette machine. Rien ne sort du serveur, mais il
    #            faut avoir telecharge le modele au prealable (~1,6 Go).
    # "genial" : l'API interne GenIAL. Aucun modele a installer et aucun calcul
    #            sur cette machine, mais l'audio de la reunion est envoye a ce
    #            service. A choisir la ou le modele ne peut pas etre installe.
    moteur: str = "local"

    # ------------------------------------------------------------------ #
    # Transcription locale (moteur "local")
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
    # Transcription au fil de l'eau
    # ------------------------------------------------------------------ #
    # Le direct n'a de sens que si la transcription va PLUS VITE que la reunion
    # ne se deroule. Sinon la file s'allonge sans fin et le texte arrive avec
    # un retard qui grandit a chaque minute.
    #
    # "auto"    : direct avec GenIAL (le calcul part sur le service, il suit),
    #             differe avec le moteur local (sur CPU, Whisper met souvent
    #             plus de temps a transcrire un segment qu'il ne dure).
    # "direct"  : force le direct. A tenter en local avec un petit modele
    #             ("small", voire "base") sur une machine rapide.
    # "differe" : force la transcription a la fin. Un peu plus precis en local,
    #             le modele gardant le contexte d'un bout a l'autre.
    mode: str = "auto"

    # Etiquettes des deux sources dans le texte final. Le micro, c'est la
    # personne devant l'ordinateur ; le son de l'ordinateur, ce sont les
    # autres participants de la visio.
    nom_micro: str = "Moi"
    nom_systeme: str = "Reunion"

    # ------------------------------------------------------------------ #
    # GenIAL (moteur "genial")
    # ------------------------------------------------------------------ #
    genial_url: str = ("https://api-genial.artemis-ia-dr.intradef.gouv.fr"
                       "/v1/audio/transcriptions")

    # Code langue attendu par GenIAL (3 lettres), a ne pas confondre avec
    # `language` ci-dessus qui sert au moteur local.
    genial_langue: str = "fra"

    # Le jeton n'est PAS ecrit ici : ce fichier est versionne. Il est lu dans
    # cette variable d'environnement, a definir avant de lancer le serveur.
    genial_variable_token: str = "GENIAL_TOKEN"

    # Forme de l'en-tete d'authentification. A ajuster si GenIAL attend autre
    # chose (par exemple entete "X-API-Key" et prefixe vide).
    genial_entete_token: str = "Authorization"
    genial_prefixe_token: str = "Bearer "

    # Verification du certificat TLS. Renseigner genial_ca avec le chemin du
    # bundle de l'autorite interne est la bonne solution ; passer
    # genial_verifier_tls a False desactive la verification (liaison toujours
    # chiffree, mais plus d'assurance sur l'identite du serveur) et ne devrait
    # servir qu'en depannage.
    genial_ca: str = ""
    genial_verifier_tls: bool = True

    # Temps d'attente maximum de la reponse. Une reunion longue prend du temps
    # a transcrire cote service : 30 minutes par defaut.
    genial_timeout: int = 1800

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
