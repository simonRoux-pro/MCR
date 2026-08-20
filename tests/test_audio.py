"""Tests de la detection/capture du son systeme et du mixage micro/systeme.
Ne necessitent aucun peripherique audio reel (sd.query_* et soundcard sont simules)."""
import sys
import types
from unittest.mock import patch, MagicMock
import numpy as np

from audio import AudioRecorder, find_loopback_device_sounddevice, _mix_blocks


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
