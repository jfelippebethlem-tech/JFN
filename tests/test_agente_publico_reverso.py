# -*- coding: utf-8 -*-
"""Agente público × quadro societário do país — e as três recusas que impedem a lista de acusar.

O eixo é potente e por isso perigoso: casar 251.472 nomes de folha contra 27,6 milhões de linhas de
QSA produz 72.456 pessoas e 686.964 vínculos. Sozinho, esse número não vale nada — 41,6% dos nomes
que casam têm MAIS DE UM CPF mascarado no próprio índice, ou seja, são homônimos comprovados.

O que estes testes travam não é o SQL, é o que a casa promete: homônimo separado, explicação
institucional declarada ao lado do achado, e nome curto fora.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_agente_publico_reverso.py -q
"""
from __future__ import annotations

import pytest

from tools.agente_publico_reverso import explicacao_institucional, norm, semente


class _Con:
    """Conexão de mentira com o mínimo que `semente` consulta."""

    def __init__(self, folha, alerj):
        self._folha, self._alerj = folha, alerj

    def execute(self, sql, *a):
        return iter(self._alerj if "alerj_folha" in sql else self._folha)


def test_nome_curto_nao_entra():
    """"JOSE SILVA" casa com meio estado. Menos de três termos não é identificação, é sorteio."""
    con = _Con([("JOSE SILVA", "ASSESSOR", "CARGO COMISSAO", "SEC X"),
                ("MARIA DAS DORES PEREIRA", "ASSESSOR", "CARGO COMISSAO", "SEC X")], [])
    alvo = semente(con)
    assert "JOSE SILVA" not in alvo
    assert "MARIA DAS DORES PEREIRA" in alvo


def test_alerj_prevalece_e_marca_comissionado():
    """Mandato e gabinete são o poder que interessa — e vencem o registro na folha do Estado."""
    con = _Con([("ANA PAULA DE SOUZA", "PROFESSOR DOCENTE I", "EFETIVO", "SEEDUC")],
               [("ANA PAULA DE SOUZA", "ASSESSOR PARLAMENTAR V")])
    alvo = semente(con)["ANA PAULA DE SOUZA"]
    assert alvo["origem"] == "alerj" and alvo["comissionado"] == 1


def test_efetivo_de_concurso_nao_e_comissionado():
    """O marcador tem de separar quem entra por concurso de quem entra por nomeação."""
    con = _Con([("CARLOS EDUARDO DA MOTA", "PROFESSOR DOCENTE I", "EFETIVO", "SEEDUC")], [])
    assert semente(con)["CARLOS EDUARDO DA MOTA"]["comissionado"] == 0


@pytest.mark.parametrize("razao,classe", [
    ("ASSOCIACAO DE APOIO A ESCOLA CIEP 052", "apoio_a_escola"),
    ("FUNDACAO APOIO A PESQUISA ENSINO E ASSISTENCIA", "fundacao_de_apoio_universitaria"),
    ("MUTUA DOS MAGISTRADOS DO ESTADO DO RIO DE JANEIRO", "associacao_de_classe"),
    ("COOPERATIVA DE TRABALHO MEDICO", "cooperativa"),
])
def test_explicacao_institucional_e_o_desenho_do_programa(razao, classe):
    """35,1% dos pares defensáveis são Associação de Apoio à Escola — a entidade que a própria rede
    estadual usa para descentralizar recurso à unidade, dirigida por desenho por um professor
    daquela escola. Sem este veto a lista acusaria um terço do magistério."""
    assert explicacao_institucional(razao) == classe


def test_empresa_comum_nao_ganha_explicacao_de_graca():
    """Controle positivo: vetar demais é tão ruim quanto vetar de menos."""
    assert explicacao_institucional("MEDVIVA SERVICOS MEDICOS LTDA") == ""
    assert explicacao_institucional("LIFECARE - GESTAO, ASSISTENCIA E EDUCACAO") == ""


def test_norm_nao_funde_pessoas_por_acento_nem_separa_por_ele():
    assert norm("JOSÉ D'ÁVILA-NETO") == norm("JOSE D AVILA NETO")
