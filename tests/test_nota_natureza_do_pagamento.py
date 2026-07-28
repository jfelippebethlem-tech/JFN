# -*- coding: utf-8 -*-
"""Repasse a ente federativo não se apresenta como pagamento de contratação.

A nota de SEI-420001/004819/2025 afirma "**Pago (OB SIAFE):** R$ 21.657.753,00". O credor é
"Pref Munic De Campos De Goytacazes"; a de SEI-080001/003356/2024, R$ 24.600.000,00, é o
"Fundo Munic. de Saúde de São João de Meriti". São **transferências a entes federativos**, e a
própria fila da análise as exclui de propósito — `_pagos_por_chave(so_contratacao=True)` sabe
que ali não há licitação do Estado a fiscalizar.

O produto e a fila estavam medindo coisas diferentes: a fila dava R$ 0,00 para o mesmo
processo em que a nota anunciava R$ 21,6 milhões. Quem lê a nota entende contratação, e a
diligência que ela sugere (edital, contrato, fiscal) não existe nesse tipo de despesa — a
fiscalização cabível é outra, de prestação de contas do convênio.

Medido: 2 notas em 159, somando R$ 46.257.753,00. Poucas, e de valor alto o bastante para
irem ao topo de qualquer priorização por dinheiro.
"""
from tools.sei_analise_em_serie import ressalva_de_natureza


def test_credor_de_ente_federativo_ganha_ressalva():
    r = ressalva_de_natureza("Pref Munic De Campos De Goytacazes", 1.0)
    assert r and "transferência" in r.lower()
    assert "Pref Munic De Campos De Goytacazes" in r


def test_fornecedor_comum_nao_ganha_ressalva():
    assert ressalva_de_natureza("Dragmaq Engenharia Ltda", 0.0) is None


def test_maioria_de_contratacao_nao_ganha_ressalva():
    """Um repasse pequeno no meio de contratação não descaracteriza o processo."""
    assert ressalva_de_natureza("Pref Munic De Campos De Goytacazes", 0.2) is None


def test_sem_credor_conhecido_nao_inventa():
    assert ressalva_de_natureza("", 1.0) is None
    assert ressalva_de_natureza(None, 1.0) is None


def test_a_ressalva_nao_afirma_irregularidade():
    """Transferência é despesa legítima — o aviso é de NATUREZA, não de suspeita."""
    r = ressalva_de_natureza("Fundo Munic,de Saude De Sao Joao Meriti", 0.9).lower()
    for proibida in ("irregular", "indício", "suspeit", "desvio"):
        assert proibida not in r


def test_a_nota_do_processo_de_repasse_traz_a_ressalva():
    """Fio completo: o aviso precisa chegar ao produto, não ficar na função."""
    from tools.sei_analise_em_serie import _nota_vault

    conf = {"regex_nomes": [], "ids_regex": [], "ids_dossie": [], "so_no_dossie": [], "so_na_regex": []}
    nota = _nota_vault("420001_004819_2025", 21_657_753.00, "# dossiê", [], conf,
                       credor="Pref Munic De Campos De Goytacazes", prop_nao_fornecedor=1.0)
    assert "transferência a ente federativo" in nota
    assert "R$ 21.657.753,00" in nota, "o valor continua sendo mostrado, com a natureza ao lado"


def test_processo_de_contratacao_nao_ganha_ressalva_na_nota():
    from tools.sei_analise_em_serie import _nota_vault

    conf = {"regex_nomes": [], "ids_regex": [], "ids_dossie": [], "so_no_dossie": [], "so_na_regex": []}
    nota = _nota_vault("070002_006145_2024", 14_115_112.37, "# dossiê", [], conf,
                       credor="Dragmaq Engenharia Ltda", prop_nao_fornecedor=0.0)
    assert "transferência" not in nota
