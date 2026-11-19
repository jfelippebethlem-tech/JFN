"""3ª assinatura (fina, 48×48 com tolerância a deslocamento) — 18/11/2026, varredura do acervo inteiro.

Falso positivo que ensinou: relatório socioambiental do INEA (070002_005874_2024, "Limpa Rios") com FUNDO de imagem
esmaecida. Sem fundo branco o recorte de foto (`_regioes_foto`) devolve a faixa inteira: CABEÇALHO grande da página
+ fotos pequenas. Na miniatura 16×16 o cabeçalho domina e páginas com fotos DIFERENTES confirmavam (grupos #862,
#864); o mesmo com páginas de TEXTO sobre a marca d'água (#519). Medido: mesma foto recortada de páginas diferentes
≤ 0,062 de células divergentes; cabeçalho + fotos diferentes 0,26–0,28; texto diferente 0,30.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from PIL import Image, ImageDraw

from compliance_agent import foto_medicao as FM


def _cena(semente: int, tamanho=(300, 200)) -> Image.Image:
    random.seed(semente)
    im = Image.new("RGB", tamanho, (150, 170, 200))
    d = ImageDraw.Draw(im)
    w, h = tamanho
    for _ in range(18):                                          # manchas grandes: foto real é suave, não ruído
        x, y = random.randint(0, w), random.randint(0, h)
        c = random.randint(30, 200)
        d.ellipse([x, y, x + w // 4, y + h // 3], fill=(c, c - 20 if c > 20 else c, 60))
    return im


_ARQ = Path("data/sei_arquivo")
_INEA = _ARQ / "070002_005874_2024" / "fotos"
_GEO = _ARQ / "070002_005897_2024" / "fotos"
_reais = pytest.mark.skipif(not (_INEA / "285_p48.jpg").exists() or not (_GEO / "140_p26.jpg").exists(),
                            reason="acervo SEI não presente nesta máquina")


def _sigs(arq: Path) -> list:
    with Image.open(arq) as im:
        im.load()
        return [FM._assinatura_da_imagem(a) for a in ([im.crop(c) for c in FM._regioes_foto(im)] or [im])]


@_reais
def test_cabecalho_igual_com_fotos_diferentes_nao_confirma():
    """#862: faixa de cabeçalho "inea / Limpa Rios" + fotos DIFERENTES (33ª medição, partes II e IV)."""
    a, b = _sigs(_INEA / "285_p48.jpg")[0], _sigs(_INEA / "287_p34.jpg")[0]
    assert FM._confirma(a[:2], b[:2])                   # a 2ª assinatura sozinha confirmava (o defeito)
    assert not FM._confirma(a, b)


@_reais
def test_paginas_de_texto_sobre_marca_dagua_nao_confirmam():
    """#519: duas páginas de TEXTO diferentes do relatório socioambiental, com a mesma marca d'água de fundo."""
    a, b = _sigs(_INEA / "260_p05.jpg")[0], _sigs(_INEA / "260_p06.jpg")[0]
    assert not FM._confirma(a, b)


@_reais
def test_controle_positivo_geo_ambiental_segue_confirmando():
    """A mesma foto do trator na 11ª (jun–jul/2024) e na 16ª medição (nov–dez/2024) — caso real, tem de continuar."""
    A, B = _sigs(_GEO / "140_p26.jpg"), _sigs(_GEO / "269_p17.jpg")
    assert any(FM._confirma(a, b) for a in A for b in B)


def test_mesma_foto_recortada_com_deslocamento_confirma():
    base = _cena(7, (640, 420))
    a = base.crop((0, 0, 620, 410))
    b = base.crop((8, 5, 628, 415))                             # recorte da mesma foto noutra página: ~1,3% de folga
    assert FM._confirma(FM._assinatura_da_imagem(a), FM._assinatura_da_imagem(b))


def test_mesma_foto_recomprimida_confirma(tmp_path):
    base = _cena(9, (640, 420))
    base.save(tmp_path / "a.jpg", quality=92)
    base.resize((480, 315)).save(tmp_path / "b.jpg", quality=60)
    a, b = Image.open(tmp_path / "a.jpg"), Image.open(tmp_path / "b.jpg")
    assert FM._confirma(FM._assinatura_da_imagem(a), FM._assinatura_da_imagem(b))


def test_assinatura_antiga_sem_fina_segue_valendo():
    """Índice gravado antes da 3ª assinatura (2 elementos) não quebra a confirmação."""
    s = FM._assinatura_da_imagem(_cena(3))
    assert FM._confirma(s[:2], s[:2])
