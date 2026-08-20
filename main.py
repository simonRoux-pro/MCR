import sys
import os
import tempfile
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QFileDialog
)
from PySide6.QtCore import QThread, Signal

from audio import AudioRecorder
from pipeline import validate_audio_file
from transcribe import transcribe
from summarize import summarize


class Worker(QThread):
    transcript_progress = Signal(float, float)   # secondes traitees, duree totale
    summary_progress = Signal(int, int)          # etape, nb etapes
    transcribed = Signal(str)                    # transcription terminee (avant le CR)
    done = Signal(str, str)
    failed = Signal(str)                         # echec avant meme d'avoir une transcription
    summary_failed = Signal(str, str)            # transcription obtenue, mais echec du CR (ex : Ollama eteint)

    def __init__(self, audio_path, from_file=False):
        super().__init__()
        self.audio_path = audio_path
        self.from_file = from_file

    def run(self):
        try:
            if self.from_file:
                validate_audio_file(self.audio_path)
            transcript_file = os.path.join(tempfile.gettempdir(), "transcript.txt")
            transcript = transcribe(
                self.audio_path, transcript_file,
                progress=lambda s, d: self.transcript_progress.emit(s, d),
            )
        except Exception as e:
            self.failed.emit(str(e))
            return

        # La transcription est acquise : on la remonte tout de suite. Sur une reunion
        # de 2 h, elle ne doit jamais etre perdue meme si la generation du CR echoue.
        self.transcribed.emit(transcript)

        try:
            report = summarize(
                transcript,
                progress=lambda i, n: self.summary_progress.emit(i, n),
            )
        except Exception as e:
            self.summary_failed.emit(transcript, str(e))
            return

        self.done.emit(transcript, report)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Compte-rendu de reunion - 100% local")
        self.recorder = AudioRecorder()
        self.audio_path = os.path.join(tempfile.gettempdir(), "meeting.wav")

        central = QWidget()
        layout = QVBoxLayout(central)

        self.status = QLabel("Pret.")
        layout.addWidget(self.status)

        btns = QHBoxLayout()
        self.btn_rec = QPushButton("Demarrer l'enregistrement")
        self.btn_stop = QPushButton("Arreter et generer le CR")
        self.btn_stop.setEnabled(False)
        self.btn_load = QPushButton("Charger un fichier audio...")
        btns.addWidget(self.btn_rec)
        btns.addWidget(self.btn_stop)
        btns.addWidget(self.btn_load)
        layout.addLayout(btns)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        layout.addWidget(QLabel("Transcription :"))
        self.txt_transcript = QTextEdit()
        layout.addWidget(self.txt_transcript)

        layout.addWidget(QLabel("Compte-rendu :"))
        self.txt_report = QTextEdit()
        layout.addWidget(self.txt_report)

        mail_row = QHBoxLayout()
        self.mail_to = QLineEdit()
        self.mail_to.setPlaceholderText("destinataire@exemple.fr")
        self.btn_send = QPushButton("Envoyer par mail")
        self.btn_send.setEnabled(False)
        mail_row.addWidget(self.mail_to)
        mail_row.addWidget(self.btn_send)
        layout.addLayout(mail_row)

        export_row = QHBoxLayout()
        self.btn_export_txt = QPushButton("Exporter en .txt")
        self.btn_export_md = QPushButton("Exporter en .md")
        self.btn_export_txt.setEnabled(False)
        self.btn_export_md.setEnabled(False)
        export_row.addWidget(self.btn_export_txt)
        export_row.addWidget(self.btn_export_md)
        layout.addLayout(export_row)

        self.setCentralWidget(central)

        self.btn_rec.clicked.connect(self.start_rec)
        self.btn_stop.clicked.connect(self.stop_rec)
        self.btn_load.clicked.connect(self.load_file)
        self.btn_send.clicked.connect(self.send_mail)
        self.btn_export_txt.clicked.connect(self.export_txt)
        self.btn_export_md.clicked.connect(self.export_md)

    def start_rec(self):
        self.recorder.start(self.audio_path)
        if self.recorder.system_audio_active:
            self.status.setText("Enregistrement en cours (micro + son systeme)...")
        else:
            self.status.setText(
                "Enregistrement en cours (micro uniquement : son systeme non "
                "capte, voir README section \"Capture du son des participants\")."
            )
        self.btn_rec.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_load.setEnabled(False)
        self.progress.setValue(0)

    def stop_rec(self):
        try:
            self.recorder.stop()
        except Exception as e:
            QMessageBox.warning(self, "Erreur", str(e))
            self._reset_buttons()
            return
        self.btn_stop.setEnabled(False)
        self._start_worker(self.audio_path, from_file=False)

    def load_file(self):
        """Mode fichier : charge un WAV/MP3 existant au lieu d'enregistrer le micro.
        Permet de tester la chaine transcription + CR sans materiel audio."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir un fichier audio", "",
            "Fichiers audio (*.wav *.mp3 *.m4a)"
        )
        if not path:
            return
        self.btn_rec.setEnabled(False)
        self.btn_load.setEnabled(False)
        self._start_worker(path, from_file=True)

    def _start_worker(self, audio_path, from_file):
        self.status.setText("Transcription en cours... (peut durer plusieurs heures sur CPU)")
        self.progress.setValue(0)
        self.worker = Worker(audio_path, from_file=from_file)
        self.worker.transcript_progress.connect(self.on_transcript_progress)
        self.worker.summary_progress.connect(self.on_summary_progress)
        self.worker.transcribed.connect(self.on_transcribed)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.summary_failed.connect(self.on_summary_failed)
        self.worker.start()

    def on_transcript_progress(self, seconds, duration):
        if duration > 0:
            pct = int(min(seconds / duration, 1.0) * 100)
            self.progress.setValue(pct)
            self.status.setText(f"Transcription : {pct} %")

    def on_summary_progress(self, step, total):
        pct = int(step / total * 100)
        self.progress.setValue(pct)
        self.status.setText(f"Generation du compte-rendu : {step}/{total}")

    def on_transcribed(self, transcript):
        self.txt_transcript.setPlainText(transcript)

    def on_done(self, transcript, report):
        self.txt_transcript.setPlainText(transcript)
        self.txt_report.setPlainText(report)
        self.status.setText("Termine.")
        self.progress.setValue(100)
        self.btn_send.setEnabled(True)
        self.btn_export_txt.setEnabled(True)
        self.btn_export_md.setEnabled(True)
        self._reset_buttons()

    def on_failed(self, msg):
        QMessageBox.critical(self, "Erreur", msg)
        self.status.setText("Echec.")
        self._reset_buttons()

    def on_summary_failed(self, transcript, msg):
        # La transcription est deja affichee (signal transcribed) : on ne la perd pas.
        self.txt_transcript.setPlainText(transcript)
        QMessageBox.critical(self, "Erreur - Compte-rendu", msg)
        self.status.setText("Transcription obtenue, mais echec de la generation du CR.")
        self._reset_buttons()

    def send_mail(self):
        from mailer import send_report
        to = self.mail_to.text().strip()
        if not to:
            QMessageBox.warning(self, "Mail", "Renseigne un destinataire.")
            return
        try:
            send_report(to, "Compte-rendu de reunion", self.txt_report.toPlainText())
            self.status.setText(f"CR envoye a {to}.")
        except Exception as e:
            QMessageBox.critical(self, "Erreur mail", str(e))

    def export_txt(self):
        self._export(".txt", "Fichiers texte (*.txt)", save_as="txt")

    def export_md(self):
        self._export(".md", "Fichiers Markdown (*.md)", save_as="md")

    def _export(self, suffix, filter_str, save_as):
        from export import save_txt, save_md
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter le compte-rendu", f"compte-rendu{suffix}", filter_str
        )
        if not path:
            return
        try:
            if save_as == "txt":
                save_txt(path, self.txt_report.toPlainText())
            else:
                save_md(path, self.txt_report.toPlainText())
            self.status.setText(f"CR exporte vers {path}.")
        except Exception as e:
            QMessageBox.critical(self, "Erreur export", str(e))

    def _reset_buttons(self):
        self.btn_rec.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_load.setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.resize(700, 800)
    w.show()
    sys.exit(app.exec())
