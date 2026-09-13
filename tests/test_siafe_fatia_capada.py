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


def test_nenhum_evaluate_leva_pseudo_do_playwright_para_o_navegador():
    """Varredura do pacote: `:visible` (e afins) só valem no locator do Playwright.

    `siafe_contratos.py` usa `:visible` do jeito certo — dentro de `pg.locator(...)`. O vazamento
    aconteceu em UM lugar: um seletor montado para o locator foi reaproveitado dentro de
    `pg.evaluate`, onde vira `DOMException` e mata o passo em silêncio (o log traz a exceção, mas o
    fluxo segue como se o filtro tivesse sido aplicado). Esta catraca varre `compliance_agent/`
    inteiro para a terceira cópia não nascer.
    """
    import pathlib
    import re

    raiz = pathlib.Path(__file__).resolve().parent.parent
    pseudos = (":visible", ":has-text(", ":text(")
    suspeitos = []
    for arq in (raiz / "compliance_agent").rglob("*.py"):
        txt = arq.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"\.evaluate\(", txt):
            trecho = txt[m.end():m.end() + 900]
            fim = trecho.find(")\n")
            corpo = trecho[: fim if fim > 0 else 900]
            if any(p in corpo for p in pseudos) and "replace(/:visible" not in corpo:
                suspeitos.append(f"{arq.relative_to(raiz)}: {corpo.strip()[:70]}")
    assert not suspeitos, (
        "pseudo-seletor do Playwright dentro de evaluate (vira DOMException no navegador): "
        + " | ".join(suspeitos))


def test_blocos_de_js_sao_raw_strings():
    """`\\b`, `\\d`, `\\s` numa string NÃO-raw viram escapes do Python antes de o JS ver.

    Medido em 2026-08-09: o conserto que remove `:visible` do seletor ficou INERTE por três
    execuções porque a regex `/:visible\\b/g` estava numa `\"\"\"…\"\"\"` comum — o Python trocou `\\b`
    por BACKSPACE (`\\x08`) e a expressão deixou de casar. O log continuou acusando
    `DOMException: is not a valid selector` e eu li como "o conserto não pegou".

    Regra: todo bloco de JavaScript passado a `pg.evaluate` usa `r\"\"\"`.
    """
    import inspect

    from compliance_agent import siafe_ob_orcamentaria as M

    # os escapes que o Python COME numa string não-raw e que aparecem em regex de JS:
    # \b (backspace), \a (bell), \f (form feed), \v (vertical tab). `\n`/`\t` ficam de fora
    # porque são legítimos em código-fonte formatado.
    perigosos = {"\b": chr(8), "\a": chr(7), "\f": chr(12), "\v": chr(11)}
    fonte = inspect.getsource(M)
    achados = [nome for nome, ch in perigosos.items() if ch in fonte]
    assert not achados, (
        f"escape do Python comido dentro de string de JS ({achados}): use r\"\"\" no bloco")
    for fn in (M._set_valor, M._navegar, M._esperar_linha_filtro):
        src = inspect.getsource(fn)
        assert not any(ch in src for ch in perigosos.values()), (
            f"{fn.__name__} tem escape do Python dentro do JS")
