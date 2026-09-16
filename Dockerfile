# Image de l'application, moteur GenIAL.
#
# Pourquoi "slim" : c'est une Debian reduite au minimum, avec Python et rien
# d'autre. Aucun compilateur, aucun outil superflu — l'image est plus petite et
# offre moins de surface. Le moteur GenIAL n'a rien a compiler, ca suffit.
#
# Pour le moteur LOCAL (faster-whisper), cette image ne convient pas telle
# quelle : il faudrait installer requirements.txt et monter le modele (1,6 Go)
# depuis un volume, jamais l'embarquer dans l'image.
FROM python:3.12-slim

# PYTHONUNBUFFERED : les messages du serveur arrivent immediatement dans
#   `docker compose logs` au lieu d'attendre que le tampon se remplisse. Sans
#   ca, on croit l'application muette alors qu'elle travaille.
# PYTHONDONTWRITEBYTECODE : pas de fichiers .pyc ecrits dans le conteneur.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Dans un conteneur, 127.0.0.1 ne designe que le conteneur : personne ne
    # pourrait joindre l'application depuis l'exterieur.
    MEETING_HOST=0.0.0.0

WORKDIR /app

# Les dependances AVANT le code : Docker garde en cache le resultat de cette
# etape tant que le fichier ne change pas. Modifier une ligne de code ne
# relance donc pas l'installation des paquets.
COPY requirements-genial.txt .
RUN pip install --no-cache-dir -r requirements-genial.txt

COPY . .

# Ne pas tourner en root : si quelqu'un exploitait une faille de l'application,
# il se retrouverait avec les droits d'un utilisateur sans privilege.
RUN useradd --create-home meeting && chown -R meeting /app
USER meeting

EXPOSE 8000

CMD ["python", "serveur.py"]
