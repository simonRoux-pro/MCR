"""Assemble le plugin de composant Appian.

    python construire_plugin.py

Produit dist/mcr-enregistreur-<version>.zip — un fichier ZIP, que l'on depose
dans Appian (Administration > Plug-ins, ou le dossier des plug-ins du serveur).

POURQUOI UN SCRIPT ET PAS DES FICHIERS COPIES A LA MAIN.
La fenetre d'enregistrement du plugin EST la page de l'outil, celle de
static/. La dupliquer dans le depot garantirait qu'un jour les deux versions
divergent, et qu'une correction faite d'un cote manquerait de l'autre. Le
plugin est donc fabrique a partir de la source, jamais recopie.

CE QUE LE PLUGIN NE CONTIENT PAS.
Aucun jeton, aucun secret : le composant ne connait que l'adresse du service,
qui lui est donnee par l'interface. Le jeton du moteur de transcription reste
cote serveur, ou il doit rester.
"""

import os
import re
import shutil
import zipfile
from pathlib import Path

DOSSIER = Path(__file__).parent
SOURCE_PLUGIN = DOSSIER / "appian"
SOURCE_PAGE = DOSSIER / "static"
SORTIE = DOSSIER / "dist"

MANIFESTE = "appian-component-plugin.xml"

# Les seuls types de fichiers qu'Appian accepte dans le contenu web d'un
# composant. Un fichier d'un autre type fait echouer le deploiement.
EXTENSIONS_WEB = {".html", ".htm", ".css", ".less", ".js", ".woff", ".woff2",
                  ".png", ".gif", ".jpg", ".jpeg", ".svg", ".ico", ".map"}


def version_du_manifeste(texte: str) -> str:
    """La version declaree dans le manifeste, pour nommer le fichier produit.

    Une seule source de verite : si le nom du fichier etait ecrit ailleurs, il
    finirait par ne plus correspondre a ce que le manifeste annonce."""
    trouve = re.search(r"<version>([^<]+)</version>", texte)
    if not trouve:
        raise SystemExit(f"Aucune <version> dans {MANIFESTE}.")
    return trouve.group(1).strip()


def dossier_du_composant(texte: str) -> Path:
    """Le dossier impose par Appian : <rule-name>/v<numero majeur>."""
    nom = re.search(r'rule-name="([^"]+)"', texte)
    version = re.search(r'<component[^>]*version="([^"]+)"', texte)
    if not nom or not version:
        raise SystemExit(f"rule-name ou version du composant absents de {MANIFESTE}.")
    return SOURCE_PLUGIN / nom.group(1) / ("v" + version.group(1).split(".")[0])


def construire() -> Path:
    ecartes: list[str] = []
    manifeste = (SOURCE_PLUGIN / MANIFESTE).read_text(encoding="utf-8")
    version = version_du_manifeste(manifeste)
    composant = dossier_du_composant(manifeste)
    if not (composant / "index.html").is_file():
        raise SystemExit(f"index.html du composant introuvable dans {composant}.")

    # La page de l'outil devient la fenetre d'enregistrement du plugin. Ses
    # chemins sont deja relatifs, il n'y a donc rien a reecrire.
    shutil.copy(SOURCE_PAGE / "index.html", composant / "enregistreur.html")
    cible_statique = composant / "static"
    shutil.rmtree(cible_statique, ignore_errors=True)
    cible_statique.mkdir(parents=True)
    for fichier in ("app.js", "style.css"):
        shutil.copy(SOURCE_PAGE / fichier, cible_statique / fichier)

    SORTIE.mkdir(exist_ok=True)
    # Un composant se livre en .zip, pas en .jar : le .jar est la forme des
    # plug-ins qui embarquent du code Java (fonctions, services intelligents).
    # Un composant n'est que du contenu web, et Appian attend une archive dont
    # la racine porte le manifeste et les dossiers de composants.
    archive = SORTIE / f"mcr-enregistreur-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_:
        for chemin in sorted(SOURCE_PLUGIN.rglob("*")):
            if not chemin.is_file():
                continue
            interne = chemin.relative_to(SOURCE_PLUGIN).as_posix()
            # Appian n'accepte que certains types de fichiers dans le contenu
            # web. Tout le reste — documentation, notes — doit rester hors de
            # l'archive, sous peine de refus sans explication.
            if interne != MANIFESTE and chemin.suffix.lower() not in EXTENSIONS_WEB:
                ecartes.append(interne)
                continue
            zip_.write(chemin, interne)

    return archive, ecartes


if __name__ == "__main__":
    archive, ecartes = construire()
    taille = archive.stat().st_size
    print(f"Plugin construit : {archive.relative_to(DOSSIER)} ({taille // 1024} Ko)")
    with zipfile.ZipFile(archive) as zip_:
        for nom in sorted(zip_.namelist()):
            print("   ", nom)
    if ecartes:
        # Dit a voix haute ce qui n'est pas entre : un fichier manquant a
        # l'execution se diagnostique mal, un fichier annonce comme ecarte se
        # remarque tout de suite.
        print()
        print("Ecartes (type non accepte par Appian) :")
        for nom in ecartes:
            print("   ", nom)
    print()
    print("A deposer dans Appian : Administration > Plug-ins.")
