# -*- coding: utf-8 -*-
"""Consolidação de memória do ecossistema — JFN 2.0, Onda 11 (higiene/resiliência).

Reúne num só lugar o que cada agente aprendeu: lições do Massare (`learning`), base empírica do
Lex e memória do Hermes (se acessível). Leitura unificada p/ o Yoda e p/ avaliação. Best-effort:
fonte ausente vira nota, nunca fabrica.
"""
from __future__ import annotations


def consolidar(limite: int = 15) -> dict:
    """Memória consolidada {ok, massare_licoes[], lex_base, hermes, _fontes}."""
    out: dict = {"ok": True, "_fontes": []}

    # Massare — lições aprendidas (learning.recent_lessons)
    try:
        from massare import learning
        learning.init()
        out["massare_licoes"] = (learning.recent_lessons(limit=limite) or [])
        out["_fontes"].append("massare.learning")
    except Exception as e:  # noqa: BLE001
        out["massare_licoes"] = {"_nota": f"INDISPONÍVEL: {e}"}

    # Lex — base empírica (calibração de pesos/dosimetria), se houver
    try:
        from compliance_agent import lex_base_empirica as lbe
        stats = getattr(lbe, "stats", None) or getattr(lbe, "resumo", None)
        out["lex_base"] = stats() if callable(stats) else {"_nota": "sem resumo exposto"}
        out["_fontes"].append("lex_base_empirica")
    except Exception as e:  # noqa: BLE001
        out["lex_base"] = {"_nota": f"INDISPONÍVEL: {e}"}

    # Hermes — memória do orquestrador (arquivo, se acessível)
    try:
        import json
        from pathlib import Path
        hm = Path.home() / ".hermes" / "memory.json"
        if hm.exists():
            out["hermes"] = {"itens": len(json.loads(hm.read_text(encoding="utf-8")) or [])}
            out["_fontes"].append("hermes/memory.json")
        else:
            out["hermes"] = {"_nota": "sem memory.json acessível"}
    except Exception as e:  # noqa: BLE001
        out["hermes"] = {"_nota": f"INDISPONÍVEL: {e}"}

    out["_nota"] = "Memória consolidada do ecossistema (Massare/Lex/Hermes); fonte ausente = nota, nunca fabricada."
    return out
