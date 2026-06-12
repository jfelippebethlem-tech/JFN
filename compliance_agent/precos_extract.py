# -*- coding: utf-8 -*-
"""Extração de PREÇOS UNITÁRIOS de editais/contratos + sobrepreço INTERNO (dispersão).

Gap p/ sobrepreço: o SEI/PNCP captura o TEXTO do edital/contrato, mas ninguém extraía a **tabela de itens**
(descrição × quantidade × preço unitário). Este módulo extrai isso por heurística determinística (regex,
livre/testável, nunca inventa) e habilita 2 análises:
  1. **Sobrepreço EXTERNO** (via `sobrepreco.py`): preço unitário vs mediana de mercado (precisa CATMAT — futuro).
  2. **Sobrepreço INTERNO** (aqui, SEM API): o MESMO item comprado a preços unitários muito diferentes entre
     contratos/órgãos → dispersão alta = **indício** de sobrepreço (a confirmar: especificação/região/qtd diferem).

Honestidade (regra-mãe): preço unitário é FATO extraído do texto; dispersão é INDÍCIO, não prova. Onde o texto
não permite extrair com segurança, o item fica de fora (nunca fabrica número).
"""
from __future__ import annotations

import re
import statistics
import unicodedata

# valor BR: 1.234.567,89 → float
_VALOR = r"(\d{1,3}(?:\.\d{3})*,\d{2})"
_UNID = r"(UN|UNID|UNIDADE|PC|PCT|CX|CAIXA|KG|G|L|ML|M|M2|M3|MES|MÊS|HORA|H|SERV|SERVICO|SERVIÇO|GLOBAL|VB|RESMA|PAR|KIT|FRASCO|LITRO|METRO|TON)"

# Padrão A — explícito: "...Valor/Vlr Unitário[ : ] R$ X" (com qtd opcional antes)
_RE_UNIT_EXPLICITO = re.compile(
    r"(?:qtd|quant(?:idade)?\.?\s*[:.]?\s*(?P<qtd>[\d.]+(?:,\d+)?))?"
    r".{0,80}?(?:valor|vlr|pre[çc]o)\s*unit[aá]rio\s*[:\-]?\s*R?\$?\s*" + _VALOR,
    re.I | re.S)

# Padrão B — linha tabular: "<item> <descr> <unid> <qtd> R$ <unit> R$ <total>"
_RE_LINHA_TAB = re.compile(
    r"^\s*(?P<item>\d{1,4})[\s.\-)]+(?P<descr>.+?)\s+" + _UNID + r"\s+(?P<qtd>[\d.]+(?:,\d+)?)\s+"
    r"R?\$?\s*" + _VALOR + r"\s+R?\$?\s*" + _VALOR + r"\s*$",
    re.I | re.M)


def _f(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _norm(s: str) -> str:
    s = (s or "").upper().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)[:120]


def extrair_itens(texto: str) -> list[dict]:
    """Extrai itens {descricao, quantidade, unidade, preco_unitario, preco_total, fonte} do texto. Honesto."""
    texto = texto or ""
    itens: list[dict] = []
    vistos: set = set()

    # B) linhas tabulares (mais confiável: tem unidade + qtd + unit + total)
    for m in _RE_LINHA_TAB.finditer(texto):
        # grupos: 1=item, 2=descr, 3=unidade, 4=qtd, 5=preço unit, 6=preço total
        unit = _f(m.group(5))
        total = _f(m.group(6))
        qtd = _f(m.group("qtd")) if m.group("qtd") else None
        descr = _norm(m.group("descr"))
        if unit <= 0 or len(descr) < 4:
            continue
        # sanidade: total ≈ qtd*unit (tolerância) — descarta linha mal-parseada
        if qtd and total and abs(total - qtd * unit) > max(1.0, 0.05 * total):
            continue
        key = (descr, unit)
        if key in vistos:
            continue
        vistos.add(key)
        itens.append({"descricao": descr, "quantidade": qtd, "unidade": m.group(3).upper(),
                      "preco_unitario": round(unit, 2), "preco_total": round(total, 2), "fonte": "tabela"})

    # A) padrão explícito "valor unitário: R$ X" (quando não há tabela limpa)
    if not itens:
        for m in _RE_UNIT_EXPLICITO.finditer(texto):
            unit = _f(m.group(m.lastindex))
            if unit <= 0:
                continue
            # descrição = trecho do match ANTES de "valor/vlr/preço unit", sem o "quantidade: N"
            seg = re.split(r"(?:valor|vlr|pre[çc]o)\s*unit", m.group(0), flags=re.I)[0]
            seg = re.sub(r"quant\w*\.?\s*[:.]?\s*[\d.,]+", "", seg, flags=re.I)
            # se o match começou no meio do texto, usa também o que vem logo antes (até 60 chars) p/ contexto
            if m.start() > 0 and len(_norm(seg)) < 4:
                seg = texto[max(0, m.start() - 60):m.start()] + seg
            descr = _norm(seg)[-90:].strip(" .:-")
            qm = re.search(r"quant\w*\.?\s*[:.]?\s*([\d.]+(?:,\d+)?)", m.group(0), re.I)
            qtd = _f(qm.group(1)) if qm else (_f(m.group("qtd")) if m.group("qtd") else None)
            key = (descr, unit)
            if key in vistos or len(descr) < 4:
                continue
            vistos.add(key)
            itens.append({"descricao": descr, "quantidade": qtd, "unidade": None,
                          "preco_unitario": round(unit, 2), "preco_total": None, "fonte": "explicito"})
    return itens


def sobrepreco_interno(registros: list[dict], min_amostras: int = 3) -> list[dict]:
    """Compara o MESMO item entre contratos/órgãos (chave = descrição normalizada). Dispersão alta de preço
    unitário = INDÍCIO de sobrepreço. `registros`: [{descricao, preco_unitario, ref, orgao?}]. Honesto:
    só reporta itens com >= min_amostras (senão amostra insuficiente → INDISPONÍVEL, não conclui)."""
    por_item: dict[str, list[dict]] = {}
    for r in registros:
        d = _norm(r.get("descricao", ""))
        if not d or not r.get("preco_unitario"):
            continue
        por_item.setdefault(d, []).append(r)
    achados = []
    for descr, regs in por_item.items():
        precos = [x["preco_unitario"] for x in regs]
        if len(precos) < min_amostras:
            continue
        mn, mx = min(precos), max(precos)
        med = statistics.median(precos)
        if med <= 0:
            continue
        razao = mx / mn if mn > 0 else 0.0
        # indício: o maior preço é >= 2x o menor (a mesma coisa custou o dobro+ em outro lugar)
        if razao >= 2.0:
            caro = max(regs, key=lambda x: x["preco_unitario"])
            barato = min(regs, key=lambda x: x["preco_unitario"])
            achados.append({"item": descr, "n": len(precos), "min": mn, "max": mx, "mediana": med,
                            "razao_max_min": round(razao, 1),
                            "mais_caro": {"preco": mx, "ref": caro.get("ref"), "orgao": caro.get("orgao")},
                            "mais_barato": {"preco": mn, "ref": barato.get("ref"), "orgao": barato.get("orgao")},
                            "sobrepreco_pct_vs_mediana": round(100 * (mx - med) / med, 1)})
    achados.sort(key=lambda a: -a["razao_max_min"])
    return achados


if __name__ == "__main__":  # pragma: no cover
    import sys
    txt = sys.stdin.read() if not sys.stdin.isatty() else " ".join(sys.argv[1:])
    for it in extrair_itens(txt):
        print(it)
