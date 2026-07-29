# -*- coding: utf-8 -*-
"""Licitantes do TCE-RJ — a fonte que destrava J4/J3/CRI, e as três coisas que ela NÃO é.

Os melhores detectores de julgamento da casa dependem da lista de proponentes, e `proposta_item`
tinha 77 linhas. Não é falha dos detectores: o registro típico do PNCP traz só o vencedor, e
`indice_certame` já avisava que "1 fornecedor distinto" não prova licitante único.

Esta fonte traz a lista — e traz três limitações que precisam ficar no código, não na cabeça de
quem lembrar:

  1. **`Participante` é NOME, não CNPJ.** Cruzar licitantes por nome é o caminho da homonímia.
  2. **Cobertura é MUNICIPAL.** Chamar isso de "os certames do RJ" seria erro de cobertura.
  3. **Coleta parcial ≠ licitante único.** Se a fonte declara 13 participantes e coletamos 2, o
     certame não é de proponente único — é de coleta incompleta, e confundir os dois produz
     exatamente o falso positivo que a fonte veio corrigir.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.collectors.tcerj_licitantes import (
    DDL,
    coletar,
    contexto_certame,
    gravar,
    normalizar,
)

# Registro VERBATIM da API (município de Porciúncula, pregão eletrônico de 2024).
_REG = {
    "Ente": "PORCIUNCULA", "Ano": 2024, "Mes": 5, "ProcessoLicitatorio": "00.595/24",
    "Participante": "FORTMAQ MAQUINAS E IMPLEMENTOS AGRICOLAS LTDA", "Resultado": "PERDEDOR",
    "TipoParticipacao": "COMUM", "DataHomologacao": "2024-05-28",
    "Modalidade": "PREGÃO ELETRÔNICO", "Objeto": "AQUISIÇÃO DE PATRULHA MECANIZADA",
    "QuantidadeParticipante": "13", "ValorHomologacao": 50740.0,
    "Tipologia": "VEÍCULOS, MÁQUINAS E/OU EQUIPAMENTOS (AQUISIÇÃO DE)",
    "ValorEstimado": 115133.34,
}


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(DDL)
    return c


def _paginador(paginas):
    it = iter(paginas)

    def buscar(_rota, _params):
        try:
            return next(it)
        except StopIteration:
            return {}
    return buscar


# ───────────────────────────── normalização ───────────────────────────────────────────────────

def test_normaliza_o_registro_real():
    r = normalizar(_REG)
    assert r["processo"] == "00.595/24" and r["resultado"] == "PERDEDOR"
    assert r["qtd_participantes"] == 13          # a API manda como STRING
    assert r["valor_estimado"] == pytest.approx(115133.34)


def test_registro_sem_chave_completa_e_recusado():
    """Chave incompleta vira duplicata silenciosa na próxima coleta."""
    for faltante in ("ProcessoLicitatorio", "Participante", "Ente"):
        assert normalizar({**_REG, faltante: ""}) is None


def test_resultado_ausente_usa_o_padrao_da_rota():
    r = normalizar({**_REG, "Resultado": ""}, resultado_padrao="perdedor")
    assert r["resultado"] == "PERDEDOR"


# ───────────────────────────── coleta ─────────────────────────────────────────────────────────

def test_pagina_ate_o_fim():
    p1 = {"LicitantesPerdedores": [{**_REG, "Participante": f"EMP {i}"} for i in range(1000)]}
    p2 = {"LicitantesPerdedores": [{**_REG, "Participante": "EMP FINAL"}]}
    assert len(list(coletar("perdedor", buscar=_paginador([p1, p2])))) == 1001


def test_para_na_pagina_vazia():
    assert list(coletar("perdedor", buscar=_paginador([{"LicitantesPerdedores": []}]))) == []


def test_limite_total_e_respeitado():
    p = {"LicitantesPerdedores": [{**_REG, "Participante": f"EMP {i}"} for i in range(50)]}
    assert len(list(coletar("perdedor", limite_total=10, buscar=_paginador([p])))) == 10


def test_corpo_que_nao_e_json_interrompe_sem_corromper():
    """HTTP 200 com página de erro já matou um coletor desta casa em silêncio."""
    def buscar(_r, _p):
        raise ValueError("resposta não é objeto JSON")

    assert list(coletar("perdedor", buscar=buscar)) == []


def test_tipo_desconhecido_falha_alto():
    with pytest.raises(ValueError):
        list(coletar("inventado"))


# ───────────────────────────── persistência ───────────────────────────────────────────────────

def test_grava_e_e_idempotente(con):
    linhas = [normalizar(_REG)]
    assert gravar(con, linhas) == 1
    gravar(con, linhas)
    assert con.execute("SELECT COUNT(*) FROM tcerj_licitante").fetchone()[0] == 1


# ───────────────────────────── ponte para os detectores ───────────────────────────────────────

def _semear(con, *, qtd=13, participantes=("VENC",), perdedores=("P1", "P2")):
    linhas = [normalizar({**_REG, "Participante": p, "Resultado": "VENCEDOR",
                          "QuantidadeParticipante": str(qtd)}) for p in participantes]
    linhas += [normalizar({**_REG, "Participante": p, "Resultado": "PERDEDOR",
                           "QuantidadeParticipante": str(qtd)}) for p in perdedores]
    gravar(con, linhas)


def test_contexto_traz_vencedor_e_perdedores(con):
    _semear(con)
    ctx = contexto_certame(con, "PORCIUNCULA", 2024, "00.595/24")
    assert ctx["encontrado"] and ctx["vencedor"] == "VENC"
    assert set(ctx["perdedores"]) == {"P1", "P2"}


def test_n_proponentes_vem_da_FONTE_nao_da_contagem_de_linhas(con):
    """Coleta parcial não pode virar 'licitante único' — o falso positivo que a fonte corrige."""
    _semear(con, qtd=13)
    ctx = contexto_certame(con, "PORCIUNCULA", 2024, "00.595/24")
    assert ctx["n_proponentes"] == 13
    assert ctx["n_proponentes_coletados"] == 3
    assert ctx["coleta_completa"] is False


def test_coleta_completa_quando_bate_com_a_fonte(con):
    _semear(con, qtd=3)
    assert contexto_certame(con, "PORCIUNCULA", 2024, "00.595/24")["coleta_completa"] is True


def test_desconto_e_calculado_do_estimado_para_o_homologado(con):
    _semear(con)
    ctx = contexto_certame(con, "PORCIUNCULA", 2024, "00.595/24")
    assert ctx["desconto"] == pytest.approx((115133.34 - 50740.0) / 115133.34)


def test_media_do_mercado_vem_da_MESMA_tipologia(con):
    """É ela que separa licitante único de monopólio natural."""
    _semear(con)
    gravar(con, [normalizar({**_REG, "ProcessoLicitatorio": "99/24", "Participante": "OUTRA",
                             "Resultado": "VENCEDOR", "QuantidadeParticipante": "7"})])
    ctx = contexto_certame(con, "PORCIUNCULA", 2024, "00.595/24")
    assert ctx["proponentes_medios_mercado"] == pytest.approx(7.0)


def test_campos_que_a_fonte_NAO_tem_saem_None_nao_False(con):
    """`aviso_publicado=False` acenderia bandeira do CRI sobre dado inexistente."""
    _semear(con)
    ctx = contexto_certame(con, "PORCIUNCULA", 2024, "00.595/24")
    assert ctx["aviso_publicado"] is None
    assert ctx["dias_publicidade"] is None and ctx["dias_ate_decisao"] is None


def test_certame_ausente_declara_em_vez_de_devolver_vazio(con):
    ctx = contexto_certame(con, "PORCIUNCULA", 2024, "nao-existe")
    assert ctx["encontrado"] is False and "não consta" in ctx["motivo"]


def test_contexto_carrega_as_limitacoes_da_fonte(con):
    _semear(con)
    r = contexto_certame(con, "PORCIUNCULA", 2024, "00.595/24")["ressalva"]
    assert "NOME, não CNPJ" in r and "MUNICIPAL" in r


# ───────────────────────────── integração com o CRI ───────────────────────────────────────────

def test_contexto_alimenta_o_CRI_direto(con):
    from compliance_agent.editais.cri import calcular

    _semear(con, qtd=1, participantes=("VENC",), perdedores=())
    gravar(con, [normalizar({**_REG, "ProcessoLicitatorio": "88/24", "Participante": "X",
                             "Resultado": "VENCEDOR", "QuantidadeParticipante": "9"})])
    ctx = contexto_certame(con, "PORCIUNCULA", 2024, "00.595/24")
    r = calcular(ctx)
    assert "licitante_unico" in r["acesas"], r
    assert r["confianca"] < 1.0, "campos ausentes deveriam derrubar a confiança"


# ───────────────────────────── ranking por ente ───────────────────────────────────────────────

def _certame(con, ente, processo, *, qtd, mercado_qtd=9):
    """Semeia um certame e um vizinho da mesma tipologia (para haver média de mercado)."""
    gravar(con, [normalizar({**_REG, "Ente": ente, "ProcessoLicitatorio": processo,
                             "Participante": f"V-{processo}", "Resultado": "VENCEDOR",
                             "QuantidadeParticipante": str(qtd)})])
    gravar(con, [normalizar({**_REG, "Ente": "MERCADO", "ProcessoLicitatorio": f"m{processo}",
                             "Participante": "M", "Resultado": "VENCEDOR",
                             "QuantidadeParticipante": str(mercado_qtd)})])


def test_ranking_ordena_por_cri_e_declara_amostra_pequena(con):
    from compliance_agent.collectors.tcerj_licitantes import ranking_por_ente

    for i in range(12):
        _certame(con, "RUIM", f"r{i}", qtd=1)      # licitante único em mercado competitivo
    for i in range(12):
        _certame(con, "BOM", f"b{i}", qtd=8)
    _certame(con, "PEQUENO", "p1", qtd=1)

    r = ranking_por_ente(con, ano=2024)
    por_ente = {x["ente"]: x for x in r}
    assert por_ente["RUIM"]["cri_medio"] > por_ente["BOM"]["cri_medio"]
    assert por_ente["PEQUENO"]["comparavel"] is False


def test_ente_com_amostra_pequena_aparece_mas_nao_disputa_o_topo(con):
    """Esconder amostra pequena faz a fila parecer completa quando não é."""
    from compliance_agent.collectors.tcerj_licitantes import ranking_por_ente

    for i in range(12):
        _certame(con, "GRANDE", f"g{i}", qtd=8)
    _certame(con, "PEQUENO", "p1", qtd=1)          # CRI alto, n=1

    r = ranking_por_ente(con, ano=2024)
    assert {x["ente"] for x in r} >= {"GRANDE", "PEQUENO"}
    assert r[0]["ente"] != "PEQUENO", "amostra de 1 certame assumiu o topo da fila"


def test_ranking_lista_as_bandeiras_mais_frequentes(con):
    from compliance_agent.collectors.tcerj_licitantes import ranking_por_ente

    for i in range(12):
        _certame(con, "RUIM", f"r{i}", qtd=1)
    alvo = next(x for x in ranking_por_ente(con, ano=2024) if x["ente"] == "RUIM")
    assert alvo["bandeiras_mais_frequentes"].get("licitante_unico") == 12
