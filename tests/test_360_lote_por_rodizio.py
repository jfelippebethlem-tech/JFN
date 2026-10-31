# -*- coding: utf-8 -*-
"""O lote do cron pegava sempre os MESMOS 120 processos — o acervo nunca convergia.

`tools/processo_360.py --lote N` escolhia "os N maiores por número de documentos". Como o acervo
muda pouco, isso significa **os mesmos 120 processos a cada 4 horas, para sempre**: o resto nunca
era reavaliado, e uma correção de detector só alcançava o topo da lista.

Foi o que me obrigou, em 2026-08-04, a rodar passadas manuais sobre os 2.174 processos CINCO
vezes num único dia — o cron não convergia sozinho. Com rodízio por `avaliado_em`, o acervo
inteiro se atualiza em poucos dias (120 a cada 4h = 720/dia) e a correção chega em todo lugar sem
ninguém empurrar.

A prioridade do que NUNCA foi avaliado continua intacta: captura nova entra na frente.
"""
import json
import sqlite3
import sys

import tools.processo_360 as P


def _ambiente(tmp_path, monkeypatch, processos, avaliados):
    """processos: nomes no acervo. avaliados: {numero: avaliado_em}."""
    base = tmp_path / "data" / "sei_arquivo"
    base.mkdir(parents=True)
    for nome in processos:
        pasta = base / nome.replace("/", "_").replace("SEI-", "")
        pasta.mkdir()
        (pasta / "manifest.json").write_text(
            json.dumps({"processo": nome, "docs": [{"i": 0, "titulo": "x", "tipo": "outro"}]}),
            encoding="utf-8")
    db = tmp_path / "data" / "compliance.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE processo_avaliacao (numero_sei TEXT, avaliado_em TEXT)")
    for num, quando in avaliados.items():
        con.execute("INSERT INTO processo_avaliacao VALUES (?,?)", (num, quando))
    con.commit(); con.close()
    monkeypatch.setattr(P, "REPO", tmp_path)
    return tmp_path


def test_nunca_avaliado_entra_na_FRENTE(tmp_path, monkeypatch):
    _ambiente(tmp_path, monkeypatch,
              ["080001/000001/2025", "080001/000002/2025"],
              {"080001/000002/2025": "2026-08-04T10:00:00"})
    assert P._lote_por_rodizio(2)[0] == "080001/000001/2025"


def test_depois_vem_o_mais_DESATUALIZADO(tmp_path, monkeypatch):
    _ambiente(tmp_path, monkeypatch,
              ["080001/000001/2025", "080001/000002/2025", "080001/000003/2025"],
              {"080001/000001/2025": "2026-08-04T12:00:00",
               "080001/000002/2025": "2026-07-01T09:00:00",
               "080001/000003/2025": "2026-08-01T09:00:00"})
    assert P._lote_por_rodizio(3) == ["080001/000002/2025", "080001/000003/2025",
                                      "080001/000001/2025"]


def test_o_lote_respeita_o_teto(tmp_path, monkeypatch):
    _ambiente(tmp_path, monkeypatch, [f"080001/{i:06d}/2025" for i in range(10)], {})
    assert len(P._lote_por_rodizio(4)) == 4


def test_sem_base_o_lote_ainda_sai(tmp_path, monkeypatch):
    """Base ausente não pode travar o cron: sem histórico, todos são 'nunca avaliados'."""
    base = tmp_path / "data" / "sei_arquivo"
    base.mkdir(parents=True)
    for i in range(3):
        pasta = base / f"080001_00000{i}_2025"
        pasta.mkdir()
        (pasta / "manifest.json").write_text(
            json.dumps({"processo": f"080001/00000{i}/2025", "docs": []}), encoding="utf-8")
    monkeypatch.setattr(P, "REPO", tmp_path)
    assert len(P._lote_por_rodizio(5)) == 3


def test_manifesto_ilegivel_nao_derruba_o_lote(tmp_path, monkeypatch):
    _ambiente(tmp_path, monkeypatch, ["080001/000001/2025"], {})
    ruim = tmp_path / "data" / "sei_arquivo" / "quebrado"
    ruim.mkdir()
    (ruim / "manifest.json").write_text("{ nao é json", encoding="utf-8")
    assert P._lote_por_rodizio(5) == ["080001/000001/2025"]
