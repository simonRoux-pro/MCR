"""Tests de la detection/capture du son systeme et du mixage micro/systeme.
Ne necessitent aucun peripherique audio reel (sd.query_* et soundcard sont simules)."""
import sys
import types
from unittest.mock import patch, MagicMock
import numpy as np

from audio import AudioRecorder, find_loopback_device_sounddevice, _mix_blocks, _en_colonne


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


def test_loopback_windows_utilise_soundcard_include_loopback():
    """Verifie le cablage vers soundcard.get_microphone(..., include_loopback=True)
    sur Windows, sans avoir de vraie machine Windows : on injecte un faux module
    `soundcard` dans sys.modules."""
    fake_recorder = MagicMock()
    fake_recorder_cm = MagicMock()
    fake_recorder_cm.__enter__ = MagicMock(return_value=fake_recorder)
    fake_recorder_cm.__exit__ = MagicMock(return_value=False)

    fake_mic = MagicMock()
    fake_mic.recorder.return_value = fake_recorder_cm

    fake_soundcard = types.ModuleType("soundcard")
    fake_soundcard.default_speaker = MagicMock(return_value=MagicMock(name="Haut-parleurs"))
    fake_soundcard.get_microphone = MagicMock(return_value=fake_mic)

    recorder = AudioRecorder()
    with patch.dict(sys.modules, {"soundcard": fake_soundcard}), \
         patch("audio.platform.system", return_value="Windows"):
        started = recorder._start_windows_loopback()

    assert started is True
    fake_soundcard.get_microphone.assert_called_once()
    assert fake_soundcard.get_microphone.call_args.kwargs["include_loopback"] is True
    fake_mic.recorder.assert_called_once()

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
