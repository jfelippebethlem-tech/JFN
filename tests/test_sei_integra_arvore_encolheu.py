# -*- coding: utf-8 -*-
"""Captura cuja árvore ENCOLHEU entre passadas não pode se declarar completa (`tools/sei_integra_completa`).
Medido em 18/11/2026: `150016/009553/2024` na VM-2 com 668 PDFs de uma enumeração e `completo: True` gravado
por outra que só viu 356 nós; `330001/000788/2024` no acervo com `total_arvore` 15 e 257 documentos."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_arvore_anterior_le_o_maior_tamanho_ja_visto(tmp_path):
    from tools.sei_integra_completa import arvore_anterior

    m = tmp_path / "manifest.json"
    assert arvore_anterior(m) == 0                       # sem captura anterior
    m.write_text(json.dumps({"total_arvore": 668, "completo": False, "docs": [{"i": 0}]}), encoding="utf-8")
    assert arvore_anterior(m) == 668
    m.write_text(json.dumps({"total_arvore": 10, "docs": [{"i": i} for i in range(12)]}), encoding="utf-8")
    assert arvore_anterior(m) == 12                      # docs além do total também contam
    m.write_text(json.dumps([{"i": 0}, {"i": 1}]), encoding="utf-8")
    assert arvore_anterior(m) == 2                       # formato antigo (lista)
    m.write_text("{quebrado", encoding="utf-8")
    assert arvore_anterior(m) == 0


def test_main_nao_marca_completa_quando_a_arvore_encolheu():
    """A decisão está no `_grava` de `main`: `completo and not encolheu` e o total é o maior visto."""
    fonte = (Path(__file__).resolve().parents[1] / "tools" / "sei_integra_completa.py").read_text(encoding="utf-8")
    assert "n_antes = arvore_anterior(man_path)" in fonte
    assert '"completo": completo and not encolheu' in fonte
    assert '"total_arvore": max(len(docs), n_antes)' in fonte
