# -*- coding: utf-8 -*-
"""Fatiar atos no texto de PDF do DOERJ: sigla entre o tipo e o 'Nº', 'Nº SEI', cabeçalhos 'ATO DO …'."""
from __future__ import annotations

from datetime import date

from compliance_agent.collectors.doerj import DOERJCollector

_TX = """ATO DO SECRETÁRIO
RESOLUÇÃO SEPM Nº 9164 DE 03 DE AGOSTO DE 2026
O SECRETÁRIO resolve exonerar Fulano.
ATO DA VICE D I R E TO R A-GERAL
PORTARIA UERJ/PPC Nº SEI 1080/2026 - I N S TA U R A sindicância para apurar
os fatos do processo SEI-260007/000123/2026.
DESPACHOS DA DIRETORA
PORTARIA Nº 364/SGP/2026 - A referida portaria fica apostilada para
constar a matrícula correta.
"""


def test_corta_com_sigla_e_numero_sei():
    c = DOERJCollector()
    atos = c._fatiar_atos(_TX, date(2026, 9, 8), "u", edicao="I", titulo="Parte I")
    textos = [a["texto"] for a in atos]
    assert any(t.startswith("PORTARIA UERJ/PPC") and "sindicância" in t for t in textos)
    assert any(t.startswith("RESOLUÇÃO SEPM") for t in textos)
    assert any(t.startswith("PORTARIA Nº 364") for t in textos)
    assert not any("sindicância" in t and "apostilada" in t for t in textos)   # não agrupou os dois


def test_secao_por_palavra_inteira():
    from compliance_agent.collectors.doerj import _inferir_secao
    assert _inferir_secao("Parte I (Poder Executivo)", "") == "I"
    assert _inferir_secao("Parte IB - (Tribunal de Contas)", "") == "IB"
    assert _inferir_secao("Parte II (Poder Legislativo)", "") == "II"
    assert _inferir_secao("Parte IV (Municipalidades)", "") == "IV"
    assert _inferir_secao("Parte V (Publicações a Pedido)", "") == "V"
    assert _inferir_secao("Edição Extra", "") == "E"
