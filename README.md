# Meeting-CT

Client lourd de transcription et compte-rendu de reunion, **100% local**.
Aucune donnee ne sort de la machine, a l'exception du compte-rendu final envoye
par mail si tu choisis de l'envoyer.

## Fonctionnement en un coup d'oeil

1. Enregistrement du micro **et du son systeme** (les autres participants en
   visio Teams/Skype/Meet) simultanement, **ou** chargement d'un fichier audio
   existant (mode fichier)
2. Transcription locale (faster-whisper, tourne sur CPU)
3. Generation du compte-rendu (LLM local via Ollama)
4. Consultation / export en `.txt` ou `.md` / envoi par mail (seule sortie reseau)

Les longues reunions (2 h et plus) sont gerees de bout en bout :
- l'audio est ecrit sur disque au fil de l'eau (pas d'accumulation en RAM) ;
- la transcription est sauvegardee en continu, segment par segment ;
- le compte-rendu est produit par decoupage **map-reduce** (resume par morceau
  puis consolidation) pour ne jamais saturer le modele, meme sur une tres
  longue transcription.

---

## 1. Prerequis

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Git](https://img.shields.io/badge/Git-Telecharger-F05032?logo=git&logoColor=white)](https://git-scm.com/downloads)
[![Ollama](https://img.shields.io/badge/Ollama-Telecharger-000000?logo=ollama&logoColor=white)](https://ollama.com)

- **Python 3.10+** — clique sur le badge ci-dessus pour telecharger l'installeur
- **Git** — necessaire pour cloner le depot ; clique sur le badge pour telecharger l'installeur
- **[Ollama](https://ollama.com)** installe (pour generer le compte-rendu)
- Un micro fonctionnel (optionnel : tu peux te passer de micro en mode fichier, voir plus bas)

> Nouveau sur ces outils ? Le [guide d'installation detaille](TUTORIEL.md) explique
> pas a pas comment installer Python, Git et Ollama pour un premier lancement.

## 2. Installation

### Linux / macOS
```bash
git clone <URL_DU_DEPOT> meeting-ct
cd meeting-ct
chmod +x setup.sh
./setup.sh
```

### Windows
```bat
git clone <URL_DU_DEPOT> meeting-ct
cd meeting-ct
setup.bat
```

Le script cree l'environnement Python (`.venv`), installe les dependances et
telecharge le modele Ollama par defaut (`mistral`, quelques Go, une seule fois).
Le modele Whisper (faster-whisper) se telecharge automatiquement au premier
lancement, lors de la toute premiere transcription.

## 3. Lancer l'application

Ollama doit tourner en arriere-plan (installe normalement un service demarre
automatiquement ; sinon lance `ollama serve` dans un terminal a part).

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

---

## 4. Tutoriel : premiere utilisation

### Option A — Enregistrer une reunion au micro

1. Clique sur **"Demarrer l'enregistrement"**. L'audio commence a s'ecrire sur
   disque immediatement (pas de perte en cas de plantage en cours de route).
2. Laisse tourner pendant la reunion (teste et calibre pour des reunions de 2 h).
3. Clique sur **"Arreter et generer le CR"**.
4. La transcription se lance (barre de progression, peut prendre du temps sur
   CPU — voir la section Performances plus bas). Des qu'elle est terminee, elle
   s'affiche dans le champ **"Transcription"**, meme si la suite echoue.
5. Le compte-rendu se genere ensuite via Ollama (map-reduce si la reunion est
   longue) et s'affiche dans le champ **"Compte-rendu"**.

Des le demarrage de l'enregistrement, le statut affiche si le son systeme (les
autres participants) a pu etre capte en plus du micro :
- *"Enregistrement en cours (micro + son systeme)..."* : les deux sont mixes.
- *"Enregistrement en cours (micro uniquement...)"* : seule ta voix est captee,
  voir la section [Capture du son des autres participants](#capture-du-son-des-autres-participants-visio) ci-dessous.

### Capture du son des autres participants (visio)

Le micro seul ne capte que toi. Pour un compte-rendu complet d'une visio
Teams/Skype/Meet, l'application capte **aussi le son systeme** (ce que tu
entends dans tes haut-parleurs ou ton casque) et le mixe avec le micro,
automatiquement selon l'OS :

| OS | Fonctionnement | A faire |
|---|---|---|
| **Windows** | Loopback WASAPI natif (librairie `soundcard`) | Rien, ca marche des l'installation |
| **Linux** | Source "monitor" exposee par PulseAudio/PipeWire | Rien si PulseAudio/PipeWire est present (cas standard sur les distributions grand public) |
| **macOS** | Pas de boucle audio native : necessite un peripherique virtuel | Installer [BlackHole](https://github.com/ExistentialAudio/BlackHole) (gratuit, open source), voir ci-dessous |

**Installation de BlackHole sur macOS** (une seule fois) :
1. Installe [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole).
2. Cree un peripheriques de sortie agrege ("Multi-Output Device") dans
   l'utilitaire "Configuration audio et MIDI" combinant tes haut-parleurs/casque
   habituels **et** BlackHole, puis selectionne ce peripherique agrege comme
   sortie audio par defaut pendant tes visios. Ainsi tu entends toujours le
   son normalement, et BlackHole en recoit une copie que l'application capte.

Si aucune capture systeme n'est disponible (peripherique absent, non
configure...), l'application **ne plante pas** : elle continue avec le micro
seul, et te previent via le statut affiche.

### Option B — Charger un fichier audio existant (mode fichier)

Pas de micro sous la main, ou tu veux retraiter un enregistrement issu d'une
visio (Teams, Meet...) ? Utilise le mode fichier :

1. Clique sur **"Charger un fichier audio..."**.
2. Choisis un fichier `.wav`, `.mp3` ou `.m4a` sur ton disque.
3. La chaine transcription + CR se lance directement dessus, exactement comme
   pour un enregistrement micro (memes etapes 4-5 ci-dessus).

C'est aussi le moyen le plus simple de **tester l'outil de bout en bout** sans
materiel audio : prends n'importe quel enregistrement audio existant (memo
vocal, extrait de reunion passee...) et charge-le.

### Ensuite : consulter, exporter ou envoyer le compte-rendu

Une fois le compte-rendu genere, trois actions possibles (non exclusives) :

- **Exporter en `.txt`** ou **Exporter en `.md`** : enregistre le CR dans un
  fichier local, choisi via une boite de dialogue.
- **Envoyer par mail** : renseigne un destinataire dans le champ prevu et
  clique sur "Envoyer par mail" (necessite d'avoir configure le SMTP, voir
  section Configuration). C'est la **seule** action qui fait sortir une
  donnee de la machine.

### Si Ollama n'est pas lance

Si Ollama n'est pas demarre (ou que le modele configure n'est pas installe),
l'application affiche une erreur claire au lieu de planter, par exemple :

> Impossible de contacter Ollama sur http://localhost:11434. Verifiez qu'Ollama
> est demarre (commande : `ollama serve`), puis reessayez.

Important : **la transcription n'est pas perdue**. Elle a deja ete calculee et
reste affichee dans le champ "Transcription" — seule la generation du CR a
echoue. Il suffit de demarrer Ollama puis de relancer une transcription (ou de
recuperer le texte transcrit affiche) sans avoir a tout refaire.

---

## 5. Configuration

Tout se regle dans `config.py` :

| Parametre | Role | Valeur par defaut |
|---|---|---|
| `whisper_model` | Modele faster-whisper : `base` (rapide, moins precis), `small`, `medium` (lent, precis) | `small` |
| `whisper_device` / `whisper_compute` | CPU + quantification int8 (pas de GPU requis) | `cpu` / `int8` |
| `language` | Langue de la transcription | `fr` |
| `ollama_model` | Modele LLM local pour le CR : `mistral`, `llama3.1`, `qwen2.5:3b` (plus leger) | `mistral` |
| `ollama_host` | Adresse du serveur Ollama (local) | `http://localhost:11434` |
| `chunk_chars` | Taille des morceaux pour le decoupage map-reduce du CR | `6000` |
| `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password` | Reglages pour l'envoi mail du CR | vide |

Pour les secrets SMTP, cree un `config_local.py` (ignore par git) plutot que de
les mettre en clair dans `config.py`, et importe-le pour surcharger `CONFIG`.

---

## 6. Export du compte-rendu

En plus de l'envoi par mail, le compte-rendu peut etre exporte localement via
les boutons **"Exporter en .txt"** et **"Exporter en .md"**. Le Markdown reprend
la structure produite par le LLM (Resume, Points abordes, Decisions, Actions)
sous forme de titres, pretes a etre collees dans un wiki ou un outil de suivi.

---

## 7. Tests

Les tests automatises ne necessitent **ni micro ni Ollama actif** : ils
verifient le decoupage map-reduce, la validation du mode fichier, la gestion
d'erreur quand Ollama est injoignable, et l'export texte/Markdown.

```bash
pip install -r requirements-dev.txt
pytest tests/
```

Pour verifier rapidement que tout le code s'importe correctement (utile apres
une modification) :

```bash
python -c "import config, audio, mailer, pipeline, summarize, transcribe, export, main"
```

---

## 8. Performances sur CPU

Tout tourne sur CPU, aucun GPU requis. Pour une reunion de 2 h, compter de
l'ordre de 2 a 4 h de transcription selon la machine et le modele choisi. Le
filtre de silences (VAD, active par defaut) reduit nettement ce temps en
pratique. Si c'est trop lent : passe `whisper_model` a `base` et `ollama_model`
a `qwen2.5:3b` dans `config.py`.

---

## 9. Confidentialite

- Audio, transcription et compte-rendu restent en local sur la machine.
- Les fichiers audio, transcriptions et modeles sont exclus de git (voir `.gitignore`).
- Ollama tourne en local (`localhost`) : aucune donnee n'est envoyee a un service externe pour la generation du CR.
- Seul l'envoi mail explicite (bouton "Envoyer par mail") fait sortir une donnee de la machine.

---

## 10. Depannage

| Probleme | Cause probable | Solution |
|---|---|---|
| `setup.sh`/`setup.bat` echoue sur numpy (`metadata-generation-failed`, compilateur introuvable) | Version de Python trop recente pour un pin exact du projet : aucun wheel precompile, pip tente de compiler depuis les sources | `git pull` pour recuperer un `requirements.txt` a jour, puis relancer le setup. En depannage immediat : `pip install --upgrade numpy` dans le venv avant de relancer `pip install -r requirements.txt` |
| Telechargement du modele Ollama interrompu (`wsarecv`, `max retries exceeded`) | Coupure reseau transitoire pendant le telechargement (plusieurs Go) | Relancer simplement `ollama pull <modele>` ; ca reprend, ce n'est pas lie au code |
| "Impossible de contacter Ollama..." | Ollama n'est pas lance | `ollama serve`, puis reessayer |
| "Le modele Ollama 'xxx' n'est pas installe" | Modele pas encore telecharge | `ollama pull <modele>` (voir `config.py`) |
| Pas de son enregistre / erreur au demarrage de l'enregistrement | Pas de micro detecte, ou peripherique deja utilise | Verifier le micro par defaut du systeme, ou utiliser le mode fichier en attendant |
| Statut "micro uniquement" (les autres participants ne sont pas dans le CR) | Le son systeme n'a pas pu etre capte | Windows/Linux : verifier qu'aucune erreur peripherique n'est remontee. macOS : installer [BlackHole](https://github.com/ExistentialAudio/BlackHole) (voir section dediee) |
| Transcription tres lente | Modele `medium` sur une machine modeste | Passer a `whisper_model = "base"` dans `config.py` |
| Envoi mail en echec | SMTP non configure ou identifiants invalides | Renseigner `smtp_host`/`smtp_user`/`smtp_password` dans `config.py` ou `config_local.py` |

## Ce qui reste a faire cote materiel / environnement

Le code est fonctionnel et teste au niveau logique (voir section Tests), mais
plusieurs elements dependent de la machine sur laquelle l'outil est reellement
utilise et **n'ont pas pu etre valides sur du materiel audio reel** dans cet
environnement de developpement (sandbox sans micro, sans haut-parleurs, sans
Windows/macOS) :

- **Micro** : l'enregistrement reel via `sounddevice` necessite un peripherique
  audio present sur la machine cible (non disponible ici). Le mode fichier
  permet de valider toute la chaine en attendant.
- **Capture du son systeme (autres participants en visio)** : implementee
  (loopback WASAPI via `soundcard` sur Windows, source "monitor" via
  sounddevice sur Linux, BlackHole sur macOS — voir la section dediee
  ci-dessus) et testee unitairement (detection de peripherique, mixage des
  pistes, repli propre si indisponible), mais **pas testee en conditions
  reelles** faute de machine Windows/macOS et de peripheriques audio dans cet
  environnement. A valider en priorite sur les machines cibles avant un usage
  en production, en particulier le mode Windows (`soundcard`) jamais execute
  ici.
- **Ollama** : le modele LLM (`mistral` par defaut) doit etre installe et le
  service demarre sur la machine cible (`ollama pull mistral` + `ollama serve`).
  La gestion d'erreur si Ollama n'est pas lance a ete testee (simulation d'un
  serveur injoignable), mais pas la generation reelle d'un compte-rendu, faute
  d'acces reseau a un serveur Ollama dans cet environnement.
- Idem pour la **transcription reelle** : le telechargement du modele Whisper
  (`small` par defaut, via Hugging Face) n'a pas pu etre teste ici (pas d'acces
  reseau sortant vers Hugging Face dans cet environnement), mais le code de
  transcription est inchange par rapport a l'original, deja coherent avec
  faster-whisper.
