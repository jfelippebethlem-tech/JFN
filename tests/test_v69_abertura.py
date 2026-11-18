"""v69 · catraca da abertura em filme (Blender): orçamento por vídeo, as 3 fontes (AV1 → VP9 → H.264) e o pôster de
cada variante, e as garantias do JS — o filme nunca prende o painel (espera de 600 ms e queda para a abertura em
código), movimento reduzido/Save-Data nunca baixam vídeo, e nenhum texto vira pixel (marca e motores em código)."""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
V69 = RAIZ / "static" / "assets" / "v69"
JS = (RAIZ / "static/js/src/cena/abertura.js").read_text(encoding="utf-8")
# orçamento do brief v69: celular ≤ 1,5 MB, desktop ≤ 3 MB (a curta, bem menos)
LIMITE = {"abertura": 3_000_000, "abertura_m": 1_500_000, "abertura_c": 1_000_000, "abertura_c_m": 600_000}
EXTS = (".av1.mp4", ".webm", ".mp4")


def test_cada_variante_tem_as_tres_fontes_e_o_poster():
    for base in LIMITE:
        for e in EXTS + (".webp",):
            assert (V69 / f"{base}{e}").is_file(), f"falta {base}{e}"


def test_orcamento_por_video():
    for p in V69.glob("*"):
        if p.name.endswith((".mp4", ".webm")):
            base = p.name.split(".")[0]
            assert base in LIMITE, f"vídeo fora do inventário da abertura: {p.name}"
            assert p.stat().st_size <= LIMITE[base], f"{p.name}: {p.stat().st_size} B > {LIMITE[base]} B"


def test_js_so_pede_o_que_existe():
    assert "const FILME = '/static/assets/v69/';" in JS
    assert re.search(r"filmeEl\(modo === 'completa' \? 'abertura' : 'abertura_c'", JS)
    assert "(ret ? '_m' : '')" in JS


def test_filme_nunca_prende_o_painel():
    assert "const FILME_ESPERA = {completa: 600, curta: 300};" in JS
    # sem tocar a tempo → abertura em código; e rede de segurança que remove o overlay
    assert "codigo();" in JS and "setTimeout(remover, resta(3.2) + 1400)" in JS
    # a curta só usa filme se já foi pré-carregado; movimento reduzido / Save-Data → 'minima' (sem vídeo)
    assert "modo === 'curta' && curtaOk" in JS
    assert re.search(r"\(_redMotion \|\| eco \|\| [^)]*\) \? 'minima'", JS)
    assert "const comFilme = filmeOk && (modo === 'completa'" in JS


def test_marca_e_motores_continuam_em_codigo():
    assert "marcaSvg()" in JS and "motores($('.ab-m-t')" in JS
