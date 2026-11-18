"""Integrador do OCR por IA (GPU do it-campo) no arquivo canônico do SEI — 18/11/2026."""
from __future__ import annotations

import json

import tools.sei_ocr_gpu_integrar as G


def _monta(tmp_path, docs: list[dict], textos: dict[str, str], gpu: dict[int, str]):
    arq, cache = tmp_path / "sei_arquivo" / "111_222_2024", tmp_path / "sei_cache" / "integra_111_222_2024"
    (arq / "texto").mkdir(parents=True)
    cache.mkdir(parents=True)
    for nome, t in textos.items():
        (arq / "texto" / nome).write_text(t, encoding="utf-8")
    (arq / "manifest.json").write_text(json.dumps({"processo": "111/222/2024", "docs": docs}), encoding="utf-8")
    for i, t in gpu.items():
        (cache / f"{i:03d}.ocr_gpu.txt").write_text(t, encoding="utf-8")
        (cache / f"{i:03d}.ocr_gpu.json").write_text(json.dumps({"motor": "surya-ocr-2.5", "paginas": 1}))
    return arq, cache


def test_preenche_sem_texto_substitui_tesseract_e_nunca_toca_nativo(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(G, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(G, "LEDGER", tmp_path / "ledger.jsonl")
    docs = [
        {"i": 0, "titulo": "Nota Fiscal 53", "fase": "despesa", "tipo": "nota_fiscal", "texto": "", "chars": 0,
         "ocr": False, "nao_capturado": True},
        {"i": 1, "titulo": "Publicação DO", "fase": "indefinida", "tipo": "outro", "texto": "texto/001_pub.txt",
         "chars": 60, "ocr": True},
        {"i": 2, "titulo": "Despacho", "fase": "tramitacao", "tipo": "despacho", "texto": "texto/002_desp.txt",
         "chars": 70, "ocr": False},
    ]
    textos = {"001_pub.txt": "[Publicação DO] (fase: indefinida · tipo: outro)\n\nDIÁRIO E) OFICIAL DO RFO DE JANEIRO",
              "002_desp.txt": "[Despacho] (fase: tramitacao · tipo: despacho)\n\nEncaminho o processo à DIRAF."}
    gpu = {0: "NOTA FISCAL DE SERVIÇO Nº 53 Valor R$ 94.999,98", 1: "DIÁRIO OFICIAL DO ESTADO DO RIO DE JANEIRO",
           2: "lixo que não pode substituir o nativo"}
    arq, _ = _monta(tmp_path, docs, textos, gpu)
    res = G.integrar()
    man = json.loads((arq / "manifest.json").read_text())
    d0, d1, d2 = man["docs"]
    assert d0["texto"] and d0["ocr"] is True and d0["ocr_motor"].startswith("surya") and d0["chars"] > 40
    assert "94.999,98" in (arq / d0["texto"]).read_text()
    assert (arq / d0["texto"]).read_text().startswith("[Nota Fiscal 53] (fase: despesa · tipo: nota_fiscal)")
    assert "RIO DE JANEIRO" in (arq / d1["texto"]).read_text() and d1["ocr_motor"].startswith("surya")
    assert "RFO" in (arq / d1["ocr_anterior"]).read_text()          # o texto do Tesseract fica guardado
    assert d2 == docs[2]                                              # nativo intocado
    assert "lixo" not in (arq / "texto" / "002_desp.txt").read_text()
    assert res == {"preenchidos": 1, "substituidos": 1, "nativos_mantidos": 1, "sem_manifesto": 0, "fora_do_manifesto": 0,
                   "processos": 1}
    # idempotente: segunda rodada não refaz
    assert G.integrar()["preenchidos"] == 0 and G.integrar()["substituidos"] == 0


def test_texto_gpu_vazio_nao_substitui(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(G, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(G, "LEDGER", tmp_path / "ledger.jsonl")
    docs = [{"i": 1, "titulo": "Pub", "fase": "x", "tipo": "outro", "texto": "texto/001_pub.txt", "chars": 60, "ocr": True}]
    arq, _ = _monta(tmp_path, docs, {"001_pub.txt": "[Pub] (fase: x · tipo: outro)\n\ntexto do tesseract razoável"},
                    {1: "  \n[página 1]\n  "})
    G.integrar()
    assert "tesseract" in (arq / "texto" / "001_pub.txt").read_text()
