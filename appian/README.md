# Composant Appian d'enregistrement de reunion

Permet a un utilisateur d'enregistrer sa reunion **depuis n'importe quelle
interface Appian**, et de recuperer la transcription et le compte rendu dans
des variables de cette interface.

---

## Construire le plugin

```bash
python construire_plugin.py
```

Produit `dist/mcr-enregistreur-1.0.0.zip`. Ce fichier est fabrique a partir de
`static/` : **ne jamais modifier les fichiers copies dans `appian/`**, ils sont
ecrases a chaque construction. Toute correction de la page d'enregistrement se
fait dans `static/`, puis on reconstruit.

## Deployer

**Ce n'est pas un package applicatif.** Appian distingue deux choses :

| | Package applicatif | Plug-in |
|---|---|---|
| Format | `.zip` | `.zip` pour un composant, `.jar` pour du code Java |
| Contenu | des objets Appian : interfaces, regles, integrations | du code qui etend Appian |
| Ou | Concepteur > Applications > Importer | le **serveur** Appian |

Un composant etend le langage d'interface — il ajoute la fonction
`mcrEnregistreur()`. Cela ne peut pas s'importer comme un package : il faut
que le serveur le charge.

Un composant se livre en **`.zip`** : le manifeste et les dossiers de
composants a la racine de l'archive. Le `.jar` est la forme des plug-ins qui
embarquent du code Java — fonctions, services intelligents, systemes
connectes. Un composant n'est que du contenu web.

Seuls certains types de fichiers sont acceptes dans ce contenu : `.html`,
`.htm`, `.css`, `.less`, `.js`, `.woff`, `.woff2`, `.png`, `.gif`, `.jpg`,
`.jpeg`, `.svg`, `.ico`, `.map`. `construire_plugin.py` ecarte le reste et le
dit a l'ecran.

**Site auto-heberge** — la voie normale en developpement :

```bash
cp mcr-enregistreur-1.0.0.zip <APPIAN_HOME>/_admin/plugins/
```

Le chargement est a chaud : Appian relit ce dossier a intervalle regulier
(`conf.plugins.poll-interval` dans `custom.properties`), il n'y a donc rien a
redemarrer. Le journal du serveur confirme le chargement, et signale l'erreur
si le manifeste lui deplait.

**Site Appian Cloud** : Administration > **Plug-ins**.

**Un composant peut exiger une signature d'Appian.** La documentation d'Appian
indique que les composants, contrairement aux autres types de plug-ins,
passent par une revue : une fois approuve, on recoit une copie du plug-in
signee par Appian, qui seule s'installe partout. Si le deploiement echoue avec
un message d'approbation dans le journal du serveur applicatif, c'est cela —
et aucune correction de l'archive n'y changera rien.

**Verifier que c'est charge** : dans le concepteur d'interface, taper
`mcrEnregistreur(` — la fonction doit etre proposee avec ses parametres. Si
elle n'apparait pas, le plug-in n'est pas charge : regarder le journal du
serveur, pas l'interface.

Le `.zip` que vous exporterez plus tard, c'est votre **application** (les
interfaces qui utilisent ce composant) — un objet different, a creer dans le
concepteur.

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
