# -*- coding: utf-8 -*-
"""O4.1 — `dominio.documento_id`: `sei:<nº>` / `pos:<i>` + `#2`, com PARIDADE contra as cópias antigas.

Cópias achadas em 24/11/2026:
  compliance_agent/evidencias.py:135 `id_sei` + :157 o laço de `importar_pasta`  → a regra canônica (paridade exata)
  compliance_agent/sei/manifesto_norm.py:115 `numero_sei_do_titulo`             → divergência documentada
  compliance_agent/sei/reuso_documento_execucao.py:220 `numero_sei_do_titulo`   → divergência documentada
  tools/sei_integra_completa.py:252 `_num_sei` (delega a manifesto_norm)
"""
from __future__ import annotations

import json

from compliance_agent.dominio import documento_id as DI

TITULOS = [
    "Despacho de Encaminhamento de Processo (121323702)", "Despacho 121323702", "Nota Fiscal 12345678 de março (86490508)",
    "Nota Fiscal 12345678 de março", "Ofício nº 12/2024", "Termo de Referência", "", None, "  Anexo (1234567)  ",
    "Anexo (12345678901)", "Planilha(98765432)", "Doc-87654321", "Contrato 034/2026 (99887766) ", "123456789",
    "Relatório (123456)", "E-mail (1234567890)", "Despacho (86490508) assinado", "Anexo 86490508)",
]
# títulos em que as cópias de `numero_sei_do_titulo` acham um número que NÃO está no fim — o de outro documento
NUMERO_NO_MEIO = {"Nota Fiscal 12345678 de março", "Despacho (86490508) assinado"}


def test_paridade_evidencias_id_sei():
    from compliance_agent.evidencias import id_sei
    for t in TITULOS:
        assert DI.numero_sei(t) == id_sei(t), t


def test_paridade_evidencias_importar_pasta(tmp_path):
    """O laço real de `importar_pasta` (com o `#2`, o `pos:` e as entradas que não são dict) dá os mesmos ids."""
    from compliance_agent import evidencias
    docs = [{"i": 0, "titulo": "Despacho (111111111)"}, {"i": 1, "titulo": "Anexo"}, "lixo",
            {"i": 2, "titulo": "Despacho (111111111)"}, {"i": 3, "titulo": "Despacho 111111111"},
            {"i": "4", "titulo": "Nota Fiscal 12345678 de março"}, {"i": 1, "titulo": ""}, {"titulo": "sem posição"}]
    pasta = tmp_path / "080001_000123_2024"
    pasta.mkdir()
    (pasta / "manifest.json").write_text(json.dumps({"processo": "080001/000123/2024", "docs": docs}), encoding="utf-8")
    con = evidencias.conectar(tmp_path / "ev.db")
    evidencias.importar_pasta(con, pasta)
    gravados = [r[0] for r in con.execute("SELECT doc_id FROM documentos ORDER BY rowid")]
    esperado = DI.ids_documentos(docs)
    assert gravados == esperado
    assert esperado == ["sei:111111111", "pos:1", "sei:111111111#2", "sei:111111111#3", "pos:4", "pos:1#2", "pos:None"]
    h = con.execute("SELECT hash FROM arvores").fetchone()[0]
    assert h == evidencias.hash_arvore([DI.sem_repeticao(i) for i in esperado])


def test_divergencia_manifesto_norm_e_reuso_numero_no_meio():
    """DIVERGÊNCIA DOCUMENTADA: as duas cópias de `numero_sei_do_titulo` aceitam número fora do fim do título
    (manifesto_norm: o último número solto em qualquer lugar; reuso: `\\b` em vez de espaço/parêntese, então
    'Doc-87654321' também). Para IDENTIDADE vale só o número no fim, depois de espaço ou '(' — o do meio pode ser
    de outro documento citado. Fora desses casos, as três concordam."""
    from compliance_agent.sei.manifesto_norm import numero_sei_do_titulo as mn
    from compliance_agent.sei.reuso_documento_execucao import numero_sei_do_titulo as ru
    for t in TITULOS:
        novo = DI.numero_sei(t)
        if t in NUMERO_NO_MEIO:
            assert novo is None and mn(t)
        elif t == "Doc-87654321":
            assert novo is None and ru(t) == "87654321"
        elif t == "Anexo 86490508)":
            # o parêntese de fecho sem o de abertura: evidencias aceita (`\\)?`), as cópias não
            assert novo == "86490508"
        else:
            assert (mn(t) or None) == novo, t
            assert ru(t) == novo, t


def test_id_base_e_sem_repeticao():
    assert DI.id_base("Despacho (121323702)", 5) == "sei:121323702"
    assert DI.id_base("Termo de Referência", 5) == "pos:5"
    assert DI.sem_repeticao("sei:1#2") == "sei:1" and DI.sem_repeticao("pos:3") == "pos:3"
