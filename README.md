# Meeting-CT

Transcription de reunion **dans le navigateur**, transcrite **en local**.

Les utilisateurs ouvrent une page web, enregistrent leur reunion (micro **et**
son de l'ordinateur, donc les autres participants d'une visio), et recuperent
le texte. La transcription tourne sur le serveur avec faster-whisper : aucun
service externe n'est appele, aucune donnee n'est envoyee sur internet.

Pas de compte-rendu automatique : l'outil produit **le texte**, que tu reprends
ensuite dans l'outil de ton choix.

## Fonctionnement en un coup d'oeil

1. Le navigateur capte le micro et, si demande, le son de l'ordinateur
2. L'audio est envoye au serveur **au fil de l'eau** (rien ne s'accumule en
   memoire : une reunion de 2 h passe sans probleme)
3. Le serveur transcrit avec faster-whisper (CPU, en local), modele
   `large-v3-turbo` par defaut
4. Le texte s'affiche : a copier, telecharger en `.txt`, ou effacer du serveur

---

## 1. Prerequis

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Git](https://img.shields.io/badge/Git-Telecharger-F05032?logo=git&logoColor=white)](https://git-scm.com/downloads)

- **Python 3.10+** sur la machine qui heberge le serveur
- **Git** pour recuperer le code
- **~2 Go d'espace disque** pour le modele de transcription
- Cote utilisateurs : **Chrome ou Edge** (voir la limite navigateur ci-dessous)

> Nouveau sur ces outils ? Le [guide d'installation detaille](TUTORIEL.md)
> explique pas a pas comment installer Python et Git.

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
pre-telecharge le modele Whisper (**environ 1,6 Go**, une seule fois ; le
telechargement reprend tout seul en cas de coupure).
Le modele est ainsi deja sur le disque avant la premiere reunion : rien ne se
telecharge au moment ou tu attends ton texte.

## 3. Lancer le serveur

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

Puis ouvrir **http://127.0.0.1:8000** dans le navigateur.

---

## 4. Utilisation

1. Coche (ou non) **"Capter aussi le son de l'ordinateur"**.
2. Renseigne les **"Mots a ne pas ecorcher"** : noms des participants, du
   projet, sigles metier. C'est facultatif, mais c'est le geste qui evite les
   orthographes fantaisistes sur le vocabulaire maison. La liste est retenue
   par le navigateur pour les reunions suivantes.
3. Clique sur **"Demarrer l'enregistrement"**, autorise le micro.
4. Si le son de l'ordinateur est demande, le navigateur demande quoi partager :
   choisis **l'onglet ou l'ecran de la visio** et **coche « Partager l'audio »**.
   Sans cette case, seul ton micro sera enregistre.
5. A la fin, clique sur **"Arreter et transcrire"**.
6. Le texte s'affiche : **Copier**, **Telecharger (.txt)**, ou
   **Effacer du serveur**.

### Capter les autres participants : ce qu'il faut savoir

Un navigateur **ne peut pas** lire le son du systeme comme une application de
bureau. Le seul moyen prevu par les navigateurs est le partage d'ecran avec
audio (`getDisplayMedia`) : c'est pour cela que la page demande de partager un
onglet ou un ecran. **La video n'est jamais enregistree** : elle est simplement
laissee de cote, seul le son est conserve. (Elle n'est pas non plus coupee : sous
Chrome, arreter la piste video met fin a tout le partage, y compris au son.)

| Navigateur | Son de l'ordinateur |
|---|---|
| **Chrome / Edge (Windows)** | Oui — partage d'un onglet ou de l'ecran entier, avec « Partager l'audio » |
| **Chrome / Edge (macOS)** | Partiel — l'audio d'onglet fonctionne, pas l'audio systeme complet |
| **Firefox** | Non — micro uniquement |

Si le son de l'ordinateur n'est pas disponible ou refuse, l'enregistrement
continue **avec le micro seul** et la page le signale clairement.

---

## 5. Ouvrir l'acces aux autres postes

Par defaut le serveur n'ecoute que sur `127.0.0.1` : accessible **depuis le
poste qui l'heberge uniquement**. Pour en faire un service utilisable par une
equipe, dans `config.py` :

```python
host: str = "0.0.0.0"     # ecoute sur toutes les interfaces reseau
```

Les autres postes ouvrent alors `http://<ip-du-serveur>:8000`.

**Deux points a connaitre avant de faire ca :**

- **Confidentialite** : l'audio des reunions quitte alors le poste de
  l'utilisateur pour aller vers le serveur. Tout reste sur ton reseau (rien ne
  part sur internet), mais ce n'est plus "tout reste sur ma machine". Si cette
  garantie compte, chacun lance le serveur sur son propre poste et utilise
  `127.0.0.1`.
- **Micro et navigateur** : hors `localhost`, les navigateurs n'autorisent le
  micro que sur des pages **HTTPS**. En HTTP simple, seul le poste serveur
  pourra enregistrer. Pour un usage en equipe, il faut donc placer le serveur
  derriere un reverse proxy avec un certificat (nginx, Caddy...).

---

## 6. Configuration

Tout se regle dans `config.py` :

| Parametre | Role | Valeur par defaut |
|---|---|---|
| `whisper_model` | Modele : `small` (rapide, approximatif), `medium`, `large-v3-turbo` (precis et raisonnable sur CPU), `large-v3` (le plus precis, tres lent) | `large-v3-turbo` |
| `whisper_device` / `whisper_compute` | CPU + quantification (pas de GPU requis). `int8_float32` est un cran plus fidele, `float32` encore plus mais 2 a 3 fois plus lent | `cpu` / `int8` |
| `beam_size` | Hypotheses comparees par le decodeur. `5` = qualite de reference, `1` = plus rapide et plus fautif | `5` |
| `vocabulaire` | Mots souffles au modele pour toutes les reunions (le champ de la page s'y ajoute pour une reunion donnee) | vide |
| `cpu_threads` | Coeurs utilises. `0` = tous | `0` |
| `language` | Langue de la transcription | `fr` |
| `host` / `port` | Adresse d'ecoute du serveur | `127.0.0.1` / `8000` |
| `transcriptions_simultanees` | Transcriptions en parallele. `1` = les demandes s'enchainent, recommande sur CPU | `1` |

Apres avoir change `whisper_model`, relancer `python telecharge_modele.py`
pour recuperer le nouveau modele.

### Ameliorer la qualite de la transcription

Par ordre d'efficacite, si le texte n'est pas assez propre :

1. **Le son d'abord.** Un mot mal capte ne sera jamais bien transcrit. Le
   bouton **"Ecouter l'audio"** rejoue exactement ce que le serveur a recu :
   si une voix y est faible, lointaine ou saturee, le probleme est a la prise
   de son (micro, position, casque des participants), pas au modele. Les
   barres de niveau pendant l'enregistrement servent au meme diagnostic.
2. **Les "mots a ne pas ecorcher"** dans la page : noms propres, produits,
   sigles. Gain immediat sur le vocabulaire specifique a l'equipe.
3. **Un modele plus gros** : `whisper_model = "large-v3"` dans `config.py`,
   puis `python telecharge_modele.py`. Nettement plus lent sur CPU.
4. **Un calcul plus fidele** : `whisper_compute = "int8_float32"`, puis
   `"float32"`. Aucun nouveau telechargement, seulement plus de temps machine.

Ce qui est deja regle par defaut, sans avoir a y toucher : le decodage compare
plusieurs hypotheses (`beam_size = 5`), le texte deja produit n'est pas
reinjecte comme contexte (c'est ce qui evite les boucles de repetition de
Whisper), les silences sont ecartes avant transcription, et chaque source audio
est attenuee avant melange pour ne pas saturer l'enregistrement.

---

## 7. Tests

```bash
pip install -r requirements-dev.txt
pytest tests/
```

Les tests couvrent l'API du serveur (session, envoi au fil de l'eau, suivi,
telechargement, effacement, cas d'erreur), le telechargeur de modele avec
reprise, et les contournements reseau. Ils ne necessitent ni micro, ni modele
Whisper installe.

---

## 8. Performances sur CPU

Tout tourne sur CPU, aucun GPU requis. Compter de l'ordre de la duree de la
reunion, parfois davantage, selon la machine et le modele choisi. Le filtre de
silences (VAD, actif par defaut) reduit nettement ce temps en pratique.

Le modele par defaut `large-v3-turbo` est un compromis : sa qualite est proche
du plus gros modele, mais son decodeur allege le rend **plus rapide que
`medium`**. Si c'est encore trop lent sur la machine, dans `config.py` :
`beam_size = 1` d'abord (gain immediat, sans retelecharger), puis
`whisper_model = "small"` (et `python telecharge_modele.py`).

Avec `transcriptions_simultanees = 1`, plusieurs utilisateurs simultanes sont
mis en file d'attente (la page l'indique) plutot que de saturer le processeur.

---

## 9. Confidentialite

- La transcription tourne **en local**, sur la machine qui heberge le serveur.
  Aucun service externe, aucune cle d'API, aucun envoi sur internet.
- L'audio et le texte sont stockes dans un dossier temporaire du serveur, et
  supprimes par le bouton **"Effacer du serveur"**.
- Les fichiers audio, transcriptions et modeles sont exclus de git (voir
  `.gitignore`).
- Seule sortie reseau du projet : le telechargement initial du modele Whisper
  (`telecharge_modele.py`), une seule fois a l'installation.

---

## 10. Depannage

| Probleme | Cause probable | Solution |
|---|---|---|
| "Le modele Whisper 'xxx' n'est pas installe sur cette machine" | Modele pas encore telecharge (le serveur ne telecharge jamais rien tout seul, pour ne pas bloquer en pleine reunion) | `python telecharge_modele.py` : telechargement avec reprise automatique sur coupure, relançable autant de fois que necessaire |
| Telechargement du modele lent ou hache | Reseau instable | C'est prevu : un blocage est detecte en 30 s max et le transfert reprend a l'octet exact ou il s'est arrete. Laisser tourner, ou relancer plus tard, rien n'est perdu |
| Le navigateur n'enregistre que le micro | Case « Partager l'audio » non cochee lors du partage, ou navigateur non compatible | Rechoisir le partage en cochant « Partager l'audio » ; utiliser Chrome ou Edge |
| Le micro n'est pas propose sur un autre poste | Les navigateurs exigent HTTPS hors `localhost` | Voir la section "Ouvrir l'acces aux autres postes" |
| Transcription approximative, mots inventes | Voix trop faible a la prise de son, ou modele trop leger | Ecouter l'audio recu (bouton **"Ecouter l'audio"**) pour situer le probleme, puis voir "Ameliorer la qualite de la transcription" |
| "Aucun son n'a ete recu" a l'arret | Micro refuse ou muet | Verifier l'autorisation du micro dans le navigateur et le peripherique d'entree du systeme |
| Installation qui echoue sur un paquet (`metadata-generation-failed`, "Microsoft Visual C++ required") | Version de Python tres recente : pas de wheel precompile pour ce paquet | `git pull` pour recuperer un `requirements.txt` a jour, puis relancer l'installation |
