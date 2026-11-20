# -*- coding: utf-8 -*-
"""normalizadores — a RÉGUA de cada tarefa de juízo: resposta crua do modelo → (veredito curto, nível, confiança).

Nível: ⚪ 0 · 🟡 1 · 🔴 2 (None = a resposta não diz). Quem compara dois modelos precisa da MESMA régua: o co-motor
(`llm/comotor`, Claude × cascata na hora) e a conferência do Opus (`llm/conferencia_opus`, Opus × modelo de
contingência depois) leem esta tabela. Tarefa fora dela é prosa sem régua: não há o que cruzar.
"""
from __future__ import annotations

from typing import Callable

from compliance_agent.llm.json_resposta import parse_json_llm


def _json(txt):
    d = parse_json_llm(txt or "")
    return d if isinstance(d, dict) else {}


def _nivel_nota(n) -> int | None:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return None
    if not 0 <= n <= 10:
        return None
    return 2 if n >= 7 else 1 if n >= 4 else 0


def norm_execucao(txt):
    d = _json(txt)
    ex = str(d.get("execucao_comprovada") or "").strip().lower() or None
    nivel = _nivel_nota(d.get("nota_risco_execucao"))
    if nivel is None and ex not in ("sim", "parcial", "nao", "não"):
        return None, None, None
    return f"{ex or '?'}/nota {d.get('nota_risco_execucao')}", nivel, None


_CONF = {"alta": 0.9, "media": 0.6, "média": 0.6, "baixa": 0.3}


def norm_fachada(txt):
    d = _json(txt)
    v = str(d.get("veredito") or "").strip().upper()
    nivel = {"FACHADA_PROVAVEL": 2, "INDICIOS": 1, "INDÍCIOS": 1, "INSUFICIENTE": 0}.get(v)
    return (v or None), nivel, _CONF.get(str(d.get("confianca") or "").strip().lower())


def norm_risco(txt):
    d = _json(txt)
    r = str(d.get("risco") or "").strip().lower()
    nivel = {"baixo": 0, "médio": 1, "medio": 1, "alto": 2}.get(r)
    return (r or None), nivel, None


def norm_adversarial(txt):
    d = _json(txt)
    if "refuta" not in d:
        return None, None, None
    return ("refutada", 0, None) if bool(d.get("refuta")) else ("mantida", 2, None)


def norm_triagem(txt):
    d = _json(txt)
    p = str(d.get("prioridade") or "").strip().lower()
    nivel = {"aprofundar": 2, "monitorar": 1, "provavel_falso_positivo": 0}.get(p)
    try:
        conf = max(0.0, min(1.0, float(d.get("nota")) / 10))
    except (TypeError, ValueError):
        conf = None
    return (p or None), nivel, conf


def norm_pericia_integral(txt):
    """Perícia integral (`compliance_agent.pericia_integral`): grau global = MÁXIMO dos eixos determinados
    (null = INDETERMINADO fica fora; todos null ⇒ nível None). Genérico nos nomes dos eixos."""
    e = _json(txt).get("eixos")
    if not isinstance(e, dict) or not e:
        return None, None, None
    graus = {k: (v.get("grau") if isinstance(v, dict) and v.get("grau") in (0, 1, 2)
                 and not isinstance(v.get("grau"), bool) else None) for k, v in e.items()}
    det = [g for g in graus.values() if g is not None]
    if not det:
        return "indeterminado", None, None
    return " ".join(f"{k[:4]}{'?' if g is None else g}" for k, g in graus.items())[:80], max(det), None


NORMALIZADORES: dict[str, Callable] = {
    "pericia_integral": norm_pericia_integral,
    "pericia_execucao": norm_execucao,
    "pericia_fornecedor": norm_fachada,
    "investigacao_risco": norm_risco,
    "camada_subjetiva": norm_adversarial,
    "triagem_alertas": norm_triagem,
}
