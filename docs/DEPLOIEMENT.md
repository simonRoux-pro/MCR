# Passer du poste de travail au serveur

Ce document repond a une question : l'outil marche sur mon poste, comment en
faire un service que l'on peut joindre, qui tourne seul, et que personne n'a
besoin de relancer ?

---

## Pourquoi votre poste ne peut pas faire l'affaire

Ce n'est pas une question de puissance. Trois raisons de fond :

| | Sur un poste | Ce qu'il faut |
|---|---|---|
| **Disponibilite** | s'eteint le soir, part en reunion | tourne en continu |
| **Adresse** | `127.0.0.1` ne designe que lui-meme | une adresse stable sur le reseau |
| **Joignabilite** | le serveur applicatif ne peut pas l'atteindre | joignable depuis ce serveur |

La troisieme est la plus contraignante et la moins visible. L'affichage de
l'outil se fait dans le **navigateur** de l'utilisateur, donc depuis son poste.
Mais la recuperation du resultat part du **serveur** de l'application
appelante. Un outil qui tourne sur le poste d'un utilisateur est invisible pour
ce serveur.

## Ce qu'il faut demander

Une seule chose : **une machine virtuelle Linux sur le reseau, avec Docker**.
Ni base de donnees, ni stockage partage, ni compte de service.

| Demande | Valeur | Pourquoi |
|---|---|---|
| Systeme | Linux, Docker installe | l'application est livree en conteneur |
| Processeur / memoire | 2 vCPU, 4 Go | suffisant avec le moteur GenIAL, qui ne calcule rien sur place |
| Disque | 20 Go | l'audio est efface au bout de quelques jours |
| Nom reseau | un nom stable, ex. `transcription.<domaine>` | il sera ecrit en dur dans l'application appelante |
| Certificat TLS | delivre par l'autorite interne, pour ce nom | sans HTTPS, les navigateurs refusent le micro |
| Flux entrant | 443 depuis les postes utilisateurs **et** depuis le serveur applicatif | les deux moities de l'integration |
| Flux sortant | vers l'API interne de transcription | c'est elle qui transcrit |

Le **certificat** est le point a lancer en premier : c'est ce qui prend le plus
de temps a obtenir, et rien ne fonctionne sans lui.

Pour le **moteur local** (transcription sur la machine, sans service externe),
compter plutot 8 vCPU et 8 Go, plus un volume pour le modele.

## Installation

```bash
git clone <depot> /opt/meeting-ct
cd /opt/meeting-ct
cp .env.exemple .env
```

Renseigner `.env` :

```
GENIAL_TOKEN=<le jeton>
MEETING_MOTEUR=genial
MEETING_MODE=differe
MEETING_MODELE=<le modele de redaction>

MEETING_DONNEES=/donnees
MEETING_RETENTION_JOURS=7

MEETING_CLE_API=<une chaine longue et aleatoire>

MEETING_SSL_CERT=/certificats/certificat.pem
MEETING_SSL_KEY=/certificats/cle.pem
```

Poser le certificat et sa cle dans `./certificats/`, puis decommenter les deux
lignes `MEETING_SSL_*` dans `docker-compose.yml`. Enfin :

```bash
docker compose up -d --build
docker compose logs -f
```

Verification, depuis n'importe quel poste du reseau :

```bash
curl -H "X-Cle-Api: <la cle>" https://transcription.<domaine>/api/reunions/TEST
```

Une reponse `{"erreur":"Aucune reunion pour la reference TEST."}` est le bon
resultat : le service repond, il n'y a simplement pas encore de reunion.

## « Qui le relance ? » — personne

C'est le role de `restart: unless-stopped` dans `docker-compose.yml` :

- l'application plante → Docker la relance ;
- la machine redemarre → Docker la relance ;
- on l'arrete a la main → elle reste arretee, sans se relancer toute seule.

Aucun script de demarrage a ecrire, aucun service systemd a declarer.

**Et les reunions en cours pendant un redemarrage ?** Elles sont conservees sur
disque (`MEETING_DONNEES`) et relues au demarrage. Une reunion deja transcrite
est retrouvee intacte ; une reunion qui etait en cours passe explicitement en
echec, avec le motif. C'est volontaire : un etat « transcription en cours »
qui n'avancerait plus jamais ferait attendre l'appelant indefiniment.

## Les trois reglages a ne pas oublier

Ce sont les trois seuls dont l'oubli produit une panne difficile a diagnostiquer.

**1. `MEETING_SSL_CERT` / `MEETING_SSL_KEY`.** Sans eux, les utilisateurs
voient la page mais le micro est refuse — et le message du navigateur ne dit
pas pourquoi. Le serveur affiche un avertissement au demarrage dans ce cas.

**2. `MEETING_CLE_API`.** Sans elle, la route de lecture est ouverte : qui
devine une reference lit la transcription. Acceptable sur un poste, pas sur un
service joignable.

**3. `MEETING_DONNEES`.** Sans lui, tout est perdu a chaque redemarrage.

## Ce qui est conserve, et combien de temps

Par reunion : l'audio, la transcription, le compte rendu, et un fichier d'etat.

Tout est efface automatiquement au bout de `MEETING_RETENTION_JOURS` (7 par
defaut), au demarrage puis une fois par jour. Une transcription de reunion est
une donnee sensible : elle ne doit pas s'accumuler parce que personne n'a pense
a faire le menage.

A confirmer avec le responsable de la protection des donnees : la duree de
conservation, et le fait que l'audio des reunions est transmis au service de
transcription.

## Etapes, dans l'ordre

1. Demander la machine et le certificat — **le certificat d'abord**, c'est le
   plus long.
2. Ouvrir les flux : 443 entrant depuis les postes et depuis le serveur
   applicatif, sortant vers l'API de transcription.
3. Installer, remplir `.env`, demarrer.
4. Verifier par le `curl` ci-dessus.
5. Brancher l'application appelante — voir `INTEGRATION.md`.

Les etapes 1 et 2 ne dependent pas de vous et prennent le plus de temps :
les lancer avant tout le reste.
