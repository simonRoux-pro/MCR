"""Assemble le plugin de composant Appian.

    python construire_plugin.py

Produit dist/mcr-enregistreur-<version>.jar — un fichier ZIP, que l'on depose
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
    archive = SORTIE / f"mcr-enregistreur-{version}.jar"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_:
        # Un JAR porte toujours ce fichier, en premiere position. Le notre ne
        # contient aucune classe Java, mais un outil qui refuserait une archive
        # sans manifeste nous rejetterait sans expliquer pourquoi.
        zip_.writestr("META-INF/MANIFEST.MF",
                      "Manifest-Version: 1.0\r\n"
                      f"Implementation-Title: Enregistreur de reunion\r\n"
                      f"Implementation-Version: {version}\r\n"
                      "\r\n")
        for chemin in sorted(SOURCE_PLUGIN.rglob("*")):
            if chemin.is_file():
                zip_.write(chemin, chemin.relative_to(SOURCE_PLUGIN).as_posix())

    return archive


if __name__ == "__main__":
    archive = construire()
    taille = archive.stat().st_size
    print(f"Plugin construit : {archive.relative_to(DOSSIER)} ({taille // 1024} Ko)")
    with zipfile.ZipFile(archive) as zip_:
        for nom in sorted(zip_.namelist()):
            print("   ", nom)
    print()
    print("A deposer dans Appian : Administration > Plug-ins.")
