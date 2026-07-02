# -*- coding: utf-8 -*-
"""Partes puras do experimento IA-fraca-vs-gabarito (tools/experimento_ia_fraca).

A chamada de LLM é ao vivo (groq); aqui travamos o que é determinístico: a
normalização de acento (fonte de falso desacordo) e o cálculo de concordância
que ignora documentos que o gabarito não sabe classificar."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.experimento_ia_fraca import _canon, _concordancia


def test_canon_remove_acento_e_caixa():
    assert _canon("Tramitação") == "tramitacao"
    assert _canon("SELEÇÃO") == "selecao"
    assert _canon("  execução ") == "execucao"


def test_concordancia_ignora_indefinida_do_gabarito():
    titulos = ["a", "b", "c"]
    gab = {0: "despesa", 1: "indefinida", 2: "selecao"}   # doc 1 gabarito não sabe
    llm = {0: "despesa", 1: "qualquer", 2: "selecao"}
    conc, erros = _concordancia(titulos, gab, llm)
    assert conc == 1.0 and erros == []                    # 2/2 válidos, doc 1 fora


def test_concordancia_conta_erro_real():
    titulos = ["a", "b"]
    gab = {0: "planejamento", 1: "despesa"}
    llm = {0: "contratacao", 1: "despesa"}                # erra o 0 (TR≠contrato)
    conc, erros = _concordancia(titulos, gab, llm)
    assert conc == 0.5
    assert erros[0]["gabarito"] == "planejamento" and erros[0]["ia"] == "contratacao"


def test_concordancia_acento_nao_e_erro():
    # a IA devolve com acento; _classificar_llm já normaliza, mas a função de
    # concordância compara canônico com canônico (gabarito já é sem acento)
    titulos = ["a"]
    gab = {0: "tramitacao"}
    llm = {0: _canon("tramitação")}
    conc, _ = _concordancia(titulos, gab, llm)
    assert conc == 1.0
