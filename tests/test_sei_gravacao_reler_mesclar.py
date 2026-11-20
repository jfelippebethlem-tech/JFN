# -*- coding: utf-8 -*-
"""Quem lê, demora (OCR, LLM) e grava não pode apagar o que outro escritor gravou no meio.

`sei_reparar_vazios` lia o manifesto, fazia OCR por minutos e regravava o objeto velho; `sei_refichar` lia o blob,
esperava ~60 s de LLM e regravava. Agora os dois relêem e mesclam sob trava de arquivo
(`acervo_texto.mutar_manifesto`, `cache_arquivo.mutar_json`).
"""
from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import sys

from compliance_agent.sei import acervo_texto, cache_arquivo


def _incrementa(pasta, chave, n):
    for _ in range(n):
        def f(m):
            m[chave] = int(m.get(chave) or 0) + 1
        acervo_texto.mutar_manifesto(pasta, f, espera=None)


def test_dois_escritores_concorrentes_nao_perdem_escrita(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"docs": []}))
    ctx = mp.get_context("fork")
    ps = [ctx.Process(target=_incrementa, args=(tmp_path, k, 60)) for k in ("a", "b")]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert (m["a"], m["b"]) == (60, 60)


def test_manifesto_ilegivel_ou_lista_nao_e_recriado(tmp_path):
    (tmp_path / "manifest.json").write_text("[1, 2]")
    assert acervo_texto.mutar_manifesto(tmp_path, lambda m: m.update(x=1)) is None
    assert (tmp_path / "manifest.json").read_text() == "[1, 2]"


def test_reparar_vazios_preserva_o_que_outro_escritor_gravou_durante_o_ocr(tmp_path, monkeypatch):
    from tools import sei_reparar_vazios as R
    (tmp_path / "texto").mkdir()
    txt = tmp_path / "texto" / "000_nad.txt"
    txt.write_text("[Nota de Autorização (82011111)] (tipo: outro)\n", encoding="utf-8")
    man = tmp_path / "manifest.json"
    man.write_text(json.dumps({"docs": [{"i": 0, "titulo": "Nota de Autorização (82011111)",
                                         "texto": "texto/000_nad.txt", "chars": 0}]}), encoding="utf-8")
    pdf = tmp_path / "000.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    def ocr_lento(*a, **k):
        # durante o OCR, OUTRO escritor (a captura) acrescenta um documento e uma marca no manifesto
        def outro(m):
            m["docs"].append({"i": 1, "titulo": "Despacho (82022222)", "texto": "texto/001_d.txt", "chars": 900})
            m["captura_completa"] = True
        acervo_texto.mutar_manifesto(tmp_path, outro)
        return "Nota de Autorização 82011111 — teor recuperado, longo o bastante para passar do piso exigido."

    monkeypatch.setattr("compliance_agent.sei.ocr_docs.ocr_documento", ocr_lento)
    r = R.reparar([{"processo": "p", "i": 0, "tipo": "outro", "titulo": "Nota de Autorização (82011111)",
                    "pdf": pdf, "txt": txt, "manifest": man, "kb": 10.0}], aplicar=True)
    assert r["recuperados"] == 1 and r["manifests_atualizados"] == 1
    m = json.loads(man.read_text())
    assert m["captura_completa"] is True and len(m["docs"]) == 2, "o reparo apagou o que a captura gravou"
    assert m["docs"][0]["chars"] > 80 and m["docs"][0]["ocr"] is True


def test_refichar_preserva_o_que_o_sweep_gravou_durante_o_llm(tmp_path, monkeypatch):
    from tools import sei_refichar as RF
    blob = tmp_path / "cdp_080001_000001_2024.json"
    blob.write_text(json.dumps({"numero": "SEI-080001/000001/2024", "documentos": [{"t": "a"}],
                                "conteudo_documentos": [{"doc": "a", "conteudo": "x" * 200}]}))

    async def ficha_lenta(*a, **k):
        # durante a chamada ao LLM, o sweep grava mais documentos no MESMO blob
        d = json.loads(blob.read_text())
        d["documentos"].append({"t": "b"})
        cache_arquivo.escrever_json(blob, d)
        return {"situacao": "em andamento"}

    monkeypatch.setattr(RF, "CACHE", tmp_path)
    monkeypatch.setattr(RF, "extrair_ficha", ficha_lenta)
    monkeypatch.setattr(RF, "_refresh_nous_se_preciso", lambda: None)
    monkeypatch.setattr(sys, "argv", ["sei_refichar"])
    asyncio.run(RF.main())
    d = json.loads(blob.read_text())
    assert d["ficha"] == {"situacao": "em andamento"} and d["_ficha_schema"] == RF.CAMPO_NOVO
    assert [x["t"] for x in d["documentos"]] == ["a", "b"], "a ficha apagou o que o sweep gravou"
