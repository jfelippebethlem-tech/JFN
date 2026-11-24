# -*- coding: utf-8 -*-
"""COR-07 (teto de coleta não é total) nas rotas das manchetes — reincidência medida em 14–20/11/2026.

O sensor `payloads_painel` acusava, rodada após rodada:
  - `/api/compliance/painel`: `obs_recentes` cortada em 25 (`.limit(25)`) sem o total ao lado;
  - `/api/ao-vivo/estado`: `eventos` cortada em 60 (`eventos_publicos(limite=60)`) sem o total ao lado.
Lista cortada é legítima desde que diga "N de M": cada uma passa a levar `<lista>_total`. Dados sintéticos.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from compliance_agent.qualidade import verificadores as v


def test_total_da_propria_lista_ao_lado_conta_como_declarado():
    assert not v.listas_no_teto({"achados": [0] * 100, "achados_total": 554})       # "100 de 554"
    assert v.listas_no_teto({"achados": [0] * 100, "outra_total": 554})             # total de OUTRA lista não vale
    assert v.listas_no_teto({"achados": [0] * 100, "achados_total": True})          # bool não é total


@pytest.fixture()
def painel(tmp_path, monkeypatch):
    # 24/11/2026: `obs_recentes` passou a ser a OB PAGA do SIAFE (antes, as 25 últimas linhas do espelho TFE)
    (tmp_path / "data").mkdir()
    db = tmp_path / "data" / "compliance.db"
    monkeypatch.setenv("JFN_DB", str(db))
    from compliance_agent.database.models import get_engine, get_session, init_db
    init_db(str(db))
    get_session(get_engine(str(db))).close()
    import sqlite3
    con = sqlite3.connect(db)
    con.execute("DROP TABLE IF EXISTS ob_orcamentaria_siafe")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT, "
                "status_envio TEXT, credor TEXT, nome_credor TEXT, valor REAL, exercicio INTEGER, processo TEXT, "
                "coletado_em TEXT)")
    hoje = dt.date.today()
    for i in range(30):
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (f"{hoje.year}OB{i:05d}", "100100", (hoje - dt.timedelta(days=i % 2)).strftime("%d/%m/%Y"),
                     "Contabilizado", "Processado e Pago", f"{i:014d}", f"Fornecedor {i}", 100.0 + i, hoje.year,
                     None, None))
    con.commit()
    con.close()
    from rotas import investigacao as R
    monkeypatch.setattr(R, "RAIZ", tmp_path)
    monkeypatch.setattr(R, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(R, "_cache_put", lambda chave, val: val)
    return json.loads(R.api_painel().body)


def test_painel_obs_recentes_diz_de_quantas(painel):
    assert len(painel["obs_recentes"]) == 25 and painel["obs_recentes_total"] == 30
    assert not v.listas_no_teto(painel)


def test_ao_vivo_eventos_diz_de_quantos(monkeypatch):
    from compliance_agent.aovivo import coleta
    monkeypatch.setattr(coleta, "catalogo", lambda: [])
    monkeypatch.setattr(coleta, "ler_systemd", lambda units: {})
    monkeypatch.setattr(coleta, "travas_presas", lambda: set())
    c = coleta.Coletor()
    agora = coleta.time.time()
    for i in range(70):
        c.eventos.append({"id": i + 1, "_ts": agora - 70 + i, "motor": "x", "tipo": "dado", "texto": f"e{i}"})
    monkeypatch.setattr(c, "tick", lambda *a, **k: None)
    snap = c.snapshot()
    assert len(snap["eventos"]) == 60 and snap["eventos_total"] == 70
    assert not v.listas_no_teto(snap)
