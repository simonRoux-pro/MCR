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

## Cote Appian

**Afficher l'outil.** Un lien, ou un `a!webContentField` pointant sur l'URL
avec la reference :

```
a!webContentField(
  source: "https://<outil>/?ref=" & ri!numeroDossier,
  height: "TALL"
)
```

**Point a verifier avant de choisir l'iframe** : la capture du micro et du son
de l'ordinateur n'y fonctionne que si Appian delegue les permissions
correspondantes (`allow="microphone; display-capture"` sur son iframe). La
question a poser a l'administrateur de la plateforme :

> *Les iframes des interfaces Appian portent-elles `microphone` et
> `display-capture` dans leur Permissions Policy, et est-ce configurable ?*

Si la reponse est non, on ouvre l'outil dans un onglet plutot qu'en iframe :
tout le reste de l'integration est identique.

**Recuperer le resultat.** Un objet *Integration* en GET sur
`/api/reunions/{ref}`, avec la cle dans l'en-tete, appele depuis un bouton
(« Recuperer le compte rendu ») ou depuis un noeud de processus. Le JSON se
mappe directement dans un enregistrement.

**Rien a installer cote Appian** : pas de plugin, pas de composant a deployer.
Un lien et un objet Integration, donc du parametrage reproductible d'un
environnement a l'autre et d'un client a l'autre.
