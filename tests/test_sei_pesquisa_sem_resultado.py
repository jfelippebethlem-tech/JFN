# -*- coding: utf-8 -*-
"""A pesquisa do SEI que responde "Nenhum resultado encontrado" é resposta definitiva (medido 10/09 com
controle positivo na mesma unidade) — o reader devolve honesto e rápido, sem retentativa nem cracked."""
from __future__ import annotations

from tools.sei_reader import pesquisa_sem_resultado


def test_reconhece_a_frase_do_sei_no_fim_da_pagina():
    corpo = ("… Data de Inclusão no SEI | Data do Processo / Documento | Nenhum resultado encontrado. | "
             "Sugestões: | Certifique-se de que todas as palavras estejam escritas corretamente.")
    assert pesquisa_sem_resultado(corpo) is True


def test_pagina_com_resultado_ou_vazia_nao_dispara():
    assert pesquisa_sem_resultado("Resultado da Pesquisa | SEI-080002/004881/2026 | Financeiro: Pagamento") is False
    assert pesquisa_sem_resultado("") is False
    assert pesquisa_sem_resultado(None) is False
