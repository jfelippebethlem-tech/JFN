# -*- coding: utf-8 -*-
"""Partes puras do detector TAC × favorecimento: chave de casamento por nome e grau do agente público."""
from __future__ import annotations

from tools.doerj_tac_favorecimento import grau_agente, tokens


def test_tokens_ignora_forma_juridica_e_acentos():
    assert tokens("BRAVO ASSESSORIA E SERVIÇOS EMPRESARIAIS LTDA") == ["BRAVO", "ASSESSORIA"]
    assert tokens("LEFE EMERGÊNCIAS MÉDICAS LTDA") == ["LEFE", "EMERGENCIAS"]
    assert tokens("LTDA") == []


def test_agente_da_saude_e_vermelho_outros_amarelo():
    assert grau_agente("FUNDACAO SAUDE DO ESTADO DO RIO DE JANEIRO") == "🔴"
    assert grau_agente("Secretaria de Estado de Saúde") == "🔴"
    assert grau_agente("SECRETARIA DE ESTADO DE POLICIA MILITAR") == "🟡"
    assert grau_agente(None) == "🟡"
    assert grau_agente("PREFEITURA DO RIO — RioSaúde (RS/PRE)") == "🟡"   # saúde municipal não é o contratante do TAC
