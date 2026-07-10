# -*- coding: utf-8 -*-
"""Extração e rotulagem das cláusulas de habilitação/participação de um edital.

Reusa o extrator determinístico do E7 (`coletor_edital`), que já traz cada
exigência com PROVENIÊNCIA, e acrescenta:
  • o EIXO da Lei 14.133 (arts. 62-70): jurídica/técnica/econ-financeira/fiscal/participação
  • a ASSINATURA (eixo:subtipo:faixa) — a chave que o peer-diff usa para dizer
    "esta MESMA exigência aparece em quantos editais do grupo?"
Determinístico; ausente ≠ 0 (o que o regex não pega fica de fora, não vira zero).
"""
from __future__ import annotations

from compliance_agent.detectores.coletor_edital import (
    _extrair_clausulas_restritivas,
    _extrair_exigencias,
    _linhas_com_contexto,
)

# tipo (exigências) → (eixo, subtipo)
_EIXO_POR_TIPO = {
    "atestado": ("habilitacao_tecnica", "atestado"),
    "capital_social": ("habilitacao_econ_financeira", "capital"),
    "patrimonio_liquido": ("habilitacao_econ_financeira", "patrimonio"),
}
# categoria (cláusulas restritivas do catálogo E7) → eixo
_EIXO_POR_CATEGORIA = {
    "tecnica": "habilitacao_tecnica",
    "economica": "habilitacao_econ_financeira",
    "geografico": "condicao_participacao",
    "temporal": "condicao_participacao",
    "marca": "condicao_participacao",
}


def rotular_eixo(clau: dict) -> tuple[str, str]:
    """(eixo, subtipo). Cobre as duas formas: exigência (tipo) e restritiva (categoria)."""
    if clau.get("tipo") in _EIXO_POR_TIPO:
        return _EIXO_POR_TIPO[clau["tipo"]]
    cat = clau.get("categoria")
    if cat in _EIXO_POR_CATEGORIA:
        return _EIXO_POR_CATEGORIA[cat], clau.get("tipo") or cat
    return "condicao_participacao", clau.get("tipo") or clau.get("categoria") or "outro"


def _faixa(clau: dict) -> str:
    """Bucketiza o parâmetro numérico p/ a assinatura ser estável a pequenas variações."""
    pct = clau.get("quantitativo_exigido_pct")
    if pct is not None:
        return "alto" if pct > 50 else "baixo"
    if clau.get("valor") is not None:
        return "com_valor"
    return "na"


def assinatura(clau: dict) -> str:
    eixo, subtipo = rotular_eixo(clau)
    return f"{eixo}:{subtipo}:{_faixa(clau)}"


def _parametro_num(clau: dict) -> float | None:
    v = clau.get("quantitativo_exigido_pct")
    if v is None:
        v = clau.get("valor")
    return float(v) if v is not None else None


def extrair_clausulas(texto: str, valor_estimado: float | None) -> list[dict]:
    """Todas as cláusulas de habilitação/participação do texto, rotuladas e assinadas."""
    linhas = _linhas_com_contexto([{"texto": texto or "", "fonte": "edital"}])
    brutas = _extrair_exigencias(linhas, valor_estimado) + _extrair_clausulas_restritivas(linhas, valor_estimado)
    out = []
    for c in brutas:
        eixo, subtipo = rotular_eixo(c)
        prov = c.get("prov")
        out.append({
            "eixo": eixo, "subtipo": subtipo, "texto": c.get("texto", "")[:400],
            "parametro_num": _parametro_num(c), "assinatura": assinatura(c),
            "trecho_fonte": prov.get("trecho") if isinstance(prov, dict) else str(prov or ""),
        })
    return out


def gravar(con, numero_controle_pncp: str, clausulas: list[dict]) -> int:
    con.execute("DELETE FROM edital_clausula WHERE numero_controle_pncp=?", (numero_controle_pncp,))
    for c in clausulas:
        con.execute(
            """INSERT INTO edital_clausula
                 (numero_controle_pncp, eixo, subtipo, texto, parametro_num, assinatura, trecho_fonte)
               VALUES (?,?,?,?,?,?,?)""",
            (numero_controle_pncp, c["eixo"], c["subtipo"], c["texto"],
             c["parametro_num"], c["assinatura"], c["trecho_fonte"]))
    con.commit()
    return len(clausulas)
