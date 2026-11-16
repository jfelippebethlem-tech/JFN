"""VIDRO + JARVIS (16/11/2026) obedecem as leis da casa — provado no arquivo.

O estrato `99z2-v61-95-vidro.css` (vidro ajustável) e o `99z2-v61-96-jarvis.css` (vida contínua e
coreografia por família de aba) mexem em DUAS coisas que ja derrubaram este painel: animacao de
entrada (o KPI que sumia, v43; a tela em branco em aba oculta) e `backdrop-filter` (o ReadPixels por
quadro, v50). Estes testes cobram as mesmas leis do `test_painel_revelacao.py` e as tres quedas do
`test_painel_modo_sobrio_para_os_canvas.py` sobre os estratos novos — que aqueles testes nao leem.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "static" / "css" / "src"
_VIDRO = _SRC / "99z2-v61-95-vidro.css"
_JARVIS = _SRC / "99z2-v61-96-jarvis.css"
_JS = _REPO / "static" / "js" / "src"

# Adornos: nao sao conteudo, podem partir do zero (a linha de varredura, a onda do clique, o
# reflexo, o anel que gira e a particula). Nenhum deles carrega dado.
_ADORNOS = {"jvScan", "jvOnda", "jvBrilho", "jvGira", "jvDeriva"}
_PROIBIDAS = ("width", "height", "top", "left", "right", "bottom", "margin", "padding", "filter",
              "box-shadow", "background-position", "clip-path", "background")


def _keyframes(texto: str) -> list[tuple[str, str]]:
    return re.findall(r"@keyframes\s+(\w+)\s*\{(.*?)\}\s*\n", texto)


@pytest.mark.parametrize("arq", [_VIDRO, _JARVIS])
def test_estrato_existe_e_entra_na_concatenacao(arq: Path):
    from tools.painel_css_cortar import juntar

    assert arq.is_file(), f"{arq.name} sumiu"
    marca = "--vidro-blur" if arq == _VIDRO else "jvHolo"
    assert marca in juntar(), f"{arq.name} nao entrou na concatenacao do painel.css"


def test_lei_1_entrada_de_conteudo_nunca_parte_de_opacidade_baixa():
    achou = 0
    for nome, corpo in _keyframes(_JARVIS.read_text(encoding="utf-8")):
        if nome in _ADORNOS:
            continue
        achou += 1
        m = re.search(r"from\s*\{([^}]*)\}", corpo + "}")
        assert m, f"@keyframes {nome} sem `from` legivel"
        op = re.search(r"opacity:\s*([\d.]+)", m.group(1))
        assert op and float(op.group(1)) >= 0.3, f"@keyframes {nome} parte de opacidade < .3 (lei 1)"
    assert achou >= 5, "as cinco coreografias (holo, grade x2, pulso, fluxo, lado) sumiram"


@pytest.mark.parametrize("arq", [_VIDRO, _JARVIS])
def test_lei_2_so_transform_e_opacidade(arq: Path):
    for nome, corpo in _keyframes(arq.read_text(encoding="utf-8")):
        for prop in _PROIBIDAS:
            assert not re.search(rf"[{{;\s]{prop}\s*:", corpo), f"@keyframes {nome} anima `{prop}` (lei 2)"


def test_entrada_nunca_segura_o_estado_final():
    """`both`/`forwards` numa entrada deixa transform em efeito: vira bloco de contencao de fixed."""
    texto = _JARVIS.read_text(encoding="utf-8")
    regra = re.search(r"\.fade \.jv-c\{([^}]*)\}", texto).group(1)
    assert "animation-fill-mode:backwards" in regra.replace(" ", "")


@pytest.mark.parametrize("piso", ["reduced", "sobrio"])
@pytest.mark.parametrize("alvo", [".jv-c", ".jv-scan", ".jv-onda", ".jv-brilho", "#jv-part", ".jv-hud b"])
def test_lei_3_tudo_desliga_nos_dois_pisos(piso: str, alvo: str):
    texto = _JARVIS.read_text(encoding="utf-8")
    i = texto.index("OS DOIS PISOS")
    bloco = texto[i:]
    if piso == "reduced":
        m = re.search(r"@media \(prefers-reduced-motion:reduce\)\{(.*?)\n\}", bloco, re.S)
        assert m and alvo in m.group(1), f"{alvo} nao desliga com prefers-reduced-motion"
    else:
        linhas = [ln for ln in bloco.splitlines() if ln.startswith("html.v61 body.fps-baixo")]
        assert any(alvo in ln for ln in linhas), f"{alvo} nao desliga no modo sobrio"


def test_vidro_tres_quedas():
    texto = _VIDRO.read_text(encoding="utf-8")
    s = texto.replace(" ", "")
    # 1 · sobrio: superficie opaca + sem desfoque nos pseudo/fixos que o `*` da casa nao alcanca
    assert "body.fps-baixo{--surface:rgba(255,255,255,.96)}" in s
    assert re.search(r"body\.fps-baixo\.wrap>header::before[^{]*\{backdrop-filter:none", s)
    # 2 · celular: a capsula e o desfoque derivado so existem em min-width (>= 821, a regra opaca da v50 e <= 820)
    cap = texto.index("html.v61 .wrap > header::before{")
    assert "@media (min-width:821px)" in texto[:cap][-2500:], "capsula do cabecalho fora do min-width"
    assert re.search(r"@media \(min-width:821px\)\{\s*html\.v61 body\{--blur:", texto)
    # 3 · transparencia reduzida
    assert "prefers-reduced-transparency:reduce" in texto


def test_limites_do_controle_batem_com_o_css():
    """O minimo de opacidade e o maximo de tinta sao limites de LEGIBILIDADE medidos."""
    js = (_JS / "ui" / "vidro.js").read_text(encoding="utf-8")
    assert re.search(r"\['alfa',\s*'Opacidade',\s*\.40,", js)
    assert re.search(r"\['tinta',\s*'Tinta azul',\s*0,\s*\.12,", js)
    assert "try { o = JSON.parse(localStorage" in js and "try { localStorage.setItem" in js


def test_pintar_marca_familia_e_aba_no_fade():
    entrada = (_JS / "entrada.js").read_text(encoding="utf-8")
    assert 'class="fade" data-esf="${esfera}" data-aba="${id}" data-fam="${_fam}"' in entrada
    rev = (_JS / "ui" / "revelacao.js").read_text(encoding="utf-8")
    assert "censo.coreo = _coreografia(v)" in rev
    assert "_primeiros(" in rev[rev.index("function _coreografia"):], "a gramatica 7 perdeu o teto de nos"


@pytest.mark.parametrize("fam,esf,aba", [("holo", "inicio", "i_cockpit"), ("holo", "sistema", "s_motores"),
                                         ("pulso", "estado", "e_pericias"), ("pulso", "geral", "g_casos"),
                                         ("pulso", "estado", "e_alertas"), ("grade", "estado", "e_siafe"),
                                         ("grade", "estado", "e_orcorg"), ("fluxo", "geral", "g_vinculos")])
def test_familia_da_aba(fam, esf, aba):
    """Espelho em Python das duas regex de `familiaDaAba` — se o JS mudar, este teste aponta."""
    rev = (_JS / "ui" / "revelacao.js").read_text(encoding="utf-8")
    pulso = re.search(r"_FAM_PULSO = /(.*?)/;", rev).group(1)
    grade = re.search(r"_FAM_GRADE = /(.*?)/;", rev).group(1)
    got = ("holo" if esf in ("inicio", "sistema") else "pulso" if re.search(pulso, aba)
           else "grade" if re.search(grade, aba) else "fluxo")
    assert got == fam
