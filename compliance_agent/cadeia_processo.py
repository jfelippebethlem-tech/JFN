# -*- coding: utf-8 -*-
"""CADEIA DO PROCESSO — as peças existem, mas estão na ORDEM que a lei exige?

`sei/fases.lacunas` responde o que FALTA nos autos. Faltava a outra metade: a SEQUÊNCIA. Presença sem
ordem não prova regularidade — e a inversão costuma ser o vício mais eloquente do processo:

  • **contrato assinado ANTES do parecer jurídico** — o art. 53 da Lei 14.133/2021 exige análise jurídica
    PRÉVIA; assinar antes reduz o controle a carimbo (e o parecer, a formalidade retroativa);
  • **pagamento ANTES da liquidação** — os arts. 62 e 63 da Lei 4.320/1964 mandam liquidar (verificar o
    direito adquirido do credor) antes de pagar; inverter é pagar sem conferir;
  • **liquidação ANTES do empenho** — art. 60 da Lei 4.320: a despesa se empenha antes de se realizar;
  • **aditivo ANTES do contrato** — não se adita o que ainda não existe.

O RELÓGIO: quando o título traz data, ela manda. Quando não traz, usa-se o **ID do documento no SEI**,
que é sequencial e global — cresce com o tempo. É PROXY, e o módulo declara isso em cada achado: o
documento pode ter sido produzido antes e juntado depois. Por isso o veredito é indício a verificar, não
prova — a data real do ato está no próprio documento, que o auditor abre.

HONESTIDADE: sem data e sem ID não há relógio → `nao_aplicavel` (não se inventa cronologia). Peça
ausente NÃO vira inversão (ausência é a família das lacunas). Veredito sempre RESOLVIDO.
"""
from __future__ import annotations

import re
from datetime import date, datetime

_RE_ID_SEI = re.compile(r"\((\d{6,10})\)")
_RE_DATA = re.compile(r"\b(\d{2})[/.-](\d{2})[/.-](\d{4})\b")

# marcos da cadeia, reconhecidos pelo TIPO do classificador ou pelo título
_MARCOS: dict[str, tuple[str, str]] = {
    # SÓ o parecer JURÍDICO exerce o controle prévio do art. 53. "Parecer Técnico de Medição" é peça de
    # execução e foi lido como jurídico no acervo real, gerando inversão falsa.
    "parecer_juridico": (r"parecer_juridic",
                         r"parecer\s+jur[íi]dic|parecer\s+(?:d[ao]\s+)?(?:PGE|PGM|procuradoria|assessoria\s+jur)|"
                         r"manifesta[çc][ãa]o\s+jur[íi]dica|cota\s+jur[íi]dica"),
    "contrato": (r"^contrato$|termo_contrato", r"termo\s+de\s+contrato|contrato\s+n[ºo°]|instrumento\s+contratual"),
    "aditivo": (r"aditivo", r"termo\s+aditivo|aditamento"),
    "empenho": (r"empenho|nota_empenho", r"nota\s+de\s+empenho|\b20\d{2}NE\d+"),
    "liquidacao": (r"liquidacao|nota_liquidacao", r"nota\s+de\s+liquida|\b20\d{2}NL\d+"),
    "pagamento": (r"ordem_bancaria|ob\b", r"ordem\s+banc[áa]ria|\b20\d{2}OB\d+"),
}

# (antes, depois, tipo do achado, fundamento) — o que a lei manda vir primeiro
_REGRAS: tuple[tuple[str, str, str, str], ...] = (
    ("parecer_juridico", "contrato", "contrato_antes_do_parecer",
     "art. 53 da Lei 14.133/2021 — a análise jurídica é PRÉVIA à celebração"),
    ("empenho", "liquidacao", "liquidacao_antes_do_empenho",
     "art. 60 da Lei 4.320/1964 — a despesa é empenhada antes de realizada"),
    ("liquidacao", "pagamento", "pagamento_antes_da_liquidacao",
     "arts. 62 e 63 da Lei 4.320/1964 — o pagamento só após a regular liquidação"),
    ("contrato", "aditivo", "aditivo_antes_do_contrato",
     "art. 124 da Lei 14.133/2021 — só se altera contrato existente"),
)
# TOLERÂNCIA DO RELÓGIO: medido no acervo (165 documentos que trazem data E id), o ID do SEI anda
# ~113.000 por DIA (p25 61 mil, p75 495 mil). Logo, diferenças pequenas são MINUTOS — a mesma sessão de
# juntada, não a ordem dos atos. Foi assim que "Despacho de Liquidação (87839016)" e "Nota de Empenho
# (87839511)", separados por 495, viraram falsa inversão. Exige-se ~meio dia (p25/2) para afirmar.
_TOLERANCIA_ID = 60_000
_TOLERANCIA_DIAS = 1.0

_RESSALVA = (
    "a ordem é aferida pela data do título quando existe e, na falta dela, pelo ID sequencial do "
    "documento no SEI — que é PROXY do tempo: a peça pode ter sido produzida antes e juntada depois. "
    "Indício a verificar na data do próprio ato, nunca prova; presunção de legitimidade")


def id_sei(titulo: str) -> int | None:
    """ID do documento no SEI (o número entre parênteses no título). É o relógio de reserva."""
    m = _RE_ID_SEI.search(titulo or "")
    return int(m.group(1)) if m else None


def _data_do_titulo(titulo: str) -> date | None:
    m = _RE_DATA.search(titulo or "")
    if not m:
        return None
    d, mth, y = m.groups()
    try:
        return datetime(int(y), int(mth), int(d)).date()
    except ValueError:
        return None


def momento(doc: dict) -> tuple[str, float] | tuple[None, None]:
    """(fonte, valor comparável) do documento: ('data', ordinal) · ('id_sei', id) · (None, None).
    A data explícita tem precedência sobre o ID — ela é o ato, o ID é só a juntada."""
    t = str(doc.get("titulo") or "")
    d = _data_do_titulo(t)
    if d:
        return "data", float(d.toordinal())
    i = id_sei(t)
    if i is not None:
        return "id_sei", float(i)
    return None, None


# o TÍTULO desmente o TIPO: o classificador marca "Parecer Técnico - 5ª Medição" como parecer_juridico,
# e parecer técnico de medição é peça de EXECUÇÃO, não o controle prévio do art. 53 (caso real
# 070002/006215/2024). Quando os dois discordam, vale o que está escrito.
_RE_NAO_JURIDICO = re.compile(r"parecer\s+t[ée]cnic|parecer\s+de\s+medi[çc]|parecer\s+contabil|"
                              r"parecer\s+de\s+engenh|laudo|certid", re.I)
# MINUTA de contrato/aditivo antes do parecer é o fluxo CORRETO (o art. 53 analisa a minuta);
# NF/e-mail classificados como contrato pelo conteúdo escaneado também não são o marco.
_RE_NAO_CONTRATO = re.compile(r"minuta|nota\s+fiscal|\bnfs?-?e?\b|e-?mail|gmail", re.I)


def _marco(doc: dict) -> str | None:
    tipo = str(doc.get("tipo") or "").lower()
    titulo = str(doc.get("titulo") or "")
    if _RE_NAO_JURIDICO.search(titulo):
        tipo = tipo.replace("parecer_juridico", "parecer_tecnico")
    for nome, (pat_tipo, pat_titulo) in _MARCOS.items():
        if re.search(pat_tipo, tipo, re.I) or re.search(pat_titulo, titulo, re.I):
            if nome in ("contrato", "aditivo") and _RE_NAO_CONTRATO.search(titulo):
                continue
            return nome
    return None


def analisar_cadeia(docs: list[dict]) -> dict:
    """Veredito RESOLVIDO sobre a ORDEM dos marcos do processo.

    `docs`: [{titulo, tipo}] na ordem dos autos. Retorna {grau, inversoes[], marcos, resumo, ressalva}.
    """
    marcos: dict[str, dict] = {}
    fontes: set[str] = set()
    for d in docs or []:
        nome = _marco(d)
        if not nome:
            continue
        fonte, valor = momento(d)
        if valor is None:
            continue
        fontes.add(fonte)
        # guarda o PRIMEIRO de cada marco (o ato original, não a repetição/juntada posterior)
        if nome not in marcos or valor < marcos[nome]["valor"]:
            marcos[nome] = {"valor": valor, "fonte": fonte, "titulo": d.get("titulo")}
    if not marcos:
        return {"grau": "nao_aplicavel", "inversoes": [], "marcos": {},
                "resumo": ("Nenhum documento com data no título nem ID do SEI — não há relógio para "
                           "aferir a ordem dos atos neste processo. A sequência não é avaliável aqui."),
                "acao": "abrir os documentos e conferir as datas dos atos",
                "ressalva": _RESSALVA, "fonte": "cadeia_processo (determinístico/offline)"}
    inversoes = []
    for antes, depois, tipo, fundamento in _REGRAS:
        a, b = marcos.get(antes), marcos.get(depois)
        if not a or not b:
            continue                    # peça ausente é LACUNA, não inversão
        # distância mínima para afirmar: abaixo dela é a mesma janela de juntada (ver _TOLERANCIA_ID)
        tol = _TOLERANCIA_DIAS if (a["fonte"] == "data" and b["fonte"] == "data") else _TOLERANCIA_ID
        if b["valor"] < a["valor"] and (a["valor"] - b["valor"]) >= tol:
            inversoes.append({
                "tipo": tipo, "fundamento": fundamento,
                "antes_esperado": antes, "depois_esperado": depois,
                "doc_anterior": b["titulo"], "doc_posterior": a["titulo"],
                "como_soube": (f"comparação por {b['fonte']} — "
                               + ("data no título" if b["fonte"] == "data"
                                  else "ID sequencial do documento no SEI (proxy do tempo)")),
                "observacao": (f"O documento de {depois.replace('_', ' ')} aparece nos autos ANTES do de "
                               f"{antes.replace('_', ' ')}, o que inverte a ordem exigida pelo "
                               f"{fundamento}. Indício a confirmar na data do próprio ato."),
            })
    if not inversoes:
        return {"grau": "verde", "inversoes": [], "marcos": {k: v["titulo"] for k, v in marcos.items()},
                "resumo": (f"{len(marcos)} marco(s) da cadeia localizados e em ordem compatível com a "
                           "sequência legal (parecer → contrato; empenho → liquidação → pagamento)."),
                "acao": "", "ressalva": _RESSALVA, "fonte": "cadeia_processo (determinístico/offline)"}
    return {"grau": "vermelho", "inversoes": inversoes,
            "marcos": {k: v["titulo"] for k, v in marcos.items()},
            "resumo": ("; ".join(i["observacao"] for i in inversoes)),
            "acao": ("abrir os documentos apontados e conferir a DATA DO ATO (a ordem aqui vem da "
                     "juntada); se a inversão se confirmar, é vício de instrução a apurar"),
            "ressalva": _RESSALVA, "fonte": "cadeia_processo (determinístico/offline)"}
