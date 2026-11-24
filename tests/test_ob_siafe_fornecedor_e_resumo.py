# -*- coding: utf-8 -*-
"""Painel, favorecido_resumo, fênix e modelo de anomalias pela OB PAGA do SIAFE (24/11/2026). Dados sintéticos.

Decisão do dono: "corrige o painel usando o SIAFE e as OBs; OBs são o principal; TFE pode ter erro".
Controle POSITIVO: Ministério da Fazenda, Banco do Brasil e credor de natureza 1xxx saem do ranking de fornecedores
e aparecem ROTULADOS em outros credores, com os dois totais; credor só do espelho vira divergência no fênix.
Controle NEGATIVO: fornecedor privado (inclusive "Locação de Pessoal" com natureza 2xxx e concessionária) fica nos
fornecedores; OB não paga e o espelho TFE não entram no valor de favorecido_resumo; modelo não rodado = INDISPONÍVEL.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

import pytest

_SIAFE = ("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, ug_pagadora TEXT, data_emissao TEXT, "
          "status TEXT, tipo TEXT, tipo_ob TEXT, credor TEXT, nome_credor TEXT, status_envio TEXT, processo TEXT, "
          "tipo_regularizacao TEXT, valor REAL, exercicio INTEGER, coletado_em TEXT, "
          "PRIMARY KEY (numero_ob, ug_emitente, exercicio))")
_TFE = ("CREATE TABLE ordens_bancarias (id INTEGER PRIMARY KEY, numero_ob TEXT, data_emissao DATE, ug_codigo TEXT, "
        "ug_nome TEXT, favorecido_cpf TEXT, favorecido_nome TEXT, valor FLOAT, exercicio INTEGER)")

FAZENDA, BB, FMS, PESSOAL, CEDAE, FORN = ("00394460010880", "00000000000191", "11128809000110", "41274317000100",
                                          "33352394000104", "19024253000123")


def _siafe(con, n, ug, data, credor, nome, valor, status="Contabilizado", ex=None):
    con.execute("INSERT INTO ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, status_envio, "
                "credor, nome_credor, valor, exercicio) VALUES (?,?,?,?,?,?,?,?,?)",
                (n, ug, data, status, "Processado e Pago", credor, nome, valor, ex or int(data[-4:])))


def _cadastro(con):
    con.execute("CREATE TABLE empresas_cadastro (cnpj_basico TEXT, natureza_cod TEXT, capital_social REAL, "
                "razao_social TEXT)")
    con.executemany("INSERT INTO empresas_cadastro VALUES (?,?,0,'')",
                    [(FAZENDA[:8], "1015"), (BB[:8], "2038"), (FMS[:8], "1201"), (PESSOAL[:8], "2062"),
                     (CEDAE[:8], "2038"), (FORN[:8], "2062")])


# ── 1. classificador_credor (peneira canônica) ───────────────────────────────────────────────────────────────
def test_classificador_separa_tributo_banco_e_ente_publico_dos_fornecedores():
    from compliance_agent.cruzamentos_intel import classificador_credor
    con = sqlite3.connect(":memory:")
    _cadastro(con)
    f = classificador_credor(con)
    assert f("MINISTÉRIO DA FAZENDA", FAZENDA)                         # positivo: tributo retido
    assert f("Banco Do Brasil S/a", BB)                                # positivo: repasse/consignado
    assert f("Fundo Municipal De Saude De Duque De Caxias", FMS)       # positivo: repasse fundo a fundo
    assert f("ENTIDADE QUALQUER", FMS)                                 # positivo: natureza 1xxx basta
    assert f("FGTS - CAIXA", "") and f("RECOLHIMENTO DE ENCARGO", None)
    assert f("SCALLE CONSTRUCOES, REFORMAS E INSTALACOES LTDA", FORN) is None   # negativo: fornecedor
    assert f("ALFA LOCACAO DE PESSOAL LTDA", PESSOAL) is None          # negativo: nome casa, Receita diz 2xxx
    assert f("Companhia Estadual De Aguas E Esgotos Cedae", CEDAE) is None      # negativo: concessionária VENDE


# ── 2. painel: fornecedores × outros credores, os dois totais ──────────────────────────────────────────────────
@pytest.fixture()
def painel(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db = tmp_path / "data" / "compliance.db"
    monkeypatch.setenv("JFN_DB", str(db))
    from compliance_agent.database.models import get_engine, get_session, init_db
    init_db(str(db))
    get_session(get_engine(str(db))).close()
    con = sqlite3.connect(db)
    con.execute("DROP TABLE IF EXISTS ob_orcamentaria_siafe")
    con.execute(_SIAFE)
    _cadastro(con)
    hoje = dt.date.today().strftime("%d/%m/%Y")
    for i, (doc, nome, v) in enumerate([(FAZENDA, "MINISTÉRIO DA FAZENDA", 7e9), (BB, "Banco Do Brasil S/a", 5e9),
                                        (FMS, "Fundo Municipal De Saude De Duque De Caxias", 3e9),
                                        (FORN, "SCALLE CONSTRUCOES LTDA", 1e9), (CEDAE, "Cedae", 2e9),
                                        (PESSOAL, "ALFA LOCACAO DE PESSOAL LTDA", 5e8),
                                        ("CG0004700", "FOLHA DE PAGAMENTOS", 9e9)]):
        _siafe(con, f"2026OB{i:05d}", "100100", hoje, doc, nome, v)
    con.commit()
    con.close()
    from rotas import investigacao as R
    monkeypatch.setattr(R, "RAIZ", tmp_path)
    monkeypatch.setattr(R, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(R, "_cache_put", lambda chave, val: val)
    return json.loads(R.api_painel().body)


def test_painel_fornecedores_e_outros_credores_rotulados(painel):
    forn = [t["doc"] for t in painel["top_favorecidos"]]
    assert forn == [CEDAE, FORN, PESSOAL]                               # negativo: fornecedores ficam, em ordem
    outros = {t["doc"]: t["motivo"] for t in painel["top_outros_credores"]}
    assert set(outros) == {FAZENDA, BB, FMS} and all(outros.values())   # positivo: rotulados, não escondidos
    tc = painel["totais_credores"]
    assert tc["fornecedores"]["valor"] == 3.5e9 and tc["fornecedores"]["n_credores"] == 3
    assert tc["outros_credores"]["valor"] == 15e9 and tc["codigo_interno"]["valor"] == 9e9
    assert (tc["fornecedores"]["valor"] + tc["outros_credores"]["valor"] + tc["codigo_interno"]["valor"]
            == painel["obs"]["valor_total"])                            # nada some: as três partes fecham o total


# ── 3. favorecido_resumo: valor do SIAFE; espelho só confronto ──────────────────────────────────────────────────
def _base_resumo(tmp_path):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute(_SIAFE)
    con.execute(_TFE)
    _siafe(con, "2025OB00001", "100100", "10/03/2025", FORN, "Scalle Ltda", 100.0)
    _siafe(con, "2025OB00002", "100100", "11/03/2025", FORN, "SCALLE CONSTRUCOES", 50.0)
    _siafe(con, "2025OB00003", "100100", "12/03/2025", FORN, "Scalle Ltda", 999.0, status="Cancelado")
    _siafe(con, "2025OB00004", "100100", "12/03/2025", "CG0004700", "FOLHA", 1e6)
    tfe = [(FORN, "Scalle Antiga", 2025, 7777.0), (FORN, "Scalle Antiga", 2015, 1.0),
           ("88888888000188", "SO NO ESPELHO", 2025, 300.0), ("77777777000177", "SO ANTES", 2010, 40.0)]
    con.executemany("INSERT INTO ordens_bancarias (favorecido_cpf, favorecido_nome, exercicio, valor, data_emissao) "
                    "VALUES (?,?,?,?,'2025-01-01')", tfe)
    con.commit()
    con.close()
    return db


def test_favorecido_resumo_soma_ob_paga_do_siafe_e_isola_o_espelho(tmp_path):
    from compliance_agent.reporting.intel_dados import atualizar_favorecido_resumo
    db = _base_resumo(tmp_path)
    r = atualizar_favorecido_resumo(str(db))
    assert r["ok"] and r["credores_siafe"] == 1 and r["credores_so_tfe"] == 2
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    t = {x["favorecido_cpf"]: dict(x) for x in con.execute("SELECT * FROM favorecido_resumo")}
    assert t[FORN]["total_pago"] == 150.0 and t[FORN]["n_obs"] == 2     # positivo: só a OB paga do SIAFE
    assert t[FORN]["total_tfe"] == 7777.0                               # espelho só no exercício que o SIAFE cobre
    assert "scalle antiga" in t[FORN]["nome_match"] and "scalle ltda" in t[FORN]["nome_match"]
    assert t["88888888000188"]["total_pago"] is None                    # INDISPONÍVEL, nunca zero
    assert t["88888888000188"]["fonte_valor"] == "so_tfe" and t["88888888000188"]["total_tfe"] == 300.0
    assert t["77777777000177"]["total_tfe"] == 0.0                      # fora do período coberto: sem confronto
    assert "CG0004700" not in t                                         # folha/código interno fora


def test_fenix_valor_do_siafe_e_credor_so_do_espelho_vira_divergencia(tmp_path):
    from compliance_agent.cruzamentos_intel import empresa_fenix
    from compliance_agent.reporting.intel_dados import atualizar_favorecido_resumo
    db = _base_resumo(tmp_path)
    atualizar_favorecido_resumo(str(db))
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE empresas (cnpj TEXT, razao_social TEXT, data_abertura TEXT, situacao TEXT)")
    con.executemany("INSERT INTO empresas VALUES (?,?,?,?)",
                    [(FORN, "SCALLE", "2001-01-01", "BAIXADA"), ("88888888000188", "SO NO ESPELHO", "2001-01-01",
                                                                  "Baixada"),
                     ("77777777000177", "SO ANTES", "2001-01-01", "BAIXADA")])
    con.commit()
    con.close()
    r = empresa_fenix(str(db))
    assert [a["cnpj"] for a in r["achados"]] == [FORN] and r["total_defunta"] == 150.0   # SIAFE é o valor
    assert [d["cnpj"] for d in r["divergencias_tfe"]] == ["88888888000188"]              # dito, não somado
    assert r["total_divergencias_tfe"] == 300.0


# ── 4. modelo de anomalias: SIAFE, chave estável, INDISPONÍVEL ≠ 0 ─────────────────────────────────────────────
def test_anomalias_le_o_siafe_e_declara_indisponivel_sem_modelo(tmp_path, monkeypatch):
    from compliance_agent import anomalias as A
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute(_SIAFE)
    _siafe(con, "2025OB00001", "100100", "10/03/2025", FORN, "SCALLE", 100.0)
    _siafe(con, "2025OB00002", "100100", "10/03/2025", FAZENDA, "MINISTÉRIO DA FAZENDA", 900.0)
    con.commit()
    con.close()
    monkeypatch.setattr(A, "_DB", str(db))
    assert A.estado_modelo()["estado"] == "INDISPONÍVEL"               # negativo: nunca "0 anomalias"
    assert A.top_anomalias(5) == []
    con = sqlite3.connect(db)
    con.executemany("INSERT INTO ob_anomaly_siafe VALUES (?,?,?,?,?,?,?,?)",
                    [("2025OB00001", "100100", 2025, 0.9, '["log_valor"]', A.MODELO_VERSAO, "h", "agora"),
                     ("2025OB00002", "100100", 2025, 0.95, '["log_valor"]', A.MODELO_VERSAO, "h", "agora")])
    con.execute("INSERT INTO ob_redflag_siafe VALUES ('2025OB00001','100100',2025,'R_X',0.5,'p','f','agora')")
    con.commit()
    con.close()
    top = A.top_anomalias(5)
    assert [r["numero_ob"] for r in top] == ["2025OB00001"]            # positivo: join pela PK; Fazenda fora
    assert top[0]["regras"] == "R_X" and top[0]["favorecido_cpf"] == FORN
    assert A.estado_modelo()["estado"] == "VERIFICADO"


def test_anomalias_chave_do_siafe_e_le_so_ob_paga(tmp_path):
    import pandas as pd
    from compliance_agent import anomalias as A
    con = sqlite3.connect(":memory:")
    con.execute(_SIAFE)
    _siafe(con, "2025OB00001", "100100", "10/03/2025", FORN, "SCALLE", 100.0)
    _siafe(con, "2025OB00002", "100100", "10/03/2025", FORN, "SCALLE", 100.0, status="Cancelado")
    _siafe(con, "2025OB00003", "100100", "10/03/2025", "CG0004700", "FOLHA", 100.0)
    df = pd.read_sql(A._sql_ob_siafe(con), con)
    assert list(df["numero_ob"]) == ["2025OB00001"] and df["data_emissao"][0] == "2025-03-10"
    df.insert(0, "id", range(len(df)))
    assert A._chaves(df, [0]) == [("2025OB00001", "100100", 2025)]
