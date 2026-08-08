# -*- coding: utf-8 -*-
"""`_lido_agora` tem de ler o cache COMPRIMIDO — e `_trimado` NÃO é buraco de captura.

Defeito real (2026-08-08): `_lido_agora()` lia `cdp_X.json` com `read_text` cru. Blob comprimido
(`.json.zst`, ~91% do acervo) → `exists()` False → devolve 0 → `_marcar(antes, 0)` grava
"sem ganho" FALSO e o processo EXPIRA da fila apesar do ganho real. Quinta ferramenta da casa
cega à compressão (as quatro anteriores estão no catálogo de falhas, família 22/26).

ARMADILHA DOCUMENTADA DE PROPÓSITO (quase virou a 6ª família): `_trimado` PARECE captura rasa,
mas é política de STORAGE — o texto integral FOI lido, a ficha foi extraída dele
(`tools/sei_sweep.py`, storage após `extrair_ficha`), e só então o cru vira excerto de 400 chars.
Medido: 3.909 dos 6.419 blobs têm doc trimado; tratar trim como buraco teria posto 1.686
processos JÁ LIDOS de volta na fila de recaptura. `fila()` deve continuar contando PRESENÇA
(árvore − lidos); quem quer o teor integral de um processo específico usa leitura dirigida
(`tools/sei_consultar.py` / `sei_processo_integral`), não a fila.
"""
from __future__ import annotations

import json
import subprocess

import tools.sweep_recaptura_integral as SRI


def _blob(numero: str, *, arvore: int, lidos_ok: int, trimados: int) -> dict:
    docs = [{"doc": f"D{i}"} for i in range(arvore)]
    conteudo = ([{"doc": f"D{i}", "conteudo": "teor real com substância " * 20}
                 for i in range(lidos_ok)] +
                [{"doc": f"T{i}", "conteudo": "x" * 400, "_trimado": True}
                 for i in range(trimados)])
    return {"numero": numero, "documentos": docs, "conteudo_documentos": conteudo}


def test_lido_agora_enxerga_blob_comprimido(tmp_path, monkeypatch):
    monkeypatch.setattr(SRI, "CACHE", tmp_path)
    corpo = json.dumps(_blob("SEI-080002/014914/2024", arvore=10, lidos_ok=9, trimados=0))
    bruto = tmp_path / "cdp_SEI_080002_014914_2024.json"
    bruto.write_text(corpo, encoding="utf-8")
    # comprime pelo MESMO binário que a casa usa para descomprimir (`zstd`); --rm remove o cru
    subprocess.run(["zstd", "-q", "--rm", str(bruto)], check=True)
    assert SRI._lido_agora("SEI-080002/014914/2024") == 9, (
        "blob .zst leu como 0 — 'sem ganho' falso expira o processo da fila")


def test_fila_nao_trata_trimado_como_buraco(tmp_path, monkeypatch):
    """Doc trimado JÁ FOI lido (a ficha veio do texto integral) — refilar seria retrabalho."""
    monkeypatch.setattr(SRI, "CACHE", tmp_path)
    # isola as OUTRAS fontes da fila (arquivo real e fila da VM-2) — aqui só o cache importa
    monkeypatch.setattr(SRI, "ARQUIVO", tmp_path / "arquivo_vazio")
    monkeypatch.setattr(SRI, "_compartilhada", lambda: [])
    (tmp_path / "cdp_SEI_080002_011699_2024.json").write_text(
        json.dumps(_blob("SEI-080002/011699/2024", arvore=8, lidos_ok=0, trimados=8)),
        encoding="utf-8")
    assert all(x["numero"] != "SEI-080002/011699/2024" for x in SRI.fila()), (
        "processo com storage trimado (já lido e fichado) voltou para a fila — 1.686 de "
        "retrabalho; ver docstring")
