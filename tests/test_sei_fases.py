# -*- coding: utf-8 -*-
"""Taxonomia determinística das fases de contratação (compliance_agent/sei/fases.py).

Títulos REAIS de documentos SEI-RJ (inclusive mutilados pelo encoding dos nomes
de arquivo, ex.: 'Atestado_de_Realiza__o_de_Servi_os') → (fase, tipo). Sem LLM:
o entendimento das fases vive em código testado, não na memória de modelo.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_agent.sei.fases import (
    FASES, classificar, lacunas, linha_do_tempo,
)


def test_classificar_titulos_reais():
    casos = {
        # planejamento
        "Estudo Técnico Preliminar 12": "planejamento",
        "Termo de Referência SEFAZ/SUBLOG": "planejamento",
        "Projeto Básico": "planejamento",
        "Pesquisa de Preços": "planejamento",
        "Cota__o_02": "planejamento",
        "Mapa de Riscos": "planejamento",
        "DFD - Documento de Formalização da Demanda": "planejamento",
        # seleção do fornecedor
        "Edital de Pregão Eletrônico 44/2023": "selecao",
        "Aviso de Licitação": "selecao",
        "Ata de Realização do Pregão Eletrônico": "selecao",
        "Proposta": "selecao",
        "Documentos de Habilitação": "selecao",
        "Termo de Homologação": "selecao",
        "Termo de Adjudicação": "selecao",
        "Justificativa de Dispensa de Licitação": "selecao",
        "Ato de Inexigibilidade": "selecao",
        "Recurso Administrativo - Licitante": "selecao",
        # contratação (formalização)
        "Contrato 011/2025": "contratacao",
        "Termo de Contrato": "contratacao",
        "Ata de Registro de Preços 05/2024": "contratacao",
        "Extrato de Contrato - D.O.": "contratacao",
        "Ordem de Início dos Serviços": "contratacao",
        "Garantia Contratual - Seguro": "contratacao",
        # execução (física)
        "1º Boletim de Medição": "execucao",
        "Relatório Fotográfico - 5ª Medição": "execucao",
        "Relatório de Fiscalização": "execucao",
        "Diário de Obra - Abril": "execucao",
        "Atestado_de_Realiza__o_de_Servi_os": "execucao",
        "Termo de Recebimento Definitivo": "execucao",
        "Publica__o_do_2_Termo_Aditivo_ao_Contrat": "execucao",
        "Apostilamento de Reajuste": "execucao",
        # despesa (execução financeira)
        "Anexo NE - 2025NE00669": "despesa",
        "Nota de Empenho 2024NE01234": "despesa",
        "Nota Fiscal 118": "despesa",
        "DANFE": "despesa",
        "Nota de Liquidação": "despesa",
        "Despacho de Formalização de Liquidação de Despesa": "despesa",
        "Despacho sobre Autorização de Despesa": "despesa",
        "Programação de Desembolso": "despesa",
        "Ordem Bancária 2026OB00384": "despesa",
        "Autorização de Despesa - NAD": "despesa",
        # controle e assessoramento
        "Parecer Jurídico PGE": "controle",
        "Parecer 33/2024 - ASSJUR": "controle",
        "Nota Técnica de Auditoria": "controle",
        "Ofício TCE-RJ - Diligência": "controle",
        # tramitação (genérico)
        "Despacho de Encaminhamento de Processo": "tramitacao",
        "Ofício 123/2024": "tramitacao",
        "Memorando": "tramitacao",
        "Termo de Cancelamento de Documento": "tramitacao",
    }
    erros = []
    for titulo, esperada in casos.items():
        fase, tipo = classificar(titulo)
        if fase != esperada:
            erros.append(f"{titulo!r}: esperava {esperada}, veio {fase} ({tipo})")
    assert not erros, "\n".join(erros)


def test_anexo_generico_e_indefinido():
    fase, tipo = classificar("Anexo")
    assert fase == "indefinida" and tipo == "anexo"
    assert classificar("")[0] == "indefinida"


def test_tipo_e_extraido():
    assert classificar("1º Boletim de Medição")[1] == "medicao"
    assert classificar("Relatório Fotográfico - 5ª Medição")[1] == "relatorio_fotografico"
    assert classificar("Ordem Bancária 2026OB00384")[1] == "ordem_bancaria"


def test_linha_do_tempo_agrupa_por_fase():
    tl = linha_do_tempo(["Termo de Referência", "Edital 1", "Proposta",
                         "Contrato 9", "Nota de Empenho", "Nota Fiscal 3",
                         "Despacho", "Despacho"])
    assert tl["planejamento"] == ["Termo de Referência"]
    assert set(tl["selecao"]) == {"Edital 1", "Proposta"}
    assert tl["despesa"] == ["Nota de Empenho", "Nota Fiscal 3"]
    assert len(tl["tramitacao"]) == 2


def test_lacunas_licitacao_completa_sem_lacuna_critica():
    presentes = {"planejamento", "selecao", "contratacao", "execucao", "despesa"}
    assert lacunas(presentes, modalidade="pregão", com_pagamento=True) == []


def test_lacunas_pagamento_sem_execucao_e_critico():
    ls = lacunas({"despesa"}, modalidade="pregão", com_pagamento=True)
    assert any(l["gravidade"] == "critica" and "execução" in l["falta"].lower()
               for l in ls)
    assert any("seleção" in l["falta"].lower() or "planejamento" in l["falta"].lower()
               for l in ls)


def test_lacunas_dispensa_nao_cobra_edital():
    ls = lacunas({"planejamento", "contratacao", "execucao", "despesa"},
                 modalidade="dispensa", com_pagamento=True)
    assert not any("edital" in l["falta"].lower() for l in ls)


def test_fases_ordenadas():
    assert list(FASES)[:5] == ["planejamento", "selecao", "contratacao",
                               "execucao", "despesa"]
