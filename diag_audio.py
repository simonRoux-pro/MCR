"""Diagnostic de la capture du son systeme (voix des autres participants).

Repond a une seule question, sans ambiguite : la boucle audio capte-t-elle
reellement le son qui sort des haut-parleurs / du casque ?

Utilisation : lance une video ou une visio avec du son AUDIBLE, puis :

    python diag_audio.py

Le script liste les peripheriques, montre lequel serait retenu par
l'application, enregistre 5 secondes et affiche le niveau sonore mesure.
"""
import platform
import sys

import numpy as np

from audio import trouver_loopback_windows, find_loopback_device_sounddevice
from config import CONFIG

DUREE = 5           # secondes d'ecoute
SEUIL_SILENCE = 0.001


def niveau(bloc) -> float:
    bloc = np.asarray(bloc, dtype=np.float32)
    return float(np.abs(bloc).max()) if bloc.size else 0.0


def verdict(mesure: float, quoi: str):
    if mesure < SEUIL_SILENCE:
        print(f"\n  ECHEC : {quoi} n'a capte QUE DU SILENCE (niveau {mesure:.5f}).")
        return False
    print(f"\n  SUCCES : {quoi} capte bien du son (niveau max {mesure:.3f}).")
    return True


def diag_windows():
    import soundcard as sc

    version = getattr(sc, "__version__", "inconnue")
    print(f"soundcard {version} / numpy {np.__version__}")
    if tuple(int(x) for x in str(version).split(".")[:3] if x.isdigit()) < (0, 4, 6) \
            and int(np.__version__.split(".")[0]) >= 2:
        print("  ATTENTION : soundcard < 0.4.6 est incompatible avec numpy 2.x "
              "(numpy.fromstring supprime) : la capture du son systeme echouera.")
        print("  Corriger avec : pip install -r requirements.txt\n")
    else:
        print()

    haut_parleur = sc.default_speaker()
    print(f"Sortie audio par defaut : {haut_parleur.name}")
    print(f"  id : {haut_parleur.id}\n")

    micros = sc.all_microphones(include_loopback=True)
    print("Peripheriques d'entree vus par l'application :")
    for m in micros:
        genre = "BOUCLE (son systeme)" if getattr(m, "isloopback", False) else "micro reel"
        print(f"  - [{genre}] {m.name}")
    print()

    source = trouver_loopback_windows(sc, haut_parleur)
    if source is None:
        print("ECHEC : aucun peripherique de boucle disponible sur cette machine.")
        print("La capture du son systeme est impossible ; l'application enregistrera le micro seul.")
        return False

    print(f"Boucle retenue par l'application : {source.name}")
    print(f"\nEcoute de {DUREE} s... FAIS DU BRUIT MAINTENANT (video, visio) !", flush=True)
    with source.recorder(samplerate=CONFIG.samplerate, channels=None) as enregistreur:
        mesure = niveau(enregistreur.record(numframes=CONFIG.samplerate * DUREE))
    return verdict(mesure, "la boucle audio")


def diag_autres_os():
    import sounddevice as sd

    index = find_loopback_device_sounddevice()
    print("Peripheriques d'entree disponibles :")
    for i, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0:
            marque = "  <-- retenu" if i == index else ""
            print(f"  - {dev['name']}{marque}")
    print()

    if index is None:
        print("ECHEC : aucune source de boucle trouvee.")
        print("Linux : verifier PulseAudio/PipeWire (source 'monitor').")
        print("macOS : installer BlackHole (voir README).")
        return False

    print(f"Ecoute de {DUREE} s... FAIS DU BRUIT MAINTENANT (video, visio) !", flush=True)
    enregistrement = sd.rec(int(CONFIG.samplerate * DUREE), samplerate=CONFIG.samplerate,
                            channels=1, device=index)
    sd.wait()
    return verdict(niveau(enregistrement), "la boucle audio")


def main():
    print("== Diagnostic de la capture du son systeme ==\n")
    try:
        ok = diag_windows() if platform.system() == "Windows" else diag_autres_os()
    except Exception as e:
        print(f"\nECHEC du diagnostic : {type(e).__name__}: {e}")
        return 1

    if not ok:
        print("\n  Pistes, dans l'ordre :")
        print("  1. Le son doit sortir sur le peripherique PAR DEFAUT de Windows")
        print("     (Parametres > Systeme > Son) : si la video joue sur un autre")
        print("     peripherique que celui indique ci-dessus, la boucle ne l'entend pas.")
        print("  2. Verifier que du son etait bien audible PENDANT les 5 secondes d'ecoute.")
        print("  3. Certaines applications en mode exclusif privent la boucle de son :")
        print("     fermer puis rouvrir l'application qui joue le son.")
        return 1
    print("\nLa capture du son systeme fonctionne : les autres participants seront enregistres.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
