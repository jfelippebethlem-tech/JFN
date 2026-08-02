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


CSS_EXTRAIDO = Path(__file__).resolve().parents[1] / "static" / "css" / "painel.css"
# v58: o CSS passou a ser CONCATENACAO de `static/css/src/*.css`. Este teste le a ENTRADA e
# nao o artefato: validar a saida do build esconderia um comentario orfao escrito num estrato
# que ainda nao foi concatenado — e comentario orfao engolindo um @media inteiro e exatamente
# o bug de 25/07 que este arquivo existe para travar.
CSS_SRC = Path(__file__).resolve().parents[1] / "static" / "css" / "src"


def _css() -> tuple[str, int]:
    """Conteudo do CSS do painel, esteja ele INLINE ou em arquivo servido.

    v49: os 178 KB de CSS sairam de dentro do HTML para `static/css/painel.css`, servido com gzip e
    cache. Este teste lia so o `<style>` — depois da extracao ele nao encontrava nada e falhava com
    "o painel perdeu o bloco <style>", que e verdade e nao e problema. Ler as DUAS formas mantem a
    protecao valendo durante e depois da migracao, e continua valendo se um dia o CSS voltar para
    dentro. O que este teste protege — comentario orfao engolindo um `@media` inteiro — independe de
    onde o CSS mora.
    """
    fonte = PAINEL.read_text(encoding="utf-8")
    m = re.search(r"<style>(.*?)</style>", fonte, re.S)
    if m:
        return m.group(1), fonte[: m.start(1)].count("\n") + 1
    if CSS_SRC.is_dir():
        partes = sorted(CSS_SRC.glob("*.css"))
        if partes:
            return "".join(p.read_text(encoding="utf-8") for p in partes), 1
    assert CSS_EXTRAIDO.exists(), (
        "o painel nao tem <style> inline nem static/css/painel.css — o CSS sumiu de vez")
    assert '<link rel="stylesheet" href="/static/css/painel.css' in fonte, (
        "o CSS foi extraido mas o HTML nao o referencia — a pagina carregaria SEM estilo nenhum")
    return CSS_EXTRAIDO.read_text(encoding="utf-8"), 1


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
        # As guardas do v14 (.fac, chanfro, --dim 0.63) sairam junto com a reversao
        # de 2026-07-25 — teste tem de refletir o codigo que EXISTE, senao vira
        # ruido vermelho que todo mundo aprende a ignorar. Voltam com o v14, que
        # esta preservado no commit 62ffd7dc. O achado que o motivou permanece
        # valido e registrado: `.card::before` pinta um veu branco de 6% sobre todo
        # card, invisivel a qualquer leitor de estilo porque `::before` nao e
        # ancestral, e ele derruba `--dim` de 4,78 para 4,14:1 medido no pixel.
    }
    faltando = [k for k, ok in obrigatorias.items() if not ok]
    assert not faltando, "regra(s) que ja foram perdidas antes sumiram de novo: " + "; ".join(faltando)
