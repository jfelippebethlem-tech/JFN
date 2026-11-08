# -*- coding: utf-8 -*-
"""Sinais do cruzamento íntegra PNCP × extrato do D.O. — só sinal POSITIVO; ausência nunca acusa."""
from __future__ import annotations

from tools.pcrj_integra_x_doe import casa_fornecedor, sinais_do_contrato

_C = {"numero_controle_pncp": "X-2-000001/2026", "valor_global": 1_000_000.0,
      "fornecedor_documento": "11111111000111", "orgao_cnpj": "42498733000148", "data_assinatura": "2026-05-01"}


def _ev(**k):
    base = {"tipo": "contrato", "processos": ["000900.000001/2026-11"], "id_materia": 7, "data_doe": "2026-05-03",
            "objeto": "", "partes": "", "valor": None, "fundamento": None, "aditivo_n": None,
            "mesmo_fornecedor": True}
    return {**base, **k}


def test_sem_eventos_nao_ha_sinal():
    assert sinais_do_contrato(_C, [], []) == []


def test_extrato_sem_fundamento_e_valor_igual_nao_acusa():
    assert sinais_do_contrato(_C, [_ev(valor=1_000_000.0)], []) == []


def test_emergencial_com_incumbente_e_vermelho():
    ev = [_ev(fundamento="art. 75, VIII")]
    hist = [{"numero_controle_pncp": "X-2-000900/2023", "data_assinatura": "2023-11-01"}]
    s = {x["sinal"]: x for x in sinais_do_contrato(_C, ev, hist)}
    assert s["contratacao_direta"]["grau"] == "🟡"
    assert s["emergencial_incumbente"]["grau"] == "🔴" and "2023-11-01" in s["emergencial_incumbente"]["detalhe"]
    assert "emergencial" not in s                      # o sinal fraco não duplica o forte


def test_emergencial_sem_historico_fica_amarelo():
    s = {x["sinal"] for x in sinais_do_contrato(_C, [_ev(fundamento="art. 75, VIII")], [])}
    assert s == {"contratacao_direta", "emergencial"}


def test_acrescimo_acima_do_teto_inclusivo():
    exatos = [_ev(tipo="aditivo", objeto="Acréscimo de 25% do valor", valor=250_000.0)]
    assert not [x for x in sinais_do_contrato(_C, exatos, []) if x["sinal"] == "acrescimo_acima_teto"]
    acima = [_ev(tipo="aditivo", objeto="Acréscimo quantitativo", valor=250_000.01)]
    (x,) = [x for x in sinais_do_contrato(_C, acima, []) if x["sinal"] == "acrescimo_acima_teto"]
    assert x["grau"] == "🔴"


def test_prorrogacao_nao_conta_como_acrescimo():
    ev = [_ev(tipo="aditivo", objeto="Prorrogação de prazo contratual", valor=900_000.0)]
    assert not [x for x in sinais_do_contrato(_C, ev, []) if x["sinal"] == "acrescimo_acima_teto"]


def test_valor_divergente_entre_fontes():
    (x,) = sinais_do_contrato(_C, [_ev(valor=1_300_000.0)], [])
    assert x["sinal"] == "valor_divergente" and "30%" in x["detalhe"]


def test_casa_fornecedor_ignora_juridico_e_acentos():
    assert casa_fornecedor("AGILE CORP SERVICOS ESPECIALIZADOS LTDA", "MRJ e AGILE CORP SERVIÇOS LTDA") is True
    assert casa_fornecedor("AGILE CORP SERVICOS LTDA", "MRJ e VR BENEFÍCIOS E SERVIÇOS") is False
    assert casa_fornecedor("AGILE CORP", None) is None


def test_evento_de_outro_fornecedor_no_mesmo_processo_nao_gera_sinal():
    outro = [_ev(valor=64_800.0, mesmo_fornecedor=False, fundamento="art. 75, VIII")]
    assert sinais_do_contrato(_C, outro, [{"numero_controle_pncp": "H", "data_assinatura": "2024-01-01"}]) == []


def test_partes_desconhecidas_so_informam_nunca_comparam():
    desconhecido = [_ev(valor=1_300_000.0, mesmo_fornecedor=None, fundamento="art. 75, VIII")]
    s = {x["sinal"] for x in sinais_do_contrato(_C, desconhecido, [{"numero_controle_pncp": "H", "data_assinatura": "2024-01-01"}])}
    assert s == {"contratacao_direta", "emergencial"}      # sem valor_divergente nem incumbente
