# -*- coding: utf-8 -*-
"""Achados DD/ com identidade própria (10/09/2026): TAC recorrente e sócio-agente não são 'fachada'.
Antes, todo DD/… caía na família DD: código impresso duas vezes, defesa de fachada aplicada a um Termo de
Ajuste de Contas e 'dolo a apurar' por padrão."""
from __future__ import annotations

from compliance_agent.lex_redflags import _RF, _destinatarios, _elemento_subjetivo, _exculpatorio, _fam_exculpatorio


def test_codigos_dd_especificos_tem_nome_e_familia_propria():
    assert "Termo de Ajuste de Contas" in _RF["DD/TAC-RECORRENTE"][0]
    assert "agente público" in _RF["DD/SOCIO-AGENTE"][0]
    assert _fam_exculpatorio("DD/TAC-RECORRENTE") == "DD/TAC-RECORRENTE"
    assert _fam_exculpatorio("DD/FACHADA-XYZ") == "DD"      # hipóteses de fachada seguem na família DD
    assert _fam_exculpatorio("R8") == "R8"


def test_defesa_e_destinatario_do_tac_nao_sao_os_da_fachada():
    a = {"rf": "DD/TAC-RECORRENTE", "grav": 4, "obs": "8 Termos de Ajuste de Contas publicados no DOERJ"}
    (e,) = _exculpatorio([a])
    assert "Termo de Ajuste de Contas" in e["defesa"] and "fachada" not in e["defesa"]
    assert e["encaminhamento"] == "representação"   # grav 4 refuta a defesa
    dest = _destinatarios([a])
    assert {d["familia"] for d in dest} == {"debito", "improbidade"}
    assert any("TAC em série" in d["motivo"] for d in dest if d["familia"] == "improbidade")


def test_tac_em_serie_e_gestao_nao_dolo_por_si_e_socio_agente_pede_apurar_dolo():
    assert _elemento_subjetivo({"rf": "DD/TAC-RECORRENTE", "obs": "8 TACs"})[0] == "irregularidade / erro de gestão"
    assert _elemento_subjetivo({"rf": "DD/TAC-RECORRENTE", "obs": "8 TACs; sócio em comum com a concorrente"})[0] == "dolo a apurar"
    assert _elemento_subjetivo({"rf": "DD/SOCIO-AGENTE", "obs": "sócia é diretora da UPA"})[0] == "dolo a apurar"


def test_lista_suja_grave_4_so_com_pagamento_depois_da_inclusao():
    from compliance_agent.lex_conflito import achado_lista_suja
    assert achado_lista_suja(None) is None
    e = {"cnpj": "00638595000105", "nome": "VIABRAS ENGENHARIA EIRELI", "inclusao": "06/04/2026", "obs_depois": 0, "pago_depois": 0.0}
    a = achado_lista_suja(e)
    assert a["rf"] == "DD/LISTA-SUJA" and a["grav"] == 2 and "monitorar" in a["obs"]
    e2 = dict(e, obs_depois=3, pago_depois=150000.0)
    a2 = achado_lista_suja(e2)
    assert a2["grav"] == 4 and "DEPOIS da inclusão" in a2["obs"] and "150.000,00" in a2["obs"]
    assert _RF["DD/LISTA-SUJA"][0].startswith("Empregador no Cadastro")
