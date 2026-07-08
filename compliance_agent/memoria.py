# -*- coding: utf-8 -*-
"""Consolidação de memória do ecossistema — JFN 2.0, Onda 11 (higiene/resiliência).

Reúne num só lugar o que cada agente aprendeu: base empírica do Lex e memória do Hermes
(se acessível). Leitura unificada p/ o Yoda e p/ avaliação. Best-effort: fonte ausente vira
nota, nunca fabrica. (Massare saiu da VM em 2026-07-07 — vive só no GitHub.)
"""
from __future__ import annotations


def consolidar(limite: int = 15) -> dict:
    """Memória consolidada {ok, lex_base, hermes, _fontes}."""
    out: dict = {"ok": True, "_fontes": []}

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

    out["_nota"] = "Memória consolidada do ecossistema (Lex/Hermes); fonte ausente = nota, nunca fabricada."
    return out
