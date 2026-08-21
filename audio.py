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


def trouver_loopback_windows(sc, haut_parleur):
    """Choisit le peripherique de boucle (loopback) correspondant a la sortie
    audio par defaut, parmi ceux exposes par la librairie `soundcard`.

    On ne peut PAS utiliser sc.get_microphone(nom, include_loopback=True) :
    en interne, cette fonction indexe les peripheriques par nom dans un
    dictionnaire. Or, avec un casque, la sortie et le micro portent souvent le
    meme nom : l'entree loopback est alors ecrasee par le vrai micro, et la
    fonction renvoie le MICRO au lieu de la boucle (on enregistre deux fois sa
    propre voix, jamais les autres participants).

    On selectionne donc explicitement parmi les peripheriques marques
    `isloopback`, en privilegiant l'identifiant unique de la sortie par defaut.
    Retourne None si aucune boucle n'est disponible."""
    boucles = [m for m in sc.all_microphones(include_loopback=True)
               if getattr(m, "isloopback", False)]
    if not boucles:
        return None
    for candidat in boucles:                          # 1. identifiant exact (fiable)
        if candidat.id == haut_parleur.id:
            return candidat
    for candidat in boucles:                          # 2. a defaut, meme nom
        if candidat.name == haut_parleur.name:
            return candidat
    return boucles[0]                                 # 3. sinon, la premiere boucle


def _mix_blocks(mic_block, sys_block):
    """Mixe un bloc micro (ma voix) et un bloc son systeme (les autres
    participants) en sommant les deux pistes, puis ecrete pour eviter la
    saturation si les deux parlent fort en meme temps."""
    n = min(len(mic_block), len(sys_block))
    mixed = mic_block[:n].astype(np.float32) + sys_block[:n].astype(np.float32)
    return np.clip(mixed, -1.0, 1.0)


def _en_colonne(bloc):
    """Normalise un bloc audio en colonne mono float32 de forme (n, 1), quel
    que soit le format livre par la source : mono 1D, mono (n, 1), ou stereo
    (n, 2) ramene en mono par moyenne des canaux. Indispensable car le micro
    (sounddevice) et le loopback Windows (soundcard) ne livrent pas leurs
    echantillons sous la meme forme."""
    bloc = np.asarray(bloc, dtype=np.float32)
    if bloc.ndim == 1:
        return bloc[:, None]
    if bloc.shape[1] > 1:
        return bloc.mean(axis=1, keepdims=True)
    return bloc


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
        self._sys_tampon = np.zeros((0, 1), dtype=np.float32)
        self._frames_sys_recues = 0
        self._frames_sys_melangees = 0
        self._niveau_sys_max = 0.0
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
        # Etat remis a neuf a chaque enregistrement (l'instance est reutilisee)
        self._mic_q = queue.Queue()
        self._sys_q = queue.Queue()
        self._sys_tampon = np.zeros((0, 1), dtype=np.float32)
        self._frames_sys_recues = 0
        self._frames_sys_melangees = 0
        self._niveau_sys_max = 0.0
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
            print("[MeetingCT] Son systeme NON capte : aucune source loopback trouvee, micro seul.", flush=True)
            return False
        try:
            self._sys_stream = sd.InputStream(
                samplerate=CONFIG.samplerate,
                channels=CONFIG.channels,
                device=device,
                callback=self._sys_callback,
            )
            self._sys_stream.start()
            print(f"[MeetingCT] Capture du son systeme active (source : {sd.query_devices(device)['name']}).", flush=True)
            return True
        except Exception as e:
            print(f"[MeetingCT] Son systeme NON capte (echec ouverture source : {e}), micro seul.", flush=True)
            self._sys_stream = None
            return False

    def _start_windows_loopback(self):
        try:
            import soundcard as sc
            haut_parleur = sc.default_speaker()
            source = trouver_loopback_windows(sc, haut_parleur)
            if source is None:
                print("[MeetingCT] Loopback Windows indisponible : aucun peripherique "
                      "de boucle trouve, micro seul.", flush=True)
                return False
            # channels=None : on capte le nombre de canaux natif de la sortie
            # (souvent stereo) ; le mixage ramene ensuite en mono proprement.
            self._sys_recorder_cm = source.recorder(samplerate=CONFIG.samplerate, channels=None)
            recorder = self._sys_recorder_cm.__enter__()
            haut_parleur = source   # pour le message ci-dessous : le vrai peripherique retenu
        except Exception as e:
            print(f"[MeetingCT] Loopback Windows indisponible ({type(e).__name__}: {e}), micro seul.", flush=True)
            self._sys_recorder_cm = None
            return False
        self._sys_stop.clear()
        self._sys_thread = threading.Thread(
            target=self._poll_windows_loopback, args=(recorder,), daemon=True
        )
        self._sys_thread.start()
        print(f"[MeetingCT] Capture du son systeme active (loopback Windows sur : {haut_parleur.name}).", flush=True)
        return True

    def _poll_windows_loopback(self, recorder, blocksize=1024):
        while not self._sys_stop.is_set():
            try:
                block = recorder.record(numframes=blocksize)
            except Exception:
                break
            self._sys_q.put(block)

    def _absorber_file_systeme(self):
        """Vide la file du son systeme dans le tampon continu, sans jamais
        attendre (get_nowait : pas de blocage a l'arret de l'enregistrement)."""
        while True:
            try:
                bloc = _en_colonne(self._sys_q.get_nowait())
            except queue.Empty:
                return
            self._frames_sys_recues += len(bloc)
            if len(bloc):
                # Niveau sonore reel : soundcard renvoie des zeros quand rien
                # ne joue, donc compter les echantillons ne suffit pas a savoir
                # si du son a vraiment ete capte.
                self._niveau_sys_max = max(self._niveau_sys_max, float(np.abs(bloc).max()))
            self._sys_tampon = np.concatenate([self._sys_tampon, bloc])

    def _bloc_systeme(self, n):
        """Extrait exactement n echantillons du tampon systeme, completes par
        du silence si le tampon n'en contient pas assez. Le reste du tampon
        est conserve pour les blocs suivants : contrairement a un appariement
        bloc-a-bloc, aucune hypothese sur les tailles de blocs des deux
        sources, et aucun echantillon systeme n'est jamais jete."""
        pris = self._sys_tampon[:n]
        self._sys_tampon = self._sys_tampon[n:]
        self._frames_sys_melangees += len(pris)
        if len(pris) < n:
            pris = np.concatenate([pris, np.zeros((n - len(pris), 1), dtype=np.float32)])
        return pris

    def _drain(self):
        while self._recording or not self._mic_q.empty():
            try:
                mic_block = _en_colonne(self._mic_q.get(timeout=0.5))
            except queue.Empty:
                continue
            if self.system_audio_active:
                self._absorber_file_systeme()
                block = _mix_blocks(mic_block, self._bloc_systeme(len(mic_block)))
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

        if self.system_audio_active:
            secondes = self._frames_sys_recues / CONFIG.samplerate
            print(f"[MeetingCT] Son systeme : ~{secondes:.0f} s captees, "
                  f"niveau sonore max {self._niveau_sys_max:.3f} "
                  f"({self._frames_sys_melangees} echantillons melangees au micro).", flush=True)
            if self._niveau_sys_max < 0.001:
                print("[MeetingCT] ATTENTION : la boucle audio tourne mais n'a capte QUE DU SILENCE. "
                      "Verifier que le son (visio, video...) sort bien sur le peripherique de sortie "
                      "PAR DEFAUT de Windows. Diagnostic detaille : python diag_audio.py", flush=True)

        print("[MeetingCT] audio.stop() : termine.", flush=True)
        return self._path
