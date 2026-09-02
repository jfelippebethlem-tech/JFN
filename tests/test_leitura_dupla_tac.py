# -*- coding: utf-8 -*-
"""O Termo de Ajuste de Contas tem NÚMERO próprio — e é o terceiro instrumento do acervo.

Achado lendo os autos à mão: o extrato publica o TAC como qualquer outro instrumento
(`INSTRUMENTO: Termo de Ajuste de Contas nº 1750/2024`), e um único processo carrega QUATRO.

Antes disso, os TACs eram contáveis só pelo texto do `o_que_e` — 15 processos. Com o instrumento
numerado: **101 processos e 326 TACs distintos no acervo, dos quais 75 processos e 269 TACs numa só
unidade (FSERJ), somando R$ 43,8 mi pagos por Ordem Bancária.**

O TAC é legalmente admitido (indeniza serviço prestado, veda enriquecimento sem causa). O que o
número permite não é acusar — é CONTAR, e a escala é o que distingue exceção de método.
"""
from __future__ import annotations

import pytest

from tools.sei_leitura_dupla import _FATOS, extrair_deterministico

CASOS = [
    ("INSTRUMENTO: Termo de Ajuste de Contas nº 1750/2024. PARTES: Fundação Saúde\n", "1750/2024"),
    ("TERMO DE AJUSTE DE CONTAS N° 059/2025 firmado com\n", "059/2025"),
]


@pytest.mark.parametrize("texto,esperado", CASOS)
def test_acha_o_TAC_numerado(texto, esperado):
    assert extrair_deterministico(texto)["tac"]["valor"] == esperado


def test_varios_TACs_no_mesmo_processo_entram_todos():
    """Um processo real traz quatro: 1750, 1815, 1823 e 1829/2024. Guardar só o primeiro
    subcontaria o instrumento justamente onde ele se concentra."""
    t = "".join(f"INSTRUMENTO: Termo de Ajuste de Contas nº {n}/2024.\n"
                for n in (1750, 1815, 1823, 1829))
    d = extrair_deterministico(t)["tac"]
    achados = {d["valor"]} | {a["valor"] for a in d["alternativas"]}
    assert achados == {"1750/2024", "1815/2024", "1823/2024", "1829/2024"}


def test_o_TAC_tambem_e_perguntado_a_ia():
    assert "tac" in _FATOS


def test_contrato_comum_nao_vira_TAC():
    d = extrair_deterministico("INSTRUMENTO: Contrato nº 443/2025.\n")
    assert not d["tac"]["valor"] and d["contrato"]["valor"] == "443/2025"
