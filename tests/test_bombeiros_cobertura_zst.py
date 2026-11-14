# -*- coding: utf-8 -*-
"""A cobertura dos bombeiros tem de enxergar o cache COMPRIMIDO (.json.zst).

Medido em 13/11/2026: o cache tinha 8.671 `.json.zst` contra 1.341 `.json`, e o
`bombeiros_integra_supervisor` só procurava `.json` — a LACUNA declarada (9.408 processos sem íntegra)
contava como "não coletado" tudo o que a compressão tinha guardado. O `sei_sweep` foi corrigido em 11/11;
este script não.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys

import tools.bombeiros_integra_supervisor as B

TEXTO = "Termo de referência para aquisição de equipamentos de proteção individual. " * 20


def test_cobertura_le_cache_zst(monkeypatch, tmp_path):
    cache = tmp_path / "sei_cache"
    cache.mkdir()
    cdp = {"documentos": [{"titulo": "TR"}], "conteudo_documentos": [{"titulo": "TR", "conteudo": TEXTO}]}
    cru = cache / "cdp_SEI_270006_000001_2025.json"
    cru.write_text(json.dumps(cdp), encoding="utf-8")
    subprocess.run(["zstd", "-q", "--rm", str(cru)], check=True)          # só existe o .json.zst
    (cache / "cdp_SEI_270006_000002_2025.json").write_text(json.dumps(cdp), encoding="utf-8")
    fila = tmp_path / "fila.json"
    fila.write_text(json.dumps([{"sei": "SEI-270006/000001/2025"}, {"sei": "SEI-270006/000002/2025"},
                                {"sei": "SEI-270006/000003/2025"}]), encoding="utf-8")
    for nome, val in {"CACHE": cache, "FILA": fila, "CORPUS": tmp_path / "corpus.txt",
                      "COBERTURA": tmp_path / "cob.csv", "LOG": tmp_path / "b.log"}.items():
        monkeypatch.setattr(B, nome, val)
    monkeypatch.setattr(sys, "argv", ["x"])
    B.main()
    with (tmp_path / "cob.csv").open(encoding="utf-8") as f:
        status = {r[0]: r[4] for r in csv.reader(f)}
    assert status["SEI-270006/000001/2025"] == "integra"        # comprimido: era "nao_coletado"
    assert status["SEI-270006/000002/2025"] == "integra"
    assert status["SEI-270006/000003/2025"] == "nao_coletado"
