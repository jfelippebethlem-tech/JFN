# -*- coding: utf-8 -*-
"""GET /api/sistema/slos (O8.1): estado por SLO a partir de fluxo.metricas e estado global honesto.

TestClient num app só com o router de rotas/sistema.py (sem subir o `server`). Sem PG: INDISPONIVEL com motivo, nunca
zero nem 'ok'. Com PG: esquema TEMPORÁRIO (tests/fluxo_pg.py), nunca o `fluxo` real."""
import pytest

from compliance_agent.evidencias import ENV_DSN
from compliance_agent.fluxo import sensores as S
from compliance_agent.fluxo.fila import ENV_ESQUEMA
from tests.fluxo_pg import con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures


def _cliente():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from rotas.sistema import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


SLOS_T = S.Slos(versao=1, slos={
    "disco": S.Slo(sensor="disco.livre_pct", descricao="disco livre", unidade="%", sentido="min", saudavel=25,
                   degradado=10, pior="BLOQUEADO", janela_s=1800, escopo="maquina", nos=["vm1", "vm2"], dono="infra",
                   severidade="critica", fonte="teste", runbook="nenhum", remediar="porta única do armazenamento"),
    "fila": S.Slo(sensor="fila.idade_max_s", descricao="espera da fila", unidade="s", sentido="max", saudavel=900,
                  pior="ATRASADO", janela_s=1800, escopo="global", nos=["vm1"], dono="fluxo", severidade="alta",
                  fonte="teste", runbook="nenhum", remediar="ver nós vivos"),
})


def test_sem_pg_e_indisponivel_nunca_zero(monkeypatch):
    monkeypatch.delenv(ENV_DSN, raising=False)
    r = _cliente().get("/api/sistema/slos")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False and d["estado"] == "INDISPONIVEL" and "inacessível" in d["motivo"]
    assert d["itens"] and all(i["estado"] == "INDISPONIVEL" and i["valor"] is None for i in d["itens"])
    assert d["total"] == len(d["itens"]) and d["contagem"]["INDISPONIVEL"] == d["total"]


def test_slos_yaml_invalido_e_500(monkeypatch, tmp_path):
    ruim = tmp_path / "slos.yaml"
    ruim.write_text("versao: 1\nslos: {x: {sensor: a.b}}\n", encoding="utf-8")
    monkeypatch.setattr(S, "CAMINHO_SLOS", ruim)
    r = _cliente().get("/api/sistema/slos")
    assert r.status_code == 500 and r.json()["estado"] == "INDISPONIVEL"


def test_so_leitura_metodo_de_escrita_nao_existe():
    assert _cliente().post("/api/sistema/slos").status_code == 405


@precisa_pg
def test_com_pg_julga_ultima_linha_e_estado_global(con, esquema_tmp, monkeypatch):
    monkeypatch.setenv(ENV_ESQUEMA, esquema_tmp)
    monkeypatch.setattr(S, "carregar_slos", lambda caminho=None: SLOS_T)
    ins = "INSERT INTO metricas(no, nome, valor, quando, rotulos) VALUES (%s, %s, %s, now() - make_interval(secs => %s), %s)"
    con.execute(ins, ("vm1", "disco.livre_pct", 50.0, 600, "{}"))              # mais velha: perde para a de baixo
    con.execute(ins, ("vm1", "disco.livre_pct", 16.0, 10, "{}"))               # 16% livre ⇒ DEGRADADO
    con.execute(ins, ("vm2", "disco.livre_pct", float("nan"), 10, '{"motivo": "df falhou"}'))   # não mediu
    con.execute(ins, ("vm2", "fila.idade_max_s", 4000.0, 30, "{}"))            # global, medida por qualquer nó
    d = _cliente().get("/api/sistema/slos").json()
    assert d["ok"] is True
    it = {(i["slo"], i["no"]): i for i in d["itens"]}
    assert it[("disco", "vm1")]["estado"] == "DEGRADADO" and it[("disco", "vm1")]["valor"] == 16.0
    assert it[("disco", "vm2")]["estado"] == "INDISPONIVEL" and it[("disco", "vm2")]["valor"] is None
    assert it[("disco", "vm2")]["motivo"] == "df falhou"
    assert it[("fila", "vm2")]["estado"] == "ATRASADO" and it[("fila", "vm2")]["escopo"] == "global"
    assert d["estado"] == "ATRASADO" and d["nao_medidos"] == ["disco@vm2"]
    # medida velha (além da janela) não é 'ok'
    con.execute("UPDATE metricas SET quando = now() - interval '2 hours'")
    d = _cliente().get("/api/sistema/slos").json()
    assert d["estado"] == "INDISPONIVEL" and all(i["estado"] == "INDISPONIVEL" for i in d["itens"])


@precisa_pg
def test_com_pg_slos_reais_sem_linha_sao_indisponiveis(con, esquema_tmp, monkeypatch):
    monkeypatch.setenv(ENV_ESQUEMA, esquema_tmp)
    d = _cliente().get("/api/sistema/slos").json()
    assert d["ok"] is True and d["estado"] == "INDISPONIVEL"
    assert {i["slo"] for i in d["itens"]} == set(S.carregar_slos().slos)
    assert pytest.approx(d["contagem"]["INDISPONIVEL"]) == d["total"]
