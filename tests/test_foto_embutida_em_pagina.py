"""A medição de obra chega como RELATÓRIO FOTOGRÁFICO: a foto vem DENTRO da página.

Antes desta correção o detector de reciclagem gerava hash do arquivo, então comparava o MODELO
da página e não a foto — falso negativo (mesma foto em páginas diferentes não casava) e falso
positivo (páginas do mesmo modelo com fotos diferentes casavam). Estes testes travam os dois.
"""
from pathlib import Path

import pytest

from compliance_agent import foto_medicao as fm

PIL = pytest.importorskip("PIL.Image")


def _foto(seed: int, lado: int = 400):
    """Bloco pseudo-fotográfico: colorido, com textura — passa no filtro de 'não é documento'."""
    im = PIL.new("RGB", (lado, lado))
    px = im.load()
    for y in range(lado):
        for x in range(lado):
            px[x, y] = ((x * 7 + y * 3 + seed * 53) % 256,
                        (y * 5 + seed * 31) % 256,
                        (x * 3 + seed * 17) % 200 + 55)
    return im


def _pagina_relatorio(seeds):
    """Página branca com cabeçalho de texto e as fotos embutidas, como o relatório real."""
    larg, alt = 850, 300 + 460 * len(seeds)
    pg = PIL.new("RGB", (larg, alt), (255, 255, 255))
    for i, s in enumerate(seeds):
        pg.paste(_foto(s).resize((700, 400)), (75, 220 + 460 * i))
    return pg


def test_pagina_de_relatorio_rende_um_hash_por_foto(tmp_path):
    p = tmp_path / "relatorio.jpg"
    _pagina_relatorio([1, 2]).save(p, quality=92)
    hs = fm._triar_e_hashear(p)
    assert len(hs) == 2, f"esperava 1 hash por foto embutida, veio {len(hs)}"
    assert hs[0] != hs[1], "as duas fotos são diferentes — não podem colidir"


def test_foto_solta_continua_rendendo_um_hash(tmp_path):
    """Não-regressão: imagem que já É a fotografia não pode ser recortada."""
    p = tmp_path / "solta.jpg"
    _foto(1, 600).save(p, quality=92)
    assert len(fm._triar_e_hashear(p)) == 1


def test_mesma_foto_solta_e_embutida_casa(tmp_path):
    """O falso NEGATIVO que a correção elimina: a mesma foto reaproveitada, uma solta e outra
    dentro de uma página de relatório, tem de cair no mesmo grupo."""
    solta = tmp_path / "a" / "fotos"
    pagina = tmp_path / "b" / "fotos"
    solta.mkdir(parents=True)
    pagina.mkdir(parents=True)
    _foto(1).resize((700, 400)).save(solta / "obra.jpg", quality=92)
    _pagina_relatorio([1]).save(pagina / "medicao.jpg", quality=92)

    r = fm.reciclagem([tmp_path / "a", tmp_path / "b"])
    assert r["n_grupos"] >= 1, "a mesma foto em dois processos tem de formar grupo"
    procs = {o["processo"] for g in r["grupos"] for o in g["ocorrencias"]}
    assert {"a", "b"} <= procs, f"grupo não uniu os dois processos: {procs}"


def test_paginas_do_mesmo_modelo_com_fotos_diferentes_nao_casam(tmp_path):
    """O falso POSITIVO que a correção elimina: mesmo cabeçalho, mesmo enquadramento, fotos
    DIFERENTES — não é reciclagem."""
    for nome, seed in (("a", 1), ("b", 2)):
        d = tmp_path / nome / "fotos"
        d.mkdir(parents=True)
        _pagina_relatorio([seed]).save(d / "medicao.jpg", quality=92)

    r = fm.reciclagem([tmp_path / "a", tmp_path / "b"])
    assert r["n_grupos"] == 0, f"acusou reciclagem de MODELO de página: {r['grupos']}"


def test_papel_amarelado_fica_fora_do_indice(tmp_path):
    """O falso positivo REAL que a varredura do acervo produziu: duas folhas de ponto do HEGV,
    escaneadas em papel bege, viraram um par de 'reciclagem'. Papel bege tem saturação ~39 e
    escapava do corte por saturação, que só pega documento CINZA."""
    p = tmp_path / "folha.jpg"
    pg = PIL.new("RGB", (600, 800), (222, 216, 198))       # bege, como papel envelhecido
    px = pg.load()
    for i in range(40):                                     # linhas e escrita: dá desvio suficiente
        for x in range(60, 540):
            px[x, 80 + i * 17] = (40, 40, 90)
    pg.save(p, quality=92)
    assert fm._triar_e_hashear(p) == [], "papel bege entrou no índice de reciclagem"


_REAL = Path("data/sei_arquivo/070002_005897_2024/fotos/023_p29.jpg")


@pytest.mark.skipif(not _REAL.exists(), reason="acervo SEI não presente nesta máquina")
def test_relatorio_fotografico_real_do_inea():
    """Dado real: RELATÓRIO FOTOGRÁFICO – 7ª MEDIÇÃO, contrato 35/2023, INEA/DIRRAM, Iguaba
    Grande. Duas fotos na página; o comportamento antigo devolvia um hash do layout."""
    hs = fm._triar_e_hashear(_REAL)
    assert len(hs) == 2
    assert fm.distancia(hs[0], hs[1]) > fm.LIMIAR_IGUAL, "são fotos distintas na mesma página"
