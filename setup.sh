#!/usr/bin/env bash
# Prepare un poste : environnement Python + modele Ollama.
# A lancer une seule fois par machine, apres avoir clone le depot.
set -e

echo "== 1. Environnement Python =="
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "== 2. Verification d'Ollama =="
if ! command -v ollama >/dev/null 2>&1; then
    echo "Ollama n'est pas installe. Installe-le depuis https://ollama.com puis relance ce script."
    exit 1
fi

echo "== 3. Telechargement du modele (plusieurs Go, une seule fois) =="
ollama pull mistral

echo ""
echo "== Termine. Pour lancer l'application =="
echo "  source .venv/bin/activate"
echo "  python main.py"
