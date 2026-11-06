# -*- coding: utf-8 -*-
"""Re-coletar um mês com o Portal fora do ar não pode apagar o mês que já estava no banco.

Medido em 2026-10-12: `coletar()` fazia `DELETE ... WHERE competencia=?` ANTES de saber se algum
download tinha funcionado. Com todos os downloads falhando, o mês virava zero linhas — e o sweep,
que pula meses "já coletados" pela contagem, passava a tratá-lo como nunca coletado.
"""
import sqlite3

import compliance_agent.pcrj.beneficio_pcrj as B


def _banco(path):
    con = sqlite3.connect(path)
    con.executescript(B._SCHEMA)
    con.execute("INSERT INTO pcrj_beneficio (nome_norm, nome, beneficio, municipio, uf, valor, cpf_frag, "
                "competencia, coletado_em) VALUES ('FULANO','Fulano','BPC','RIO DE JANEIRO','RJ',1,'123456',"
                "'202605','x')")
    con.commit()
    con.close()


def test_download_falho_preserva_o_mes(tmp_path, monkeypatch):
    db = tmp_path / "pcrj_benef.db"
    _banco(db)
    monkeypatch.setattr(B, "BENEF_DB", db)
    monkeypatch.setattr(B, "_TMP", tmp_path / "tmp")
    monkeypatch.setattr(B, "_alvo_nomeados", lambda: {"FULANO": "Fulano"})
    monkeypatch.setattr(B, "_baixar", lambda url, dest: False)
    r = B.coletar("202605")
    n = sqlite3.connect(db).execute("SELECT COUNT(*) FROM pcrj_beneficio WHERE competencia='202605'").fetchone()[0]
    assert n == 1, "download falho apagou a competência que já estava no banco"
    assert r.get("gravado") is False


def test_tmp_nao_mora_em_scratchpad_de_sessao():
    assert "claude-" not in str(B._TMP), "o temporário do coletor não pode depender do scratchpad de uma sessão"
