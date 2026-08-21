"""Tests de la detection/capture du son systeme et du mixage micro/systeme.
Ne necessitent aucun peripherique audio reel (sd.query_* et soundcard sont simules)."""
import sys
import types
from unittest.mock import patch, MagicMock
import numpy as np
import pytest

from audio import (AudioRecorder, find_loopback_device_sounddevice, _mix_blocks,
                   _en_colonne, trouver_loopback_windows)


class FauxPeripherique:
    """Imite un peripherique soundcard (id, name, isloopback)."""

    def __init__(self, id, name, isloopback=False):
        self.id = id
        self.name = name
        self.isloopback = isloopback


def _faux_soundcard(micros):
    sc = MagicMock()
    sc.all_microphones.return_value = micros
    return sc


# --- Selection du peripherique de boucle Windows ----------------------------

def test_boucle_choisie_par_identifiant_meme_si_un_micro_porte_le_meme_nom():
    """Cas reel a l'origine du bug : avec un casque, la sortie et le micro
    portent le MEME nom. sc.get_microphone(nom) renvoyait alors le micro au
    lieu de la boucle (on enregistrait deux fois sa propre voix). La selection
    doit se faire sur les peripheriques marques isloopback, par identifiant."""
    haut_parleur = FauxPeripherique("{0.0.0}-casque", "Casque Jabra")
    micros = [
        FauxPeripherique("{0.0.0}-casque", "Casque Jabra", isloopback=True),
        FauxPeripherique("{0.0.1}-micro", "Casque Jabra"),   # vrai micro, meme nom
    ]
    choisi = trouver_loopback_windows(_faux_soundcard(micros), haut_parleur)
    assert choisi.isloopback is True
    assert choisi.id == "{0.0.0}-casque"


def test_boucle_choisie_par_nom_si_identifiant_different():
    haut_parleur = FauxPeripherique("id-sortie", "Haut-parleurs")
    micros = [
        FauxPeripherique("id-autre", "Ecran HDMI", isloopback=True),
        FauxPeripherique("id-boucle", "Haut-parleurs", isloopback=True),
    ]
    choisi = trouver_loopback_windows(_faux_soundcard(micros), haut_parleur)
    assert choisi.id == "id-boucle"


def test_repli_sur_la_premiere_boucle_disponible():
    haut_parleur = FauxPeripherique("id-inconnu", "Sortie inconnue")
    micros = [
        FauxPeripherique("id-b1", "Ecran HDMI", isloopback=True),
        FauxPeripherique("id-micro", "Micro USB"),
    ]
    choisi = trouver_loopback_windows(_faux_soundcard(micros), haut_parleur)
    assert choisi.id == "id-b1"


def test_aucune_boucle_disponible_retourne_none():
    haut_parleur = FauxPeripherique("id-sortie", "Haut-parleurs")
    micros = [FauxPeripherique("id-micro", "Micro USB")]   # que des micros reels
    assert trouver_loopback_windows(_faux_soundcard(micros), haut_parleur) is None


def test_detecte_la_source_monitor_sur_linux():
    devices = [
        {"name": "Micro USB", "max_input_channels": 1},
        {"name": "Monitor of Built-in Audio", "max_input_channels": 2},
    ]
    with patch("audio.sd.query_devices", return_value=devices):
        assert find_loopback_device_sounddevice() == 1


def test_detecte_blackhole_sur_macos():
    devices = [
        {"name": "MacBook Pro Microphone", "max_input_channels": 1},
        {"name": "BlackHole 2ch", "max_input_channels": 2},
    ]
    with patch("audio.sd.query_devices", return_value=devices):
        assert find_loopback_device_sounddevice() == 1


def test_aucune_capture_systeme_disponible_via_sounddevice():
    devices = [{"name": "MacBook Pro Microphone", "max_input_channels": 1}]
    with patch("audio.sd.query_devices", return_value=devices):
        assert find_loopback_device_sounddevice() is None


def test_mix_blocks_additionne_les_deux_pistes():
    mic = np.array([[0.1], [0.2], [0.3]], dtype=np.float32)
    sys_ = np.array([[0.05], [0.05], [0.05]], dtype=np.float32)
    mixed = _mix_blocks(mic, sys_)
    assert np.allclose(mixed, [[0.15], [0.25], [0.35]])


def test_mix_blocks_ecrete_en_cas_de_saturation():
    mic = np.array([[0.8]], dtype=np.float32)
    sys_ = np.array([[0.8]], dtype=np.float32)
    mixed = _mix_blocks(mic, sys_)
    assert mixed[0][0] <= 1.0


def test_mix_blocks_gere_des_blocs_de_tailles_differentes():
    mic = np.array([[0.1], [0.2], [0.3]], dtype=np.float32)
    sys_ = np.array([[0.1], [0.1]], dtype=np.float32)
    mixed = _mix_blocks(mic, sys_)
    assert len(mixed) == 2


def test_loopback_windows_ouvre_bien_le_peripherique_de_boucle():
    """Cablage complet sur Windows, sans machine Windows reelle : on injecte
    un faux module `soundcard`. Le peripherique ouvert doit etre la BOUCLE
    (isloopback), pas le micro reel qui porte le meme nom."""
    fake_recorder_cm = MagicMock()
    fake_recorder_cm.__enter__ = MagicMock(return_value=MagicMock())
    fake_recorder_cm.__exit__ = MagicMock(return_value=False)

    boucle = FauxPeripherique("id-casque", "Casque Jabra", isloopback=True)
    boucle.recorder = MagicMock(return_value=fake_recorder_cm)
    micro_reel = FauxPeripherique("id-micro", "Casque Jabra")
    micro_reel.recorder = MagicMock()

    fake_soundcard = types.ModuleType("soundcard")
    fake_soundcard.default_speaker = MagicMock(
        return_value=FauxPeripherique("id-casque", "Casque Jabra"))
    fake_soundcard.all_microphones = MagicMock(return_value=[boucle, micro_reel])

    recorder = AudioRecorder()
    with patch.dict(sys.modules, {"soundcard": fake_soundcard}), \
         patch("audio.platform.system", return_value="Windows"):
        started = recorder._start_windows_loopback()

    assert started is True
    boucle.recorder.assert_called_once()      # c'est bien la boucle qui est ouverte
    micro_reel.recorder.assert_not_called()   # et surtout pas le micro reel
    assert fake_soundcard.all_microphones.call_args.kwargs["include_loopback"] is True

    recorder._sys_stop.set()   # evite de laisser un thread de poll tourner apres le test


def test_loopback_windows_indisponible_bascule_sans_erreur():
    """Si `soundcard` n'est pas installe ou echoue, on ne doit pas planter :
    system_audio_active doit rester False (repli micro seul)."""
    recorder = AudioRecorder()
    with patch("audio.platform.system", return_value="Windows"):
        started = recorder._start_windows_loopback()
    assert started is False


# --- Normalisation des blocs et tampon continu du son systeme ---------------
# Le micro (sounddevice) et le loopback Windows (soundcard) ne livrent pas
# leurs echantillons sous la meme forme ni avec les memes tailles de blocs.

def test_en_colonne_normalise_les_trois_formats():
    mono_1d = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    assert _en_colonne(mono_1d).shape == (3, 1)

    mono_colonne = np.array([[0.1], [0.2]], dtype=np.float32)
    assert _en_colonne(mono_colonne).shape == (2, 1)

    stereo = np.array([[0.2, 0.4], [0.6, 0.8]], dtype=np.float32)
    ramene = _en_colonne(stereo)
    assert ramene.shape == (2, 1)
    assert np.allclose(ramene, [[0.3], [0.7]])   # moyenne des deux canaux


def test_le_tampon_systeme_ne_perd_aucun_echantillon():
    """Coeur du correctif : des blocs systeme de taille differente du micro
    ne doivent plus etre tronques (l'ancien appariement bloc-a-bloc jetait
    le surplus a chaque bloc)."""
    rec = AudioRecorder()
    rec.system_audio_active = True

    # 3 blocs systeme de 100 echantillons, consommes par blocs micro de 128
    for i in range(3):
        rec._sys_q.put(np.full((100, 1), i + 1, dtype=np.float32))
    rec._absorber_file_systeme()

    assert rec._frames_sys_recues == 300
    assert len(rec._sys_tampon) == 300

    premier = rec._bloc_systeme(128)
    assert len(premier) == 128
    # Continuite : on retrouve la fin du bloc 1 puis le debut du bloc 2
    assert premier[99][0] == 1.0 and premier[100][0] == 2.0

    second = rec._bloc_systeme(128)
    assert len(second) == 128
    assert rec._frames_sys_melangees == 256
    assert len(rec._sys_tampon) == 44   # le reste est conserve, pas jete


def test_le_tampon_systeme_complete_par_du_silence_si_insuffisant():
    """Si le son systeme prend du retard, on complete par du silence plutot
    que de desynchroniser les deux pistes."""
    rec = AudioRecorder()
    rec._sys_q.put(np.full((10, 1), 0.5, dtype=np.float32))
    rec._absorber_file_systeme()

    bloc = rec._bloc_systeme(25)
    assert bloc.shape == (25, 1)
    assert np.allclose(bloc[:10], 0.5)
    assert np.allclose(bloc[10:], 0.0)       # silence de complement
    assert rec._frames_sys_melangees == 10   # seuls les vrais echantillons comptent


def test_mixage_de_blocs_de_tailles_differentes_via_le_tampon():
    """Verification de bout en bout : bloc micro 1D de 4 echantillons et
    source systeme stereo par blocs de 3 -> mixage correct, sans perte."""
    rec = AudioRecorder()
    rec.system_audio_active = True
    rec._sys_q.put(np.full((3, 2), 0.2, dtype=np.float32))   # stereo
    rec._sys_q.put(np.full((3, 2), 0.4, dtype=np.float32))
    rec._absorber_file_systeme()

    mic = _en_colonne(np.full(4, 0.1, dtype=np.float32))
    mixe = _mix_blocks(mic, rec._bloc_systeme(len(mic)))

    assert mixe.shape == (4, 1)
    assert np.allclose(mixe[:3], 0.1 + 0.2)   # 3 premiers : micro + bloc systeme 1
    assert np.allclose(mixe[3], 0.1 + 0.4)    # 4e : la suite du tampon, rien de perdu


def test_le_niveau_sonore_distingue_silence_et_vrai_son():
    """soundcard renvoie des ZEROS quand rien ne joue : compter les
    echantillons ne suffit pas a savoir si du son a ete capte, il faut
    mesurer le niveau."""
    rec = AudioRecorder()
    rec._sys_q.put(np.zeros((100, 1), dtype=np.float32))
    rec._absorber_file_systeme()
    assert rec._frames_sys_recues == 100     # des echantillons, mais...
    assert rec._niveau_sys_max == 0.0        # ...que du silence

    rec._sys_q.put(np.full((100, 1), 0.42, dtype=np.float32))
    rec._absorber_file_systeme()
    assert rec._niveau_sys_max == pytest.approx(0.42)


def test_capture_systeme_interrompue_ne_meurt_pas_en_silence():
    """Une erreur pendant la capture (ex. incompatibilite soundcard/numpy)
    doit etre signalee et faire basculer proprement en micro seul, jamais
    s'arreter sans le moindre message."""
    rec = AudioRecorder()
    rec.system_audio_active = True
    enregistreur = MagicMock()
    enregistreur.record.side_effect = ValueError("The binary mode of fromstring is removed")

    with patch("builtins.print") as trace:
        rec._poll_windows_loopback(enregistreur)

    assert rec.system_audio_active is False          # repli micro seul
    messages = " ".join(str(a) for appel in trace.call_args_list for a in appel.args)
    assert "INTERROMPUE" in messages
    assert "fromstring" in messages                  # la cause reelle est remontee
