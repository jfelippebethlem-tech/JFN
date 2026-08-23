# -*- coding: utf-8 -*-
"""Pipeline íntegra→arquivo compacto (tools/sei_arquivar.py). Offline:
constrói uma 'íntegra' sintética (PDF textual + relatório fotográfico com
imagem) e verifica: txt por documento, fotos preservadas em JPEG, manifest
com fase por doc, linha do tempo e lacunas."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz


def _integra_fake(base: Path) -> Path:
    d = base / "integra_TESTE"
    d.mkdir(parents=True)
    # doc 0: contrato textual
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((50, 100), "CONTRATO 011/2025 - Cláusula primeira: o objeto é "
                              "a reforma predial. Valor: R$ 457.179,31." * 3)
    doc.save(str(d / "000.pdf")); doc.close()
    # doc 1: relatório fotográfico (página com imagem grande e quase sem texto)
    doc = fitz.open()
    pg = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 320, 240), False)
    pix.set_rect(pix.irect, (200, 120, 40))     # "foto" laranja
    pg.insert_image(fitz.Rect(30, 60, 560, 740), pixmap=pix)
    doc.save(str(d / "001.pdf")); doc.close()
    (d / "manifest.json").write_text(json.dumps([
        {"i": 0, "arquivo": "000.pdf", "titulo": "Contrato 011/2025", "ok": True},
        {"i": 1, "arquivo": "001.pdf",
         "titulo": "Relatório Fotográfico - 5ª Medição", "ok": True},
    ], ensure_ascii=False), encoding="utf-8")
    return d


def test_arquivar_integra_sintetica(tmp_path):
    from tools.sei_arquivar import arquivar

    origem = _integra_fake(tmp_path)
    destino = tmp_path / "arquivo"
    m = arquivar(origem, destino, processo="000000/000000/0000")

    raiz = destino
    man = json.loads((raiz / "manifest.json").read_text(encoding="utf-8"))
    assert man["processo"] == "000000/000000/0000"
    docs = {d["i"]: d for d in man["docs"]}

    # contrato: texto extraído, fase certa
    assert docs[0]["fase"] == "contratacao"
    txt0 = (raiz / docs[0]["texto"]).read_text(encoding="utf-8")
    assert "457.179,31" in txt0

    # relatório fotográfico: fase execução + foto JPEG preservada
    assert docs[1]["fase"] == "execucao"
    assert docs[1]["tipo"] == "relatorio_fotografico"
    assert docs[1]["fotos"], "fotos do relatório fotográfico devem ser preservadas"
    foto = raiz / docs[1]["fotos"][0]
    assert foto.exists() and foto.stat().st_size > 1000
    assert foto.suffix == ".jpg"

    # linha do tempo e lacunas calculadas
    assert man["linha_do_tempo"]["contratacao"] == 1
    assert man["linha_do_tempo"]["execucao"] == 1
    assert isinstance(man["lacunas"], list)
    # o retorno é o mesmo manifest
    assert m["docs"][0]["fase"] == "contratacao"


def test_arquivar_e_idempotente(tmp_path):
    from tools.sei_arquivar import arquivar

    origem = _integra_fake(tmp_path)
    destino = tmp_path / "arquivo"
    arquivar(origem, destino, processo="P")
    m2 = arquivar(origem, destino, processo="P")   # 2ª rodada não duplica
    assert len(m2["docs"]) == 2
    fotos = list((destino / "fotos").glob("*.jpg"))
    assert len(fotos) == len(set(f.name for f in fotos))


def test_preservar_toca_o_mtime_do_manifesto(tmp_path, monkeypatch):
    """Preservar o arquivo maior é certo — mas TEM de tocar o mtime, ou a fila não anda.

    `arquivar_pendentes` monta a fila por "cache mais novo que o manifesto". Preservando sem
    tocar, o processo reaparece em TODO disparo, e o OCR roda ANTES da decisão de preservar:
    medido em 2026-08-23, os dois primeiros processos comiam os 25 min do `timeout` e o lane
    terminava em 124 sem alcançar o resto da fila. É o mesmo bug que `sei_arquivar_do_cache`
    corrigiu em 2026-08-15 — o irmão tinha o conserto, este não.
    """
    import os
    import time

    from tools.sei_arquivar import arquivar

    origem = _integra_fake(tmp_path)
    destino = tmp_path / "arq"
    (destino / "texto").mkdir(parents=True)
    # manifesto anterior com MAIS docs capturados do que a íntegra sintética (2) tem
    mdest = destino / "manifest.json"
    mdest.write_text(json.dumps({"docs": [{"i": i, "titulo": f"d{i}"} for i in range(9)]}),
                     encoding="utf-8")
    antigo = time.time() - 86_400          # manifesto de ontem
    os.utime(mdest, (antigo, antigo))

    devolvido = arquivar(origem, destino, processo="030001/087722/2024", ocr=False)

    assert len(devolvido["docs"]) == 9, "preservou o manifesto errado — regrediu para o menor"
    assert mdest.stat().st_mtime > antigo + 3600, (
        "preservou sem tocar o mtime: o processo volta à fila em todo disparo e o lane "
        "nunca alcança o resto"
    )
