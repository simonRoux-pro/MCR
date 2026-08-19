import httpx
import ollama
from config import CONFIG

MAP_PROMPT = """Tu recois un extrait de transcription de reunion en francais.
Resume factuellement cet extrait : sujets abordes, decisions, actions mentionnees.
Reste bref et n'invente rien. Cet extrait est partiel, ne cherche pas a conclure."""

REDUCE_PROMPT = """Tu recois plusieurs resumes partiels d'une meme reunion, dans l'ordre.
Produis le compte-rendu final consolide en francais :

## Resume
Trois a cinq phrases sur l'essentiel.

## Points abordes
Liste des sujets traites.

## Decisions
Liste des decisions prises. Ecris "Aucune decision explicite" si rien.

## Actions
Liste des actions : action, responsable si mentionne, echeance si mentionnee.

Fusionne les redondances. Reste factuel. N'invente rien."""

SINGLE_PROMPT = """Tu recois la transcription d'une reunion en francais.
Produis le compte-rendu final en francais :

## Resume
Trois a cinq phrases sur l'essentiel.

## Points abordes
Liste des sujets traites.

## Decisions
Liste des decisions prises. Ecris "Aucune decision explicite" si rien.

## Actions
Liste des actions : action, responsable si mentionne, echeance si mentionnee.

Reste factuel. N'invente rien."""


def _chat(client, messages):
    """Appelle Ollama et transforme les erreurs de bas niveau en message clair
    et comprehensible pour l'utilisateur (Ollama non lance, modele absent...)."""
    try:
        resp = client.chat(model=CONFIG.ollama_model, messages=messages, options={"temperature": 0.2})
    except httpx.ConnectError as e:
        raise RuntimeError(
            f"Impossible de contacter Ollama sur {CONFIG.ollama_host}. "
            "Verifiez qu'Ollama est demarre (commande : `ollama serve`), puis reessayez."
        ) from e
    except ollama.ResponseError as e:
        if e.status_code == 404:
            raise RuntimeError(
                f"Le modele Ollama '{CONFIG.ollama_model}' n'est pas installe. "
                f"Installez-le avec : `ollama pull {CONFIG.ollama_model}`."
            ) from e
        raise RuntimeError(f"Erreur Ollama : {e.error}") from e
    return resp["message"]["content"]


def _chunk_text(text: str, max_chars: int):
    """Decoupe la transcription en morceaux geres par un 7B sur CPU.
    Decoupe sur les fins de ligne pour ne pas couper au milieu d'une phrase."""
    lines = text.split("\n")
    chunks, current, size = [], [], 0
    for line in lines:
        if size + len(line) > max_chars and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def summarize(transcript: str, progress=None) -> str:
    """Genere le compte-rendu. Pour les longues transcriptions, applique un
    map-reduce : resume par morceau (map) puis consolidation (reduce).

    progress(etape_courante, nb_etapes) est appele apres chaque morceau.
    """
    client = ollama.Client(host=CONFIG.ollama_host)
    chunks = _chunk_text(transcript, CONFIG.chunk_chars)

    # Cas court : un seul appel suffit
    if len(chunks) <= 1:
        result = _chat(client, [
            {"role": "system", "content": SINGLE_PROMPT},
            {"role": "user", "content": transcript},
        ])
        if progress:
            progress(1, 1)
        return result

    # Etape MAP : un resume par morceau
    partials = []
    for i, chunk in enumerate(chunks):
        result = _chat(client, [
            {"role": "system", "content": MAP_PROMPT},
            {"role": "user", "content": chunk},
        ])
        partials.append(result)
        if progress:
            progress(i + 1, len(chunks) + 1)

    # Etape REDUCE : consolidation finale
    merged = "\n\n---\n\n".join(
        f"Resume partiel {i + 1} :\n{p}" for i, p in enumerate(partials)
    )
    result = _chat(client, [
        {"role": "system", "content": REDUCE_PROMPT},
        {"role": "user", "content": merged},
    ])
    if progress:
        progress(len(chunks) + 1, len(chunks) + 1)
    return result
