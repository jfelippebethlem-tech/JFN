# -*- coding: utf-8 -*-
"""A SUBORDINAÇÃO de uma UG muda no tempo — e isso NÃO é troca de entidade.

MEDIDO em 2026-07-28 sobre `ordens_bancarias` (152 UGs, 8 exercícios):

    UG 133100   2019-2020  INST. DE TERRAS E CARTOGR. DO EST. RJ   (ITERJ)
                2021-2022  Secretaria de Estado de Cidades
                2023       Secretaria de Estado de Infraestrutura e Cidades
                2024-2026  Secretaria de Estado de Infraestrutura e Obras Públicas

    UG 220100   2019       Secretaria de Estado da Casa Civil e Governança
                2020+      Secretaria de Desenvolvimento Econômico...

⚠️ ERRO COMETIDO E CORRIGIDO AQUI EM 2026-07-28: li essa troca de rótulo como "o código foi
reaproveitado por outro órgão" e cheguei a corrigir o invariante do projeto ("ITERJ = UG
133100") como se estivesse errado. Estava CERTO. As Ordens Bancárias rotulam a UG com o nome do
ÓRGÃO SUPERIOR — aprendizado que o `compliance_agent/ugs.py` já registrava desde 2026-06-06 — e
`despesa_execucao` mostra o nome REAL, estável: 133100 é sempre o ITERJ, 043400 é sempre a
Agência Reguladora, 135300 é sempre a EMATER.

O que estes testes protegem, então: que a troca de SUBORDINAÇÃO seja detectada (ela muda quem
responde: ordenador, autoridade homologadora), e que variação de GRAFIA não seja confundida com
ela.
"""
from __future__ import annotations

import pytest

from compliance_agent.ug_nomes import (
    _agrupar_orgaos, _mesmo_orgao, historico, mudancas_no_exercicio, mudou_de_subordinacao, subordinacao,
)

pytestmark = pytest.mark.skipif(
    not historico("133100"), reason="requer data/compliance.db com ordens_bancarias")


# ── entre exercícios ───────────────────────────────────────────────────────────────────────

def test_a_subordinacao_depende_do_exercicio():
    assert "TERRAS" in (subordinacao("133100", 2019) or "").upper()
    assert "INFRAESTRUTURA" in (subordinacao("133100", 2025) or "").upper()


def test_a_unidade_permanece_a_mesma_e_isso_vem_da_fonte_certa():
    """O contraponto do teste acima, e a razão de este módulo não ser sobre nome de unidade."""
    from compliance_agent.ugs import nome_canonico
    assert "ITERJ" in (nome_canonico("133100") or "")


def test_troca_de_subordinacao_e_detectada():
    assert mudou_de_subordinacao("133100", 2019, 2026) is True
    assert mudou_de_subordinacao("220100", 2019, 2026) is True


def test_intervalo_sob_a_mesma_secretaria_nao_dispara():
    """2024-2026 é a mesma Secretaria — acusar aqui seria ruído."""
    assert mudou_de_subordinacao("133100", 2024, 2026) is False


def test_ano_sem_dado_devolve_None_e_nao_o_nome_de_outro_ano():
    """Devolver o nome de 2025 para uma pergunta sobre 1998 seria inventar."""
    assert subordinacao("133100", 1998) is None


def test_codigo_inexistente_devolve_None():
    assert subordinacao("999999", 2025) is None
    assert subordinacao("", 2025) is None


# ── dentro do exercício ────────────────────────────────────────────────────────────────────

def test_mudanca_dentro_do_exercicio_e_detectada_com_data():
    """Transferência vem por decreto e não espera a virada do ano."""
    m = mudancas_no_exercicio("135300", 2025)
    assert len(m) >= 2, "a UG 135300 apareceu sob dois órgãos superiores em 2025"
    assert all(x.get("primeira_ob") for x in m), "sem a data não dá para separar o período"


@pytest.mark.parametrize("ug,ano", [("010100", 2024), ("030100", 2024), ("053100", 2019),
                                    ("203100", 2019)])
def test_variacao_de_grafia_nao_e_troca_de_subordinacao(ug, ano):
    """"Assembleia Legislativa" e "Assembleia Legislativa do Rio de Janeiro" são o mesmo órgão.
    Comparar sequência de palavras acusava 11 casos; por contenção de tokens, sobra 1 real."""
    assert mudancas_no_exercicio(ug, ano) == []


# ── a régua de identidade ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("Assembleia Legislativa", "Assembleia Legislativa do Rio de Janeiro"),
    ("Instituto de Pesos e Medidas do RIO", "Instituto de Pesos e Medidas do RJ"),
    ("Secretaria de Estado de Infraestrutura e Obras", "Secretaria de Infraestrutura e Obras"),
])
def test_mesmo_orgao_apesar_da_grafia(a, b):
    assert _mesmo_orgao(a, b) is True


@pytest.mark.parametrize("a,b", [
    ("Secretaria de Estado da Casa Civil", "Secretaria de Desenvolvimento Econômico"),
    ("INST. DE TERRAS E CARTOGR. DO EST. RJ", "Secretaria de Estado de Cidades"),
])
def test_orgaos_superiores_distintos_nao_sao_colapsados(a, b):
    assert _mesmo_orgao(a, b) is False


def test_agrupamento_colapsa_grafias_e_separa_orgaos():
    nomes = ["Assembleia Legislativa", "Assembleia Legislativa do Rio de Janeiro",
             "Secretaria de Estado de Cidades"]
    assert len(_agrupar_orgaos(nomes)) == 2
