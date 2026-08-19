import queue
import threading
import sounddevice as sd
import soundfile as sf
from config import CONFIG


class AudioRecorder:
    """Ecrit l'audio directement dans un WAV pendant l'enregistrement.
    Aucune accumulation en RAM, resistant aux longues durees (reunions de 2 h)."""

    def __init__(self):
        self._q = queue.Queue()
        self._recording = False
        self._stream = None
        self._writer = None
        self._thread = None
        self._path = None

    def _callback(self, indata, frames, time, status):
        if self._recording:
            self._q.put(indata.copy())

    def start(self, path: str):
        self._path = path
        self._recording = True
        self._writer = sf.SoundFile(
            path, mode="w",
            samplerate=CONFIG.samplerate,
            channels=CONFIG.channels,
            subtype="PCM_16",
        )
        self._stream = sd.InputStream(
            samplerate=CONFIG.samplerate,
            channels=CONFIG.channels,
            callback=self._callback,
        )
        self._stream.start()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self):
        while self._recording or not self._q.empty():
            try:
                block = self._q.get(timeout=0.5)
                self._writer.write(block)   # ecrit sur disque immediatement
            except queue.Empty:
                pass

    def stop(self):
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
        if self._thread:
            self._thread.join(timeout=5)
        if self._writer:
            self._writer.close()
        return self._path
