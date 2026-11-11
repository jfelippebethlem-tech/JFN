# -*- coding: utf-8 -*-
"""Extração do processo SEI dos atos do DOERJ — casos REAIS de `publicacoes_doerj` (ids citados).

Medido em 11/11/2026: só 185 de 2.636 atos de contrato tinham processo, e só 49 válidos. A regex
antiga `SEI[-\\s]*\\d` casava UM dígito e gravava `["SEI-\\n0"]` onde o texto trazia
`SEI-040014/005088/2025` — e o território herdou o zero ("DOERJ: 0 contratos ganharam o texto").
Na amostra de 4.000 atos, o formato `SEI-6/6/4` aparece 15.031 vezes; 2.754 com quebra de linha
depois do hífen.
"""
import pytest

from compliance_agent.collectors.doerj import extrair_processos_sei


@pytest.mark.parametrize("texto,esperado", [
    # id 1868: quebra de linha depois do hífen (o caso que gravava "SEI-\n0")
    ("Processo \nnº \nSEI-\n040014/005088/2025.\nId: 2740903", ["SEI-040014/005088/2025"]),
    # id 50019
    ("Interessado: FERNANDA SENNA XAVIER SEI-\n270089/001130/2023 - Acórdão",
     ["SEI-270089/001130/2023"]),
    # forma limpa e com espaço no lugar do hífen
    ("SEI-180002/001293/2026", ["SEI-180002/001293/2026"]),
    ("processo SEI 350069/000051/2021 -", ["SEI-350069/000051/2021"]),
    ("SEI - 330002/006353/2026", ["SEI-330002/006353/2026"]),
    ("SEI/040006/006282/2026\n1", ["SEI-040006/006282/2026"]),
    # id 49637: o número do termo na linha seguinte não pode grudar no ano
    ("1\nSEI-150016/144576/2024\n026/26\nABL System", ["SEI-150016/144576/2024"]),
    # id 49970: PDF com dígitos espaçados
    ("Processo\nnº\nSEI-\n2 6 0 0 0 6 / 0 4 8 0 11 / 2 0 2 6 .", ["SEI-260006/048011/2026"]),
    # numeração antiga E- (com e sem SEI na frente)
    ("o processo nº SEI-E-04/079/1807/2017 foram devolvidos", ["E-04/079/1807/2017"]),
    ("*PROCESSO N° SEI-E-08/301.708/1986 - SANDRA", ["E-08/301.708/1986"]),
    ("Processos-\nSEI: \nE-16/061/010081/2019; \nE-16/061/017026/2019; \nE-\n16/061/105162/2019;",
     ["E-16/061/010081/2019", "E-16/061/017026/2019", "E-16/061/105162/2019"]),
    ("Conforme processo N° SEI\n04/161/002148/2019.", ["E-04/161/002148/2019"]),
    # sem o prefixo SEI
    ("Processo nº 040014/005088/2025, Id", ["SEI-040014/005088/2025"]),
])
def test_extrai_processo_sei_real(texto, esperado):
    assert extrair_processos_sei(texto) == esperado


@pytest.mark.parametrize("texto", [
    # id 50016: número de DOCUMENTO do SEI (9 dígitos) não é processo
    "confirmada pelo Parecer n.º 144111760 (SEI-144111760). VALOR",
    # id 5986: outro sistema de numeração com o mesmo desenho
    "PROCESSO: nº JPR-010125/000713/2025\nREQUISITA",
    # processo do TCE não é processo SEI
    "Processo TCE nº 100737-6/2026 - Interessado",
])
def test_nao_inventa_processo(texto):
    assert extrair_processos_sei(texto) == []


def test_deduplica_e_preserva_a_ordem():
    t = "SEI-180002/001293/2026 ... SEI-\n180002/001293/2026 ... E-12/412576/2012"
    assert extrair_processos_sei(t) == ["SEI-180002/001293/2026", "E-12/412576/2012"]
