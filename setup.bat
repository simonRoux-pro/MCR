@echo off
REM Prepare un poste Windows : environnement Python + modele de transcription.
REM A lancer une seule fois par machine, apres avoir clone le depot.

echo == 1. Environnement Python ==
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 (
    echo Echec de la mise a jour de pip. Verifie ta connexion et relance le script.
    exit /b 1
)
pip install -r requirements.txt
if errorlevel 1 (
    echo Echec de l'installation des dependances Python ^(voir l'erreur ci-dessus^).
    echo Si l'erreur mentionne un compilateur manquant ^(Visual C++...^), verifie que
    echo requirements.txt est a jour ^(git pull^) et relance ce script.
    exit /b 1
)

echo == 2. Telechargement du modele Whisper (quelques centaines de Mo, une seule fois) ==
python telecharge_modele.py
if errorlevel 1 (
    echo Le telechargement du modele Whisper a echoue.
    echo Relance simplement : python telecharge_modele.py
    exit /b 1
)

echo.
echo == Termine. Pour lancer le serveur ==
echo   .venv\Scripts\activate.bat
echo   python serveur.py
echo puis ouvrir http://127.0.0.1:8000 dans le navigateur
