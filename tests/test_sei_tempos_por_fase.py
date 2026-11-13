# -*- coding: utf-8 -*-
"""Cada leitura do sweep diz ONDE gastou o tempo: pesquisa, árvore, conteúdo.

Medido em 13/11/2026 sobre `data/sei_sweep.log` (30 dias): 9.046 leituras, 398 h; leitura com 0-19
documentos leva 124 s na mediana, e a leitura que termina em 0 documento leva 48 s — mas o log só
tinha o TOTAL por processo. Não havia como dizer se o tempo ia na pesquisa, na árvore ou no laço
de documentos (e o dono pediu exatamente isso: "o SEI precisa ser mais rápido"). Sem medição por
fase, qualquer otimização é palpite. A VM não comporta medir ao vivo em carga; o log passa a medir.
"""
import inspect

from tools import sei_reader as R
from tools import sei_sweep as S


def test_formato_compacto_no_log():
    t = {"pesquisa": 12.4, "arvore": 3.9, "conteudo": 140.2, "docs_tentados": 18}
    assert S._fmt_tempos(t) == " [t pesq 12s · árv 4s · docs 140s/18]"


def test_sem_tempos_nao_muda_a_linha():
    assert S._fmt_tempos(None) == ""
    assert S._fmt_tempos({}) == ""


def test_fase_ausente_nao_quebra():
    """Pesquisa respondeu 'Nenhum resultado': só há a fase de pesquisa."""
    assert S._fmt_tempos({"pesquisa": 30.0}) == " [t pesq 30s]"


def test_ler_processo_mede_as_tres_fases():
    fonte = inspect.getsource(R.ler_processo)
    for chave in ('"pesquisa"', '"arvore"', '"conteudo"', '"docs_tentados"'):
        assert chave in fonte, f"ler_processo não mede {chave}"
    assert fonte.count('"_tempos"') >= 2, "o caminho 'sem resultado' também tem de levar o tempo"


def test_sweep_escreve_as_fases_na_linha_do_processo():
    fonte = inspect.getsource(S.run)
    assert "_fmt_tempos(" in fonte
