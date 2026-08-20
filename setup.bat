@echo off
REM Prepare un poste Windows : environnement Python + modele Ollama.
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

echo == 2. Verification d'Ollama ==
where ollama >nul 2>nul
if errorlevel 1 (
    echo Ollama n'est pas installe. Installe-le depuis https://ollama.com puis relance ce script.
    exit /b 1
)

echo == 3. Telechargement du modele (plusieurs Go, une seule fois) ==
ollama pull mistral
if errorlevel 1 (
    echo.
    echo Le telechargement du modele a echoue ^(souvent une coupure reseau transitoire^).
    echo L'environnement Python est pret, mais il manque le modele Ollama.
    echo Relance simplement : ollama pull mistral
    exit /b 1
)

echo.
echo == Termine. Pour lancer l'application ==
echo   .venv\Scripts\activate.bat
echo   python main.py
