# -*- coding: utf-8 -*-
"""Testes da lógica pura do coletor do D.O. Rio (``pcrj/doweb.py``).

Rede não é exercida aqui (isso é feito ao vivo, "como humano"); estes testes
travam a extração de nº de processo e a classificação de tipo — onde mora o risco
de falso positivo. Texto real capturado do D.O. de 2025-09-04 (contrato da PPP).
"""
from compliance_agent.pcrj.doweb import extrair_processos, classificar

# Trecho verbatim do ato de assinatura do contrato de PPP do Souza Aguiar (D.O. Rio 2025-09-04)
TXT_PPP = (
    "PROCESSOS Nº 09/002.991/2022 - 09/61/000.285/2023 CONSIDERANDO as razões de "
    "interesse público que culminaram na celebração do Contrato de Parceria "
    "Público-Privada entre o MUNICÍPIO DO RIO DE JANEIRO e a Concessionária "
    "SMART HOSPITAL S.A, que tem por objeto a Concessão Administrativa para "
    "Modernização e Adequação de Instalações Prediais"
)
TXT_SEIRIO = "Autorizado ... Processo nº.: 000900.048716/2026-91 1. Nº DA AQUISIÇÃO: 2609406"
TXT_HOMOLOG = "HOMOLOGO o resultado do Pregão Eletrônico nº 078/25 e ADJUDICO o objeto"


def test_extrai_processo_siga_ppp():
    procs = extrair_processos(TXT_PPP)
    assert "09/002.991/2022" in procs
    assert "09/61/000.285/2023" in procs


def test_nao_extrai_submatch_espurio():
    """`61/000.285/2023` é substring de `09/61/000.285/2023` — não deve virar item próprio."""
    procs = extrair_processos(TXT_PPP)
    assert "61/000.285/2023" not in procs


def test_extrai_processo_seirio():
    assert "000900.048716/2026-91" in extrair_processos(TXT_SEIRIO)


def test_dedup_estavel():
    procs = extrair_processos(TXT_PPP + " " + TXT_PPP)  # texto repetido
    assert procs.count("09/002.991/2022") == 1


def test_classifica_ppp():
    assert classificar(TXT_PPP) == "ppp"


def test_classifica_homologacao():
    assert classificar(TXT_HOMOLOG) == "homologacao"


def test_classifica_outro():
    assert classificar("Nomeação de servidor para cargo em comissão.") == "outro"


# Regressão de precisão (bugs achados testando a base real — página do D.O. mistura atos)
def test_relatorio_fiscal_com_ppp_nao_e_ppp():
    """'obrigações de PPP' em balanço/RREO NÃO é ato de PPP (era falso positivo)."""
    t = "DESPESAS COM SAÚDE NÃO COMPUTADAS NO CÁLCULO MÍNIMO. OBRIGAÇÕES DE PPP SALDO TOTAL EM 31 DE DEZEMBRO."
    assert classificar(t) == "outro"


def test_homologacao_de_conselheiro_nao_e_licitacao():
    assert classificar("DELIBERA: Art. 1º Homologar a indicação do Conselheiro Fulano de Tal.") == "outro"


def test_homologacao_de_ppp_real_e_ppp():
    """Homologação de concorrência de PPP é ato de PPP (instrumento presente)."""
    t = "HOMOLOGO o resultado da CONCESSÃO ADMINISTRATIVA - CONCORRÊNCIA PPP ADM SMS Nº 01/2023."
    assert classificar(t) == "ppp"


def test_concessao_solta_nao_e_ppp():
    assert classificar("Concessão de diária ao servidor para viagem.") == "outro"


# ── novos tipos de ato de contratação (refino PCRJ 2026-07-24) ──────────────

def test_classifica_dispensa():
    t = ("RATIFICO a DISPENSA DE LICITAÇÃO com fundamento no art. 75, II da Lei "
         "14.133/2021, em favor da empresa XPTO LTDA, no valor de R$ 48.000,00.")
    assert classificar(t) == "dispensa"


def test_classifica_inexigibilidade():
    t = ("Reconheço a INEXIGIBILIDADE DE LICITAÇÃO, art. 74, caput, da Lei nº "
         "14.133/2021, por inviabilidade de competição, favor de FORNECEDOR ÚNICO S.A.")
    assert classificar(t) == "inexigibilidade"


def test_classifica_aditivo():
    t = ("EXTRATO DE TERMO ADITIVO Nº 03 ao Contrato nº 12/2023. Objeto: "
         "prorrogação de prazo e acréscimo de 25% do valor contratual.")
    assert classificar(t) == "aditivo"


def test_classifica_ata_registro_preco():
    t = "EXTRATO DE ATA DE REGISTRO DE PREÇOS Nº 045/2025 - Pregão Eletrônico 078/2025."
    assert classificar(t) == "ata_registro_preco"


def test_dispensa_tem_prioridade_sobre_edital_solto():
    """'dispensa de licitação' contém a palavra 'licitação' mas é dispensa, não edital."""
    assert classificar("DISPENSA DE LICITAÇÃO nº 10/2025 ratificada.") == "dispensa"


def test_diaria_de_viagem_nao_e_aditivo():
    assert classificar("Concede diárias e adiantamento ao servidor.") == "outro"
