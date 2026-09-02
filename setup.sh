#!/usr/bin/env bash
# Prepare un poste : environnement Python + modele de transcription.
# A lancer une seule fois par machine, apres avoir clone le depot.
set -e

echo "== 1. Environnement Python =="
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "== 2. Telechargement du modele Whisper (environ 1,6 Go, une seule fois) =="
python telecharge_modele.py

echo ""
echo "== Termine. Pour lancer le serveur =="
echo "  source .venv/bin/activate"
echo "  python serveur.py"
echo "puis ouvrir http://127.0.0.1:8000 dans le navigateur"
