# -*- coding: utf-8 -*-
"""Organização por ano e mês (compliance_agent/periodo.py + periodo_fontes.py + rotas/periodo.py).

Diretriz do dono: "não pode ter margem pra erro em nada". Então o que se testa é o que pode errar:
a soma que não fecha, o mês vazio lido como zero, a OB anulada somada como paga, a data DD/MM/AAAA
agrupada como texto e a esfera misturada. Base 100% sintética (repositório público).
"""
from __future__ import annotations

import random
import sqlite3
from datetime import date

import pytest

from compliance_agent import periodo as P
from compliance_agent import periodo_fontes as F

HOJE = date(2026, 11, 13)


# ── datas ────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v,esp", [
    ("28/12/2023", (2023, 12)), ("01/02/2016", (2016, 2)), ("2024-03-21T00:00:00.000", (2024, 3)),
    ("2026-11-13", (2026, 11)), ("2026-08-10 12:47:43", (2026, 8)), ("07/2025", (2025, 7)),
    (date(2025, 5, 1), (2025, 5)), ("", None), (None, None), ("31/13/2024", None), ("2024-00-10", None),
    ("lixo", None)])
def test_ano_mes_todos_os_formatos_da_casa(v, esp):
    assert P.ano_mes(v) == esp


def test_sql_ano_mes_agrupa_dd_mm_aaaa_por_data_e_nao_por_texto():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE t(d TEXT)")
    con.executemany("INSERT INTO t VALUES(?)", [("01/12/2023",), ("02/01/2016",), ("15/01/2016",), ("xx",)])
    a, m = P.sql_ano_mes("d", "br")
    got = con.execute(f"SELECT {a}, {m}, COUNT(*) FROM t GROUP BY 1,2 ORDER BY 1,2").fetchall()
    assert got == [(None, None, 1), (2016, 1, 2), (2023, 12, 1)]
    with pytest.raises(ValueError):
        P.sql_ano_mes("d; DROP TABLE t", "br")


@pytest.mark.parametrize("ano,mes,esp", [("", "", (None, None)), ("2025", "", (2025, None)),
                                         ("2025", "3", (2025, 3)), (None, None, (None, None))])
def test_validar_aceita(ano, mes, esp):
    assert P.validar(ano, mes) == esp


@pytest.mark.parametrize("ano,mes", [("abc", ""), ("2025", "13"), ("2025", "0"), ("", "3"), ("1800", "")])
def test_validar_recusa_com_motivo(ano, mes):
    with pytest.raises(P.PeriodoInvalido):
        P.validar(ano, mes)


# ── quebra ───────────────────────────────────────────────────────────────────────────────────────
COB = P.Cobertura(inicio=(2024, 3), fim=(2026, 11), anos_sem_coleta=frozenset({2025}), mes_corrente=(2026, 11))


def _linhas_aleatorias(seed):
    rnd = random.Random(seed)
    out = []
    for _ in range(400):
        a = rnd.choice([2024, 2026, None])
        m = rnd.choice(list(range(1, 12))) if a else None
        out.append((a, m, rnd.randint(1, 5), {"pago": rnd.randint(0, 10**12)}))
    return out


@pytest.mark.parametrize("seed", range(5))
def test_soma_dos_meses_e_o_ano_e_a_dos_anos_e_o_total(seed):
    q = P.quebra(_linhas_aleatorias(seed), medidas=["pago"], cobertura=COB)
    tot = 0
    for a in q["anos"]:
        assert sum(m["c"]["pago"] for m in a["meses"]) + a["sem_mes"]["c"]["pago"] == a["c"]["pago"]
        assert sum(m["n"] for m in a["meses"]) + a["sem_mes"]["n"] == a["n"]
        tot += a["c"]["pago"]
    assert tot == q["total_datado"]["c"]["pago"]
    assert tot + q["sem_data"]["c"]["pago"] == q["total_geral"]["c"]["pago"]


def test_centavos_somam_exato_onde_float_erraria():
    linhas = [(2024, 5, 1, {"pago": P.centavos(0.1)}) for _ in range(10)]
    q = P.quebra(linhas, medidas=["pago"], cobertura=COB)
    assert q["total_geral"]["c"]["pago"] == 100 and q["total_geral"]["v"]["pago"] == 1.0


def test_conferir_pega_soma_adulterada():
    q = P.quebra([(2024, 5, 1, {"pago": 100})], medidas=["pago"], cobertura=COB)
    q["anos"][0]["meses"][4]["c"]["pago"] = 99
    with pytest.raises(P.SomaNaoFecha):
        P.conferir(q)


def test_mes_vazio_e_zero_so_dentro_da_cobertura():
    q = P.quebra([(2024, 5, 1, {"pago": 100}), (2026, 2, 1, {"pago": 5})], medidas=["pago"], cobertura=COB)
    a24 = next(a for a in q["anos"] if a["ano"] == 2024)
    st = {m["mes"]: m["status"] for m in a24["meses"]}
    assert st[1] == P.INDISPONIVEL and st[2] == P.INDISPONIVEL     # antes do início da cobertura
    assert st[4] == P.ZERO and st[5] == P.OK                       # coberto: vazio é zero
    a25 = next(a for a in q["anos"] if a["ano"] == 2025)
    assert a25["status"] == P.INDISPONIVEL                          # exercício não coletado ≠ 0
    assert {m["status"] for m in a25["meses"]} == {P.INDISPONIVEL}
    a26 = next(a for a in q["anos"] if a["ano"] == 2026)
    assert len(a26["meses"]) == 11                                  # dezembro ainda não aconteceu
    assert a26["meses"][-1]["status"] == P.INDISPONIVEL            # mês em curso vazio não é zero


def test_fonte_que_sempre_tem_registro_nunca_mostra_zero():
    cob = P.Cobertura(inicio=(2024, 1), fim=(2024, 12), zero_possivel=False)
    q = P.quebra([(2024, 5, 1, {"pago": 1})], medidas=["pago"], cobertura=cob)
    assert {m["status"] for m in q["anos"][0]["meses"] if m["n"] == 0} == {P.INDISPONIVEL}


def test_fonte_anual_nao_inventa_mes():
    cob = P.Cobertura(inicio=(2023, 1), fim=(2025, 12), anos_parciais=frozenset({2025}))
    q = P.quebra([(2023, None, 3, {"pago": 10}), (2025, None, 2, {"pago": 7})], medidas=["pago"],
                 cobertura=cob, granularidade="ano")
    assert [a["status"] for a in q["anos"]] == [P.OK, P.ZERO, P.PARCIAL]
    assert all(a["meses"] is None for a in q["anos"])
    s = P.selecao(q, 2023, 4)
    assert s["status"] == P.INDISPONIVEL and s["v"] is None
    assert P.selecao(q, 2023, None)["v"]["pago"] == 0.1


def test_selecao_e_o_mesmo_numero_da_tabela():
    q = P.quebra([(2024, 5, 2, {"pago": 300}), (2024, 6, 1, {"pago": 50})], medidas=["pago"], cobertura=COB)
    assert P.selecao(q, 2024, 5)["c"]["pago"] == 300
    assert P.selecao(q, 2024, None)["c"]["pago"] == 350
    assert P.selecao(q, None, None)["c"]["pago"] == 350
    assert P.selecao(q, 2019, None)["status"] == P.INDISPONIVEL


def test_cpf_mascarado_cnpj_inteiro():
    assert P.mascarar_doc("12345678901") == "***.456.789-**"
    assert P.mascarar_doc("12.345.678/0001-90") == "12.345.678/0001-90"


# ── fontes sobre base sintética ──────────────────────────────────────────────────────────────────
@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.executescript("""
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT,
        credor TEXT, nome_credor TEXT, valor REAL, exercicio INTEGER);
    CREATE TABLE pcrj_contratos (numero_controle_pncp TEXT, orgao_nome TEXT, unidade TEXT, fornecedor_nome TEXT,
        fornecedor_documento TEXT, objeto TEXT, valor_inicial REAL, valor_global REAL, data_assinatura TEXT);
    CREATE TABLE contrato_aditivo (numero_controle_pncp TEXT, data_assinatura TEXT, valor_acrescido REAL,
        objeto TEXT, numero_termo TEXT, tipo_termo TEXT);
    CREATE TABLE pncp_ente (cnpj TEXT, esfera_id TEXT);
    INSERT INTO pncp_ente VALUES ('11111111000111','E'), ('22222222000122','M');
    """)
    obs = [("1", "100", "05/01/2025", "Contabilizado", "12345678901", "PESSOA", 0.1, 2025),
           ("2", "100", "20/01/2025", "Contabilizado", "33333333000133", "EMPRESA", 0.2, 2025),
           ("3", "100", "03/02/2025", "Anulado", "33333333000133", "EMPRESA", 999.0, 2025),
           ("4", "100", "03/02/2025", "Excluído", "33333333000133", "EMPRESA", 999.0, 2025),
           ("5", "100", "10/12/2024", "Contabilizado", "33333333000133", "EMPRESA", 1000.55, 2024)]
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?)", obs)
    ctr = [("11111111000111-2-000001/2025", "ESTADO DO RIO DE JANEIRO", "SECRETARIA DE ESTADO X", "A", "1", "o", 100, 120, "2025-03-02"),
           ("22222222000122-2-000001/2025", "MUNICIPIO DO RIO DE JANEIRO", "SECRETARIA MUNICIPAL Y", "B", "2", "o", 50, 50, "2025-03-09"),
           ("11111111000111-2-000002/2025", "ESTADO DO RIO DE JANEIRO", "SECRETARIA DE ESTADO X", "C", "3", "o", 7, 7, None)]
    c.executemany("INSERT INTO pcrj_contratos VALUES (?,?,?,?,?,?,?,?,?)", ctr)
    c.executemany("INSERT INTO contrato_aditivo VALUES (?,?,?,?,?,?)",
                  [("11111111000111-2-000001/2025", "2025-04-01", 20, "acr", "1", ""),
                   ("22222222000122-2-000001/2025", "2025-04-02", 5, "acr", "1", "")])
    c.commit()
    yield c
    c.close()


def test_ob_so_conta_contabilizada_e_agrupa_dd_mm_aaaa(con):
    d = F.calcular(con, "ob_siafe", HOJE)
    q = d["quebra"]
    a25 = next(a for a in q["anos"] if a["ano"] == 2025)
    assert a25["c"]["pago"] == 30                                   # 0,10 + 0,20 — anulada/excluída fora
    assert a25["meses"][0]["c"]["pago"] == 30 and a25["meses"][0]["n"] == 2
    assert len(a25["meses"]) == 1                                   # fev só com anulada: fora da cobertura…
    assert P.selecao(q, 2025, 2)["status"] == P.INDISPONIVEL        # …e o filtro diz INDISPONÍVEL, não "pago 0"
    assert next(a for a in q["anos"] if a["ano"] == 2024)["meses"][11]["c"]["pago"] == 100055
    assert q["total_geral"]["c"]["pago"] == 100085
    fora = {x["status"]: x["valor"] for x in d["extra"]["fora_do_pago"]}
    assert fora == {"Anulado": 999.0, "Excluído": 999.0}
    it = F.FONTES["ob_siafe"].itens(con, 2025, 1)
    assert [x["doc"] for x in it] == ["33333333000133", "***.456.789-**"]


def test_contratos_e_aditivos_nao_misturam_esfera(con):
    est = F.calcular(con, "contratos_estado", HOJE)["quebra"]
    pref = F.calcular(con, "contratos_prefeitura", HOJE)["quebra"]
    assert est["total_datado"]["c"]["valor_inicial"] == 10000 and est["sem_data"]["n"] == 1
    assert pref["total_geral"]["c"]["valor_inicial"] == 5000
    assert [x["nome"] for x in F.FONTES["contratos_estado"].itens(con, 2025, 3)] == ["A"]
    assert F.calcular(con, "aditivos_estado", HOJE)["quebra"]["total_geral"]["c"]["valor_acrescido"] == 2000
    assert F.calcular(con, "aditivos_prefeitura", HOJE)["quebra"]["total_geral"]["c"]["valor_acrescido"] == 500


def test_toda_fonte_declara_esfera_medida_e_campo_de_data():
    for f in F.FONTES.values():
        assert f.esfera in ("estado", "prefeitura", "transversal")
        assert f.campo_data and f.origem and f.granularidade in ("mes", "ano")
        assert set(f.rotulos_medidas) == set(f.medidas)
    # "pago" só existe na fonte de OB; relatório anual usa outro nome
    assert [f.id for f in F.FONTES.values() if "pago" in f.medidas] == ["ob_siafe"]


# ── rota ─────────────────────────────────────────────────────────────────────────────────────────
def test_rota_valida_e_recorta(con, monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import rotas.investigacao as inv
    import rotas.periodo as rp
    db = tmp_path / "base.db"
    dst = sqlite3.connect(db)
    con.backup(dst)
    dst.close()
    monkeypatch.setattr(rp, "_con", lambda: sqlite3.connect(db))
    monkeypatch.setattr(inv, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(inv, "_cache", {})
    app = FastAPI()
    app.include_router(rp.router)
    cli = TestClient(app)
    assert cli.get("/api/periodo/ob_siafe?mes=3").status_code == 400
    assert cli.get("/api/periodo/ob_siafe?ano=2025&mes=13").status_code == 400
    assert cli.get("/api/periodo/nao_existe").status_code == 404
    r = cli.get("/api/periodo/ob_siafe?ano=2025&mes=1").json()
    assert r.get("ok"), r
    assert r["ok"] and r["selecao"]["c"]["pago"] == 30 and r["filtro"]["rotulo"] == "jan/2025"
    assert len(r["itens"]) == 2
    r0 = cli.get("/api/periodo/ob_siafe").json()
    assert r0["itens"] is None and r0["selecao"]["c"]["pago"] == 100085
    assert {f["id"] for f in cli.get("/api/periodo/fontes").json()["fontes"]} == set(F.FONTES)
