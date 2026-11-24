# -*- coding: utf-8 -*-
"""Conciliação OB do SIAFE × espelho TFE e o painel pela OB paga do SIAFE (24/11/2026). Dados sintéticos.

Controle POSITIVO: cada classe de divergência aparece onde foi plantada (complementar, devolvida, reemitida, não
contabilizada, casada por credor+valor+data, cobertura parcial, fora do universo do espelho, espelho defasado).
Controle NEGATIVO: base em que os dois lados batem não acusa divergência; OB complementar/devolvida/folha não entram
no pago nem no ranking do painel; OB só do espelho não aparece como paga.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

import pytest

from compliance_agent import conciliacao_ob_tfe as C

_SIAFE = ("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, ug_pagadora TEXT, data_emissao TEXT, "
          "status TEXT, tipo TEXT, tipo_ob TEXT, credor TEXT, nome_credor TEXT, status_envio TEXT, processo TEXT, "
          "tipo_regularizacao TEXT, valor REAL, exercicio INTEGER, coletado_em TEXT, "
          "PRIMARY KEY (numero_ob, ug_emitente, exercicio))")
_TFE = ("CREATE TABLE ordens_bancarias (id INTEGER PRIMARY KEY, numero_ob TEXT, data_emissao DATE, ug_codigo TEXT, "
        "ug_nome TEXT, favorecido_cpf TEXT, favorecido_nome TEXT, valor FLOAT, status TEXT, numero_processo TEXT, "
        "numero_sei TEXT)")


def _base(tmp_path, siafe, tfe, reem=()):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute(_SIAFE)
    con.execute(_TFE)
    con.execute("CREATE TABLE ob_reemitida (ob TEXT NOT NULL, ug TEXT NOT NULL, valor REAL, PRIMARY KEY (ob, ug))")
    for r in siafe:   # (numero, ug, dd/mm/aaaa, status, status_envio, tipo_reg, credor, valor)
        num, ug, d, st, ste, treg, cred, v = r
        con.execute("INSERT INTO ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, status_envio, "
                    "tipo_regularizacao, credor, nome_credor, valor, exercicio, processo) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (num, ug, d, st, ste, treg, cred, f"Credor {cred}", v, int(num[:4]), "SEI-080001/000001/2025"))
    for num, ug, iso, doc, v in tfe:
        con.execute("INSERT INTO ordens_bancarias (numero_ob, data_emissao, ug_codigo, ug_nome, favorecido_cpf, "
                    "favorecido_nome, valor) VALUES (?,?,?,?,?,?,?)", (num, iso, ug, f"UG {ug}", doc, f"F {doc}", v))
    con.executemany("INSERT INTO ob_reemitida VALUES (?,?,?)", reem)
    con.commit()
    con.close()
    return db


CNPJ = "11222333000181"
PAGA = ("Contabilizado", "Processado e Pago", None)


def _classe(r, lado, c):
    return r["por_ano"][0][f"classes_{lado}"].get(c, {"n": 0})["n"]


def test_negativo_dois_lados_iguais_nao_acusam_divergencia(tmp_path):
    siafe = [(f"2025OB{i:05d}", "100100", "10/03/2025", *PAGA, CNPJ, 100.0) for i in range(5)]
    tfe = [(f"2025OB{i:05d}", "100100", "2025-03-10", CNPJ, 100.0) for i in range(5)]
    r = C.medir(_base(tmp_path, siafe, tfe))
    a = r["por_ano"][0]
    assert r["ok"] and r["rotulo"] == C.ROTULO
    assert (a["siafe_pago_valor"], a["tfe_valor"], a["diferenca"]) == (500.0, 500.0, 0.0)
    assert a["casadas_numero"] == 5 and a["so_siafe_n"] == 0 and a["so_tfe_n"] == 0
    assert r["maiores_so_tfe"] == [] and r["maiores_so_siafe"] == []


def test_positivo_cada_classe_onde_foi_plantada(tmp_path):
    ug = "100100"
    siafe = [
        ("2025OB00001", ug, "10/03/2025", *PAGA, CNPJ, 100.0),                                    # casada
        ("2025OB00002", ug, "10/03/2025", "Contabilizado", "Enviado Manualmente", "Pagamento Complementar", CNPJ, 7.0),
        ("2025OB00003", ug, "10/03/2025", "Contabilizado", "Erro no Pagamento", None, CNPJ, 8.0),  # devolvida
        ("2025OB00004", ug, "10/03/2025", "Contabilizado", "Enviado ao Banco", None, CNPJ, 9.0),   # reemitida
        ("2025OB00005", ug, "10/03/2025", "Cancelado", None, None, CNPJ, 10.0),                   # não contabilizada
        ("2025OB00090", ug, "11/03/2025", *PAGA, CNPJ, 55.0),           # mesma OB do espelho com outro número
        ("2025OB00091", ug, "12/03/2025", *PAGA, "CG0004700", 1000.0),  # folha: fora do universo do espelho
        ("2025OB00092", ug, "20/12/2025", *PAGA, CNPJ, 30.0),           # depois do último dia do espelho
        ("2025OB00093", ug, "05/02/2025", *PAGA, CNPJ, 40.0),           # o espelho deveria ter: ausente_no_tfe
    ]
    tfe = [("2025OB00001", ug, "2025-03-10", CNPJ, 100.0), ("2025OB00002", ug, "2025-03-10", CNPJ, 7.0),
           ("2025OB00003", ug, "2025-03-10", CNPJ, 8.0), ("2025OB00004", ug, "2025-03-10", CNPJ, 9.0),
           ("2025OB00005", ug, "2025-03-10", CNPJ, 10.0), ("2025OB08888", ug, "2025-03-11", CNPJ, 55.0),
           ("2025OB09999", ug, "2025-06-30", CNPJ, 66.0)]   # ausente no SIAFE com o par coberto
    r = C.medir(_base(tmp_path, siafe, tfe, reem=[("2025OB00004", ug, 9.0)]))
    a = r["por_ano"][0]
    for c in ("complementar", "devolvida", "reemitida", "nao_contabilizada", "casada_credor_valor_data",
              "ausente_no_siafe"):
        assert _classe(r, "tfe", c) == 1, c
    for c in ("fora_do_universo_tfe", "tfe_defasado", "ausente_no_tfe", "casada_credor_valor_data"):
        assert _classe(r, "siafe", c) == 1, c
    # pago = só a régua `_ob_paga`: 100 + 55 + 1000 + 30 + 40 (complementar, devolvida, reemitida e cancelada fora)
    assert a["siafe_pago_valor"] == 1225.0 and a["siafe_pago_n"] == 5
    assert a["tfe_valor"] == 255.0
    assert {x["classe"] for x in r["maiores_so_tfe"]} >= {"complementar", "ausente_no_siafe"}
    assert all(x["explicacao"] for x in r["maiores_so_tfe"] + r["maiores_so_siafe"])


def test_par_sem_coleta_siafe_vira_cobertura_parcial_nao_divergencia(tmp_path):
    siafe = [("2025OB00001", "100100", "10/03/2025", *PAGA, CNPJ, 1.0)]
    tfe = [(f"2025OB{i:05d}", "200200", "2025-04-01", CNPJ, 50.0) for i in range(3)]   # UG nunca coletada
    r = C.medir(_base(tmp_path, siafe, tfe))
    assert _classe(r, "tfe", "cobertura_parcial_siafe") == 3 and _classe(r, "tfe", "ausente_no_siafe") == 0
    par = next(x for x in r["por_ug"] if x["ug"] == "200200")
    assert par["cobertura_siafe"] == "INDISPONÍVEL"
    assert r["por_ano"][0]["pares_indisponiveis"] == 1


def test_linha_alheia_do_espelho_fica_fora_da_soma(tmp_path):
    tfe = [("2025OB00001", "100100", "2025-03-10", CNPJ, 100.0), ("ERIKA LIMA", "100100", "ÉRIKA", CNPJ, 1e15)]
    r = C.medir(_base(tmp_path, [("2025OB00001", "100100", "10/03/2025", *PAGA, CNPJ, 100.0)], tfe))
    assert r["linhas_alheias_tfe"]["n"] == 1
    assert r["por_ano"][0]["tfe_valor"] == 100.0


def test_sem_tabela_e_indisponivel_nunca_zero(tmp_path):
    db = tmp_path / "v.db"
    sqlite3.connect(db).close()
    r = C.medir(db)
    assert r["ok"] is False and r["indisponivel"] and r["rotulo"] == C.ROTULO


# ── painel: /api/compliance/painel pela OB paga do SIAFE ──────────────────────────────────────────────────────────
@pytest.fixture()
def painel(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db = tmp_path / "data" / "compliance.db"
    monkeypatch.setenv("JFN_DB", str(db))
    from compliance_agent.database.models import OrdemBancaria, get_engine, get_session, init_db
    init_db(str(db))
    s = get_session(get_engine(str(db)))
    # espelho TFE: 30 OB de um favorecido que o SIAFE não paga — nada disso pode virar "pago"
    for i in range(30):
        s.add(OrdemBancaria(numero_ob=f"2026OB9{i:04d}", data_emissao=dt.date(2026, 10, 1),
                            favorecido_nome="SÓ NO ESPELHO", favorecido_cpf="99888777000166", valor=1e9))
    s.commit()
    s.close()
    con = sqlite3.connect(db)
    con.execute("DROP TABLE IF EXISTS ob_orcamentaria_siafe")
    con.execute(_SIAFE)
    con.execute("CREATE TABLE IF NOT EXISTS ob_reemitida (ob TEXT NOT NULL, ug TEXT NOT NULL, valor REAL, "
                "PRIMARY KEY (ob, ug))")
    hoje = dt.date.today()
    for i in range(30):
        d = (hoje - dt.timedelta(days=i % 3)).strftime("%d/%m/%Y")
        con.execute("INSERT INTO ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, status_envio, "
                    "credor, nome_credor, valor, exercicio, processo) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (f"{hoje.year}OB{i:05d}", "100100", d, "Contabilizado", "Processado e Pago",
                     CNPJ if i % 2 else "22333444000155", "Fornecedor A" if i % 2 else "Fornecedor B", 10.0 + i,
                     hoje.year, "SEI-080001/000001/2026"))
    con.execute("INSERT INTO ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, status_envio, "
                "tipo_regularizacao, credor, nome_credor, valor, exercicio) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"{hoje.year}OB09999", "100100", hoje.strftime("%d/%m/%Y"), "Contabilizado", "Enviado Manualmente",
                 "Pagamento Complementar", "55666777000188", "COMPLEMENTAR", 5e9, hoje.year))
    con.execute("INSERT INTO ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, status_envio, "
                "credor, nome_credor, valor, exercicio) VALUES (?,?,?,?,?,?,?,?,?)",
                (f"{hoje.year}OB09998", "100100", hoje.strftime("%d/%m/%Y"), "Contabilizado", "Processado e Pago",
                 "CG0004700", "FOLHA DE PAGAMENTOS", 7e9, hoje.year))
    con.commit()
    con.close()
    from rotas import investigacao as R
    monkeypatch.setattr(R, "RAIZ", tmp_path)
    monkeypatch.setattr(R, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(R, "_cache_put", lambda chave, val: val)
    return json.loads(R.api_painel().body)


def test_painel_top_favorecidos_e_obs_recentes_sao_do_siafe(painel):
    nomes = {t["nome"] for t in painel["top_favorecidos"]}
    assert nomes == {"Fornecedor A", "Fornecedor B"}                      # positivo: credores pagos no SIAFE
    assert "SÓ NO ESPELHO" not in nomes and "COMPLEMENTAR" not in nomes   # negativo: espelho e complementar fora
    assert "FOLHA DE PAGAMENTOS" not in nomes                              # folha fica no total, fora do ranking
    assert sum(t["n"] for t in painel["top_favorecidos"]) == 30
    rec = painel["obs_recentes"]
    assert len(rec) == 25 and all(r["favorecido"] != "SÓ NO ESPELHO" for r in rec)
    assert all(r["numero"] != f"{dt.date.today().year}OB09999" for r in rec)   # complementar não é pagamento
    o = painel["obs"]
    assert o["total"] == 31 and painel["obs_recentes_total"] == 31             # 30 fornecedores + folha
    assert o["valor_total"] == round(sum(10.0 + i for i in range(30)) + 7e9, 2)
    assert o["hoje"] == 11 and o["valor_hoje"] == round(sum(10.0 + i for i in range(0, 30, 3)) + 7e9, 2)
    assert o["tfe_total"] == 30                                                # espelho só como confronto, rotulado
    assert "espelho" in painel["fonte_ob"]


def test_processos_de_risco_do_orgao_pagam_pelo_siafe(tmp_path, monkeypatch):
    """/orgao 1-D.1: "Pago (R$)" é OB paga do SIAFE da UG (antes: soma do espelho TFE por numero_sei)."""
    from compliance_agent import correlacao_sei as cs
    db = _base(tmp_path, [
        ("2025OB00001", "100100", "10/03/2025", *PAGA, CNPJ, 300.0),
        ("2025OB00002", "100100", "11/03/2025", "Contabilizado", "Enviado Manualmente", "Pagamento Complementar",
         CNPJ, 99.0),                                                       # complementar: fora
        ("2025OB00003", "200200", "11/03/2025", *PAGA, CNPJ, 77.0),        # outra UG: fora
    ], [("2025OB00001", "100100", "2025-03-10", CNPJ, 5_000.0)])           # espelho: nunca soma
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sei_ficha (numero_sei TEXT, nivel_risco TEXT, objeto TEXT, red_flags TEXT)")
    con.executemany("INSERT INTO sei_ficha VALUES (?,?,?,?)", [
        ("SEI-080001/000001/2025", "alto", "obra", "[]"),        # mesmo processo das OB (grafia igual)
        ("SEI-080001/000077/2025", "medio", "sem OB", "[]")])    # sem pagamento: não entra
    con.commit()
    con.close()
    monkeypatch.setattr(cs, "_DB", db)
    r = cs.processos_risco_de_orgao("100100")
    assert [(x["numero_sei"], x["n_obs"], x["total"]) for x in r] == [("SEI-080001/000001/2025", 1, 300.0)]
    assert cs.processos_risco_de_orgao("999999") == []
