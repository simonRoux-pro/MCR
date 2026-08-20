import platform
import queue
import threading
import numpy as np
import sounddevice as sd
import soundfile as sf
from config import CONFIG


def find_loopback_device_sounddevice():
    """Linux (PulseAudio/PipeWire) et macOS (BlackHole) : le son systeme est
    expose comme un peripherique d'entree normal, repere par mot-cle dans son
    nom ("monitor" pour PulseAudio/PipeWire, "blackhole" pour le pilote
    virtuel macOS). Retourne un index de peripherique sounddevice, ou None
    si aucun n'est trouve."""
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    keywords = ("monitor", "blackhole")
    for i, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) > 0 and any(k in dev["name"].lower() for k in keywords):
            return i
    return None


def _mix_blocks(mic_block, sys_block):
    """Mixe un bloc micro (ma voix) et un bloc son systeme (les autres
    participants) en sommant les deux pistes, puis ecrete pour eviter la
    saturation si les deux parlent fort en meme temps."""
    n = min(len(mic_block), len(sys_block))
    mixed = mic_block[:n].astype(np.float32) + sys_block[:n].astype(np.float32)
    return np.clip(mixed, -1.0, 1.0)


class AudioRecorder:
    """Enregistre le micro et, si possible, le son systeme (voix des AUTRES
    participants en visio Teams/Skype/Meet) en simultane, mixe les deux
    pistes, et ecrit le resultat directement dans un WAV pendant
    l'enregistrement. Aucune accumulation en RAM, resistant aux longues
    durees (reunions de 2 h).

    Capture du son systeme selon l'OS :
    - Windows : loopback WASAPI natif (librairie `soundcard`), fonctionne
      sans configuration particuliere ;
    - Linux : source "monitor" exposee par PulseAudio/PipeWire ;
    - macOS : peripherique virtuel type BlackHole, a installer par
      l'utilisateur (voir README).

    Si aucune capture systeme n'est disponible sur la machine, on continue
    avec le micro seul plutot que d'empecher l'enregistrement : voir
    `system_audio_active` apres `start()`."""

    def __init__(self):
        self._mic_q = queue.Queue()
        self._sys_q = queue.Queue()
        self._recording = False
        self._mic_stream = None
        self._sys_stream = None          # mode sounddevice (Linux/macOS)
        self._sys_recorder_cm = None     # mode soundcard (Windows, loopback WASAPI)
        self._sys_thread = None
        self._sys_stop = threading.Event()
        self._drain_thread = None
        self._writer = None
        self._path = None
        self.system_audio_active = False

    def _mic_callback(self, indata, frames, time, status):
        if self._recording:
            self._mic_q.put(indata.copy())

    def _sys_callback(self, indata, frames, time, status):
        if self._recording:
            self._sys_q.put(indata.copy())

    def start(self, path: str):
        self._path = path
        self._recording = True
        self._writer = sf.SoundFile(
            path, mode="w",
            samplerate=CONFIG.samplerate,
            channels=CONFIG.channels,
            subtype="PCM_16",
        )

        self._mic_stream = sd.InputStream(
            samplerate=CONFIG.samplerate,
            channels=CONFIG.channels,
            callback=self._mic_callback,
        )
        self._mic_stream.start()

        self.system_audio_active = self._start_system_audio()

        self._drain_thread = threading.Thread(target=self._drain, daemon=True)
        self._drain_thread.start()

    def _start_system_audio(self):
        """Tente de demarrer la capture du son systeme. Renvoie True si elle a
        pu demarrer, False sinon (l'enregistrement continue alors micro seul)."""
        if platform.system() == "Windows" and self._start_windows_loopback():
            return True
        device = find_loopback_device_sounddevice()
        if device is None:
            return False
        try:
            self._sys_stream = sd.InputStream(
                samplerate=CONFIG.samplerate,
                channels=CONFIG.channels,
                device=device,
                callback=self._sys_callback,
            )
            self._sys_stream.start()
            return True
        except Exception:
            self._sys_stream = None
            return False

    def _start_windows_loopback(self):
        try:
            import soundcard as sc
            mic = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
            self._sys_recorder_cm = mic.recorder(samplerate=CONFIG.samplerate, channels=CONFIG.channels)
            recorder = self._sys_recorder_cm.__enter__()
        except Exception:
            self._sys_recorder_cm = None
            return False
        self._sys_stop.clear()
        self._sys_thread = threading.Thread(
            target=self._poll_windows_loopback, args=(recorder,), daemon=True
        )
        self._sys_thread.start()
        return True

    def _poll_windows_loopback(self, recorder, blocksize=1024):
        while not self._sys_stop.is_set():
            try:
                block = recorder.record(numframes=blocksize)
            except Exception:
                break
            self._sys_q.put(block)

    def _drain(self):
        while self._recording or not self._mic_q.empty():
            try:
                mic_block = self._mic_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.system_audio_active:
                try:
                    sys_block = self._sys_q.get(timeout=0.1)
                    block = _mix_blocks(mic_block, sys_block)
                except queue.Empty:
                    block = mic_block   # rien de neuf cote son systeme sur ce cycle
            else:
                block = mic_block
            self._writer.write(block)   # ecrit sur disque immediatement

    def stop(self):
        self._recording = False

        print("[MeetingCT] audio.stop() : arret du flux micro...", flush=True)
        if self._mic_stream:
            self._mic_stream.stop()
            self._mic_stream.close()
        print("[MeetingCT] audio.stop() : flux micro arrete.", flush=True)

        if self._sys_stream:
            print("[MeetingCT] audio.stop() : arret du flux son systeme...", flush=True)
            self._sys_stream.stop()
            self._sys_stream.close()
            print("[MeetingCT] audio.stop() : flux son systeme arrete.", flush=True)

        if self._sys_recorder_cm:
            print("[MeetingCT] audio.stop() : arret du thread loopback Windows...", flush=True)
            self._sys_stop.set()
            if self._sys_thread:
                self._sys_thread.join(timeout=5)
            try:
                self._sys_recorder_cm.__exit__(None, None, None)
            except Exception:
                pass
            print("[MeetingCT] audio.stop() : thread loopback Windows arrete.", flush=True)

        if self._drain_thread:
            # Pas de timeout definitif ici : on doit avoir la certitude que
            # _drain a fini d'ecrire avant de fermer le fichier, sinon on
            # ferme le WAV sous les pieds du thread encore en train d'y
            # ecrire (I/O operation on closed file). On boucle par petites
            # tranches pour pouvoir signaler si ca prend anormalement longtemps
            # plutot que de bloquer en silence.
            print("[MeetingCT] audio.stop() : finalisation de l'ecriture disque...", flush=True)
            waited = 0
            while self._drain_thread.is_alive():
                self._drain_thread.join(timeout=1)
                waited += 1
                if self._drain_thread.is_alive():
                    print(f"[MeetingCT] audio.stop() : ecriture disque toujours en cours ({waited}s)...", flush=True)
            print("[MeetingCT] audio.stop() : ecriture disque terminee.", flush=True)

        if self._writer:
            self._writer.close()
        print("[MeetingCT] audio.stop() : termine.", flush=True)
        return self._path
