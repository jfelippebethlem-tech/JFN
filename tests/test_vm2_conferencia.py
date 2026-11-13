# -*- coding: utf-8 -*-
"""Conferência das entregas da VM-2: só entra no acervo o que passa (md5, documentos × árvore, texto legível,
amostra × leitura da VM-1, juízo do Claude); o resto vai para a quarentena e o log da fila não ganha "ok"."""
from __future__ import annotations

import json

import tools.vm2_conferencia as C
import tools.vm2_lote as L

TEXTO = "Despacho de encaminhamento do processo administrativo para a coordenadoria de contratos. " * 5


def _pasta(base, tag, *, n=3, total=None, texto=TEXTO):
    p = base / tag
    (p / "texto").mkdir(parents=True)
    docs = []
    for i in range(n):
        nome = f"{i:03d}_despacho_{i}.txt"
        (p / "texto" / nome).write_text(texto, encoding="utf-8")
        docs.append({"i": i, "titulo": f"Despacho {i} ({1000 + i})", "texto": f"texto/{nome}", "chars": len(texto)})
    m = {"processo": tag, "docs": docs, "total_arvore": total if total is not None else n, "nao_capturados": 0,
         "captura_vazia": False}
    (p / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    return p


def _isolar(monkeypatch, tmp_path):
    d = tmp_path / "data"
    for nome, val in {"DATA": d, "ENTREGA": d / "vm2_entrega", "QUARENTENA": d / "vm2_quarentena",
                      "SUBST": d / "vm2_entrega" / "_substituidos", "IMPORTADOS": d / "vm2_entrega" / "_importados",
                      "LOG": d / "vm2_conferencia.log", "LOG_FILA": d / "sei_integra_fila.log",
                      "ARQUIVO": d / "sei_arquivo", "CACHE": d / "sei_cache", "AMOSTRA": d / "amostra.json"}.items():
        monkeypatch.setattr(C, nome, val)
    (d / "sei_arquivo").mkdir(parents=True)
    (d / "sei_cache").mkdir(parents=True)
    monkeypatch.setattr(L, "LOTES", d / "vm2_entrega")      # o lote "chega" direto onde a VM-1 o espera
    return d


def test_lote_aprova_o_bom_e_poe_em_quarentena_o_adulterado_e_o_incompleto(monkeypatch, tmp_path):
    d = _isolar(monkeypatch, tmp_path)
    src = tmp_path / "vm2"
    _pasta(src, "100000_000001_2025")
    _pasta(src, "100000_000002_2025")
    _pasta(src, "100000_000003_2025", n=2, total=10)          # árvore com 10, entregou 2
    base = L.montar("integras", {f"arquivo/{t}": src / t for t in
                                 ("100000_000001_2025", "100000_000002_2025", "100000_000003_2025")},
                    {p: {"status": "ok", "juizo": {"legivel": True, "corresponde": True}}
                     for p in ("100000/000001/2025", "100000/000002/2025", "100000/000003/2025")},
                    {"linhas_log": [f"[2026-11-13 17:00:00]   100000/00000{i}/2025: ok" for i in (1, 2, 3)]})
    # adulteração em trânsito
    (base / "arquivo/100000_000002_2025/texto/000_despacho_0.txt").write_text("x", encoding="utf-8")
    r = C.importar(base.name)
    assert r["aprovados"] == ["100000/000001/2025"]
    assert set(r["reprovados"]) == {"100000/000002/2025", "100000/000003/2025"}
    assert (d / "sei_arquivo" / "100000_000001_2025" / "manifest.json").exists()
    assert not (d / "sei_arquivo" / "100000_000002_2025").exists()
    assert (d / "vm2_quarentena" / base.name / "100000_000002_2025.motivo.json").exists()
    log = (d / "sei_integra_fila.log").read_text(encoding="utf-8")
    assert "100000/000001/2025: ok\n" in log
    assert "100000/000002/2025: ok-quarentena" in log and "100000/000003/2025: ok-quarentena" in log
    # sem leitura independente na VM-1 → vai para a fila da amostra independente
    assert json.loads((d / "amostra.json").read_text()) == ["100000/000001/2025"]


def test_juizo_do_claude_reprova_texto_ilegivel(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    p = _pasta(tmp_path / "vm2", "100000_000004_2025")
    ok, motivos, _ = C.conferir_integra(p, "ok", "100000_000004_2025",
                                        {"legivel": False, "corresponde": False, "motivo": "tela de login"})
    assert not ok and any("Claude" in m for m in motivos)


def test_referencia_da_vm1_divergente_reprova(monkeypatch, tmp_path):
    d = _isolar(monkeypatch, tmp_path)
    _pasta(d / "sei_arquivo", "100000_000005_2025", texto="Contrato de locação de veículos blindados " * 10)
    novo = _pasta(tmp_path / "vm2", "100000_000005_2025")
    ok, motivos, met = C.conferir_integra(novo, "ok", "100000_000005_2025", None)
    assert not ok and "diverge" in " ".join(motivos)


def test_legivel():
    assert C.legivel(TEXTO)
    assert not C.legivel("@@@@ #### 1234 5678 9999 %%%% ----" * 3)
    assert not C.legivel("")
