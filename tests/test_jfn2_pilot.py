# -*- coding: utf-8 -*-
"""Piloto SEI (Onda B) — partes puras (sem rede): seleção explícita + avaliação/agregação."""
from __future__ import annotations


def test_selecionar_processos_explicitos():
    from tools.pilot_sei_avaliar import selecionar
    r = selecionar("A, B ,C", auto=False, n=2)
    assert r == ["A", "B"]  # respeita o limite n


def test_avaliar_agrega_e_e_honesto_sem_llm():
    from tools.pilot_sei_avaliar import avaliar
    regs = [
        {"ok_abertura": True, "tipos": {"homologacao": 1, "outros": 2},
         "itens": [{"valor_unitario": 10.0}, {"valor_unitario": 30.0}]},
        {"ok_abertura": False, "tipos": {}, "itens": []},
    ]
    a = avaliar(regs, gerar_ok=False)
    assert a["n_processos"] == 2 and a["abertos_ok"] == 1 and a["taxa_abertura"] == 0.5
    assert a["n_itens_extraidos"] == 2 and a["dispersao_preco"]["mediana"] == 20.0
    assert a["llm_disponivel"] is False and "pendente" in a["_nota"]
    assert a["tipos_doc_vistos"]["homologacao"] == 1
