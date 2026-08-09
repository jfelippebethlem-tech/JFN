# -*- coding: utf-8 -*-
"""O guard de fatia capada tem de disparar no platô MEDIDO, não no teto teórico.

`coletar_por_ug_grande` divide a UG em fatias por prefixo de número e subdivide a fatia que
"estourou". O limiar era `n >= 990`, escolhido pelo teto nominal de 1.000 registros por consulta
do SIAFE. Medido em 2026-08-09 sobre **5.893 fatias** já coletadas (checkpoints de junho):

    fatias com n >= 990 .......... 0      ← o guard NUNCA disparou
    fatias com n == 989 ......... 48      ← platô
    fatias com n == 984 ......... 28      ← platô
    fatias entre 950 e 989 ...... 124     ← aceitas como COMPLETAS

A colheita satura abaixo do teto teórico (a tabela é virtualizada e o scroller entrega ~989 antes
de parar), então nenhuma fatia truncada foi subdividida: 124 fatias entraram no banco como se
fossem o universo. Somado à PK que apagava OB de outra UG, é a explicação de por que a UG 180100
tem 1.000 linhas onde o log diz 10.046.

Subdividir uma fatia que por acaso tenha 980-989 registros VERDADEIROS custa consultas a mais e
nada de errado — os sub-prefixos devolvem as mesmas linhas e a ingestão é idempotente. Aceitar uma
fatia truncada custa dado que ninguém sabe que falta. O limiar erra para o lado barato.
"""
from __future__ import annotations

import pytest

from compliance_agent.siafe_ob_orcamentaria import _fatia_capou


@pytest.mark.parametrize("n", [989, 984, 986, 980, 1000])
def test_plato_medido_conta_como_capada(n):
    assert _fatia_capou(n, "2023OB1", 2023), f"fatia de {n} linhas passou como completa"


@pytest.mark.parametrize("n", [0, 100, 643, 979])
def test_fatia_pequena_e_completa(n):
    assert not _fatia_capou(n, "2023OB1", 2023)


def test_profundidade_maxima_para_de_subdividir():
    """Prefixo já longo não subdivide para sempre — o SIAFE tem 8 dígitos depois de 'OB'."""
    fundo = "2023OB" + "1" * 8
    assert not _fatia_capou(1000, fundo, 2023), "subdivisão infinita: o prefixo já esgotou"


def test_espera_a_segunda_linha_do_filtro_antes_de_usar():
    """A linha 1 do filtro NASCE SOZINHA — usar antes da hora dá Timeout que parece falta de tela.

    Inventário do painel medido em 2026-08-09: os únicos controles são "Ocultar este painel",
    "Limpar" e o botão de excluir de cada linha. **Não há botão de adicionar linha** — o ADF
    acrescenta a seguinte por PPR quando a de cima fica completa. Ir direto para
    `table_rtfFilter:1` estourava em `Locator.click: Timeout 30000ms`, e o erro se lia como "o
    SIAFE 1 não tem segunda linha"; era corrida — a MESMA coleta já tinha funcionado e subdividido
    prefixos numa passada anterior. Sem essa linha não há subdivisão, e sem subdivisão o teto de
    1.000 nunca é furado.
    """
    import inspect

    from compliance_agent import siafe_ob_orcamentaria as M

    assert callable(M._esperar_linha_filtro)
    for fn in (M.coletar_por_ug_grande, M.coletar_por_data):
        fonte = inspect.getsource(fn)
        i_espera = fonte.find("_esperar_linha_filtro")
        i_uso = fonte.find("_F_PROP1")
        assert i_espera > 0, f"{fn.__name__} usa a linha 1 sem esperar que ela exista"
        assert i_espera < i_uso, f"{fn.__name__} espera DEPOIS de usar — não adianta"


def test_seletor_do_playwright_nao_vaza_para_o_navegador():
    """`:visible` é do Playwright, não é CSS — no `querySelectorAll` ele lança DOMException.

    Medido em 2026-08-09: o commit do valor do filtro (o evento que faz o SIAFE 1 APLICAR o
    filtro e criar a linha seguinte) lançava
    `DOMException: '...:visible' is not a valid selector` em toda chamada. O log já dizia isso —
    e a coleta parecia apenas "intermitente". Os seletores de valor são `_F_VAL_SEL`/`_F_VAL1_SEL`,
    escritos com `:visible` porque servem TAMBÉM ao locator do Playwright; quem os leva para
    dentro do navegador tem de limpar o sufixo (a visibilidade é filtrada em JS logo depois).
    """
    import inspect

    from compliance_agent import siafe_ob_orcamentaria as M

    fonte = inspect.getsource(M._set_valor)
    assert ":visible" in M._F_VAL_SEL, "premissa mudou: o seletor não usa mais o pseudo do Playwright"
    assert "replace(/:visible" in fonte, (
        "o seletor com `:visible` volta a ir cru para o navegador — DOMException a cada filtro")
