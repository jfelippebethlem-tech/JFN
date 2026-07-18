# -*- coding: utf-8 -*-
"""retro_auditoria — ledger append-first de sinais + hindsight (sanção depois, pago depois)."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import retro_auditoria as RA


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE fantasma_score (cnpj TEXT PRIMARY KEY, razao_social TEXT, score INTEGER,
        classificacao TEXT, sinais_json TEXT, origem TEXT, avaliado_em TEXT);
    CREATE TABLE sancoes_federais (cpf_cnpj TEXT, nome TEXT, cadastro TEXT, categoria TEXT,
        data_inicio TEXT, data_fim TEXT, orgao TEXT);
    CREATE TABLE ob_orcamentaria_siafe (credor TEXT, nome_credor TEXT, numero_ob TEXT,
        valor REAL, data_emissao TEXT, ug_emitente TEXT);
    CREATE TABLE pncp_resultado (certame TEXT, fornecedor_cnpj TEXT, valor_homologado REAL,
        ordem_classificacao INTEGER, data_pub TEXT);
    """)
    con.execute("INSERT INTO fantasma_score (cnpj, razao_social, classificacao) "
                "VALUES ('11111111000111','ALFA','alto')")
    con.execute("INSERT INTO fantasma_score (cnpj, razao_social, classificacao) "
                "VALUES ('22222222000122','BETA','medio')")
    con.commit()
    con.close()
    # caches vazios (só fantasma_score alimenta o ledger neste fixture)
    monkeypatch.setattr("compliance_agent.cruzamentos_intel.ler_cache_intel", lambda n: None)
    return p


def test_registrar_preserva_primeira_vez(db):
    r1 = RA.registrar_sinais(db)
    assert r1["ok"] and r1["novos"] == 2 and r1["no_ledger"] == 2
    con = sqlite3.connect(db)
    con.execute("UPDATE sinal_ledger SET primeira_vez='2026-01-01'")  # simula ledger antigo
    con.commit()
    con.close()
    r2 = RA.registrar_sinais(db)                     # re-registro NÃO clobra a primeira_vez
    assert r2["novos"] == 0
    con = sqlite3.connect(db)
    pv = [r[0] for r in con.execute("SELECT primeira_vez FROM sinal_ledger")]
    assert pv == ["2026-01-01", "2026-01-01"]
    con.close()


def test_medir_corrobora_sancao_posterior_e_pago_depois(db):
    RA.registrar_sinais(db)
    con = sqlite3.connect(db)
    con.execute("UPDATE sinal_ledger SET primeira_vez='2026-01-01'")
    # ALFA: sanção DEPOIS do sinal + pagamento depois → corrobora e soma custo da inação
    con.execute("INSERT INTO sancoes_federais VALUES "
                "('11111111000111','ALFA','CEIS','Impedimento','2026-03-01','2028-01-01','CGU')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES "
                "('11111111000111','ALFA','OB1',50000.0,'15/04/2026','133100')")
    # BETA: sanção ANTES do sinal → NÃO corrobora; pagamento antes → não soma
    con.execute("INSERT INTO sancoes_federais VALUES "
                "('22222222000122','BETA','CEIS','Impedimento','2025-06-01','2027-01-01','CGU')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES "
                "('22222222000122','BETA','OB2',99999.0,'10/12/2025','133100')")
    con.commit()
    con.close()
    d = RA.medir(db)
    assert d["ok"] is True
    alto, medio = d["por_sinal"]["fantasma_alto"], d["por_sinal"]["fantasma_medio"]
    assert alto["n_sancao_depois"] == 1 and alto["pago_depois"] == pytest.approx(50000.0)
    assert medio["n_sancao_depois"] == 0 and medio["pago_depois"] == 0.0
    ex = d["exemplos"][0]
    assert ex["cnpj"] == "11111111000111" and ex["sancao_depois"]["data_inicio"] == "2026-03-01"
    assert "Indício" in d["ressalva"]


def test_medir_sem_ledger_e_honesto(db):
    d = RA.medir(db)
    assert d["ok"] is False and "ledger vazio" in d["erro"]
