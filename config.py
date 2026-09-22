import os
from dataclasses import dataclass

DOSSIER = os.path.dirname(os.path.abspath(__file__))


def charger_env_local(nom: str = ".env") -> None:
    """Lit un fichier .env pose a cote du code et en tire des variables.

    Evite de refaire `export GENIAL_TOKEN=...` a chaque nouveau terminal : le
    jeton est ecrit une fois dans ce fichier, qui n'est jamais versionne (voir
    .gitignore). Docker lit le meme fichier, il n'y a donc qu'un seul endroit
    ou poser un secret.

    Une variable deja definie dans l'environnement n'est PAS remplacee : ce qui
    vient du systeme, du terminal ou de Docker reste prioritaire sur le
    fichier.
    """
    fichier = os.path.join(DOSSIER, nom)
    if not os.path.isfile(fichier):
        return
    with open(fichier, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            cle, _, valeur = ligne.partition("=")
            # Les guillemets autour de la valeur sont une habitude de shell,
            # ils ne font pas partie du secret.
            os.environ.setdefault(cle.strip(), valeur.strip().strip("\"'"))


# AVANT la lecture des reglages ci-dessous : certains s'appuient dessus.
charger_env_local()


def _reglage(variable: str, defaut: str) -> str:
    """Valeur d'un reglage, surchargeable par variable d'environnement.

    Sert au deploiement : on change l'adresse d'ecoute ou le moteur sans
    modifier ni reconstruire quoi que ce soit, en posant la variable dans .env
    ou dans docker-compose.yml.
    """
    return os.environ.get(variable, defaut)


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
    moteur: str = _reglage("MEETING_MOTEUR", "local")

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
    mode: str = _reglage("MEETING_MODE", "auto")

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

    # --- Redaction du compte rendu (chat/completions) --- #
    genial_url_chat: str = ("https://api-genial.artemis-ia-dr.intradef.gouv.fr"
                            "/v1/chat/completions")

    # Nom du modele de redaction. A renseigner : la liste depend du service.
    # `python diag_genial.py` affiche les modeles disponibles.
    genial_modele: str = _reglage("MEETING_MODELE", "")

    # La documentation GenIAL le dit : une reponse longue fait expirer la
    # requete si elle n'est pas diffusee en flux. Un compte rendu EST une
    # reponse longue, le flux est donc actif par defaut.
    genial_stream: bool = True

    genial_max_tokens: int = 4000
    genial_temperature: float = 0.2   # bas : on resume, on n'invente pas

    # Consigne envoyee au modele, suivie de la transcription. A adapter au
    # style de compte rendu attendu dans le service.
    consigne_cr: str = (
        "Tu rédiges le compte rendu d'une réunion à partir de sa transcription "
        "automatique. Cette transcription contient des erreurs de "
        "reconnaissance vocale et des tournures orales : ne les reprends pas "
        "telles quelles.\n\n"
        "Produis un compte rendu en français, structuré ainsi :\n"
        "- un résumé de quelques lignes ;\n"
        "- les points abordés, regroupés par sujet ;\n"
        "- les décisions prises ;\n"
        "- les actions à mener, avec la personne qui en a la charge lorsque la "
        "transcription permet de l'identifier.\n\n"
        "N'invente rien : une information absente de la transcription ne doit "
        "pas apparaître. Les intervenants sont désignés par leur étiquette en "
        "début de réplique.\n\n"
        "Transcription :\n"
    )

    # ------------------------------------------------------------------ #
    # Serveur web
    # ------------------------------------------------------------------ #
    # "0.0.0.0" pour ouvrir aux autres postes du reseau. Dans un conteneur
    # c'est obligatoire : 127.0.0.1 n'y designe que le conteneur lui-meme, et
    # rien ne repondrait de l'exterieur.
    host: str = _reglage("MEETING_HOST", "127.0.0.1")
    port: int = int(_reglage("MEETING_PORT", "8000"))

    # Ou conserver les enregistrements et leurs resultats.
    #
    # Vide (defaut) : dossier temporaire du systeme, et les sessions ne vivent
    # qu'en memoire. Parfait sur son poste — rien ne s'accumule, rien ne
    # survit a une reunion. Mais tout redemarrage efface tout.
    #
    # Renseigne : chaque session est ecrite sur le disque et relue au
    # demarrage. Indispensable des qu'une application tierce vient chercher
    # le resultat plus tard : un redemarrage ne doit pas lui faire perdre
    # une reunion.
    dossier_donnees: str = _reglage("MEETING_DONNEES", "")

    # Duree de conservation, en jours. Au-dela, la reunion est effacee —
    # audio, transcription et compte rendu. 0 desactive l'effacement.
    #
    # Une transcription de reunion est une donnee sensible : elle ne doit pas
    # s'accumuler indefiniment sur un serveur parce que personne n'a pense a
    # faire le menage.
    retention_jours: int = int(_reglage("MEETING_RETENTION_JOURS", "7"))

    # Domaines autorises a appeler l'API depuis un navigateur.
    #
    # Quand la page est servie par une autre application (un composant Appian,
    # par exemple), le navigateur refuse par defaut qu'elle appelle un serveur
    # d'un autre domaine. Il faut donc nommer ici l'application appelante.
    #
    # Plusieurs domaines se separent par des virgules. Vide = aucun appel
    # d'origine etrangere, ce qui est le bon reglage quand l'outil sert sa
    # propre page. On ne met JAMAIS "*" : n'importe quel site pourrait alors
    # lire les transcriptions du navigateur de l'utilisateur.
    origines: str = _reglage("MEETING_ORIGINES", "")

    # Certificat TLS, pour servir en HTTPS. Chemins vers le certificat et sa
    # cle privee ; laisser vide pour servir en HTTP simple.
    #
    # Ce n'est PAS un raffinement : les navigateurs n'autorisent l'acces au
    # micro et a la capture d'ecran que dans un "contexte securise", c'est a
    # dire en HTTPS. La seule exception est localhost, ce qui permet de
    # travailler sur son poste sans certificat. Des que le serveur est joint
    # par son adresse reseau, sans HTTPS le micro est refuse et l'outil ne
    # sert plus a rien.
    ssl_cert: str = _reglage("MEETING_SSL_CERT", "")
    ssl_key: str = _reglage("MEETING_SSL_KEY", "")

    # Nombre de transcriptions simultanees. 1 = les demandes s'enchainent :
    # sur CPU, lancer plusieurs transcriptions en parallele ralentit tout le
    # monde (et le modele Whisper n'est pas prevu pour un usage concurrent).
    transcriptions_simultanees: int = 1


CONFIG = Config()


def chemin_modele_whisper() -> str:
    """Dossier local ou telecharge_modele.py depose le modele Whisper.
    (dans models/, deja exclu de git par le .gitignore)"""
    return os.path.join(DOSSIER, "models", f"whisper-{CONFIG.whisper_model}")
