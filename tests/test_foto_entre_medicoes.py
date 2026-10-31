"""Mesma foto em medições de PERÍODOS diferentes do mesmo contrato (INEA 35/2023, Geo Ambiental, 27/09/2026)."""
import json
import random

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
