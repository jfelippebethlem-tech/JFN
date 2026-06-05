"""
Ollama local LLM client wrapper.

Provides a lightweight interface to run local language models via Ollama,
reducing Claude API costs for simple classification and summarization tasks.
"""

import os
from typing import Optional

DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

# Lazy availability flag
_OLLAMA_AVAILABLE: Optional[bool] = None


def is_available() -> bool:
    """Check if Ollama is installed and the service is running."""
    global _OLLAMA_AVAILABLE
    if _OLLAMA_AVAILABLE is not None:
        return _OLLAMA_AVAILABLE
    try:
        import ollama
        ollama.list()
        _OLLAMA_AVAILABLE = True
    except (ImportError, Exception):
        _OLLAMA_AVAILABLE = False
    return _OLLAMA_AVAILABLE


def chat(prompt: str, model: str = DEFAULT_MODEL, system: str = "") -> str:
    """
    Send a chat prompt to the local Ollama model.

    Returns the model's response as a string, or empty string on error.
    """
    if not is_available():
        return ""
    try:
        import ollama
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = ollama.chat(model=model, messages=messages)
        return response["message"]["content"].strip()
    except Exception:
        return ""


def classify_text(text: str, categories: list[str], model: str = DEFAULT_MODEL) -> str:
    """
    Classify the given text into exactly one of the provided categories.

    Returns the category name, or categories[0] on failure.
    """
    if not is_available() or not categories:
        return categories[0] if categories else ""
    cats = ", ".join(categories)
    prompt = (
        f"Classifique o texto abaixo em UMA categoria: {cats}. "
        f"Responda APENAS o nome da categoria, sem explicação.\n\nTexto: {text[:1000]}"
    )
    result = chat(prompt, model=model)
    # Validate result is one of the categories
    result_clean = result.strip().lower()
    for cat in categories:
        if cat.lower() in result_clean or result_clean in cat.lower():
            return cat
    return categories[0]


def summarize(text: str, max_words: int = 100, model: str = DEFAULT_MODEL) -> str:
    """
    Summarize the given text in at most max_words words.

    Returns the summary, or the first 300 chars of text on failure.
    """
    if not is_available():
        return text[:300] + ("..." if len(text) > 300 else "")
    prompt = (
        f"Resuma o texto abaixo em no máximo {max_words} palavras, "
        f"em português, mantendo as informações mais importantes.\n\nTexto: {text[:3000]}"
    )
    result = chat(prompt, model=model)
    return result if result else text[:300] + ("..." if len(text) > 300 else "")


def extract_entities(text: str, model: str = DEFAULT_MODEL) -> dict:
    """
    Extract named entities from the text.

    Returns a dict with keys: pessoas, empresas, valores, cpfs, cnpjs.
    Each key maps to a list of strings found in the text.
    """
    empty = {"pessoas": [], "empresas": [], "valores": [], "cpfs": [], "cnpjs": []}
    if not is_available():
        return empty
    prompt = (
        "Extraia as entidades do texto abaixo e retorne um JSON com as chaves: "
        "pessoas (lista de nomes de pessoas), empresas (lista de nomes de empresas), "
        "valores (lista de valores monetários), cpfs (lista de CPFs), cnpjs (lista de CNPJs). "
        "Retorne APENAS o JSON, sem explicação.\n\nTexto: " + text[:2000]
    )
    result = chat(prompt, model=model)
    if not result:
        return empty
    import json
    # Try to parse JSON from response
    try:
        # Find JSON block in response
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(result[start:end])
            return {
                "pessoas":  parsed.get("pessoas", []),
                "empresas": parsed.get("empresas", []),
                "valores":  parsed.get("valores", []),
                "cpfs":     parsed.get("cpfs", []),
                "cnpjs":    parsed.get("cnpjs", []),
            }
    except Exception:
        pass
    return empty
