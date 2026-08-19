import smtplib
from email.message import EmailMessage
from config import CONFIG


def send_report(to: str, subject: str, body: str):
    """Seule sortie reseau de l'outil : l'envoi du compte-rendu par mail."""
    msg = EmailMessage()
    msg["From"] = CONFIG.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(CONFIG.smtp_host, CONFIG.smtp_port) as s:
        s.starttls()
        s.login(CONFIG.smtp_user, CONFIG.smtp_password)
        s.send_message(msg)
