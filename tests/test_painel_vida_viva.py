"""Guarda-corpo do v36-v38: a faceta com sentido, a nebulosa viva e o corpo do no.

Nao roda navegador — le o HTML e garante que a fiacao dos tres recursos continua
inteira: o JS que poe o sentido, o CSS que gira a faceta, o encaixe progressivo
do video e do anel (que so ligam quando o arquivo existe) e as saidas de
prefers-reduced-motion. Custa milissegundos e vale na VM-2.
"""

from pathlib import Path

# v49: o CSS (178 KB) e o JS (337 KB) sairam de dentro do HTML para `static/css/painel.css` e
# `static/js/painel.js`, servidos com gzip e cache — o HTML ficou em ~3 KB de casca. Este arquivo
# lia so o HTML e passou a nao achar NADA: cinco testes vermelhos de uma vez, todos pela mesma
# causa. `HTML` agora e a superficie INTEIRA do painel (casca + CSS + JS), que e o que estes testes
# sempre quiseram olhar. Terceiro leitor a ser reapontado, depois de `test_painel_css_integro` e
# `tools/painel_abas` — e o unico que eu tinha DEIXADO PASSAR: quem o pegou foi a rodada completa
# dos quatro lotes da suite, nao o lote 1 sozinho.
_RAIZ = Path(__file__).resolve().parents[1]

# v58: quarto reapontamento deste mesmo leitor, agora que `painel.js` virou `src/` + bundle. A
# resolucao passou a morar em `tests/superficie.fonte_do_painel()`, que le a casca + o CSS + o
# JS-FONTE (nunca o bundle, que duplicaria o texto e quebraria as assercoes de contagem daqui).
from tests.superficie import fonte_do_painel  # noqa: E402

HTML = fonte_do_painel()


def test_faceta_tem_sentido():
    """v36: ir() poe data-nav-dir e o CSS gira para o lado certo."""
    assert "data-nav-dir" in HTML, "o atributo de sentido sumiu do painel"
    assert HTML.count("setAttribute('data-nav-dir'") == 1, "quem poe o sentido e o ir(), uma vez so"
    for kf in ("facetaSaiFwd", "facetaChegaFwd", "facetaSaiBack", "facetaChegaBack"):
        assert f"@keyframes {kf}" in HTML, f"keyframe {kf} sumiu — a faceta perdeu um dos sentidos"
    assert ':root[data-nav-dir="fwd"]::view-transition-new(jfn-miolo)' in HTML
    assert ':root[data-nav-dir="back"]::view-transition-new(jfn-miolo)' in HTML


def test_faceta_nunca_entra_menor():
    """Lei do alvo de clique: o quadro que ENTRA parte de escala >= 1."""
    for kf in ("facetaChegaFwd", "facetaChegaBack"):
        ini = HTML.split(f"@keyframes {kf}")[1].split("to{")[0]
        assert "scale(1.014)" in ini and "scale(.9" not in ini and "scale(0" not in ini, (
            f"{kf} passou a entrar menor que 1 — quebra a regra sem excecao do painel"
        )


def test_nebulosa_viva_e_progressiva():
    """v37: video da esfera so liga se o mp4 responder 200; JPG segue de poster."""
    assert "function nebulaViva" in HTML
    assert "nebulaViva==='function'" in HTML, "ir() deixou de chamar nebulaViva na troca de esfera"
    assert "#esfnebula video" in HTML, "o CSS do encaixe do video sumiu"
    assert "{method:'HEAD'}" in HTML, "a checagem de existencia (HEAD) sumiu — 404 viraria erro"


def test_no_ganha_corpo_so_com_arte():
    """v38: o anel usinado do no so entra com body.art-no (posto se o PNG existe)."""
    assert "body.art-no .nu-chip::after" in HTML
    assert "no-energia.png" in HTML
    assert "classList.add('art-no')" in HTML


def test_reduced_motion_cobre_o_novo():
    """Toda animacao nova tem saida: quem pede menos movimento recebe menos."""
    juntos = "".join(HTML.split("prefers-reduced-motion:reduce")[1:])
    assert ":root[data-nav-dir]::view-transition-old(jfn-miolo)" in juntos, (
        "a faceta v36 nao respeita prefers-reduced-motion"
    )
    assert "#esfnebula video{display:none}" in juntos, (
        "o video da nebulosa nao respeita prefers-reduced-motion"
    )
    assert "body.art-no .nu-chip::after{animation:none}" in juntos, (
        "o pulso do no v38 nao respeita prefers-reduced-motion"
    )
