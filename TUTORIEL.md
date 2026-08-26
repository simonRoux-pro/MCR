# Tutoriel d'installation — Meeting-CT

Guide pas a pas pour installer le serveur de transcription et l'utiliser dans
le navigateur, destine a quelqu'un qui n'a jamais installe Python ou Git. Pour
la reference rapide (configuration, tests, depannage), voir le
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
2. Lance l'installeur en laissant les options par defaut.
3. Verifie l'installation :
   ```bash
   git --version
   ```

## Etape 3 — Recuperer le code du projet

Ouvre un terminal a l'endroit ou tu veux installer le projet, puis :

```bash
git clone <URL_DU_DEPOT> meeting-ct
cd meeting-ct
```

## Etape 4 — Installer les dependances et le modele

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
- installe les librairies necessaires (faster-whisper, FastAPI...) ;
- pre-telecharge le modele de transcription (quelques centaines de Mo, une
  seule fois) — relançable seul via `python telecharge_modele.py`.

Le script s'arrete et affiche une erreur claire des qu'une etape echoue plutot
que de continuer silencieusement. Si tu ne vois pas le message final
`== Termine. ==`, lis le message d'erreur juste au-dessus et relance le script
(les etapes deja faites ne sont pas refaites inutilement).

## Etape 5 — Lancer le serveur

### Linux / macOS
```bash
source .venv/bin/activate
python serveur.py
```

### Windows
```bat
.venv\Scripts\activate.bat
python serveur.py
```

Laisse ce terminal ouvert : c'est lui qui fait tourner le serveur. Ouvre
ensuite **http://127.0.0.1:8000** dans **Chrome ou Edge**.

## Etape 6 — Enregistrer une premiere reunion

1. Laisse coche **"Capter aussi le son de l'ordinateur"** si tu veux
   enregistrer les autres participants d'une visio.
2. Clique sur **"Demarrer l'enregistrement"** et **autorise le micro**.
3. Le navigateur demande quoi partager : choisis **l'onglet de la visio** (ou
   l'ecran entier) et surtout **coche « Partager l'audio »** en bas de la
   fenetre de selection. Sans cette case, seul ton micro sera enregistre.
   (La video n'est pas enregistree : elle est coupee immediatement, seul le son
   est conserve.)
4. Parle, laisse la reunion se derouler.
5. Clique sur **"Arreter et transcrire"** : la transcription demarre, la barre
   de progression avance, puis le texte s'affiche.
6. **Copier** ou **Telecharger (.txt)** pour reprendre le texte ailleurs, et
   **Effacer du serveur** quand tu n'en as plus besoin.

---

## Ca ne marche pas ?

| Symptome | Piste |
|---|---|
| `python` / `git` : commande introuvable | Redemarre le terminal (voire la machine) apres l'installation, la variable PATH doit se recharger |
| `python --version` affiche une version 2.x | Utilise `python3` a la place de `python` (frequent sur macOS/Linux) |
| Le script echoue pendant `pip install` (compilateur manquant) | `git pull` dans le dossier du projet, puis relance le script |
| Le telechargement du modele est tres lent ou s'interrompt | Normal sur une connexion instable : relance `python telecharge_modele.py`, il reprend ou il s'est arrete |
| La page ne s'ouvre pas | Verifie que le terminal du serveur est toujours ouvert et affiche bien `http://127.0.0.1:8000` |
| Seul mon micro est enregistre | La case « Partager l'audio » n'a pas ete cochee au moment du partage, ou le navigateur n'est pas Chrome/Edge |
| Autres erreurs | Voir la section **Depannage** du [README principal](README.md#10-depannage) |
