# -*- coding: utf-8 -*-
"""Processo de ADITIVO/PRORROGAÇÃO não carrega a fase de seleção — ela vive no processo de origem.

Achado ao ler o SEI-270131/000548/2023 na íntegra (2026-08-03): o sistema lançou, com gravidade
ALTA, a lacuna "Seleção (edital, julgamento, homologação)". Mas o processo é de prorrogação do
Contrato nº 16/2023 — edital, julgamento e homologação estão no processo que originou o contrato.
Cobrar a fase aqui é o mesmo erro que a casa já corrigiu para processo de PAGAMENTO ("observação
≠ achado"): sem isso, todo processo de aditivo nasce com um achado alto estrutural, o score infla
e a fila do fiscal se enche de ruído.

A natureza `aditivo` é uma espécie de contratação: ela mantém tudo o que se cobra da execução e
do controle (parecer, autorização, dotação, atesto) — só não cobra a seleção, que já ocorreu.
"""
from compliance_agent.sei import fases
from tools.sei_triagem_pericia import natureza


def _docs(*titulos):
    return [{"titulo": t, "tipo": "", "fase": ""} for t in titulos]


def test_processo_de_prorrogacao_e_reconhecido_como_aditivo():
    man = {"processo": "270131/000548/2023"}
    docs = _docs("Minuta de Termo Aditivo ao Contrato 74778400",
                 "Termo Aditivo 75769317",
                 "Parecer 462 (74886257)",
                 "Justificativa 74779736")
    assert natureza(man, docs) == "aditivo"


def test_contratacao_normal_nao_vira_aditivo():
    man = {"processo": "X"}
    docs = _docs("Edital de Pregão Eletrônico 10/2024", "Termo de Referência",
                 "Ata de Registro de Preços", "Contrato nº 15/2024")
    assert natureza(man, docs) == "contratacao"


def test_aditivo_nao_cobra_lacuna_de_selecao():
    faltas = {f["falta"] for f in fases.lacunas({"contratacao", "despesa"}, "", com_pagamento=True,
                                                natureza="aditivo")}
    assert not any("Sele" in f for f in faltas), (
        f"aditivo continua cobrando a fase de seleção: {faltas}")


def test_contratacao_continua_cobrando_a_selecao():
    faltas = {f["falta"] for f in fases.lacunas({"contratacao", "despesa"}, "", com_pagamento=True,
                                                natureza="contratacao")}
    assert any("Sele" in f for f in faltas), "a cobrança legítima da seleção sumiu junto"


def test_aditivo_continua_cobrando_evidencia_de_execucao():
    """A isenção é só da seleção: pagamento sem prova de execução segue sendo achado crítico."""
    faltas = {f["falta"] for f in fases.lacunas({"contratacao", "despesa"}, "", com_pagamento=True,
                                                natureza="aditivo")}
    assert any("execu" in f.lower() for f in faltas)
