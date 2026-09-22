# Composant Appian d'enregistrement de reunion

Permet a un utilisateur d'enregistrer sa reunion **depuis n'importe quelle
interface Appian**, et de recuperer la transcription et le compte rendu dans
des variables de cette interface.

---

## Construire le plugin

```bash
python construire_plugin.py
```

Produit `dist/mcr-enregistreur-1.0.0.jar`. Ce fichier est fabrique a partir de
`static/` : **ne jamais modifier les fichiers copies dans `appian/`**, ils sont
ecrases a chaque construction. Toute correction de la page d'enregistrement se
fait dans `static/`, puis on reconstruit.

## Deployer

Administration Appian > **Plug-ins** > deposer le `.jar`. Ou, sur un serveur
auto-heberge, le copier dans le dossier des plug-ins et redemarrer.

## Utiliser dans une interface

```
a!localVariables(
  local!transcription,
  local!compteRendu,
  {
    mcrEnregistreur(
      reference: ri!numeroDossier,
      urlService: cons!MCR_URL_SERVICE,
      libelleBouton: "Enregistrer la reunion",
      transcription: local!transcription,
      compteRendu: local!compteRendu
    ),
    a!paragraphField(
      label: "Compte rendu",
      value: local!compteRendu,
      readOnly: true
    )
  }
)
```

| Parametre | Role |
|---|---|
| `reference` | Identifiant metier — suit l'enregistrement et permet de le retrouver cote service |
| `urlService` | Adresse du service de transcription, par exemple `https://transcription.interne/` |
| `libelleBouton` | Libelle du bouton, pour coller au vocabulaire de l'application |
| `transcription` | Recoit le texte transcrit |
| `compteRendu` | Recoit le compte rendu redige |

Mettre `urlService` dans une **constante**, pas en dur : elle change d'un
environnement a l'autre.

---

## Pourquoi une fenetre separee

C'est la question qu'on posera en revue, autant y repondre ici.

L'iframe dans laquelle Appian affiche un composant autorise `microphone`,
`geolocation`, `camera` et `autoplay` — **mais pas `display-capture`**. Or
c'est `display-capture` qui permet de capter le son de l'ordinateur, donc
d'entendre les autres participants d'une reunion a distance. Un composant qui
enregistrerait directement dans son iframe ne capterait que la personne
devant l'ecran, ce qui n'a aucun interet pour un compte rendu.

Le bac a sable d'Appian autorise en revanche `allow-popups-to-escape-sandbox`.
Une fenetre ouverte depuis le composant n'est plus bridee : elle retrouve tous
ses droits de capture. L'enregistrement s'y deroule, et le resultat revient au
composant par `postMessage`, qui le remonte a l'interface.

Le composant ne lit que les messages venant de la fenetre qu'il a lui-meme
ouverte : une autre page ne peut pas ecrire dans l'interface Appian.

## Ce qu'il faut cote service

Le composant n'appelle pas le moteur de transcription : il appelle le service,
qui detient le jeton. **Ce jeton ne descend jamais dans le navigateur** — sinon
chaque utilisateur pourrait le lire et s'en servir.

Le service doit donc :

1. **tourner et etre joignable depuis le poste de l'utilisateur** ;
2. **etre servi en HTTPS** si Appian l'est — un navigateur refuse qu'une page
   securisee appelle une adresse qui ne l'est pas (`localhost` fait exception,
   ce qui permet de tester depuis son poste) ;
3. **nommer l'origine d'Appian** dans son `.env`, sinon le navigateur bloque
   l'appel :

```
MEETING_ORIGINES=https://votre-appian.exemple
```

Sans ce reglage, le bouton ouvrira bien la fenetre, mais l'enregistrement
echouera au premier envoi — et le message du navigateur ne dira pas pourquoi.
C'est le premier endroit a regarder en cas de panne.
