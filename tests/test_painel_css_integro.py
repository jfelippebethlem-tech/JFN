"""O CSS do painel esta INTEIRO — um comentario quebrado engole regras em silencio.

Nasceu de um bug real (25/07/2026) que custou tres rodadas de diagnostico errado. Uma
edicao deixou um fecha-comentario orfao no meio de um bloco: o comentario terminou cedo,
o texto seguinte virou seletor invalido e o parser do navegador **consumiu o `@media`
inteiro de baixo como bloco de declaracao dele**. A regra simplesmente nao existia — sem
erro, sem aviso, sem nada no console. Eu culpei o `right`, depois a margem, depois o
`border-collapse`; so `getComputedStyle` no DOM vivo revelou a verdade.

O painel tem ~4.300 linhas e ~126 blocos de comentario, muitos deles longos e em
portugues. A chance de isso repetir e alta, e o sintoma (uma regra some) nao se parece
nem um pouco com a causa (um comentario). Este teste custa milissegundos e trava a volta.
"""
import re
from pathlib import Path

import pytest

PAINEL = Path(__file__).resolve().parents[1] / "static" / "jfn-painel.html"


def _css() -> tuple[str, int]:
    """Devolve o conteudo do <style> e a linha em que ele comeca (para o laudo)."""
    fonte = PAINEL.read_text(encoding="utf-8")
    m = re.search(r"<style>(.*?)</style>", fonte, re.S)
    assert m, "o painel perdeu o bloco <style>"
    return m.group(1), fonte[: m.start(1)].count("\n") + 1


def test_comentarios_css_balanceados():
    """Nenhum `/*` sem par e nenhum fecha-comentario solto no meio do CSS."""
    css, base = _css()
    i, dentro, abriu_em, orfaos = 0, False, 0, []
    while i < len(css) - 1:
        par = css[i : i + 2]
        if not dentro and par == "/*":
            dentro, abriu_em = True, i
            i += 2
            continue
        if dentro and par == "*/":
            dentro = False
            i += 2
            continue
        if not dentro and par == "*/":
            orfaos.append(base + css[:i].count("\n"))
        i += 1

    if orfaos:
        pytest.fail(
            "fecha-comentario orfao no CSS do painel nas linhas "
            + ", ".join(map(str, orfaos))
            + ". Tudo depois dele ate a proxima chave vira seletor invalido e a regra "
            "seguinte e engolida em silencio. Se voce estava DESCREVENDO o bug num "
            "comentario, escreva 'fecha-comentario' por extenso — nao os dois caracteres."
        )
    assert not dentro, (
        f"comentario aberto na linha {base + css[:abriu_em].count(chr(10))} nunca fecha — "
        "todo o CSS depois dele esta morto"
    )


def test_chaves_css_balanceadas():
    """`{` e `}` batem fora dos comentarios — bloco desbalanceado mata o resto da folha."""
    css, base = _css()
    sem_comentario = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    abre, fecha = sem_comentario.count("{"), sem_comentario.count("}")
    assert abre == fecha, (
        f"chaves desbalanceadas no CSS do painel: {abre} abrem, {fecha} fecham "
        f"(bloco <style> comeca na linha {base})"
    )


def test_regras_que_ja_foram_perdidas_continuam_vivas():
    """Guarda-corpo nominal: regras que JA sumiram uma vez, por bug de parse ou de lote.

    Nao e teste de estilo — e teste de PRESENCA. Cada linha aqui corresponde a um
    defeito que chegou aos olhos do dono; se o seletor sumir de novo, o teste fala.
    """
    css, _ = _css()
    obrigatorias = {
        # o botao A→Z foi arrancado de dentro do campo por uma regra em lote que
        # impos `position:relative` a quem ja estava `absolute`
        ".search .az{position:absolute}": ".search .az" in css and "position:absolute}" in css,
        # as 4 esferas se sobrepunham no celular com `flex:1;min-width:0`
        "esferas com largura natural no celular": "flex:0 0 auto;min-width:0;white-space:nowrap" in css,
        # o score saia da tela no celular
        "coluna de score grudada no celular": "#radar-tbl tbody td:last-child{" in css
        and "position:sticky" in css,
        # alvo de toque do nome do fornecedor abaixo da WCAG 2.5.8
        "area de toque do .clk": ".clk{padding:3px 0}" in css,
        # v14: a camada da faceta e onde toda decoracao nova mora. Se o seletor
        # sumir, as 51 assinaturas somem juntas e nada avisa.
        "camada .fac declarada": ".fac{position:absolute;inset:0" in css,
        "chanfro pintado no card": ".card>.fac::before{" in css,
        "moldura que se desenha": "@keyframes facTracar{" in css,
        # v14: --dim medido no PIXEL contra o veu de 6% do .card::before. L=0.60
        # foi calibrado pelo auditor de paradas, que lia 4,78 onde o real era 4,14.
        "--dim no valor medido no pixel": "--dim:oklch(0.63 0.03 240)" in css,
    }
    faltando = [k for k, ok in obrigatorias.items() if not ok]
    assert not faltando, "regra(s) que ja foram perdidas antes sumiram de novo: " + "; ".join(faltando)
