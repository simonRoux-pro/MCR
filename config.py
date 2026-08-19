from dataclasses import dataclass


@dataclass
class Config:
    # Transcription
    whisper_model: str = "small"        # base | small | medium (medium = plus lent, meilleur)
    whisper_device: str = "cpu"
    whisper_compute: str = "int8"       # quantification CPU
    language: str = "fr"

    # LLM
    ollama_model: str = "mistral"       # ou "llama3.1" / "qwen2.5:3b"
    ollama_host: str = "http://localhost:11434"

    # Audio
    samplerate: int = 16000             # Whisper attend du 16 kHz
    channels: int = 1

    # Decoupage pour le CR (map-reduce)
    chunk_chars: int = 6000

    # Mail (seule donnee qui sort de l'outil)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""


CONFIG = Config()
