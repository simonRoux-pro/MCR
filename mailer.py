import smtplib
from email.message import EmailMessage
from config import CONFIG


def send_report(to: str, subject: str, body: str):
    """Seule sortie reseau de l'outil : l'envoi du compte-rendu par mail."""
    # Sans cette verification, un SMTP non configure produit une erreur
    # incomprehensible ("run connect() first") : smtplib ne se connecte pas
    # quand l'hote est vide, et c'est l'appel suivant qui echoue.
    manquants = [nom for nom, valeur in (
        ("smtp_host", CONFIG.smtp_host),
        ("smtp_user", CONFIG.smtp_user),
        ("smtp_password", CONFIG.smtp_password),
    ) if not valeur]
    if manquants:
        raise RuntimeError(
            "Envoi par mail impossible : le serveur d'envoi (SMTP) n'est pas configure "
            f"({', '.join(manquants)} manquant(s)). Renseigne ces valeurs dans config.py, "
            "ou dans un config_local.py non versionne pour garder le mot de passe prive. "
            "Le compte-rendu reste exportable en .txt et .md sans configuration."
        )

    msg = EmailMessage()
    msg["From"] = CONFIG.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(CONFIG.smtp_host, CONFIG.smtp_port, timeout=30) as s:
            s.starttls()
            s.login(CONFIG.smtp_user, CONFIG.smtp_password)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise RuntimeError(
            f"Le serveur mail a refuse les identifiants ({CONFIG.smtp_user}). "
            "Avec Gmail/Outlook et la double authentification, il faut un mot de passe "
            f"d'application dedie, pas le mot de passe habituel. Detail : {e}"
        ) from e
    except (smtplib.SMTPException, OSError) as e:
        raise RuntimeError(
            f"Echec de l'envoi via {CONFIG.smtp_host}:{CONFIG.smtp_port} "
            f"({type(e).__name__}: {e}). Verifie l'adresse du serveur, le port et ta connexion."
        ) from e
