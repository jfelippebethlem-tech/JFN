# -*- coding: utf-8 -*-
"""A retomada da íntegra é pelo IDENTIFICADOR do documento, nunca pela posição na lista.

A enumeração da árvore do SEI muda entre rodadas (`arvore_anterior`). A retomada antiga dizia "existe `{i:03d}.pdf`
→ é o documento i": numa lista reordenada, o PDF de um documento ficava sob o título de outro.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fitz")

import tools.sei_integra_completa as IC  # noqa: E402
from tools import sei_arquivar as ARQ  # noqa: E402


def _url(ident: str) -> str:
    return f"https://sei.rj.gov.br/sei/controlador.php?acao=arvore_visualizar&id_documento={ident}&infra_hash=x"


def _rodada_anterior(outdir, ids):
    outdir.mkdir(parents=True, exist_ok=True)
    man = []
    for i, ident in enumerate(ids):
        (outdir / f"{i:03d}.pdf").write_bytes(f"pdf-{ident}".encode())
        man.append({"i": i, "arquivo": f"{i:03d}.pdf", "titulo": f"Doc {ident}", "url": _url(ident), "ok": True})
    (outdir / "manifest.json").write_text(json.dumps({"processo": "x", "docs": man, "completo": True}))


def _docs(ids):
    return [{"t": f"Doc {i}", "u": _url(i), "pai": ""} for i in ids]


def test_id_documento_sai_da_url_ou_do_campo():
    assert IC.id_documento({"u": _url("126135771")}) == "126135771"
    assert IC.id_documento({"url": _url("7")}) == "7"
    assert IC.id_documento({"id_documento": "99", "u": _url("7")}) == "99"
    assert IC.id_documento({"u": "sem id"}) == ""


def test_lista_reordenada_nao_cola_pdf_de_um_documento_no_titulo_de_outro(tmp_path):
    out = tmp_path / "integra_1"
    _rodada_anterior(out, ["111", "222", "333"])
    novos = _docs(["222", "999", "111"])          # a árvore voltou noutra ordem, com um documento novo
    # o DEFEITO, reproduzido: pela posição, o 000.pdf (do 111) seria dado como o documento 222
    assert (out / "000.pdf").read_bytes() == b"pdf-111"
    r = IC.preparar_retomada(out, novos)
    assert r == {"mantidos": 0, "movidos": 3}
    achados = {i: IC.arquivo_retomado(out, i, d) for i, d in enumerate(novos)}
    assert achados[0].read_bytes() == b"pdf-222"   # o PDF do 222 volta, agora no lugar dele
    assert achados[1] is None                      # o 999 nunca foi baixado: baixa
    assert achados[2].read_bytes() == b"pdf-111"
    assert (out / IC.RETOMADA / "333.pdf").read_bytes() == b"pdf-333"   # nada apagado


def test_mesma_ordem_mantem_tudo_no_lugar(tmp_path):
    out = tmp_path / "integra_2"
    _rodada_anterior(out, ["1", "2"])
    assert IC.preparar_retomada(out, _docs(["1", "2"])) == {"mantidos": 2, "movidos": 0}
    assert IC.arquivo_retomado(out, 1, _docs(["1", "2"])[1]).read_bytes() == b"pdf-2"


def test_pdf_sem_dono_conhecido_nao_e_reaproveitado_no_lugar(tmp_path):
    out = tmp_path / "integra_3"
    out.mkdir()
    (out / "000.pdf").write_bytes(b"quem sou eu")   # sem manifesto: dono desconhecido
    IC.preparar_retomada(out, _docs(["5"]))
    assert IC.arquivo_retomado(out, 0, _docs(["5"])[0]) is None
    assert (out / IC.RETOMADA / "sem_id_000.pdf").read_bytes() == b"quem sou eu"


def test_rodada_que_morreu_no_meio_lembra_o_dono_pelo_registro(tmp_path):
    out = tmp_path / "integra_4"
    _rodada_anterior(out, ["1", "2", "3"])
    docs = _docs(["1", "2", "3"])
    IC.preparar_retomada(out, docs)
    # a rodada nova regrava o manifesto vazio (em andamento) e morre depois de registrar só o 1º
    (out / "manifest.json").write_text(json.dumps({"docs": [], "completo": False}))
    IC.registrar_dono(out, 0, docs[0])
    assert IC.preparar_retomada(out, docs) == {"mantidos": 3, "movidos": 0}


def test_arquivar_so_reaproveita_texto_cuja_etiqueta_e_do_mesmo_titulo(tmp_path):
    t = tmp_path / "000_x.txt"
    t.write_text("[Despacho 111] (fase: x · tipo: y)\n\nteor")
    assert ARQ._etiqueta_e_de(t, "Despacho 111")
    assert not ARQ._etiqueta_e_de(t, "Nota de Empenho 222")


def test_processo_com_pdf_trocado_volta_a_fila_mesmo_arquivado(tmp_path, monkeypatch):
    """Achado no acervo real (20/11/2026): 30 documentos em 4 processos com corpo idêntico ao de um irmão — o
    PDF de um colado no título de outro. Inscritos com `MOTIVO_PDF_TROCADO`, relêem mesmo com arquivo "pronto"."""
    import sqlite3
    from tools import sei_integra_fila as F
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sei_fila_captura (numero_sei TEXT PRIMARY KEY, sei_norm TEXT, motivo TEXT,"
                " total_pago REAL, n_docs INTEGER, visto_em TEXT)")
    con.execute("INSERT INTO sei_fila_captura VALUES (?,?,?,?,?,?)",
                ("SEI-600000/000009/2025", "", F.MOTIVO_PDF_TROCADO + " em 4 documento(s) | antes: x", 1.0, 4,
                 "2099-01-01 00:00:00"))
    con.commit()
    con.close()
    monkeypatch.setattr(F, "DB", db)
    monkeypatch.setattr(F, "ARQUIVO", tmp_path / "arq")
    monkeypatch.setattr(F, "_arquivado_ok", lambda p: True)
    assert F._fila_execucao() == ["SEI-600000/000009/2025"]
