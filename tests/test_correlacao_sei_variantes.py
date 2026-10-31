# -*- coding: utf-8 -*-
"""`WHERE numero_sei=?` achava 3% do que existe — e lista vazia lê-se como "não pagou".

O SIAFE grava o processo na notação oficial (`SEI-080001/001211/2024`) e `ordens_bancarias.numero_sei`
é cópia dela: **84,3% das 212.994 linhas preenchidas trazem o prefixo**, contra 3,0% sem. Quem
consulta tem o número nu — é assim que ele aparece na pasta do arquivo do SEI e nos relatórios.
Resultado: a consulta casava com 3% e devolvia vazio, que se lê como "processo sem pagamento"
quando o certo é "chave escrita de outro jeito". A família é [[coletado-nao-e-utilizavel]].

Medido no acervo de 2.354 processos: **4 achavam OB (0,2%) antes; 1.463 (62,1%) depois** — de
R$ 155.768,46 para R$ 7.769.145.359,45 em pagamentos ligáveis ao seu processo. Não é dinheiro novo:
é dinheiro que já estava na base e não se ligava.

Não é corrupção e não pede migração: as duas grafias são legítimas. O resto da casa já sabia disso
(`processo_360` e `rotas/produtos` normalizam há tempo) — esta função é que tinha ficado para trás.
"""
from __future__ import annotations

from compliance_agent.correlacao_sei import variantes_sei


def test_gera_as_duas_grafias_a_partir_do_numero_nu():
    assert variantes_sei("080001/001211/2024") == [
        "080001/001211/2024", "SEI-080001/001211/2024"]


def test_gera_as_duas_grafias_a_partir_do_numero_com_prefixo():
    """Quem já tem o prefixo não pode virar `SEI-SEI-...` — e tem de achar a linha sem prefixo."""
    assert variantes_sei("SEI-080001/001211/2024") == [
        "080001/001211/2024", "SEI-080001/001211/2024"]


def test_tolera_a_grafia_com_espaco_e_caixa_baixa():
    assert variantes_sei("sei 080001/001211/2024")[0] == "080001/001211/2024"


def test_entrada_vazia_nao_vira_consulta_por_prefixo_solto():
    """Sem isto, `variantes_sei('')` devolveria `['', 'SEI-']` e a busca casaria linha alheia."""
    assert variantes_sei("") == [] and variantes_sei(None) == []
