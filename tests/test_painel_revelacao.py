"""As GRAMATICAS DE REVELACAO (v59) obedecem as tres leis do estrato — provado no arquivo.

POR QUE ESTE TESTE EXISTE. Animacao que NAO acontece nao quebra nada: nao lanca erro, nao aparece
no console, nao muda uma contagem de teste. Foi assim que o `--i` do v34 atravessou versoes
inteiras sem numerar uma unica linha de tabela, enquanto o comentario ao lado afirmava que a coluna
era lida de cima para baixo. E foi assim que o bug do v43 ("o KPI que sumia") ficou treze versoes
na tela: um `animation:` que substituiu em vez de compor deixou o achado mais grave INVISIVEL.

As tres leis do `96-v59.css` estao escritas no cabecalho dele. Comentario nao falha build; estas
quatro asserçoes falham.

O que este arquivo NAO cobre, de proposito: se a gramatica certa cai na tela certa. Isso e
comportamento vivo, depende de dado, e quem prova e a sonda de navegador contra o censo de
`revelacaoCenso()`. Teste estatico que finge medir comportamento e pior que teste nenhum.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CSS = _REPO / "static" / "css" / "src" / "96-v59.css"
_JS = _REPO / "static" / "js" / "src" / "ui" / "revelacao.js"
_UI = _REPO / "static" / "js" / "src" / "ui" / "index.js"


def _css() -> str:
    return _CSS.read_text(encoding="utf-8")


# As classes que o motor marca. Cada uma tem de ter gesto no CSS e desligamento nos dois pisos.
_CLASSES = ["rv-linha", "rv-lado", "rv-sec", "rv-leque"]


def test_o_estrato_do_v59_existe_e_esta_na_concatenacao():
    """Estrato orfao e CSS que nao chega ao navegador — o `--juntar` le `src/*.css` por prefixo."""
    assert _CSS.is_file(), "static/css/src/96-v59.css sumiu"
    from tools.painel_css_cortar import juntar

    assert "rv-linha" in juntar(), "o estrato 96 nao entrou na concatenacao do painel.css"


def test_lei_1_nenhuma_animacao_de_revelacao_parte_de_opacidade_zero():
    """Animacao de CSS congela em aba de segundo plano. Um reveal partindo de `opacity:0` deixa a
    tela EM BRANCO para quem volta o foco no meio — a mesma familia de bug do portal (3cf2a6a1).
    Todo `@keyframes rv*` parte de .3 ou mais, como o `entraCascata` do v33.

    `rvRisca` e `rvPonto` sao a excecao declarada: a risca e um filete de 1px de altura e o ponto
    e um LED de 5px — os dois sao ADORNO da secao, nao o conteudo dela, e nenhum dos dois pode
    deixar leitura nenhuma em branco.
    """
    texto = _css()
    isentos = {"rvRisca", "rvPonto"}
    achou = False
    for nome, corpo in re.findall(r"@keyframes\s+(rv\w+)\s*\{(.*?)\n", texto, re.S):
        if nome in isentos:
            continue
        achou = True
        m = re.search(r"from\s*\{([^}]*)\}", corpo)
        assert m, f"@keyframes {nome} nao declara um `from` legivel"
        op = re.search(r"opacity:\s*([\d.]+)", m.group(1))
        assert op, f"@keyframes {nome} nao declara opacidade inicial"
        assert float(op.group(1)) >= 0.3, (
            f"@keyframes {nome} parte de opacity:{op.group(1)} — em aba de segundo plano a "
            f"animacao congela e o conteudo fica invisivel. Lei 1 do estrato v59."
        )
    assert achou, "nenhum @keyframes rv* encontrado — a lei 1 ficou sem nada para provar"


def test_lei_2_so_transform_e_opacidade_sao_animadas():
    """As duas propriedades que o compositor resolve sem repintar. Numa VM de 2 vCPU a 19-29 FPS,
    animar `width`, `top`, `height` ou `filter` em quarenta linhas e o congelamento, nao o efeito.
    """
    proibidas = ("width", "height", "top", "left", "right", "bottom", "margin",
                 "padding", "filter", "box-shadow", "background-position")
    for nome, corpo in re.findall(r"@keyframes\s+(rv\w+)\s*\{(.*?)\}\s*\n", _css(), re.S):
        for prop in proibidas:
            assert not re.search(rf"[{{;\s]{prop}\s*:", corpo), (
                f"@keyframes {nome} anima `{prop}` — so `transform` e `opacity` passam. Lei 2."
            )


@pytest.mark.parametrize("classe", _CLASSES)
def test_lei_3_toda_gramatica_desliga_nos_dois_pisos(classe: str):
    """`prefers-reduced-motion` E `body.fps-baixo`. Um piso so nao e piso: a maquina que cai para
    5 FPS nao declara preferencia nenhuma, e quem declara a preferencia nao tem FPS baixo."""
    texto = _css()
    rm = re.search(r"@media\s*\(prefers-reduced-motion:reduce\)\s*\{(.*?)\n\s*body\.fps-baixo",
                   texto, re.S)
    assert rm, "o bloco dos dois pisos sumiu do estrato v59"
    assert classe in rm.group(1), f".{classe} nao e desligada por prefers-reduced-motion"
    baixo = texto[texto.index("body.fps-baixo"):]
    assert classe in baixo, f".{classe} nao e desligada em body.fps-baixo"


def test_toda_regra_com_rise_compoe_em_vez_de_substituir():
    """A armadilha do v43, que ja deixou o achado mais grave invisivel por treze versoes.

    `.rise` tem `opacity:0` no estado ESTATICO; quem segura o cartao visivel no fim e o `both` da
    propria `rise`. Uma regra que declare `animation:` sobre um seletor com `.rise` e NAO repita a
    `rise ... both` apaga esse `both` — e ao terminar a animacao o cartao cai no zero estatico e
    some, sem erro nenhum no console.
    """
    for regra in re.findall(r"([^{}]*\.rise[^{}]*)\{([^}]*animation:[^}]*)\}", _css()):
        seletor = regra[0].strip()
        # a virgula DENTRO de `cubic-bezier(.2,.9,.25,1)` nao separa animacoes — some com ela
        # antes de olhar a lista, senao o proprio separador vira ruido de parsing.
        corpo = re.sub(r"cubic-bezier\([^)]*\)", "curva", regra[1])
        if "animation:none" in corpo.replace(" ", ""):
            continue          # o desligamento dos pisos e o caso legitimo de substituir por nada
        assert re.search(r"rise\s+[\d.]+s[^,;]*\bboth\b", corpo), (
            f"a regra `{seletor}` declara `animation:` sobre um seletor com `.rise` sem repetir "
            f"`rise ... both` — o cartao vai sumir ao fim da animacao (bug do v43)."
        )


def test_o_motor_e_chamado_pelo_vivo_e_nao_tem_efeito_de_topo():
    """Modulo com efeito de topo roda na ordem do IMPORT, nao na da sequencia de boot — e o
    `painel_efeitos_boot` existe justamente para esse invariante valer no painel inteiro.
    Aqui a checagem e a outra metade: o motor precisa ser CHAMADO por alguem."""
    ui = _UI.read_text(encoding="utf-8")
    assert "from './revelacao.js'" in ui, "ui/index.js nao importa o motor das gramaticas"
    assert re.search(r"revelar\s*\(", ui), "`revelar()` nao e chamada por ninguem em ui/index.js"

    js = _JS.read_text(encoding="utf-8")
    # linha de topo que EXECUTA algo (chamada de funcao fora de declaracao) seria efeito de topo
    for n, linha in enumerate(js.splitlines(), 1):
        if linha[:1] in (" ", "\t", "", "*", "/") or linha.startswith(("import", "export", "const",
                                                                      "let", "var", "function",
                                                                      "}", ")")):
            continue
        pytest.fail(f"{_JS.name}:{n} parece efeito de topo: {linha[:70]!r}")


def test_o_censo_e_exposto_para_a_sonda():
    """`revelacaoCenso()` e a unica forma de PROVAR que a gramatica entrou. Sem ele, a unica
    verificacao possivel seria olhar a tela e acreditar."""
    entrada = (_REPO / "static" / "js" / "src" / "entrada.js").read_text(encoding="utf-8")
    assert "window.revelacaoCenso=revelacaoCenso" in entrada.replace(" ", ""), (
        "o censo das gramaticas nao esta no escopo global — a sonda e o boot_check nao o alcancam"
    )
