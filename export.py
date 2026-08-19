def save_txt(path: str, report: str):
    """Exporte le compte-rendu en texte brut."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)


def save_md(path: str, report: str, title: str = "Compte-rendu de reunion"):
    """Exporte le compte-rendu en Markdown. Le CR genere par le LLM est deja
    structure en Markdown (titres ##), on ajoute juste un titre principal en H1."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{report}\n")
