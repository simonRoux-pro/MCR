@echo off
REM Prepare un poste Windows : environnement Python + modele Ollama.
REM A lancer une seule fois par machine, apres avoir clone le depot.

echo == 1. Environnement Python ==
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo == 2. Verification d'Ollama ==
where ollama >nul 2>nul
if errorlevel 1 (
    echo Ollama n'est pas installe. Installe-le depuis https://ollama.com puis relance ce script.
    exit /b 1
)

echo == 3. Telechargement du modele (plusieurs Go, une seule fois) ==
ollama pull mistral

echo.
echo == Termine. Pour lancer l'application ==
echo   .venv\Scripts\activate.bat
echo   python main.py
