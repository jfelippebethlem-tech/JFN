# -*- coding: utf-8 -*-
"""Triagem de fracionamento pela ÓTICA DO PAGAMENTO (SIAFE) — item 3 autorizado pelo dono 2026-07-24.

Por que existe: a fonte de dispensas do TCE-RJ tem objeto e modalidade, mas NÃO tem data — e por isso os
sinais temporais do P4 (proximidade < 30 dias, sequência pós-limite) nunca ligavam. O SIAFE tem
exatamente o que falta: DATA e o pagamento EFETIVO (§2 — só a Ordem Bancária é "pago"). Os dois não se
cruzam por número de processo (formatos incompatíveis: 'SEI-120001/009348/2022' × '2026-06041596'), então
esta camada não emite veredito de fracionamento: ela produz uma FILA DE CANDIDATOS a verificar, dizendo
com todas as letras o que não sabe (objeto e modalidade).
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import fracionamento_siafe as FS

LIM_2024 = 59906.02       # art. 75, II — Decreto 11.871/2023 (limite de compras em 2024)


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE ob_orcamentaria_siafe (
        numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT, tipo_ob TEXT,
        credor TEXT, nome_credor TEXT, processo TEXT, valor REAL, exercicio INTEGER)""")
    return c


def _ob(con, **kw):
    d = {"numero_ob": "2024OB001", "ug_emitente": "133100", "data_emissao": "10/03/2024",
         "status": "Pago", "tipo_ob": "Orçamentária", "credor": "F001",
         "nome_credor": "ALFA COMERCIO LTDA", "processo": "2024-06000001", "valor": 25000.0,
         "exercicio": 2024}
    d.update(kw)
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (:numero_ob,:ug_emitente,:data_emissao,"
                ":status,:tipo_ob,:credor,:nome_credor,:processo,:valor,:exercicio)", d)


def test_tres_pagamentos_pequenos_que_somam_acima_do_limite_viram_candidato(con):
    for i, dia in enumerate(("05/03/2024", "20/03/2024", "02/04/2024")):
        _ob(con, numero_ob=f"2024OB00{i}", data_emissao=dia, valor=25000.0,
            processo=f"2024-0600000{i}")
    r = FS.triagem(con, exercicio=2024)
    assert len(r["candidatos"]) == 1
    c = r["candidatos"][0]
    assert c["n_obs"] == 3 and c["soma"] == 75000.0
    assert c["soma"] > c["limite_dispensa"]
    assert c["intervalo_mediano_dias"] <= 20
    assert c["processos"]                      # rastreabilidade: o que puxar no SEI


def test_ob_excluida_nao_e_pagamento(con):
    # §2: só a OB efetivamente paga conta. 'Excluído' é OB cancelada — dinheiro que NÃO saiu.
    for i, st in enumerate(("Pago", "Pago", "Excluído")):
        _ob(con, numero_ob=f"2024OB01{i}", status=st, valor=25000.0, processo=f"2024-060001{i}")
    r = FS.triagem(con, exercicio=2024)
    assert r["candidatos"] == []               # sobram 2 OBs (50k) — abaixo do limite
    assert r["obs_descartadas_status"] == 1


def test_folha_e_tributo_nao_sao_fornecedor_licitavel(con):
    for i, nome in enumerate(("FOLHA DE PAGAMENTOS", "FOLHA DE PAGAMENTOS", "FOLHA DE PAGAMENTOS")):
        _ob(con, numero_ob=f"2024OB02{i}", nome_credor=nome, valor=900000.0,
            processo=f"2024-060002{i}")
    r = FS.triagem(con, exercicio=2024)
    assert r["candidatos"] == []
    assert r["obs_descartadas_credor"] == 3


def test_pagamento_individual_acima_do_limite_nao_e_fracionamento(con):
    # valor unitário acima do teto de dispensa indica contrato licitado — não é a manobra do art. 75 §1º
    for i in range(3):
        _ob(con, numero_ob=f"2024OB03{i}", valor=LIM_2024 + 10_000, processo=f"2024-060003{i}")
    assert FS.triagem(con, exercicio=2024)["candidatos"] == []


def test_soma_abaixo_do_limite_nao_entra(con):
    for i in range(3):
        _ob(con, numero_ob=f"2024OB04{i}", valor=5000.0, processo=f"2024-060004{i}")
    assert FS.triagem(con, exercicio=2024)["candidatos"] == []


def test_ugs_diferentes_nao_somam(con):
    # art. 75, §1º, I — o somatório é da respectiva UNIDADE GESTORA
    for i, ug in enumerate(("133100", "133100", "263100")):
        _ob(con, numero_ob=f"2024OB05{i}", ug_emitente=ug, valor=25000.0, processo=f"2024-060005{i}")
    assert FS.triagem(con, exercicio=2024)["candidatos"] == []


def test_veredito_e_honesto_sobre_o_que_nao_sabe(con):
    for i in range(3):
        _ob(con, numero_ob=f"2024OB06{i}", valor=25000.0, processo=f"2024-060006{i}")
    r = FS.triagem(con, exercicio=2024)
    c = r["candidatos"][0]
    assert c["grau"] == "a_verificar"           # NUNCA 'vermelho': falta objeto e modalidade
    assert "objeto" in c["ressalva"].lower() and "modalidade" in c["ressalva"].lower()
    assert "não" in c["ressalva"].lower()
    assert c["acao"]


def test_varias_obs_do_MESMO_processo_nao_sao_fracionamento(con):
    # medido no dado real: 84 OBs no mesmo dia ao mesmo credor — é UM contrato pago em parcelas.
    # Fracionamento exige CONTRATAÇÕES distintas, logo processos distintos.
    for i in range(6):
        _ob(con, numero_ob=f"2024OB10{i}", valor=25000.0, processo="2024-06000999",
            data_emissao="10/03/2024")
    r = FS.triagem(con, exercicio=2024)
    assert r["candidatos"] == []
    assert r["grupos_descartados_processo_unico"] == 1


def test_orgao_publico_nao_e_fornecedor_licitavel(con):
    # "MINISTÉRIO DA FAZENDA" apareceu como maior "candidato" real — é tributo/repasse, não compra
    for i, nome in enumerate(("MINISTÉRIO DA FAZENDA",) * 3):
        _ob(con, numero_ob=f"2024OB11{i}", nome_credor=nome, valor=25000.0,
            processo=f"2024-060011{i}")
    assert FS.triagem(con, exercicio=2024)["candidatos"] == []


def test_concessionaria_de_utilidade_publica_fica_fora(con):
    # água/luz/esgoto por concessionária é inexigibilidade (art. 74) — hipótese própria, não dispensa
    for i in range(3):
        _ob(con, numero_ob=f"2024OB12{i}", nome_credor="COMPANHIA ESTADUAL DE AGUAS E ESGOTOS",
            valor=25000.0, processo=f"2024-060012{i}")
    assert FS.triagem(con, exercicio=2024)["candidatos"] == []


def test_proximidade_temporal_agrava_a_prioridade(con):
    for i, dia in enumerate(("05/03/2024", "06/03/2024", "07/03/2024")):
        _ob(con, numero_ob=f"2024OB07{i}", data_emissao=dia, valor=25000.0,
            processo=f"2024-060007{i}")
    r = FS.triagem(con, exercicio=2024)
    c = r["candidatos"][0]
    assert c["intervalo_mediano_dias"] <= 1
    # a prioridade é ORDEM DE FILA, não probabilidade de fraude. Aqui os valores (25 mil) estão longe do
    # teto (59,9 mil), então o componente de maior peso — encaixe no teto — não pontua: o caso fica no
    # meio da fila mesmo com pagamentos em dias seguidos. Quem decide é a comparação entre candidatos.
    assert 0.2 <= c["prioridade"] <= 0.5
    assert c["n_rente_ao_teto"] == 0


def test_valor_rente_ao_teto_sobe_na_fila(con):
    """Três compras de R$ 59 mil com teto de R$ 59,9 mil (encaixe) devem vir antes de três de R$ 25 mil."""
    for i in range(3):
        _ob(con, numero_ob=f"2024OB20{i}", credor="F020", nome_credor="ENCAIXE LTDA",
            valor=LIM_2024 - 900, data_emissao=f"1{i}/03/2024", processo=f"2024-060020{i}")
    for i in range(3):
        _ob(con, numero_ob=f"2024OB21{i}", credor="F021", nome_credor="ROTINA LTDA",
            valor=25000.0, data_emissao=f"1{i}/03/2024", processo=f"2024-060021{i}")
    cands = FS.triagem(con, exercicio=2024)["candidatos"]
    assert cands[0]["nome_credor"] == "ENCAIXE LTDA"
    assert cands[0]["n_rente_ao_teto"] == 3


def test_ordena_por_prioridade(con):
    for i, dia in enumerate(("05/01/2024", "20/06/2024", "02/12/2024")):        # espaçado
        _ob(con, numero_ob=f"2024OB08{i}", credor="F008", nome_credor="BETA LTDA",
            data_emissao=dia, valor=25000.0, processo=f"2024-060008{i}")
    for i, dia in enumerate(("05/02/2024", "06/02/2024", "07/02/2024")):        # colado
        _ob(con, numero_ob=f"2024OB09{i}", credor="F009", nome_credor="GAMA LTDA",
            data_emissao=dia, valor=25000.0, processo=f"2024-060009{i}")
    cands = FS.triagem(con, exercicio=2024)["candidatos"]
    assert len(cands) == 2
    assert cands[0]["nome_credor"] == "GAMA LTDA"     # o mais colado no tempo vem primeiro


def test_fundo_municipal_de_saude_nao_e_fornecedor_licitavel(con):
    """Repasse fundo-a-fundo do SUS é transferência LEGAL — fracionar ali é juridicamente impossível.

    Medido no acervo real em 2026-07-27: 70 dos 1.240 candidatos eram ente público que o regex
    local deixava passar, e "Fundo Municipal De Saude De Itaboraí" liderava a fila de 2024. A
    correção reusa `entidades_gov.eh_nao_fornecedor`, o classificador canônico da casa, em vez de
    engordar mais uma lista paralela.
    """
    for i in range(3):
        _ob(con, numero_ob=f"2024OB77{i}", nome_credor="Fundo Municipal De Saude De Itaborai",
            valor=25000.0, processo=f"2024-060077{i}")
    assert FS.triagem(con, exercicio=2024)["candidatos"] == []


@pytest.mark.parametrize("nome", [
    "Prefeitura Municipal de Niterói",
    "Fundo Estadual de Saúde",
    "Instituto Nacional do Seguro Social",
])
def test_outros_entes_publicos_tambem_ficam_fora(con, nome):
    for i in range(3):
        _ob(con, numero_ob=f"2024OB88{i}", nome_credor=nome, valor=25000.0,
            processo=f"2024-060088{i}")
    assert FS.triagem(con, exercicio=2024)["candidatos"] == []


def test_fornecedor_privado_continua_entrando(con):
    """A peneira não pode cegar o caso bom."""
    for i in range(3):
        _ob(con, numero_ob=f"2024OB99{i}", nome_credor="ACME MATERIAIS HOSPITALARES LTDA",
            valor=25000.0, processo=f"2024-060099{i}")
    assert len(FS.triagem(con, exercicio=2024)["candidatos"]) == 1
