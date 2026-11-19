# -*- coding: utf-8 -*-
"""Processo com MAIS DE 1.000 documentos: a captura grava `1000.pdf`, `1001.pdf`… (`{i:03d}` não trunca) e o
arquivador lia o índice com `int(pdf.name[:3])` — `1000.pdf` virava o documento 100. Medido em 18/11/2026 no
`210108/000169/2023` (2.770 na árvore): 1.000 índices distintos para 2.770 entradas, o mesmo `i=100` repetido
11 vezes com o texto da NF 731, e os 1.770 documentos de 1.000 em diante marcados `nao_capturado` com o PDF no
disco. O documento 1.000 nunca virava texto; o 100 podia ter o teor sobrescrito pelo de outro."""
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


def test_pdf_com_indice_de_quatro_digitos_nao_colide_com_o_de_tres(tmp_path):
    from tools.sei_arquivar import arquivar

    origem = tmp_path / "integra_TESTE"
    origem.mkdir()
    _pdf(origem / "100.pdf", "NOTA FISCAL 731 do documento cem " * 4)
    _pdf(origem / "1000.pdf", "DESPACHO do documento mil, outro teor " * 4)
    docs = [{"i": i, "arquivo": f"{i:03d}.pdf", "titulo": f"Documento {i}", "ok": i in (100, 1000)}
            for i in range(1001)]
    (origem / "manifest.json").write_text(json.dumps(
        {"processo": "000000/000000/0000", "total_arvore": 1001, "completo": True, "docs": docs}),
        encoding="utf-8")

    man = arquivar(origem, tmp_path / "arquivo", processo="000000/000000/0000", ocr=False)

    indices = [d["i"] for d in man["docs"]]
    assert len(indices) == len(set(indices)) == 1001, "cada documento da árvore entra uma vez só"
    por_i = {d["i"]: d for d in man["docs"]}
    assert not por_i[1000].get("nao_capturado"), "o PDF 1000.pdf existe: o documento 1000 foi capturado"
    assert por_i[1000]["titulo"] == "Documento 1000"
    t100 = (tmp_path / "arquivo" / por_i[100]["texto"]).read_text(encoding="utf-8")
    t1000 = (tmp_path / "arquivo" / por_i[1000]["texto"]).read_text(encoding="utf-8")
    assert "documento cem" in t100 and "documento mil" not in t100
    assert "documento mil" in t1000
    assert man["nao_capturados"] == 999
