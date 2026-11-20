# -*- coding: utf-8 -*-
"""Cada documento da árvore veio? A régua ÚNICA de "captura completa" (`manifesto_norm.conferir_documentos`).

Pedido do dono (20/11/2026): "checar se a íntegra do processo baixado tem todos os documentos mencionados
individualmente". `captura_completa` só é True com a árvore medida e todo documento presente; cada um que falta
sai com id/nº/título/motivo.
"""
from __future__ import annotations

import json

from compliance_agent.sei import manifesto_norm as mn

TEOR = "Governo do Estado do Rio de Janeiro. Documento com teor de verdade, assinado eletronicamente."


def _pasta(tmp_path, docs, **extra):
    p = tmp_path / "080001_000001_2024"
    (p / "texto").mkdir(parents=True)
    for d in docs:
        if d.get("texto") and "_corpo" in d:
            (p / d["texto"]).write_text(f"[{d['titulo']}] (fase: x · tipo: y)\n\n{d.pop('_corpo')}", encoding="utf-8")
    (p / "manifest.json").write_text(json.dumps({"docs": docs, **extra}))
    return p


def test_todos_vieram_com_arvore_medida_e_completa(tmp_path):
    p = _pasta(tmp_path, [{"i": 0, "titulo": "Despacho (121323702)", "texto": "texto/000_a.txt", "_corpo": TEOR},
                          {"i": 1, "titulo": "Foto", "texto": "", "fotos": ["fotos/001_p01.jpg"]}],
               total_arvore=2)
    c = mn.conferir_documentos(p)
    assert c["captura_completa"] and c["vieram"] == 2 and c["com_texto"] == 1 and c["docs_faltantes"] == []


def test_cada_faltante_sai_com_id_numero_titulo_e_motivo(tmp_path):
    p = _pasta(tmp_path, [
        {"i": 0, "titulo": "Despacho (121323702)", "texto": "texto/000_a.txt", "_corpo": TEOR},
        {"i": 1, "titulo": "Nota de Empenho (121323703)", "texto": "texto/001_b.txt", "_corpo": "",
         "id_documento": "126149056"},
        {"i": 2, "titulo": "Planilha 74889284", "nao_capturado": True},
        {"i": 3, "titulo": "Anexo (74889285)", "texto": "texto/003_c.txt", "sem_conteudo": True, "_corpo": ""},
    ], docs_na_arvore=6)
    c = mn.conferir_documentos(p)
    assert not c["captura_completa"]
    assert [(f["i"], f["numero_sei"], f["motivo"]) for f in c["docs_faltantes"]] == [
        (1, "121323703", "so_etiqueta"), (2, "74889284", "nao_capturado"), (3, "74889285", "sem_conteudo")]
    assert c["docs_faltantes"][0]["id_documento"] == "126149056"
    assert c["faltam_sem_identificacao"] == 2              # a árvore tem 6, o manifesto lista 4


def test_arvore_nao_medida_nunca_e_completa(tmp_path):
    p = _pasta(tmp_path, [{"i": 0, "titulo": "Despacho", "texto": "texto/000_a.txt", "_corpo": TEOR}])
    c = mn.conferir_documentos(p)
    assert c["medido"] is False and c["captura_completa"] is False and c["docs_faltantes"] == []


def test_os_dois_nomes_da_arvore_valem_e_pecas_alheias_saem_da_conta(tmp_path):
    assert mn.tamanho_da_arvore({"total_arvore": 10, "docs_na_arvore": 12}) == 12
    assert mn.tamanho_da_arvore({"total_arvore": 10, "alheios_fora": 3}) == 7
    assert mn.tamanho_da_arvore({"total_arvore": 10, "descontaminado": {"removidos": 2}}) == 8
    assert mn.tamanho_da_arvore({"docs": []}) is None


def test_captura_integra_le_a_arvore_pela_regua_unica(tmp_path):
    """`total_arvore` (íntegra) também conta — antes só `docs_na_arvore` (cache) entrava no teto de coleta."""
    docs = [{"i": i, "titulo": f"D{i}", "texto": f"texto/{i:03d}.txt", "_corpo": TEOR} for i in range(3)]
    p = _pasta(tmp_path, docs, total_arvore=9)
    ok, ev = mn.captura_integra(json.loads((p / "manifest.json").read_text()), p)
    assert ok is False and ev["teto_de_coleta"] and ev["faltam_capturar"] == 6
