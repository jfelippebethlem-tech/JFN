"""Efeito jurídico de uma sanção administrativa sobre a capacidade de contratar.

POR QUE ISTO EXISTE
-------------------
O detector `sancao_vigente_a_epoca` marcava qualquer registro em CEIS/CNEP vigente na data
de publicação do certame. Ao abrir os 4 casos da Prefeitura do Rio em 30/08/2026, os três
fornecedores tinham situações **juridicamente distintas** — e só um configurava vedação:

| fornecedor | sanção | efeito real |
|---|---|---|
| MONSARAS | Declaração de Inidoneidade sem prazo (Gov. BA) | **veda em todos os entes** |
| NEP SOLUÇÕES | Impedimento art. 156, III (Pref. São Sebastião do Alto-RJ) | veda **só naquele município** |
| MEDIC STOCK | Multa + publicação extraordinária (Lei 12.846) | **não veda contratar** |

Tratar os três como iguais produz dois falsos positivos em três. A gravidade não está na
presença no cadastro: está na CATEGORIA da sanção e em QUEM a aplicou.

FUNDAMENTO
----------
- **Lei 14.133/2021, art. 156, §4º** — o impedimento de licitar e contratar (inc. III) vale
  "no âmbito da Administração Pública direta e indireta do **ente federativo** que tiver
  aplicado a sanção". Não se estende a outros entes.
- **Lei 14.133/2021, art. 156, §5º** — a declaração de inidoneidade (inc. IV) impede licitar e
  contratar "no âmbito da Administração Pública direta e indireta de **todos os entes
  federativos**".
- **Lei 8.666/93, art. 87, II e IV** — regime anterior: suspensão (II) e inidoneidade (IV). O
  alcance da *suspensão* é **controverso**: a leitura literal a restringe ao órgão sancionador,
  mas o STJ já lhe deu efeito amplo. A controvérsia é DECLARADA, não resolvida aqui.
- **Lei 12.846/2013 (Anticorrupção), art. 6º** — multa (I) e publicação extraordinária da
  decisão condenatória (§5º, II) são sanções **pecuniárias e de publicidade**. Nenhuma delas
  interdita contratar. As sanções da Lei 12.846 que interditam estão no art. 19 (judiciais).

LIMITE
------
Isto grada o EFEITO declarado no cadastro. Não substitui a consulta ao inteiro teor da decisão
sancionadora, que pode ter alcance modulado. Indício ≠ acusação.
"""
from __future__ import annotations

import re

# efeito → (rótulo, gravidade 0-3, fundamento por extenso)
AMPLO = "AMPLO"
RESTRITO_AO_ENTE = "RESTRITO_AO_ENTE"
CONTROVERSO = "CONTROVERSO"
SEM_IMPEDIMENTO = "SEM_IMPEDIMENTO"

_REGRAS: tuple[tuple[str, str, int, str], ...] = (
    (r"inidoneidade", AMPLO, 3,
     "declaração de inidoneidade — art. 156, IV e §5º da Lei 14.133/2021 (art. 87, IV da Lei "
     "8.666/93): impede licitar e contratar no âmbito de TODOS os entes federativos"),
    (r"impedimento.*sem prazo", AMPLO, 3,
     "impedimento sem prazo determinado — equiparado à inidoneidade quanto ao alcance"),
    (r"dissolu[çc][ãa]o compuls[óo]ria", AMPLO, 3,
     "dissolução compulsória da PJ (art. 19, III da Lei 12.846/2013): a pessoa jurídica deixa "
     "de existir — não há capacidade de contratar"),
    (r"suspens[ãa]o/interdi[çc][ãa]o das atividades", AMPLO, 3,
     "interdição das atividades: a empresa está impedida de OPERAR, logo de executar o objeto"),
    (r"impedimento|proibi[çc][ãa]o de contratar", RESTRITO_AO_ENTE, 2,
     "impedimento de licitar e contratar — art. 156, III e §4º da Lei 14.133/2021: vale apenas "
     "no âmbito do ENTE FEDERATIVO que aplicou a sanção"),
    (r"^suspens[ãa]o$", CONTROVERSO, 2,
     "suspensão — art. 87, II da Lei 8.666/93: a leitura literal restringe ao órgão sancionador, "
     "mas o STJ já lhe atribuiu efeito amplo. Alcance CONTROVERSO: exige exame do caso"),
    (r"multa", SEM_IMPEDIMENTO, 0,
     "multa (art. 6º, I da Lei 12.846/2013 ou art. 156, II da Lei 14.133/2021): sanção "
     "pecuniária — NÃO interdita contratar"),
    (r"publica[çc][ãa]o extraordin[áa]ria", SEM_IMPEDIMENTO, 0,
     "publicação extraordinária da decisão condenatória (art. 6º, §5º, II da Lei 12.846/2013): "
     "sanção de publicidade — NÃO interdita contratar"),
    (r"proibi[çc][ãa]o de receber incentivos", SEM_IMPEDIMENTO, 1,
     "proibição de receber incentivos, subsídios, subvenções, doações ou empréstimos (art. 19, "
     "IV da Lei 12.846/2013): veda BENEFÍCIO, não veda contrato oneroso"),
    (r"perdimento de bens", SEM_IMPEDIMENTO, 1,
     "perdimento de bens: sanção patrimonial — não interdita contratar"),
    (r"demiss[ãa]o", SEM_IMPEDIMENTO, 0,
     "demissão: sanção aplicada a AGENTE PÚBLICO, não a fornecedor"),
)


def efeito(categoria: str) -> dict:
    """Grada o efeito de uma categoria de sanção do CEIS/CNEP.

    Devolve {efeito, gravidade, fundamento}. Categoria desconhecida devolve efeito None —
    INDISPONÍVEL, nunca "sem impedimento" por omissão."""
    c = (categoria or "").strip().lower()
    for padrao, ef, grav, fund in _REGRAS:
        if re.search(padrao, c):
            return {"efeito": ef, "gravidade": grav, "fundamento": fund}
    return {"efeito": None, "gravidade": None,
            "fundamento": f"categoria não catalogada ({categoria!r}) — INDISPONÍVEL, exige exame"}


def veda_contratar(categoria: str, *, uf_sancionador: str | None = None,
                   uf_contratante: str | None = None,
                   orgao_sancionador: str | None = None) -> dict:
    """Diz se a sanção veda a contratação PELO ÓRGÃO EM EXAME.

    Para o efeito RESTRITO_AO_ENTE não basta a sanção existir: ela só veda se o ente
    sancionador for o mesmo do contratante. Um impedimento aplicado pela Prefeitura de São
    Sebastião do Alto não alcança a Prefeitura do Rio, ainda que ambas sejam do RJ — o §4º fala
    em ENTE FEDERATIVO, e municípios distintos são entes distintos.

    Devolve {veda: True|False|None, ...}. `None` = INDISPONÍVEL (não dá para decidir com o que
    se tem), que NÃO é o mesmo que False."""
    e = efeito(categoria)
    if e["efeito"] is None:
        return {**e, "veda": None, "motivo": "categoria não catalogada"}
    if e["efeito"] == AMPLO:
        return {**e, "veda": True, "motivo": "alcança todos os entes federativos"}
    if e["efeito"] == SEM_IMPEDIMENTO:
        return {**e, "veda": False, "motivo": "a sanção não interdita contratar"}
    if e["efeito"] == CONTROVERSO:
        return {**e, "veda": None,
                "motivo": "alcance controverso na jurisprudência — exige exame do inteiro teor"}
    # RESTRITO_AO_ENTE: compara os entes
    if not orgao_sancionador:
        return {**e, "veda": None, "motivo": "órgão sancionador desconhecido — não dá para "
                                             "comparar os entes"}
    return {**e, "veda": None,
            "motivo": f"veda apenas no ente de '{orgao_sancionador}'; confirmar se é o mesmo "
                      f"ente do contratante antes de concluir"}
