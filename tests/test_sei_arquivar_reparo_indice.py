# -*- coding: utf-8 -*-
"""Reparo dos arquivos feitos com o índice de 3 dígitos (até 18/11/2026).

1. A guarda "nunca regredir" conta DOCUMENTOS DISTINTOS: o manifesto errado repetia o mesmo `i` (no `210108/000169/2023`,
   2.770 entradas capturadas para 1.000 índices) e, contando entradas, preservava o arquivo errado contra o corrigido.
2. `textos_soltos=True` rearquiva pasta depurada pelo `NNN.txt` / `NNN.ocr.txt` que ficou no lugar do PDF."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz


def _pdf(caminho: Path, texto: str) -> None:
    doc = fitz.open()
    doc.new_page().insert_text((50, 100), texto)
    doc.save(str(caminho))
    doc.close()


def _cache(origem: Path, n: int) -> None:
    origem.mkdir(parents=True, exist_ok=True)
    (origem / "manifest.json").write_text(json.dumps(
        {"processo": "000000/000000/0000", "total_arvore": n, "completo": True,
         "docs": [{"i": i, "arquivo": f"{i:03d}.pdf", "titulo": f"Documento {i}", "ok": True} for i in range(n)]}),
        encoding="utf-8")


def test_guarda_conta_documentos_distintos_nao_entradas_repetidas(tmp_path):
    from tools.sei_arquivar import arquivar

    origem, destino = tmp_path / "integra_T", tmp_path / "arq"
    _cache(origem, 3)
    for i in range(3):
        _pdf(origem / f"{i:03d}.pdf", f"teor proprio do documento numero {i} " * 4)
    destino.mkdir()
    # arquivo ERRADO: o mesmo i=0 repetido 5 vezes (5 "capturados") e os outros dois como não capturados
    errado = [{"i": 0, "titulo": "Documento 0", "texto": "", "chars": 10} for _ in range(5)] + \
             [{"i": 1, "nao_capturado": True}, {"i": 2, "nao_capturado": True}]
    (destino / "manifest.json").write_text(json.dumps({"docs": errado}), encoding="utf-8")

    man = arquivar(origem, destino, processo="000000/000000/0000", ocr=False)

    assert sorted(d["i"] for d in man["docs"]) == [0, 1, 2]
    assert man["nao_capturados"] == 0, "3 distintos agora > 1 distinto antes: o corrigido entra"


def test_guarda_segue_preservando_quando_ha_menos_documentos_distintos(tmp_path):
    from tools.sei_arquivar import arquivar

    origem, destino = tmp_path / "integra_T", tmp_path / "arq"
    _cache(origem, 3)
    _pdf(origem / "000.pdf", "so o primeiro documento veio nesta passada " * 3)
    destino.mkdir()
    bom = [{"i": i, "titulo": f"Documento {i}", "texto": "", "chars": 50} for i in range(3)]
    (destino / "manifest.json").write_text(json.dumps({"docs": bom}), encoding="utf-8")

    man = arquivar(origem, destino, processo="000000/000000/0000", ocr=False)

    assert man["docs"] == bom, "1 distinto agora < 3 antes: preserva"


def test_pasta_depurada_rearquiva_pelos_textos_soltos(tmp_path):
    from tools.sei_arquivar import arquivar

    origem, destino = tmp_path / "integra_T", tmp_path / "arq"
    _cache(origem, 3)
    (origem / "depurados.json").write_text("{}", encoding="utf-8")
    (origem / "000.txt").write_text("texto nativo depurado do documento zero", encoding="utf-8")
    (origem / "1000.txt").write_text("nao pertence a este cache", encoding="utf-8")
    (origem / "001.ocr.txt").write_text("texto do OCR da captura do documento um", encoding="utf-8")
    _pdf(origem / "002.pdf", "documento dois ainda em PDF com teor " * 3)
    destino.mkdir()
    (destino / "manifest.json").write_text(json.dumps({"docs": [{"i": 0, "titulo": "x", "chars": 1}]}),
                                           encoding="utf-8")

    sem = arquivar(origem, destino, processo="000000/000000/0000", ocr=False)
    assert sem["docs"] == [{"i": 0, "titulo": "x", "chars": 1}], "sem a opção a pasta depurada não é rearquivada"

    man = arquivar(origem, destino, processo="000000/000000/0000", ocr=False, textos_soltos=True)
    por_i = {d["i"]: d for d in man["docs"]}
    assert sorted(por_i) == [0, 1, 2] and man["nao_capturados"] == 0
    assert "nativo depurado" in (destino / por_i[0]["texto"]).read_text(encoding="utf-8")
    assert por_i[1]["ocr"] is True and "OCR da captura" in (destino / por_i[1]["texto"]).read_text(encoding="utf-8")
    assert por_i[2]["chars"] > 0
