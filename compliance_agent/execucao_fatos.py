# -*- coding: utf-8 -*-
"""Ponte TEXTO → FATOS para os detectores da fase de execução (plano #4, itens 2.1 e 2.2).

Ao executar o plano descobriu-se que a regra jurídica **já existe e está madura** no projeto:
  • `detectores/x1_crescimento_aditivo.py` — teto do art. 125 (25% / 50% reforma), reajuste e aditivo de
    só-prazo fora do teto, aditivo precoce, rubricas de justificativa/pertinência;
  • `detectores/x3_execucao_financeira.py` — pagamento ANTES do atesto, tríade comprimida, dezembro, fila;
  • `detectores/p4_fracionamento.py` + `limites_dispensa.py` — fracionamento por grupo de objeto.
Reescrever isso seria duplicar doutrina (e divergir dela na primeira manutenção). O que FALTAVA era a
ponte: alguém que leia o processo SEI e produza `{valor_inicial, aditivos[]}` e `{pagamentos[]}` — sem
eles os detectores respondem `nao_avaliavel` para sempre.

**Nenhum limiar legal mora aqui.** Este módulo só EXTRAI e CLASSIFICA o fato, com o trecho literal que o
sustenta. Quem julga é o detector.

HONESTIDADE: dado ausente → `None`/`[]` (nunca 0 — INDISPONÍVEL ≠ zero); §2 — sem Ordem Bancária não há
`data_pagamento` (empenho é compromisso, não pagamento), logo não se acusa antecipação do que não foi pago.
"""
from __future__ import annotations

import re

_RE_VALOR = re.compile(r"R\$\s*([\d.]+,\d{2})")
_RE_DATA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_RE_PERC = re.compile(r"(\d{1,3}(?:,\d+)?)\s*%")

# marcadores de cada natureza de aditivo. ORDEM IMPORTA: reajuste e prazo são testados ANTES de
# acréscimo, porque "reajuste ... no valor de R$" e "prorrogação ... sem acréscimo de valor" citam valor
# e seriam classificados como acréscimo quantitativo (o falso positivo clássico da família).
_NATUREZA = (
    ("reajuste", r"reajust|repactua|reequil[íi]brio|revis[ãa]o\s+de\s+pre[çc]|corre[çc][ãa]o\s+monet|"
                 r"\bIPCA\b|\bINCC\b|\bIGP-?M\b"),
    ("prazo", r"prorroga|prazo\s+de\s+vig[êe]ncia|dilata[çc][ãa]o\s+de\s+prazo"),
    ("valor", r"acr[ée]scim|acrescer|supress[ãa]o|suprimir|aditamento\s+de\s+valor|majora"),
)
_RE_ADITIVO = re.compile(
    r"(primeiro|segundo|terceiro|quarto|quinto|sexto|s[ée]timo|oitavo|nono|d[ée]cimo|\d+[ºo°]?)?\s*"
    r"termo\s+aditivo", re.I)
_RE_VALOR_INICIAL = re.compile(
    r"valor\s+(?:inicial|original|global\s+inicial|do\s+contrato)\s*(?:de|:)?\s*R\$\s*([\d.]+,\d{2})", re.I)
_RE_SUPRESSAO = re.compile(r"supress[ãa]o|suprimir", re.I)
# tipo de objeto que muda o teto do art.125 (quem aplica é o X1 — aqui só se classifica o objeto)
_RE_REFORMA = re.compile(r"reforma\s+(?:de\s+)?(?:edif[íi]cio|pr[ée]dio|im[óo]vel|equipamento|cobertura)|"
                         r"reforma\s+d[ao]\s", re.I)


def valor_br(s: str) -> float | None:
    """'R$ 1.234.567,89' → 1234567.89. Sem valor no texto → None (nunca 0.0: ausência ≠ zero)."""
    m = _RE_VALOR.search(s or "")
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def _data_iso(s: str) -> str | None:
    m = _RE_DATA.search(s or "")
    if not m:
        return None
    d, mth, y = m.groups()
    return f"{y}-{mth}-{d}"


def _sentencas(texto: str) -> list[str]:
    return [t.strip() for t in re.split(r"(?<=[.;])\s+", texto or "") if t.strip()]


def extrair_valor_inicial(texto: str) -> float | None:
    """Valor inicial do contrato (a base do teto do art. 125). Ausente → None."""
    m = _RE_VALOR_INICIAL.search(texto or "")
    return float(m.group(1).replace(".", "").replace(",", ".")) if m else None


def _natureza(frase: str) -> str:
    for nome, pat in _NATUREZA:
        if re.search(pat, frase, re.I):
            return nome
    return ""


def extrair_aditivos(texto: str) -> list[dict]:
    """Aditivos no formato que o X1 consome: [{data, tipo, valor, justificativa, trecho}].

    `tipo`: 'valor' (acréscimo/supressão — entra no teto) · 'prazo' (não entra) · 'reajuste' (recomposição,
    não entra). Supressão vem com valor NEGATIVO (o art. 125 as computa separadamente — quem separa é o X1).
    """
    out: list[dict] = []
    for frase in _sentencas(texto):
        if not _RE_ADITIVO.search(frase):
            continue
        nat = _natureza(frase)
        if not nat:
            continue
        valor = valor_br(frase)
        if nat == "prazo":
            valor = None                      # prorrogação: mesmo citando "sem acréscimo de valor"
        elif nat == "valor" and valor is not None and _RE_SUPRESSAO.search(frase):
            valor = -valor
        perc = _RE_PERC.search(frase)
        out.append({"data": _data_iso(frase), "tipo": nat, "valor": valor,
                    "percentual_citado": float(perc.group(1).replace(",", ".")) if perc else None,
                    "justificativa": frase, "trecho": frase[:400]})
    return out


def contexto_x1(texto: str, *, tipo_objeto: str | None = None) -> dict:
    """Contexto pronto para `X1CrescimentoAditivo`. `tipo_objeto` explícito vence a inferência do texto
    (é ele que define o teto de 25% ou 50% — a decisão é do X1, o insumo é daqui)."""
    tipo = tipo_objeto or ("reforma" if _RE_REFORMA.search(texto or "") else None)
    return {"valor_inicial": extrair_valor_inicial(texto), "aditivos": extrair_aditivos(texto),
            "tipo_objeto": tipo, "fonte": "execucao_fatos (extração do texto do processo)"}


# ───────────────────────────── X3: tríade da despesa × atesto ─────────────────────────────
_ETAPAS = (
    ("data_empenho", r"(?:nota\s+de\s+)?empenho[^.;]{0,80}?", r"20\d{2}NE\d+"),
    ("data_liquidacao", r"(?:nota\s+de\s+)?liquida[çc][ãa]o[^.;]{0,80}?", r"20\d{2}NL\d+"),
    ("data_pagamento", r"ordem\s+banc[áa]ria[^.;]{0,80}?", r"20\d{2}OB\d+"),
    ("data_atesto", r"atest[oa][^.;]{0,80}?", None),
)


def _data_da_etapa(texto: str, padrao: str, codigo: str | None) -> str | None:
    """Data da 1ª sentença que fala da etapa. Casa pelo termo OU pelo código do SIAFE (2024OB000789)."""
    for frase in _sentencas(texto):
        if re.search(padrao, frase, re.I) or (codigo and re.search(codigo, frase, re.I)):
            d = _data_iso(frase)
            if d:
                return d
    return None


def extrair_pagamentos(texto: str) -> list[dict]:
    """Tríade empenho→liquidação→OB + data do atesto, no formato que o X3 consome.

    §2: `data_pagamento` só existe se houver ORDEM BANCÁRIA — empenho/liquidação não são pagamento.
    Devolve uma entrada por processo (o texto de um processo de pagamento traz um ciclo); vazio se não há
    nenhuma etapa identificável."""
    reg = {nome: _data_da_etapa(texto, pat, cod) for nome, pat, cod in _ETAPAS}
    if not any(reg.values()):
        return []
    reg["valor"] = valor_br(texto or "")
    reg["trecho"] = (texto or "")[:400]
    return [reg]


def contexto_x3(texto: str) -> dict:
    """Contexto pronto para `X3ExecucaoFinanceira` + o cruzamento direto que o dono pediu (pagamento
    ANTES do atesto). Sem OB ou sem atesto → False, nunca True por presunção."""
    pgs = extrair_pagamentos(texto)
    antes = any(p.get("data_pagamento") and p.get("data_atesto")
                and p["data_pagamento"] < p["data_atesto"] for p in pgs)
    return {"pagamentos": pgs, "pagamento_anterior_ao_atesto": antes,
            "fonte": "execucao_fatos (extração do texto do processo)"}
