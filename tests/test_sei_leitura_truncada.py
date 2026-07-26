"""Leitura truncada do SEI nunca pode virar cache de sucesso.

Regressão de 2026-07-23: o bound de tempo (`timeout` sem `--foreground`) matava o
Chromium junto com o Python. A árvore já extraída era gravada com
`conteudo_documentos: []` e o checkpoint marcava `n_docs>0` — 75 processos saíram
da fila para sempre. Mesmo pecado do insert_textbox: salvar como sucesso o que
falhou (ver ~/vault: sei-insert-textbox-branco).
"""
from tools.sei_reader import leitura_truncada


def test_browser_morto_sem_conteudo_e_truncada():
    assert leitura_truncada(tentados=6, com_conteudo=0, pagina_viva=False) is True


def test_browser_morto_com_conteudo_parcial_e_truncada():
    """O caso silencioso: docs 1..k lidos, k+1..n perdidos."""
    assert leitura_truncada(tentados=6, com_conteudo=2, pagina_viva=False) is True


def test_pagina_viva_sem_conteudo_NAO_e_truncada():
    """Todos os documentos restritos (cadeado) = conteúdo vazio LEGÍTIMO."""
    assert leitura_truncada(tentados=6, com_conteudo=0, pagina_viva=True) is False


def test_leitura_completa_nao_e_truncada():
    assert leitura_truncada(tentados=6, com_conteudo=6, pagina_viva=True) is False
    assert leitura_truncada(tentados=6, com_conteudo=6, pagina_viva=False) is False


def test_processo_sem_documentos_nao_e_truncada():
    """Sem docs a decidir, quem manda é a guarda de INDISPONÍVEL que já existia."""
    assert leitura_truncada(tentados=0, com_conteudo=0, pagina_viva=False) is False
