# -*- coding: utf-8 -*-
"""Pensamentos determinísticos do contrato — o funil barato antes da câmara.

Cada thought é função pura (dossie) -> [achado]. Achado:
  {dimensao, risco 0-10, texto, norma, proveniencia}.
Limiares nomeados no topo (nunca no prompt do LLM). Ausente ≠ 0: sem dado, não marca.
"""
from __future__ import annotations

import re

ADITIVO_LIMITE = 0.25          # art. 125 — acréscimo de valor
ADITIVO_REFORMA = 0.50         # 50% só reforma de edifício/equipamento
SOBREPRECO_RATIO = 1.3         # >30% acima da referência = candidato
SOBREPRECO_RATIO_MAX = 8.0     # acima disso = quase sempre CATMAT errado/unidade divergente, NÃO sobrepreço real
SOBREPRECO_MIN_N = 3           # referência só vale com base de mercado suficiente
PRORROGACAO_MIN_EXERC = 3

_RX_REFORMA = re.compile(r"reforma|edif[íi]cio|equipamento", re.IGNORECASE)


def _brl(v) -> str:
    return f"{(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _achado(dimensao, risco, texto, norma, proveniencia) -> dict:
    return {"dimensao": dimensao, "risco": max(0, min(10, int(risco))), "texto": texto,
            "norma": norma, "proveniencia": proveniencia}


def t_aditivo(d: dict) -> list[dict]:
    """Acréscimo de VALOR acumulado dos termos > 25% (50% só reforma). Prazo puro não conta."""
    c = d.get("contrato", {})
    vi = c.get("valor_inicial") or 0
    if vi <= 0:
        return []
    soma = sum((a.get("valor_acrescido") or 0) for a in d.get("aditivos", []))
    if soma <= 0:
        return []                                  # só prazo/reajuste → não é acréscimo de valor
    ratio = soma / vi
    objetos = " ".join((a.get("objeto") or "") for a in d.get("aditivos", []))
    limite = ADITIVO_REFORMA if _RX_REFORMA.search(objetos + " " + (c.get("objeto") or "")) else ADITIVO_LIMITE
    if ratio <= limite:
        return []
    risco = min(9, 5 + int(ratio * 4))
    return [_achado(
        "aditivo", risco,
        f"Acréscimo de valor de {ratio:.0%} (R$ {_brl(soma)} sobre R$ {_brl(vi)}) acima do "
        f"limite de {limite:.0%} do art. 125 da Lei 14.133/2021.",
        "Lei 14.133/2021, art. 125",
        {"ratio": round(ratio, 3), "valor_acrescido": soma, "valor_inicial": vi})]


def t_prorrogacao(d: dict) -> list[dict]:
    """Serviço contínuo prorrogado além do razoável (histórico de exercícios no dossiê)."""
    hist = d.get("historico_exercicios") or []
    if len(hist) < PRORROGACAO_MIN_EXERC:
        return []
    return [_achado(
        "prorrogacao", 6,
        f"Mesmo fornecedor/objeto mantido por {len(hist)} exercícios ({', '.join(map(str, hist))}) — "
        f"prorrogação sucessiva; verificar teste de economicidade (art. 107).",
        "Lei 14.133/2021, art. 106/107", {"exercicios": hist})]


def t_execucao_financeira(d: dict) -> list[dict]:
    """NÃO AVALIÁVEL com a base atual (honestidade: ausente ≠ 0).

    `pcrj_despesa.pago` é a soma de TODOS os pagamentos do fornecedor no período —
    não liga a ESTE contrato (não há vínculo NL/empenho→contrato na base municipal).
    Comparar o total do fornecedor com o valor de um contrato gera falso-positivo
    sistemático (revisão à mão 2026-07-11). Fica para o Spec 3 (SEI liga empenho→
    contrato→medição). Até lá, esta dimensão não emite achado."""
    return []


def t_sobrepreco(d: dict, ref_fn=None) -> list[dict]:
    """Item com unitário > 1,3× a referência (peer/Painel). Sem referência → não marca."""
    if ref_fn is None:
        return []
    achados = []
    for it in d.get("itens", []):
        vu = it.get("valor_unitario") or it.get("valorUnitarioEstimado")
        desc = it.get("descricao") or ""
        if not vu or not desc:
            continue
        ref = ref_fn(desc)
        if not ref or not ref.get("disponivel") or not ref.get("mediana"):
            continue
        if (ref.get("n") or 0) < SOBREPRECO_MIN_N:
            continue                                   # base de mercado insuficiente
        ratio = vu / ref["mediana"]
        # descarta os dois lados suspeitos: ≤1.3× é normal; >8× é quase sempre CATMAT
        # errado ou unidade divergente (caixa×unidade) — não é sobrepreço real (revisão à mão)
        if ratio <= SOBREPRECO_RATIO or ratio > SOBREPRECO_RATIO_MAX:
            continue
        risco = min(9, 5 + int(ratio))
        achados.append(_achado(
            "sobrepreco", risco,
            f"Item \"{desc[:60]}\": unitário R$ {_brl(vu)} = {ratio:.1f}× a referência de mercado "
            f"(R$ {_brl(ref['mediana'])}, n={ref.get('n')}). Indício de sobrepreço/jogo de planilha.",
            "Lei 14.133/2021, art. 23 (preço de referência)",
            {"ratio": round(ratio, 2), "unitario": vu, "referencia": ref["mediana"]}))
    return achados


def _sinais_lex(d: dict, achados: list[dict]) -> dict:
    """Mapeia o dossiê+achados nos sinais que a triagem do Lex pontua."""
    dims = {a["dimensao"] for a in achados}
    sinais = {}
    if "sobrepreco" in dims:
        sinais["desconto_atipico"] = True
    if "aditivo" in dims:
        sinais["fracionamento"] = True   # aditivo recorrente ~ fuga de novo certame
    if any("rede" in s for s in d.get("sinais_fornecedor", [])):
        sinais["coincidencia_participantes"] = True
    return sinais


def t_lex(d: dict, achados: list[dict] | None = None) -> list[dict]:
    """Nota 🟢🟡🔴 do Lex sobre o dossiê (reusa o motor de triagem)."""
    from compliance_agent.lex_indicadores_fraude import triagem
    sinais = _sinais_lex(d, achados or [])
    if not sinais:
        return []
    res = triagem(sinais)
    if res["faixa"] == "🟢" or res["score_risco"] <= 0:
        return []
    risco = min(9, 3 + res["n_indicadores"] * 2)
    return [_achado(
        "lex", risco,
        f"Triagem Lex: faixa {res['faixa']}, score {res['score_risco']}, "
        f"{res['n_indicadores']} indicador(es): {', '.join(res.get('tipologias', []))}.",
        "Indicadores de fraude Lex (R2–R12)", {"score_lex": res["score_risco"]})]


def t_sinais_cruzados(d: dict) -> list[dict]:
    """Fornecedor × emendas/sanções/rede — amarra o contrato ao beneficiário."""
    sinais = d.get("sinais_fornecedor") or []
    if not sinais:
        return []
    risco = 8 if any("sancionado" in s for s in sinais) else 6
    return [_achado(
        "beneficiario", risco,
        f"Sinais cruzados do fornecedor: {', '.join(sinais)}. Reforça priorização (indício ≠ acusação).",
        "cruzamento CEIS/emendas/rede", {"sinais": sinais})]


def rodar_thoughts(d: dict, ref_fn=None) -> list[dict]:
    achados = []
    for fn in (t_aditivo, t_prorrogacao, t_execucao_financeira, t_sinais_cruzados):
        achados.extend(fn(d))
    achados.extend(t_sobrepreco(d, ref_fn=ref_fn))
    achados.extend(t_lex(d, achados))
    achados.sort(key=lambda a: -a["risco"])
    return achados
