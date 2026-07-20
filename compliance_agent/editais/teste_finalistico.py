# -*- coding: utf-8 -*-
"""Teste finalístico EXECUTADO — extrai o número exigido na cláusula e compara ao teto legal.

O INDICE_CLAUSULA (knowledge/jurisprudencia) exibe o teste como texto; aqui ele roda de verdade:
"capital 30% do estimado" vs teto 10% (Súmula TCU 275) → VIOLADO, objetivo, antes de qualquer LLM.
Serve de guard anti-FP simétrico: exigência DENTRO do teto rebaixa o achado (dentro_do_teto).
Sem número aferível → nao_aferivel (INDISPONÍVEL ≠ 0; o juízo volta ao colegiado/humano).
"""
from __future__ import annotations

import re

# percentual: "30%", "30 %", "30,5%" (a forma por extenso entre parênteses é redundante no edital)
_RE_PCT = re.compile(r"(\d{1,3}(?:[.,]\d{1,2})?)\s*%")
# moeda: "R$ 500.000,00"
_RE_BRL = re.compile(r"R\$\s*([\d.]+(?:,\d{2})?)")
# prazo: "24 horas", "2 dias", "10 (dez) dias corridos/úteis"
_RE_HORAS = re.compile(r"(\d{1,3})\s*(?:\([^)]*\)\s*)?horas?", re.I)
_RE_DIAS = re.compile(r"(\d{1,3})\s*(?:\([^)]*\)\s*)?dias?", re.I)
# expressão de equivalência que descaracteriza marca dirigida (Súmula TCU 270 / Lei 14.133 art. 41 I)
_RE_EQUIV = re.compile(r"ou\s+(?:equivalente|similar|superior)|qualidade\s+igual\s+ou\s+superior", re.I)
# vigência (Lei 14.133 arts. 106-111): meses/anos, indeterminada e a exculpatória do art. 109 (monopólio)
_RE_MESES = re.compile(r"(\d{1,3})\s*(?:\([^)]*\)\s*)?m[eê]s(?:es)?", re.I)
_RE_ANOS = re.compile(r"(\d{1,2})\s*(?:\([^)]*\)\s*)?anos?", re.I)
_RE_INDETERMINADA = re.compile(r"indeterminad", re.I)
_RE_MONOPOLIO = re.compile(r"monop[óo]lio", re.I)
_RE_CONTINUO = re.compile(r"cont[íi]nu|presta[çc][ãa]o\s+de\s+servi[çc]o", re.I)


def _pct(texto: str) -> float | None:
    m = _RE_PCT.search(texto)
    return float(m.group(1).replace(",", ".")) if m else None


def _brl(texto: str) -> float | None:
    m = _RE_BRL.search(texto)
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def _res(subtipo: str, status: str, motivo: str, valor=None, teto=None, fonte="") -> dict:
    return {"subtipo": subtipo, "status": status, "motivo": motivo,
            "valor_extraido": valor, "teto": teto, "fonte_teto": fonte}


def _teto_percentual(subtipo, clausula, valor_estimado, teto, fonte, rotulo) -> dict:
    """Regra comum: percentual exigido vs teto; valor absoluto em R$ vira % do estimado."""
    pct = _pct(clausula)
    if pct is None:
        absoluto = _brl(clausula)
        if absoluto and valor_estimado:
            pct = round(absoluto / valor_estimado * 100, 1)
        elif absoluto:
            return _res(subtipo, "nao_aferivel",
                        f"{rotulo} exigido em valor absoluto (R$ {absoluto:,.2f}) e o valor estimado do "
                        "certame não está disponível para aferir o percentual", absoluto, teto, fonte)
        else:
            return _res(subtipo, "nao_aferivel", f"cláusula não traz percentual nem valor de {rotulo} aferível",
                        None, teto, fonte)
    if pct > teto:
        return _res(subtipo, "violado",
                    f"{rotulo} de {pct:g}% excede o teto de {teto:g}% ({fonte})", pct, teto, fonte)
    return _res(subtipo, "dentro_do_teto",
                f"{rotulo} de {pct:g}% respeita o teto de {teto:g}% ({fonte}) — exigência lícita em abstrato",
                pct, teto, fonte)


def avaliar(subtipo: str, clausula: str, valor_estimado: float | None = None) -> dict | None:
    """Roda o teste finalístico do subtipo sobre a cláusula. None = subtipo sem teste executável."""
    c = clausula or ""
    if subtipo in ("capital_patrimonio", "capital", "patrimonio"):
        return _teto_percentual(subtipo, c, valor_estimado, 10.0,
                                "Súmula TCU 275; Lei 8.666/93 art. 31 §3º", "capital/patrimônio líquido")
    if subtipo in ("atestado_quantitativo", "atestado"):
        return _teto_percentual(subtipo, c, valor_estimado, 50.0,
                                "Súmula TCU 263", "quantitativo do atestado")
    if subtipo in ("garantia_proposta", "garantia"):
        return _teto_percentual(subtipo, c, valor_estimado, 1.0,
                                "Lei 14.133/2021 art. 58 §1º; Súmula TCU 275", "garantia de proposta")
    if subtipo in ("marca_dirigida", "marca"):
        if _RE_EQUIV.search(c):
            return _res(subtipo, "dentro_do_teto",
                        "a cláusula admite 'ou equivalente/similar' — a indicação de marca é referencial, "
                        "não excludente (Súmula TCU 270)", None, None, "Súmula TCU 270")
        return _res(subtipo, "violado",
                    "indicação de marca SEM expressão de equivalência — excludente em abstrato, salvo "
                    "padronização prévia justificada (Súmula TCU 270; Lei 14.133/2021 art. 41 I)",
                    None, None, "Súmula TCU 270")
    if subtipo in ("faturamento_minimo", "faturamento"):
        r = _teto_percentual(subtipo, c, valor_estimado, 10.0,
                             "Lei 14.133/2021 art. 69 (rol restrito), Súmula TCU 275 por analogia ao capital/PL",
                             "faturamento mínimo")
        if r["status"] == "dentro_do_teto":
            # simetria quebrada de propósito: faturamento mínimo NÃO consta do rol do art. 69 — mesmo abaixo
            # de 10% a exigência é atípica; o juízo de licitude em abstrato volta ao colegiado (não rebaixamos).
            r["status"] = "nao_aferivel"
            r["motivo"] += (" — porém exigência de faturamento mínimo não consta do rol restrito do art. 69 "
                            "da Lei 14.133/2021; juízo devolvido ao colegiado")
        return r
    if subtipo in ("vigencia_contratual", "vigencia"):
        if _RE_INDETERMINADA.search(c):
            if _RE_MONOPOLIO.search(c):
                return _res(subtipo, "nao_aferivel",
                            "vigência indeterminada COM menção a monopólio — possível hipótese lícita do "
                            "art. 109 (usuária de serviço público em regime de monopólio); conferir enquadramento",
                            None, 60.0, "Lei 14.133/2021 art. 109")
            return _res(subtipo, "violado",
                        "vigência por prazo INDETERMINADO fora da única hipótese legal (art. 109 — serviço "
                        "público em regime de monopólio)", None, 60.0, "Lei 14.133/2021 arts. 106-109")
        m = _RE_MESES.search(c)
        meses = float(m.group(1)) if m else None
        if meses is None:
            m = _RE_ANOS.search(c)
            meses = float(m.group(1)) * 12 if m else None
        if meses is None:
            return _res(subtipo, "nao_aferivel", "cláusula não traz vigência numérica aferível",
                        None, 60.0, "Lei 14.133/2021 art. 106")
        if meses > 60:
            if _RE_CONTINUO.search(c):
                return _res(subtipo, "violado",
                            f"vigência inicial de {meses:g} meses excede o teto de 5 anos do art. 106 para "
                            "serviços/fornecimentos contínuos (prorrogação é instituto diverso — art. 107)",
                            meses, 60.0, "Lei 14.133/2021 art. 106")
            return _res(subtipo, "nao_aferivel",
                        f"vigência de {meses:g} meses excede 5 anos, mas a cláusula não permite afirmar serviço "
                        "CONTÍNUO — contrato por escopo segue regra própria (art. 111); juízo ao colegiado",
                        meses, 60.0, "Lei 14.133/2021 arts. 106 e 111")
        return _res(subtipo, "dentro_do_teto",
                    f"vigência de {meses:g} meses respeita o teto de 5 anos do art. 106 — lícita em abstrato",
                    meses, 60.0, "Lei 14.133/2021 art. 106")
    if subtipo in ("recorte_temporal", "temporal"):
        m = _RE_HORAS.search(c)
        dias = round(float(m.group(1)) / 24, 2) if m else None
        if dias is None:
            m = _RE_DIAS.search(c)
            dias = float(m.group(1)) if m else None
        if dias is None:
            return _res(subtipo, "nao_aferivel", "cláusula não traz prazo numérico aferível",
                        None, 2.0, "Acórdão TCU 871/2023")
        if dias <= 2:
            return _res(subtipo, "violado",
                        f"prazo de {dias:g} dia(s) é objetivamente exíguo — inviabiliza quem não é o atual "
                        "prestador (Acórdão TCU 871/2023)", dias, 2.0, "Acórdão TCU 871/2023")
        return _res(subtipo, "nao_aferivel",
                    f"prazo de {dias:g} dias extraído; proporcionalidade depende do objeto — "
                    "juízo devolvido ao colegiado", dias, 2.0, "Acórdão TCU 871/2023")
    return None
