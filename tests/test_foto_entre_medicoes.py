"""Mesma foto em medições de PERÍODOS diferentes do mesmo contrato (INEA 35/2023, Geo Ambiental, 27/09/2026)."""
import json
import random
from pathlib import Path

import pytest

from PIL import Image, ImageDraw

from compliance_agent import foto_medicao as FM


def _campo(path, semente=1):
    """Foto de campo: céu claro e liso no alto, terreno texturizado embaixo."""
    random.seed(semente)
    img = Image.new("RGB", (640, 480), (190, 205, 225))
    d = ImageDraw.Draw(img)
    for _ in range(900):
        x, y = random.randint(0, 639), random.randint(140, 479)
        c = random.randint(40, 160)
        d.rectangle([x, y, x + 12, y + 8], fill=(c, c - 20, c - 40))
    d.rectangle([220, 180, 420, 300], fill=(230, 180, 20))      # "máquina"
    img.save(path, quality=92)


def _mapa(path):
    """Satélite: textura no quadro inteiro, topo escuro/verde, sem céu."""
    random.seed(7)
    img = Image.new("RGB", (640, 480), (50, 80, 60))
    d = ImageDraw.Draw(img)
    for _ in range(2500):
        x, y = random.randint(0, 639), random.randint(0, 479)
        c = random.randint(30, 140)
        d.rectangle([x, y, x + 10, y + 10], fill=(c - 10, c, c - 20))
    img.save(path, quality=92)


def _processo(tmp_path, arquivos):
    d = tmp_path / "070002_005897_2024"
    (d / "fotos").mkdir(parents=True)
    docs = [{"i": "190", "titulo": "Relatório Fotográfico - 13ª Medição (1)", "fotos": []},
            {"i": "647", "titulo": "Relatório Fotográfico - 31ª Medição (2)", "fotos": []}]
    (d / "manifest.json").write_text(json.dumps({"docs": docs}), encoding="utf-8")
    for nome, fn in arquivos:
        fn(d / "fotos" / nome)
    return d


def test_mesma_foto_de_campo_em_medicoes_diferentes_acende(tmp_path):
    d = _processo(tmp_path, [("190_p26.jpg", _campo), ("647_p14.jpg", _campo)])
    r = FM.reciclagem_entre_medicoes(d)
    assert r["grau"] == "vermelho" and r["grupos"][0]["medicoes"] == [13, 31]


def test_mapa_de_satelite_repetido_nao_acende(tmp_path):
    d = _processo(tmp_path, [("190_p09.jpg", _mapa), ("647_p09.jpg", _mapa)])
    assert FM.parece_mapa(Image.open(d / "fotos" / "190_p09.jpg"))
    assert FM.reciclagem_entre_medicoes(d)["grupos"] == []


def test_fotos_diferentes_nao_confirmam(tmp_path):
    d = _processo(tmp_path, [("190_p26.jpg", lambda p: _campo(p, 1)), ("647_p14.jpg", lambda p: _campo(p, 2))])
    assert FM.reciclagem_entre_medicoes(d)["grupos"] == []


def _faixa(fotos, gap=24):
    """Faixa de fotos lado a lado com vão branco, como o recorte de `_regioes_foto` devolve uma linha de 3 fotos."""
    w = sum(f.size[0] for f in fotos) + gap * (len(fotos) - 1)
    h = max(f.size[1] for f in fotos)
    im = Image.new("RGB", (w, h), (255, 255, 255))
    x = 0
    for f in fotos:
        im.paste(f, (x, 0))
        x += f.size[0] + gap
    return im


_FAIXAS_REAIS = [("data/sei_arquivo/070002_006481_2024/fotos/107_p04.jpg", (52, 450, 1235, 738)),
                 ("data/sei_arquivo/020001_000685_2024/fotos/039_p08.jpg", (58, 358, 1177, 640))]


@pytest.mark.skipif(not all(Path(a).exists() for a, _ in _FAIXAS_REAIS), reason="acervo SEI não presente nesta máquina")
def test_faixa_real_de_fotos_de_campo_nao_e_mapa():
    """18/11/2026, sorteio de 8 grupos 'sem céu' do acervo: 6 eram FOTOS DE OBRA. Duas eram faixas de 3 fotos com céu
    (INEA 30ª medição; SEAPPA) que o vão branco entre as fotos fazia parecer 'topo texturizado' = mapa."""
    for arq, caixa in _FAIXAS_REAIS:
        faixa = Image.open(arq).crop(caixa)
        assert FM._parece_mapa_uma(faixa)          # o defeito: a faixa inteira lida como uma imagem
        assert len(FM._sub_fotos(faixa)) == 3
        assert not FM.parece_mapa(faixa)


def test_faixa_de_mapas_continua_mapa(tmp_path):
    _mapa(tmp_path / "m.jpg")
    m = Image.open(tmp_path / "m.jpg").resize((320, 240))
    assert FM.parece_mapa(_faixa([m, m, m]))
