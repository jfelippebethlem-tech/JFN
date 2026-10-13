# -*- coding: utf-8 -*-
"""Re-arquivar pelo cache não pode REBAIXAR um arquivo de íntegra.

Medido em 2026-10-12: `270006_012128_2024` tinha a íntegra capturada pelo browser (86 docs, 48 com
texto, 83 fotos das páginas escaneadas). O cache trouxe os mesmos 48 textos; a guarda comparava
só documentos com texto e com `>` — no EMPATE 48 × 48 substituiu, e as 83 fotos saíram do arquivo
ativo (ficaram só em `_substituido/`). Em `260007_019558_2024` o cache tinha mais texto (6 × 4) e
substituiu com razão, mas levou a única foto junto. O cache nunca traz foto: quem a tem é o antigo.
"""
import json

import pytest

import tools.sei_arquivar_do_cache as M

NUM = "SEI-270006/012128/2024"


@pytest.fixture()
def arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "ARQUIVO", tmp_path)
    d = tmp_path / "270006_012128_2024"
    (d / "texto").mkdir(parents=True)
    (d / "fotos").mkdir()
    docs = []
    for i in range(2):
        (d / "texto" / f"{i:03d}_doc.txt").write_text("x" * 200, encoding="utf-8")
        docs.append({"i": i, "texto": f"texto/{i:03d}_doc.txt", "chars": 200, "fotos": []})
    for i in range(3):
        (d / "fotos" / f"002_p{i:02d}.jpg").write_bytes(b"\xff\xd8foto")
    (d / "manifest.json").write_text(json.dumps({"docs": docs, "fotos_total": 3}), encoding="utf-8")
    return d


def _item(tmp_path, n_docs):
    cache = tmp_path / "cdp_SEI_270006_012128_2024.json"
    cache.write_text("{}", encoding="utf-8")
    cd = [{"doc": f"Despacho {i}", "conteudo": "teor do documento " * 20} for i in range(n_docs)]
    return {"numero": NUM, "cache": cache, "dados": {"conteudo_documentos": cd},
            "chars": 360 * n_docs, "na_arvore": n_docs}


def test_empate_mantem_a_integra(arquivo, tmp_path):
    r = M.arquivar(_item(tmp_path, 2), aplicar=True)
    assert "mantido_antigo" in r, "empate de texto tem de manter o arquivo da íntegra"
    assert len(list((arquivo / "fotos").iterdir())) == 3


def test_substituicao_herda_as_fotos(arquivo, tmp_path):
    r = M.arquivar(_item(tmp_path, 3), aplicar=True)
    assert "mantido_antigo" not in r
    fotos = sorted(p.name for p in (arquivo / "fotos").iterdir())
    assert fotos == ["002_p00.jpg", "002_p01.jpg", "002_p02.jpg"], "as fotos do arquivo antigo se perderam"
    man = json.loads((arquivo / "manifest.json").read_text(encoding="utf-8"))
    assert man["fotos_total"] == 3
    assert len(man["docs"]) == 3
