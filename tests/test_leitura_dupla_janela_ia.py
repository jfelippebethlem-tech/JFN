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

# `pos` = onde a RÉGUA casou o valor. Sem ele a guarda não absolve ninguém, e é assim que deve ser:
# leitura antiga não tem a informação, e presumir "estava fora da janela" absolveria por comodidade.
_DET = {"pregao": {"valor": "20/24", "alternativas": [], "pos": 50_000}}
_IA = {"estado": "ok", "chars_vistos": 40_000, "fatos": {"pregao": "NAO_CONSTA"}}


def test_valor_alem_da_janela_nao_e_falha_da_ia():
    r = comparar(_DET, _IA, {"tem_ob": False}, "x" * 50_000 + "Pregão Eletrônico nº 20/24")
    assert "pregao" not in r["discordancia"]
    assert r["ausencia_concorde"]["pregao"]["estado"] == "fora_da_janela_da_ia"


def test_valor_DENTRO_da_janela_continua_sendo_falha_da_ia():
    """A guarda não pode absolver o que a IA de fato viu e não reportou."""
    dentro = {"pregao": {"valor": "20/24", "alternativas": [], "pos": 10}}
    r = comparar(dentro, _IA, {"tem_ob": False}, "Pregão Eletrônico nº 20/24" + "x" * 50_000)
    assert r["discordancia"]["pregao"]["estado"] == "so_regra"


def test_sem_saber_quanto_a_ia_leu_nao_se_absolve_ninguem():
    """Leitura antiga não tem `chars_vistos` — na dúvida, o caso PERMANECE na fila. Absolver por
    presunção seria trocar uma medida por uma comodidade."""
    antiga = {"estado": "ok", "fatos": {"pregao": "NAO_CONSTA"}}
    r = comparar(_DET, antiga, {"tem_ob": False}, "x" * 50_000 + "Pregão Eletrônico nº 20/24")
    assert r["discordancia"]["pregao"]["estado"] == "so_regra"


def test_a_posicao_vem_do_TRECHO_CASADO_e_nao_da_string_nua():
    """A guarda de janela nasceu MORTA por causa disto, e medi 0% onde a amostra manual dava 68%.

    `texto.find("02/2023")` acha uma ocorrência coincidente — por exemplo dentro do número de
    processo `SEI-040225/001202/2023` — e conclui que o instrumento está no começo do documento.
    É a MESMA armadilha que já me enganara ao inspecionar contexto: procurar o trecho casado pela
    régua, nunca o valor solto.
    """
    from tools.sei_leitura_dupla import comparar, extrair_deterministico
    texto = ("Processo SEI-040225/001202/2023 tramita. " + "x" * 50_000
             + " Pregão Eletrônico nº 02/2023")
    det = extrair_deterministico(texto)
    assert det["pregao"]["pos"] > 40_000, "a posição casada tem de ser a do CERTAME, não a coincidência"
    ia = {"estado": "ok", "chars_vistos": 40_000, "fatos": {"pregao": "NAO_CONSTA"}}
    r = comparar(det, ia, {"tem_ob": False}, texto)
    assert r["ausencia_concorde"]["pregao"]["estado"] == "fora_da_janela_da_ia"
