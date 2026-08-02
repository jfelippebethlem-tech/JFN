# -*- coding: utf-8 -*-
"""O modo sóbrio media a máquina, recuava — e deixava os dois laços de canvas a custo cheio.

Medido em 31/07/2026, com o painel renderizado de verdade (Playwright, desktop e mobile). O canto
do cabeçalho anunciava `modo sóbrio · 0 fps`, ou seja: `_medirFps` mediu, concluiu que a máquina não
sustenta animação e ligou `body.fps-baixo`. Só que a regra do modo sóbrio aplica
`animation:none !important` — isso mata `@keyframes` de CSS e **não toca em
`requestAnimationFrame`**.

`#rjbg` e `#netbg` sao canvas de tela cheia desenhados por JS a cada quadro. O `netbg` e O(n²):
ate 76 pontos, ~2.900 calculos de distancia e tracos por quadro, em devicePixelRatio ate 2. Os dois
continuavam rodando depois do recuo — o painel media o orcamento, dizia "nao cabe", e gastava
igual. O proprio comentario do bloco diz: *"em 2 vCPU, e o orcamento inteiro"*.

O padrao de parada JA existia no arquivo para `prefers-reduced-motion`
(`if(!rm)raf=requestAnimationFrame(draw)`); faltava o mesmo eixo para a capacidade MEDIDA. Sao
eixos diferentes de proposito: um e preferencia declarada, o outro e a maquina de hoje.

Junto vai o `backdrop-filter`: sao 10 declaracoes, e blur de fundo obriga o navegador a LER DE VOLTA
o framebuffer (`GPU stall due to ReadPixels`, visto no console das duas viewports) sobre canvas que
repintam por quadro. Desligar o blur sem tornar a superficie opaca seria pior: `--glass` e 76%
opaco, entao 24% do conteudo apareceria NITIDO atraves do cabecalho — que e exatamente o texto
embolado que aparece no topo da captura mobile. Por isso as duas coisas andam no mesmo commit.
"""
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
CSS = (_RAIZ / "static" / "css" / "painel.css").read_text(encoding="utf-8")


def _js() -> str:
    """O fonte do painel — monolito ou modulos, o que existir.

    v58: `static/js/painel.js` virou `static/js/src/**`. Le-se o FONTE, nunca o bundle: o bundle e
    derivado, e validar o derivado esconderia o caso "editei o fonte e nao reconstrui".
    """
    src = _RAIZ / "static" / "js" / "src"
    if src.is_dir():
        return "\n".join(p.read_text(encoding="utf-8") for p in sorted(src.rglob("*.js")))
    return (_RAIZ / "static" / "js" / "painel.js").read_text(encoding="utf-8")


JS = _js()


def _corpo(nome: str) -> str:
    """Corpo da função, do `function nome(` até a próxima função de topo.

    Aceita `export function` porque, com a quebra em modulos, e assim que estas funcoes passam a
    ser declaradas — e um teste que so reconhece a forma antiga para de proteger em silencio.
    """
    i = JS.find(f"function {nome}(")
    assert i >= 0, f"nao achei `function {nome}(` no fonte do painel"
    j = min((k for k in (JS.find("\nfunction ", i + 1),
                         JS.find("\nexport function ", i + 1)) if k > 0), default=-1)
    return JS[i: j if j > 0 else len(JS)]


def test_os_dois_lacos_de_canvas_consultam_o_modo_sobrio():
    """`netbg` e `rjbg` precisam parar de agendar quadro quando a máquina não aguenta."""
    for laco in ("netbgStart", "rjbgStart"):
        assert "_sobrio" in _corpo(laco), (
            f"{laco} nao consulta o modo sobrio — segue desenhando por quadro depois do recuo")


def test_o_reagendamento_principal_esta_guardado_nos_dois():
    """O ponto exato do defeito: era `raf=requestAnimationFrame(draw)` sem condição nenhuma."""
    for laco in ("netbgStart", "rjbgStart"):
        corpo = _corpo(laco).replace(" ", "")
        assert "if(!_sobrio)raf=requestAnimationFrame(draw)" in corpo \
            or "if(!rm&&!_sobrio)raf=requestAnimationFrame(draw)" in corpo, (
                f"{laco} ainda reagenda quadro sem consultar o modo sobrio")


def test_o_recuo_liga_a_classe_do_css_E_avisa_o_js():
    """Não basta pôr a classe no body: o JS precisa saber, senão só o CSS recua.

    Deliberadamente NÃO amarra a forma da chamada. A 1ª versão deste teste exigia
    `classList.add('fps-baixo')` e ficou vermelha quando o recuo virou `_sobrioAplicar(lig, fps)`
    com `classList.toggle(...)` — uma evolução que também passou a pausar os vídeos da nebulosa, do
    núcleo e do holograma. O código melhorou e o teste é que estava velho. O que importa travar é a
    PROPRIEDADE: os dois eixos (CSS e JS) mudam juntos.
    """
    sem_espaco = JS.replace(" ", "")
    assert "classList.toggle('fps-baixo'" in sem_espaco or "classList.add('fps-baixo')" in sem_espaco, (
        "ninguém mais aplica a classe fps-baixo no body — o CSS do modo sóbrio virou letra morta")
    assert "_sobrio=lig" in sem_espaco or "_sobrio=true" in sem_espaco, (
        "a classe do CSS é aplicada mas o JS não é avisado — os canvas seguem a custo cheio")


def test_o_flag_do_sobrio_nasce_desligado_no_topo():
    """TDZ ja matou o boot deste painel uma vez: o flag vive no topo, como `_redMotion`."""
    assert "_sobrio" in JS[:JS.index("function netbgStart(")], "_sobrio precisa ser declarado ANTES do uso"


def test_visibilitychange_nao_ressuscita_o_laco_no_modo_sobrio():
    """Voltar para a aba repinta, mas não pode reacender o laço que o recuo desligou.

    Os dois resolvem isso de formas diferentes e ambas valem: o `netbg` guarda no próprio handler
    (não chama `draw`), o `rjbg` chama `draw` de propósito — para repintar o quadro estático — e
    quem segura é o `if(!_sobrio)` de dentro do `draw`. O que este teste proíbe é o handler existir
    SEM nenhuma das duas proteções.
    """
    for laco in ("netbgStart", "rjbgStart"):
        corpo = _corpo(laco)
        assert "visibilitychange" in corpo, f"{laco} perdeu o tratamento de visibilitychange"
        j = corpo.index("visibilitychange")
        guardado_no_handler = "_sobrio" in corpo[j:j + 220]
        guardado_no_draw = "if(!_sobrio)raf=requestAnimationFrame(draw)" in corpo.replace(" ", "")
        assert guardado_no_handler or guardado_no_draw, (
            f"{laco} reacende o laco ao voltar para a aba, mesmo em modo sobrio")


def test_modo_sobrio_desliga_o_backdrop_filter():
    """O blur de fundo forca ReadPixels por quadro — no recuo ele sai."""
    assert "body.fps-baixo" in CSS
    bloco = CSS[CSS.index("body.fps-baixo #hologrid"):]
    assert "backdrop-filter:none" in bloco.replace(" ", ""), (
        "o modo sobrio nao desliga backdrop-filter — o ReadPixels continua a cada quadro")


def test_superficie_fica_opaca_quando_o_blur_sai():
    """Sem blur, `--glass` (76%) deixaria o conteudo aparecer NITIDO atraves do cabecalho."""
    bloco = CSS[CSS.index("body.fps-baixo #hologrid"):]
    assert "var(--bg2)" in bloco, (
        "desligou o blur sem tornar a superficie opaca — o texto de tras vaza pelo cabecalho")


def test_cabecalho_do_celular_e_opaco():
    """Na captura mobile o conteudo aparecia embolado atras da barra fixa: la o vidro nao vale."""
    assert "--painel-topo-opaco" in CSS, (
        "falta a regra que torna o cabecalho opaco na viewport estreita")


def test_precedente_do_reduced_transparency_continua_valendo():
    """Guarda-costas: a regra que ja existia para transparencia reduzida nao pode ter sumido."""
    assert "prefers-reduced-transparency" in CSS
