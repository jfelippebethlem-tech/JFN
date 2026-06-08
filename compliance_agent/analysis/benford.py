# -*- coding: utf-8 -*-
"""Lei de Benford (1º e 2º dígito) — JFN 2.0, Onda 3 (motor de risco).

Detecta desvios da distribuição esperada dos dígitos em populações de valores (OBs por
UG/fornecedor) — sinal clássico de fracionamento, valores fabricados ou direcionamento.
MAD de Nigrini com as faixas de conformidade consagradas. PURO (sem dependências), testável.

Honestidade: Benford é um INDÍCIO estatístico de triagem, nunca prova. Não conformidade
pede investigação dos itens, não acusação. Requer n suficiente (default >= 50).

Ref.: Nigrini, M. (2012) "Benford's Law"; faixas MAD de conformidade do 1º/2º dígito.
"""
from __future__ import annotations

import math

# Faixas de conformidade do MAD (Nigrini) — limites superiores por classe.
_FAIXAS_D1 = [(0.006, "conformidade alta"), (0.012, "conformidade aceitável"),
              (0.015, "conformidade marginal"), (float("inf"), "NÃO CONFORMIDADE")]
_FAIXAS_D2 = [(0.008, "conformidade alta"), (0.010, "conformidade aceitável"),
              (0.012, "conformidade marginal"), (float("inf"), "NÃO CONFORMIDADE")]


def esperado_primeiro() -> dict[int, float]:
    """P(1º dígito = d) = log10(1 + 1/d), d ∈ 1..9."""
    return {d: math.log10(1 + 1 / d) for d in range(1, 10)}


def esperado_segundo() -> dict[int, float]:
    """P(2º dígito = d) = Σ_{k=1..9} log10(1 + 1/(10k+d)), d ∈ 0..9."""
    return {d: sum(math.log10(1 + 1 / (10 * k + d)) for k in range(1, 10)) for d in range(0, 10)}


def _significativos(v) -> str | None:
    """Normaliza |v| para [1,10) e devolve os dígitos significativos (ex.: 1250 -> '125000000')."""
    try:
        v = abs(float(v))
    except (TypeError, ValueError):
        return None
    if v == 0 or math.isnan(v) or math.isinf(v):
        return None
    while v >= 10:
        v /= 10
    while v < 1:
        v *= 10
    return f"{v:.8f}".replace(".", "")


def _faixa(mad: float, faixas) -> str:
    for limite, rotulo in faixas:
        if mad <= limite:
            return rotulo
    return "NÃO CONFORMIDADE"


def _analise_digito(contagem: dict[int, int], esperado: dict[int, float], faixas) -> dict:
    n = sum(contagem.values())
    obs = {d: (contagem.get(d, 0) / n if n else 0.0) for d in esperado}
    mad = sum(abs(obs[d] - esperado[d]) for d in esperado) / len(esperado)
    return {
        "n": n,
        "mad": round(mad, 5),
        "faixa_nigrini": _faixa(mad, faixas),
        "obs": {str(d): round(obs[d], 4) for d in esperado},
        "esp": {str(d): round(esperado[d], 4) for d in esperado},
    }


def benford(valores, min_n: int = 50) -> dict:
    """Roda Benford 1º+2º dígito sobre uma lista de valores numéricos.

    Retorna {ok, n, suficiente, primeiro_digito:{n,mad,faixa_nigrini,obs,esp},
    segundo_digito:{...}, _nota}. Se n < min_n, suficiente=False (resultado não confiável)."""
    c1: dict[int, int] = {}
    c2: dict[int, int] = {}
    for v in valores:
        s = _significativos(v)
        if not s:
            continue
        c1[int(s[0])] = c1.get(int(s[0]), 0) + 1
        if len(s) > 1:
            c2[int(s[1])] = c2.get(int(s[1]), 0) + 1
    n = sum(c1.values())
    suficiente = n >= min_n
    return {
        "ok": True,
        "n": n,
        "suficiente": suficiente,
        "primeiro_digito": _analise_digito(c1, esperado_primeiro(), _FAIXAS_D1),
        "segundo_digito": _analise_digito(c2, esperado_segundo(), _FAIXAS_D2),
        "_nota": ("INDÍCIO estatístico de triagem (Nigrini), não prova. "
                  + ("" if suficiente else f"n={n} < {min_n}: amostra pequena, resultado pouco confiável.")),
    }


def benford_ob(orgao: str | None = None, fornecedor: str | None = None, min_n: int = 50) -> dict:
    """Benford sobre os valores de OB (ordens_bancarias), opcionalmente filtrado por UG/fornecedor."""
    import sqlite3
    from pathlib import Path

    db = Path(__file__).resolve().parent.parent.parent / "data" / "compliance.db"
    if not db.exists():
        return {"ok": False, "erro": "compliance.db ausente"}
    con = sqlite3.connect(str(db))
    try:
        where, params = ["valor > 0"], []
        if orgao:
            where.append("(ug_nome LIKE ? OR ug_codigo = ?)")
            params += [f"%{orgao}%", orgao]
        if fornecedor:
            where.append("(favorecido_nome LIKE ? OR favorecido_cpf LIKE ?)")
            params += [f"%{fornecedor}%", f"%{fornecedor}%"]
        sql = f"SELECT valor FROM ordens_bancarias WHERE {' AND '.join(where)}"
        valores = [r[0] for r in con.execute(sql, params)]
    finally:
        con.close()
    res = benford(valores, min_n=min_n)
    res["filtro"] = {"orgao": orgao, "fornecedor": fornecedor}
    res["_fonte"] = "ordens_bancarias (OB = pagamento; TFE/SIAFE)"
    return res
