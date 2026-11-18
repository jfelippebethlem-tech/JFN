"""v68 · catraca dos vídeos gerados no it-campo: orçamento por vídeo, as 3 fontes (AV1 → VP9 → H.264) de cada
variante e o que o JS pede existir no disco. Vídeo acima do orçamento atrasa o painel no celular; fonte faltando
cai no fallback errado (ou no canvas) sem erro visível."""
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
V68 = RAIZ / "static" / "assets" / "v68"
CELULAR, DESKTOP = 2_500_000, 5_000_000
# exceção medida (v68): o voo da galáxia tem milhares de fios finos em movimento — a 5 MB o AV1 borra os fios
# (CRF 44 medido). Overlay só na 1ª visita do dia em /galaxia, pulável; H.264 dele a 30 fps.
EXCECAO = {"galaxia3d": 9_000_000, "galaxia3d_m": 5_500_000}
EXTS = (".av1.mp4", ".webm", ".mp4")


def _bases():
    return sorted({p.name.split(".")[0] for p in V68.glob("*.mp4")})


def test_cada_variante_tem_as_tres_fontes():
    assert _bases(), "static/assets/v68 sem vídeos"
    for b in _bases():
        for e in EXTS:
            assert (V68 / f"{b}{e}").is_file(), f"falta {b}{e}"


def test_orcamento_por_video():
    for p in V68.glob("*.*"):
        if not p.name.endswith((".mp4", ".webm")):
            continue
        base = p.name.split(".")[0]
        lim = EXCECAO.get(base) or (CELULAR if base.endswith("_m") else DESKTOP)
        assert p.stat().st_size <= lim, f"{p.name}: {p.stat().st_size} B > {lim} B"


def test_fundo_aponta_para_v68_e_mantem_os_pôsteres_do_v65():
    js = (RAIZ / "static/js/src/v63/fundo.js").read_text(encoding="utf-8")
    assert "'/static/assets/' + (_60 ? 'v68' : 'v65')" in js
    for c in ("hero", "secao1", "secao2"):
        for s in ("", "_m"):
            assert (RAIZ / f"static/assets/v65/fluxo_{c}{s}.webp").is_file()
            assert (RAIZ / f"static/assets/v65/fluxo_{c}{s}.av1.mp4").is_file(), "fallback de 24 fps sumiu"


def test_cine3d_meta_e_pôsteres():
    meta = json.loads((V68 / "cine3d.json").read_text(encoding="utf-8"))
    assert meta["mapa3d"]["metrica"] == "valor_contratado"
    assert meta["mapa3d"]["com_contrato"] + meta["mapa3d"]["sem_contrato_atribuido"] == meta["mapa3d"]["municipios"]
    for nome in ("mapa3d", "galaxia3d"):
        if not (V68 / f"{nome}.mp4").exists():
            continue                                  # cena ainda não publicada
        for s in ("", "_m"):
            assert (V68 / f"{nome}{s}.webp").is_file(), f"pôster {nome}{s}.webp"


def test_js_so_pede_arquivo_que_existe():
    js = (RAIZ / "static/js/src/cena/cine3d.js").read_text(encoding="utf-8")
    nomes = set(re.findall(r"cineVideo\('([a-z0-9]+)'", "".join(
        p.read_text(encoding="utf-8") for p in (RAIZ / "static/js").rglob("*.js")
        if "bundle" not in p.name)))
    assert "BASE = '/static/assets/v68/'" in js
    for n in nomes:
        for s in ("", "_m"):
            for e in EXTS:
                assert (V68 / f"{n}{s}{e}").is_file(), f"JS pede {n}{s}{e}, que não existe"
