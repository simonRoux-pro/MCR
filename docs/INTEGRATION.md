# Integrer l'outil dans une autre application

Ce document s'adresse au developpeur qui branche l'outil de transcription dans
une application tierce — Appian ou autre. Il decrit un contrat stable : ces
deux routes ne changeront pas sans preavis.

Le principe tient en une phrase : **l'application appelante fournit sa propre
reference, et relit le resultat avec cette meme reference.** Elle n'a jamais
besoin de connaitre les identifiants internes de l'outil.

---

## 1. Ouvrir l'outil avec une reference

```
https://<outil>/?ref=DOSSIER-2026-0412
```

Dans un lien, un bouton, ou une iframe. La reference est libre : c'est
l'identifiant metier de l'application appelante (numero de dossier, de
demande, de reunion...). Elle est rappelee a l'ecran pour que l'utilisateur
voie a quoi son enregistrement se rattache.

L'utilisateur enregistre sa reunion normalement. Rien ne change pour lui.

## 2. Relire le resultat

```
GET https://<outil>/api/reunions/DOSSIER-2026-0412
X-Cle-Api: <cle>
```

```json
{
  "ref": "DOSSIER-2026-0412",
  "etat": "termine",
  "debut": "2026-09-18T14:30:00",
  "transcription": "Moi : bonjour a tous...\n\nReunion : d'accord...",
  "compteRendu": "# Compte rendu\n\n...",
  "compteRenduEtat": "pret",
  "erreur": ""
}
```

| Champ | Contenu |
|---|---|
| `etat` | `enregistrement`, `attente`, `transcription`, `finalisation`, `termine`, `echec` |
| `transcription` | Le texte, etiquete par locuteur. Vide tant que rien n'est transcrit |
| `compteRendu` | Le compte rendu redige, vide s'il n'a pas ete demande |
| `compteRenduEtat` | `absent`, `en_cours`, `pret`, `echec` |
| `erreur` | Message explicite quand `etat` vaut `echec` |

**Interroger avant la fin est prevu** : la route repond avec l'etat en cours
plutot qu'une erreur. L'appelant peut donc afficher « transcription en
cours » et reinterroger plus tard.

Une reference inconnue renvoie **404**. Si la meme reference a servi plusieurs
fois, c'est le **dernier** enregistrement qui est renvoye — une reunion peut
etre refaite apres un faux depart.

## 3. La cle d'API

Tant que `MEETING_CLE_API` n'est pas defini, la route est ouverte : c'est ce
qui permet de travailler en local sans ceremonie.

**Des que le serveur est joignable depuis autre chose que la machine qui
l'heberge, definir une cle** dans le `.env` :

```
MEETING_CLE_API=une-chaine-longue-et-aleatoire
```

L'appelant la fournit alors dans l'en-tete `X-Cle-Api`. Une transcription de
reunion n'a pas a etre lisible par qui devine une reference.

## 4. En iframe : la notification au parent

Quand l'outil tourne dans une iframe, il previent la page qui l'heberge, sans
qu'elle ait a interroger quoi que ce soit :

```js
window.addEventListener("message", (e) => {
  if (e.data?.source !== "meeting-ct") return;
  // e.data.evenement : "transcription" ou "compteRendu"
  // e.data.ref, e.data.transcription, e.data.compteRendu
});
```

Sans effet en navigation normale.

---

## HTTPS : prealable, pas option

Les navigateurs n'autorisent l'acces au micro et a la capture d'ecran que dans
un **contexte securise**, c'est a dire en HTTPS. `localhost` est la seule
exception, ce qui permet de travailler sur son poste sans certificat.

Consequence : **des que l'outil est joint par son adresse reseau, il lui faut
un certificat**, sinon le micro est refuse et l'outil ne sert a rien. Ce n'est
pas une exigence de l'application appelante, c'est une regle du navigateur.

```
MEETING_SSL_CERT=/chemin/certificat.pem
MEETING_SSL_KEY=/chemin/cle.pem
```

Pour une demonstration, `python genere_certificat.py <nom-ou-ip>` fabrique un
certificat auto-signe. Il affiche un avertissement a accepter une fois par
poste — et **une iframe pointant sur un certificat auto-signe reste vide sans
message**, car on ne peut pas accepter l'avertissement depuis une iframe. Il
faut donc ouvrir l'adresse une fois dans un onglet, accepter, puis revenir.

Pour un vrai deploiement, demander un certificat a l'autorite interne de
l'organisation : meme reglage, plus aucun avertissement.

---

## Cote Appian

### Afficher l'outil

`a!webContentField` **refuse une source en HTTP** — la validation echoue des la
conception, avec « La source doit etre securisee (HTTPS) ». L'outil doit donc
servir en HTTPS (voir ci-dessus).

```
a!webContentField(
  source: "https://<outil>/?ref=" & ri!numeroDossier,
  height: "TALL"
)
```

**Second point a verifier** : la capture du micro et du son ne fonctionne dans
une iframe que si la page hote delegue les permissions correspondantes
(`allow="microphone; display-capture"`). C'est Appian qui genere la balise, on
ne peut pas le forcer depuis l'interface. La question a poser a
l'administrateur de la plateforme :

> *Les iframes des `a!webContentField` portent-elles `microphone` et
> `display-capture` dans leur Permissions Policy, et est-ce configurable ?*

### Si l'iframe ne convient pas

On ouvre l'outil dans un onglet. **Le reste de l'integration ne change pas
d'une ligne** : l'iframe est un confort d'ergonomie, pas une dependance.

```
a!linkField(
  links: a!safeLink(
    label: "Enregistrer la reunion",
    uri: "https://<outil>/?ref=" & ri!numeroDossier
  )
)
```

### Recuperer le resultat

Un objet *Integration* en GET sur `/api/reunions/{ref}`, la cle d'API portee
par un *Connected System* (jamais en dur dans l'objet), appele depuis un bouton
« Recuperer le compte rendu » ou depuis un noeud de processus.

Cet appel part du **serveur** Appian, pas du navigateur : l'outil doit lui etre
joignable. Un outil qui tourne sur le poste de l'utilisateur ne l'est pas.

Prevoir le cas ou `etat` ne vaut pas encore `termine` : afficher
« transcription en cours » et laisser reinterroger, plutot qu'un appel
automatique qui tomberait trop tot.

**Rien a installer cote Appian** : pas de plugin, pas de composant a deployer.
Un lien et un objet Integration, donc du parametrage reproductible d'un
environnement a l'autre et d'un client a l'autre.
