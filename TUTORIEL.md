# Tutoriel d'installation — Meeting-CT

Guide pas a pas pour installer tous les prerequis et lancer l'application pour
la premiere fois, destine a quelqu'un qui n'a jamais installe Python, Git ou
Ollama. Pour la reference rapide (config, tests, depannage), voir le
[README principal](README.md).

---

## Etape 1 — Installer Python

[![Python](https://img.shields.io/badge/Python-Telecharger-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)

1. Va sur [python.org/downloads](https://www.python.org/downloads/) et
   telecharge la derniere version 3.x (3.10 ou plus recent).
2. Lance l'installeur.
   - **Windows** : coche bien la case **"Add python.exe to PATH"** en bas de
     la premiere fenetre avant de cliquer sur "Install Now" — c'est l'erreur
     la plus frequente si `python` n'est pas reconnu ensuite dans un terminal.
   - **macOS** : suis l'installeur `.pkg` par defaut.
   - **Linux** : Python est generalement deja installe. Verifie avec la
     commande ci-dessous ; sinon installe-le via le gestionnaire de paquets
     de ta distribution (`apt install python3 python3-venv` sur Debian/Ubuntu).
3. Verifie l'installation dans un terminal :
   ```bash
   python --version
   # ou, selon le systeme :
   python3 --version
   ```
   Tu dois voir `Python 3.10.x` ou plus.

## Etape 2 — Installer Git

[![Git](https://img.shields.io/badge/Git-Telecharger-F05032?logo=git&logoColor=white)](https://git-scm.com/downloads)

Git sert a recuperer (cloner) le code du projet.

1. Va sur [git-scm.com/downloads](https://git-scm.com/downloads) et
   telecharge l'installeur pour ton systeme.
2. Lance l'installeur en laissant les options par defaut (elles conviennent
   dans la grande majorite des cas).
3. Verifie l'installation :
   ```bash
   git --version
   ```

## Etape 3 — Installer Ollama (moteur du compte-rendu)

[![Ollama](https://img.shields.io/badge/Ollama-Telecharger-000000?logo=ollama&logoColor=white)](https://ollama.com)

Ollama fait tourner le modele de langage **en local**, sans envoyer aucune
donnee sur internet.

1. Va sur [ollama.com](https://ollama.com) et telecharge l'installeur pour
   ton systeme.
2. Installe-le : sur Windows/macOS, Ollama se lance generalement tout seul en
   arriere-plan apres l'installation (icone dans la barre systeme). Sur
   Linux, lance-le manuellement avec `ollama serve` si besoin.
3. Verifie qu'il tourne :
   ```bash
   ollama --version
   ```

Le modele de langage (`mistral` par defaut, quelques Go) sera telecharge a
l'etape 6 par le script d'installation — pas besoin de le faire main.

## Etape 4 — macOS uniquement : capter les autres participants (BlackHole)

Sur Windows et Linux, l'application capte automatiquement le son des autres
participants d'une visio (Teams/Skype/Meet) en plus de ton micro — rien a
faire. **Sur macOS, une etape manuelle est necessaire**, car Apple ne permet
pas nativement de "boucler" le son des haut-parleurs vers une application :

1. Installe [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole)
   (peripherique audio virtuel gratuit et open source).
2. Ouvre l'utilitaire macOS **"Configuration audio et MIDI"**, cree un
   **"Peripherique de sortie multiple"** combinant tes haut-parleurs/casque
   habituels et BlackHole.
3. Pendant tes visios, selectionne ce peripherique combine comme sortie audio
   par defaut : tu entends toujours normalement, et BlackHole en recoit une
   copie que l'application pourra enregistrer.

Sans cette etape sur macOS, l'application enregistre uniquement ton micro
(donc pas les autres participants) — voir la section "Capture du son des
autres participants" du [README principal](README.md#capture-du-son-des-autres-participants-visio)
pour plus de details.

## Etape 5 — Recuperer le code du projet

Ouvre un terminal a l'endroit ou tu veux installer le projet, puis :

```bash
git clone <URL_DU_DEPOT> meeting-ct
cd meeting-ct
```

## Etape 6 — Installer les dependances du projet

### Linux / macOS
```bash
chmod +x setup.sh
./setup.sh
```

### Windows
```bat
setup.bat
```

Ce script :
- cree un environnement Python isole (`.venv`), pour ne rien installer sur
  le systeme global ;
- installe les librairies Python necessaires (faster-whisper, PySide6...) ;
- pre-telecharge le modele Whisper pour la transcription (quelques centaines
  de Mo, une seule fois) — relançable seul via `python telecharge_modele.py` ;
- verifie qu'Ollama est bien installe puis telecharge le modele `mistral`
  (quelques Go, la premiere fois seulement).

Le script s'arrete et affiche une erreur claire des qu'une etape echoue (par
exemple une coupure reseau pendant le telechargement du modele) plutot que de
continuer silencieusement. Si tu ne vois pas le message final
`== Termine. ==`, une etape a echoue : lis le message d'erreur juste au-dessus
et relance simplement `setup.sh`/`setup.bat` (les etapes deja faites, comme
un paquet Python deja installe, ne sont pas refaites inutilement).

Verifie que le modele est bien present avant de continuer :
```bash
ollama list
```
Tu dois voir `mistral` dans la liste. Sinon, relance `ollama pull mistral`.

## Etape 7 — Lancer l'application

Assure-toi qu'Ollama tourne (icone dans la barre systeme, ou `ollama serve`
dans un terminal a part), puis :

### Linux / macOS
```bash
source .venv/bin/activate
python main.py
```

### Windows
```bat
.venv\Scripts\activate.bat
python main.py
```

La fenetre de l'application s'ouvre. Pour la suite (enregistrer une reunion,
charger un fichier audio, exporter ou envoyer le compte-rendu), suis la
section **"Tutoriel : premiere utilisation"** du [README principal](README.md#4-tutoriel--premiere-utilisation).

---

## Ca ne marche pas ?

| Symptome | Piste |
|---|---|
| `python` / `git` / `ollama` : commande introuvable | Redemarre le terminal (voire la machine) apres l'installation, la variable PATH doit se recharger |
| `python --version` affiche une version 2.x | Utilise `python3` a la place de `python` (frequent sur macOS/Linux) |
| Le script `setup.sh`/`setup.bat` echoue sur "Ollama n'est pas installe" | Reprends l'etape 3, puis relance le script |
| Le script echoue pendant `pip install` (compilateur manquant, `metadata-generation-failed`) | `git pull` dans le dossier du projet (requirements.txt peut avoir ete corrige entre-temps), puis relance le script |
| Le script echoue pendant `ollama pull mistral` (`wsarecv`, `max retries exceeded`...) | Coupure reseau transitoire pendant le telechargement (plusieurs Go) : relance juste `ollama pull mistral`, l'environnement Python est deja installe |
| Autres erreurs une fois l'appli lancee | Voir la section **Depannage** du [README principal](README.md#10-depannage) |
