# -*- coding: utf-8 -*-
"""Fase do documento pelo TÍTULO — o que prova entrega e o que só prova habilitação."""
import pytest


# ═══ o ATO de atestar, nas formas que o SEI-RJ usa (2026-08-04) ═══

@pytest.mark.parametrize("titulo", [
    "Despacho Atestação (76731988)",
    "Atestado de Recebimento de Materiais 70741728",
    "Atestado de Realização de Serviços",
    "Termo de Recebimento Definitivo",
    "Medição 03 - Obra",
])
def test_ato_de_atestar_entra_na_fase_de_execucao(titulo):
    """Medido em 2026-08-04: dos processos acusados de "sem evidência de execução APESAR DE HAVER
    PAGAMENTO" — acusação CRÍTICA, 353 nos EXTREMO+ALTO —, ~10% tinham o atesto nos autos e não
    eram vistos, porque o título caía em tramitacao/despacho ou indefinida/outro."""
    from compliance_agent.sei.fases import classificar
    assert classificar(titulo)[0] == "execucao", titulo


@pytest.mark.parametrize("titulo", [
    "Atestado de Capacidade Técnica",
    "Atestado Idoneidade - Empresa Representante Brasileira",
    "Atestado de Retorno ao Trabalho",
    "Atestado de Locação/Permissão Onerosa de Imóveis 135904166",
    "Atestado Técnico",
])
def test_certidao_de_habilitacao_NAO_e_prova_de_entrega(titulo):
    """`atestado` sozinho não basta: atestado de capacidade/idoneidade é CERTIDÃO de habilitação,
    e atestado de retorno ao trabalho é documento de pessoal. Confundir os dois inverteria o erro
    — passaria a dizer que houve entrega onde só houve certidão."""
    from compliance_agent.sei.fases import classificar
    assert classificar(titulo)[0] != "execucao", titulo
