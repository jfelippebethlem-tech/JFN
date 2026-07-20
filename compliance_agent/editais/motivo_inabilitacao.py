# -*- coding: utf-8 -*-
"""Classificador de motivo de inabilitação/desclassificação — TRIVIAL × SUBSTANCIAL.

Complementa o J7 (que mede SELETIVIDADE — dois pesos entre licitantes): aqui medimos a TRIVIALIDADE
do motivo em si. Eliminar licitante por falha meramente formal/sanável SEM diligência de saneamento
viola o art. 64 §1º c/c art. 12 III da Lei 14.133/2021 (formalismo moderado) — e restringe a
competição mesmo quando aplicado uniformemente a todos (J7 exculparia; aqui NÃO).

Gabarito NO CÓDIGO (lição da casa: gabarito em código > LLM fraca). O resíduo ambíguo devolve
'ambiguo' — juízo vai à rubrica LLM (flag no máximo SUSPEITO), nunca decidido aqui por palpite.

Uso: `classificar(motivo_texto, houve_diligencia=False)` → dict com classe, sinal casado e fundamento.
"""
from __future__ import annotations

import re

# ── TRIVIAL/SANÁVEL: falha formal que não altera a substância (rol construído sobre art. 64 §1º,
#    art. 12 III e prática TCU de formalismo moderado). Ordem importa: 1º match vence.
_TRIVIAIS: tuple[tuple[str, re.Pattern], ...] = (
    ("assinatura/rubrica faltante",
     re.compile(r"(?:falta|aus[êe]ncia|sem)\s+(?:de\s+)?(?:assinatura|rubrica)|n[ãa]o\s+(?:assinou|rubricou)", re.I)),
    ("certidão vencida (verificável online)",
     re.compile(r"certid[ãa]o\s+(?:\w+\s+){0,4}?(?:vencid|fora\s+do\s+prazo\s+de\s+validade|com\s+validade\s+expirad)", re.I)),
    ("falha de formatação/numeração/ordem",
     re.compile(r"(?:numera[çc][ãa]o|pagina[çc][ãa]o|formata[çc][ãa]o|ordem)\s+(?:incorret|divergent|irregular|fora)"
                r"|fora\s+da\s+ordem\s+(?:do\s+edital|exigida)", re.I)),
    ("cópia sem autenticação",
     re.compile(r"(?:c[óo]pia|documento)\s+(?:simples\s+)?(?:sem|n[ãa]o)\s+autenticad", re.I)),
    ("declaração-modelo ausente/incompleta",
     re.compile(r"declara[çc][ãa]o\s+(?:\w+\s+){0,5}?(?:aus[êe]ncia|ausente|faltante|n[ãa]o\s+apresentad|em\s+desacordo\s+com\s+o\s+modelo|fora\s+do\s+modelo)"
                r"|(?:falta|aus[êe]ncia)\s+d[ae]\s+declara[çc][ãa]o", re.I)),
    ("erro material/preenchimento",
     re.compile(r"erro\s+(?:material|de\s+preenchimento|de\s+digita[çc][ãa]o|formal)|mera\s+irregularidade", re.I)),
    ("proposta sem via/formato exigido",
     re.compile(r"(?:via|envelope|arquivo)\s+(?:\w+\s+){0,3}?(?:em\s+desacordo|incorret|errad)"
                r"|formato\s+(?:de\s+arquivo\s+)?(?:diverso|em\s+desacordo)", re.I)),
    ("prazo de validade da proposta divergente",
     re.compile(r"validade\s+da\s+proposta\s+(?:inferior|divergente|em\s+desacordo)", re.I)),
)

# ── SUBSTANCIAL: descumprimento de requisito de mérito — inabilitar é lícito (diligência não
#    substitui documento/atributo essencial).
_SUBSTANCIAIS: tuple[tuple[str, re.Pattern], ...] = (
    ("quantitativo/atestado técnico não atendido",
     re.compile(r"atestad[oa].{0,60}(?:n[ãa]o\s+(?:atend|comprov|atingi)|insuficient|inferior|em\s+desacordo)"
                r"|(?:capacidade|qualifica[çc][ãa]o)\s+t[ée]cnica\s+(?:n[ãa]o\s+comprovad|insuficient)", re.I)),
    ("capital/patrimônio/índice insuficiente",
     re.compile(r"(?:capital\s+social|patrim[ôo]nio\s+l[íi]quido|[íi]ndice\s+de\s+liquidez)\s+"
                r"(?:\w+\s+){0,3}?(?:insuficient|inferior|n[ãa]o\s+atend|n[ãa]o\s+comprovad)", re.I)),
    ("objeto social/CNAE incompatível",
     re.compile(r"(?:objeto\s+social|atividade|cnae)\s+(?:\w+\s+){0,3}?incompat[íi]vel", re.I)),
    ("documento essencial não apresentado",
     re.compile(r"n[ãa]o\s+apresent\w+\s+(?:o\s+|a\s+)?(?:balan[çc]o|contrato\s+social|registro|alvar[áa]|licen[çc]a)"
                r"|(?:balan[çc]o|contrato\s+social|alvar[áa]|licen[çc]a)\s+(?:\w+\s+){0,3}?n[ãa]o\s+apresentad", re.I)),
    ("preço inexequível/acima do estimado",
     re.compile(r"inexequ[íi]vel|acima\s+do\s+(?:or[çc]amento|valor)\s+estimado|sobrepre[çc]o", re.I)),
    ("sanção/impedimento vigente",
     re.compile(r"(?:sancionad|impedid|suspens|inid[ôo]ne|declara[çc][ãa]o\s+de\s+inidoneidade)", re.I)),
)


def classificar(motivo: str, houve_diligencia: bool = False) -> dict:
    """Classifica o motivo de eliminação de um licitante.

    Returns:
      {classe: 'trivial'|'substancial'|'ambiguo'|'nao_aferivel',
       sinal: rótulo do padrão casado, fundamento: base legal do juízo,
       violacao_saneamento: bool — True quando TRIVIAL sem diligência (art. 64 §1º descumprido)}
    """
    m = (motivo or "").strip()
    if not m:
        return {"classe": "nao_aferivel", "sinal": "", "fundamento": "motivo ausente/ilegível (INDISPONÍVEL ≠ 0)",
                "violacao_saneamento": False}
    # substancial primeiro: "atestado não atende quantitativo" contém palavras formais e não pode
    # cair em trivial por engano — precisão > cobertura (indício ≠ acusação)
    for rotulo, rx in _SUBSTANCIAIS:
        if rx.search(m):
            return {"classe": "substancial", "sinal": rotulo,
                    "fundamento": "descumprimento de requisito de mérito — inabilitação lícita em abstrato",
                    "violacao_saneamento": False}
    for rotulo, rx in _TRIVIAIS:
        if rx.search(m):
            viol = not houve_diligencia
            fund = ("falha meramente formal/sanável — eliminação SEM diligência de saneamento viola o "
                    "art. 64 §1º c/c art. 12 III da Lei 14.133/2021 (formalismo moderado)"
                    if viol else
                    "falha formal sanável, MAS houve diligência/saneamento — art. 64 §1º observado")
            return {"classe": "trivial", "sinal": rotulo, "fundamento": fund, "violacao_saneamento": viol}
    return {"classe": "ambiguo", "sinal": "",
            "fundamento": "motivo não casa gabarito trivial nem substancial — juízo à rubrica (flag no máximo suspeito)",
            "violacao_saneamento": False}


def taxa_trivialidade(motivos: list[dict]) -> dict:
    """Agrega classificações de um certame: {n, triviais, violacoes_saneamento, substanciais, ambiguos,
    nao_aferiveis, taxa_trivial}. `motivos` = lista de retornos de classificar()."""
    n = len(motivos)
    tr = sum(1 for r in motivos if r["classe"] == "trivial")
    return {"n": n,
            "triviais": tr,
            "violacoes_saneamento": sum(1 for r in motivos if r.get("violacao_saneamento")),
            "substanciais": sum(1 for r in motivos if r["classe"] == "substancial"),
            "ambiguos": sum(1 for r in motivos if r["classe"] == "ambiguo"),
            "nao_aferiveis": sum(1 for r in motivos if r["classe"] == "nao_aferivel"),
            "taxa_trivial": round(tr / n, 3) if n else None}
