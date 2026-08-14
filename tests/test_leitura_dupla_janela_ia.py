# -*- coding: utf-8 -*-
"""A IA não pode PERDER o que não leu.

Medido em 60 casos de `pregao so_regra` — "a régua achou, a IA não": **41 (68%) tinham o valor ALÉM
dos 40.000 caracteres que a IA lê**, um deles no caractere 129.161. A assimetria é do DESENHO, não
do leitor: a IA para na primeira janela que responde (decisão de custo, porque mandar 150k numa
golada levava 9 minutos e devolvia resposta amputada), enquanto a régua varre o texto inteiro.

Chamar isso de "a IA perdeu" é medir o leitor pela minha decisão de custo — e foi o que a fila fez
por 55 iterações, inflando a categoria e me mandando investigar defeito onde não havia.

O estado exige DUAS informações que agora existem: quanto a IA leu (`chars_vistos`, gravado na
leitura) e onde o valor aparece no texto.
"""
from __future__ import annotations

from tools.sei_leitura_dupla import comparar

_DET = {"pregao": {"valor": "20/24", "alternativas": []}}
_IA = {"estado": "ok", "chars_vistos": 40_000, "fatos": {"pregao": "NAO_CONSTA"}}


def test_valor_alem_da_janela_nao_e_falha_da_ia():
    r = comparar(_DET, _IA, {"tem_ob": False}, "x" * 50_000 + "Pregão Eletrônico nº 20/24")
    assert "pregao" not in r["discordancia"]
    assert r["ausencia_concorde"]["pregao"]["estado"] == "fora_da_janela_da_ia"


def test_valor_DENTRO_da_janela_continua_sendo_falha_da_ia():
    """A guarda não pode absolver o que a IA de fato viu e não reportou."""
    r = comparar(_DET, _IA, {"tem_ob": False}, "Pregão Eletrônico nº 20/24" + "x" * 50_000)
    assert r["discordancia"]["pregao"]["estado"] == "so_regra"


def test_sem_saber_quanto_a_ia_leu_nao_se_absolve_ninguem():
    """Leitura antiga não tem `chars_vistos` — na dúvida, o caso permanece na fila."""
    antiga = {"estado": "ok", "fatos": {"pregao": "NAO_CONSTA"}}
    r = comparar(_DET, antiga, {"tem_ob": False}, "x" * 50_000 + "Pregão Eletrônico nº 20/24")
    assert r["discordancia"]["pregao"]["estado"] == "so_regra"
