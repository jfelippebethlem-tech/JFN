# -*- coding: utf-8 -*-
"""E18 `observar` (O8.1): contrato do estágio, sensores novos (captura útil, duplicidade, cobertura, prova numérica,
espera p50/p95, custo por processo, fp_medida, restauração lida de fluxo.metricas) e estado honesto.

Três garantias: sem dado ⇒ INDISPONIVEL (nunca 0, nunca ok); disco por TENDÊNCIA; SLO estourado ⇒ o estado que o
config/slos.yaml declara. As partes de PG rodam em esquemas temporários (tests/fluxo_pg.py) — nunca no real."""
import json
import math
import time
import uuid
from datetime import datetime, timezone

import pytest

from compliance_agent.aplicacao.estagios import observar as O
from compliance_agent.fluxo import sensores as S
from tests.fluxo_pg import DSN, con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures

SLOS = S.carregar_slos()


def _estado(sensor: str, valor, forcado=None) -> str:
    return S.avaliar(SLOS.por_sensor()[sensor][1], valor, forcado)[0]


# ── contrato ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_estagio_observar_e_o_modulo_proprio_e_as_rotinas_chamam_o_estagio():
    from compliance_agent.aplicacao.estagios import REGISTRO, estagio_de
    from compliance_agent.fluxo import grafo as G
    assert estagio_de("observar") is O.ESTAGIO and "observar" not in REGISTRO
    assert O.ESTAGIO.recursos == ["cpu_leve"] and O.ESTAGIO.volta == {"nos": ["vm1", "vm2"]}
    g = G.carregar()
    for no in S.NOS_FLUXO:
        r = g.rotinas[f"observar_{no}"]
        assert r.comando[2] == "compliance_agent.aplicacao.estagios.observar" and r.comando[-1] == no
        assert not r.ativa and "O9.0" in (r.bloqueio or "")                  # parada de obras: nada religado


def test_todo_sensor_novo_tem_slo_e_grupo():
    julgados = set(SLOS.por_sensor())
    for nome in ("captura.util_pct", "captura.duplicidade_pct", "cobertura.docs_com_versao_pct",
                 "prova.fatos_verificados_pct", "fila.espera_p95_s", "llm.custo_por_processo_usd",
                 "detectores.fp_medida_pct", "detectores.fp_acima_teto", "restauracao.pg_idade_h",
                 "itcampo.alcancavel"):
        assert nome in julgados, nome
        assert any(nome in g.nomes for g in S.GRUPOS.values()), nome
    assert {"captura", "prova"} <= set(S.grupos_do_no("vm2", SLOS))           # PG mora na VM-2
    assert {"custo_processo", "detectores"} <= set(S.grupos_do_no("vm1", SLOS))


# ── sem dado ⇒ INDISPONIVEL ────────────────────────────────────────────────────────────────────────────────────
def test_sem_dado_e_indisponivel_nunca_zero():
    assert S.captura_util(0, 0, 0, 0) == (None, None)                       # sem captura: não há o que julgar
    assert S.pct(0, 0) is None and S.pct(0, 10) == 0.0                      # zero medido é valor
    assert S.custo_por_processo(None, 0, 10)[0] is None
    assert S.custo_por_processo(0.0, 0, 10)[0] is None                      # gateway calado ≠ custo zero
    assert S.custo_por_processo(3.0, 5, 0)[0] is None                       # sem denominador
    assert S.custo_por_processo(3.0, 5, 6)[0] == 0.5
    assert S.fp_de_detector({"fp_medida": None})[0] is None
    assert S.restauracao_de_linhas(None, None, {}, "itcampo", time.time()) is None
    assert S.restauracao_de_linhas(None, time.time(), {"execucao": "x"}, "itcampo", time.time()).valor is None
    est = S.estado_slos([], SLOS)
    assert est["estado"] == "INDISPONIVEL" and est["contagem"]["INDISPONIVEL"] == est["total"]
    # linha gravada com NaN é INDISPONIVEL com o motivo do sensor, não 0
    ln = {"no": "vm2", "nome": "prova.fatos_verificados_pct", "valor": float("nan"), "quando": time.time(),
          "rotulos": {"motivo": "nenhum fato gravado pelo E8"}}
    item = [i for i in S.estado_slos([ln], SLOS)["itens"] if i["slo"] == "prova_numerica"][0]
    assert item["estado"] == "INDISPONIVEL" and item["motivo"] == "nenhum fato gravado pelo E8"


def test_fp_por_detector_so_conta_medida_valida():
    hoje = datetime.now().date().isoformat()
    base = {"data": hoje, "amostra": "a", "taxa": "t", "fonte_primaria": "f", "onde": "o", "estratificada": False,
            "cobertura": None}
    assert S.fp_de_detector({"fp_medida": {**base, "n": 20, "falsos": 5}})[0] == 25.0
    assert S.fp_de_detector({"fp_medida": {**base, "n": 0, "falsos": 0}})[0] is None
    assert S.fp_de_detector({"fp_medida": {**base, "data": "2020-01-01", "n": 20, "falsos": 1}})[0] is None   # vencida


def test_grupo_detectores_do_registro_real():
    ctx = S.Ctx(no="vm1", con=None, agora=datetime.now(timezone.utc))
    v = S.g_detectores(ctx)
    cob = [x for x in v if x.nome == "detectores.fp_medida_pct"][0]
    det = [x for x in v if x.nome == "detector.fp_taxa_pct"]
    assert cob.valor is not None and cob.rotulos["ativos"] == len(det) > 0
    assert len([d for d in det if d.valor is not None]) == len(cob.rotulos["medidos"])
    assert all(d.motivo for d in det if d.valor is None)                    # não medido sempre diz por quê


# ── SLO estourado ⇒ estado do yaml ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sensor,valor,forcado,esperado", [
    ("captura.duplicidade_pct", 10, None, "SAUDAVEL"),
    ("captura.duplicidade_pct", 60, None, "DEGRADADO"),
    ("captura.util_pct", 10, None, "DEGRADADO"),
    ("cobertura.docs_com_versao_pct", 99, None, "SAUDAVEL"),
    ("prova.fatos_verificados_pct", 50, None, "DEGRADADO"),
    ("fila.espera_p95_s", 300, None, "SAUDAVEL"),
    ("fila.espera_p95_s", 1800, None, "DEGRADADO"),
    ("fila.espera_p95_s", 4000, None, "ATRASADO"),
    ("llm.custo_por_processo_usd", 5, None, "DEGRADADO"),
    ("detectores.fp_acima_teto", 0, None, "SAUDAVEL"),
    ("restauracao.pg_idade_h", 24, None, "SAUDAVEL"),
    ("restauracao.pg_idade_h", 400, None, "ATRASADO"),
    ("restauracao.pg_idade_h", 1, "BLOQUEADO", "BLOQUEADO"),               # restauração falhou: o sensor afirma
    ("disco.tendencia_pp_dia", 3, None, "DEGRADADO"),
    ("itcampo.alcancavel", 0, None, "DEGRADADO"),                          # sumiu da rede: modo sem it-campo
    ("itcampo.alcancavel", 1, None, "SAUDAVEL"),
])
def test_slo_estourado_da_o_estado_declarado(sensor, valor, forcado, esperado):
    assert _estado(sensor, valor, forcado) == esperado


def test_restauracao_falhou_e_bloqueado_e_ok_da_idade():
    agora = time.time()
    r = S.restauracao_de_linhas(0.0, agora - 7200, {"execucao": "e1", "falhas": ["pg"]}, "itcampo", agora)
    assert r.valor == 2.0 and r.forcado == "BLOQUEADO" and "FALHOU" in r.motivo and "pg" in r.motivo
    r = S.restauracao_de_linhas(1.0, agora - 3600, {"execucao": "e2"}, "itcampo", agora)
    assert r.valor == 1.0 and r.forcado is None and r.rotulos["no_restauracao"] == "itcampo"


def test_alcance_do_itcampo_sem_rede_e_zero_medido_e_sem_ssh_indisponivel(monkeypatch):
    import subprocess
    ctx = S.Ctx(no="vm1", con=None, agora=datetime.now(timezone.utc))
    monkeypatch.setattr(S.shutil, "which", lambda n: "/usr/bin/ssh")
    monkeypatch.setattr(S.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 255, "", "timed out"))
    r = S.g_alcance(ctx)[0]
    assert r.valor == 0.0 and "não respondeu" in r.motivo
    monkeypatch.setattr(S.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    assert S.g_alcance(ctx)[0].valor == 1.0
    monkeypatch.setattr(S.shutil, "which", lambda n: None)
    assert S.g_alcance(ctx)[0].valor is None


def test_quadro_de_texto_lista_cada_slo():
    est = S.estado_slos([], SLOS)
    q = O.quadro(est)
    assert q.startswith("estado global: INDISPONIVEL") and "prova_numerica" in q and "captura_util" in q


# ── PG (esquemas temporários) ──────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def evid(monkeypatch):
    """Esquema de evidências temporário com o mínimo que os sensores leem (aquisicao, versoes, documentos, arvores,
    arvore_leitura, fatos, leituras)."""
    import psycopg
    nome = f"tmp_evid_{uuid.uuid4().hex[:10]}"
    c = psycopg.connect(DSN, autocommit=True)
    c.execute(f'CREATE SCHEMA "{nome}"')
    c.execute(f'SET search_path TO "{nome}"')
    c.execute("CREATE TABLE aquisicao(id text PRIMARY KEY, fonte text, detalhe jsonb, concluida_em timestamptz)")
    c.execute("CREATE TABLE versoes(processo text, doc_id text, sha256 text, vista_em text, aquisicao_id text, "
              "PRIMARY KEY (processo, doc_id, sha256))")
    c.execute("CREATE TABLE documentos(processo text, doc_id text, restrito boolean, PRIMARY KEY (processo, doc_id))")
    c.execute("CREATE TABLE arvores(processo text, hash text)")
    c.execute("CREATE TABLE fatos(id bigserial, processo text, estado text)")
    c.execute("CREATE TABLE leituras(processo text, em text)")
    monkeypatch.setenv(S.ENV_ESQUEMA_CAPTURA, nome)
    monkeypatch.setenv(S.ENV_ESQUEMA_FATOS, nome)
    try:
        yield c
    finally:
        c.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')
        c.close()


def _ctx(con, no="vm2"):
    return S.Ctx(no=no, con=con, agora=datetime.now(timezone.utc))


@precisa_pg
def test_captura_util_duplicidade_e_cobertura_no_pg(con, evid):
    v = {x.nome: x for x in S.g_captura(_ctx(con))}
    assert v["captura.util_pct"].valor is None and v["captura.duplicidade_pct"].valor is None   # nada capturado
    assert v["cobertura.docs_com_versao_pct"].valor is None                                      # nada na árvore
    assert v["cobertura.e3_pendentes_docs"].valor is None                                        # sem arvore_leitura
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    evid.execute("INSERT INTO aquisicao VALUES ('a1', 'sei:e3', '{\"capturados\": 4}', now()), "
                 "('a2', 'sei:e3', '{\"capturados\": 2}', now()), ('velha', 'sei:e3', '{\"capturados\": 9}', "
                 "now() - interval '3 days')")
    evid.execute("INSERT INTO versoes VALUES ('p', 'd1', 's1', %s, 'a1'), ('p', 'd2', 's2', %s, 'a1'), "
                 "('p', 'd3', 's3', '2026-01-01 00:00:00', 'velha')", (agora, agora))
    evid.execute("INSERT INTO documentos VALUES ('p', 'd1', false), ('p', 'd2', false), ('p', 'd3', false), "
                 "('p', 'd4', false), ('p', 'r1', true)")
    evid.execute("INSERT INTO arvores VALUES ('p', 'h')")
    v = {x.nome: x for x in S.g_captura(_ctx(con))}
    assert v["captura.util_pct"].valor == pytest.approx(33.33)              # 2 novas ÷ 6 baixados na janela
    assert v["captura.duplicidade_pct"].valor == 50.0                       # a2 não trouxe versão nova
    assert v["captura.versoes_novas_24h"].valor == 2.0
    assert v["cobertura.docs_com_versao_pct"].valor == 75.0                 # 3 de 4 (o restrito fica fora)
    assert _estado("captura.duplicidade_pct", 50.0) == "DEGRADADO"
    assert _estado("cobertura.docs_com_versao_pct", 75.0) == "DEGRADADO"


@precisa_pg
def test_prova_numerica_e_custo_por_processo_no_pg(con, evid, tmp_path, monkeypatch):
    assert S.g_prova(_ctx(con))[0].valor is None                            # sem fato: INDISPONIVEL
    evid.execute("INSERT INTO fatos(processo, estado) SELECT 'p', 'VERIFICADO' FROM generate_series(1, 7)")
    evid.execute("INSERT INTO fatos(processo, estado) VALUES ('p', 'INDISPONIVEL'), ('p', 'A_CONFIRMAR_OCR'), "
                 "('p', 'INDETERMINADO_FALHA_CITACAO')")
    p = S.g_prova(_ctx(con))[0]
    assert p.valor == 70.0 and p.rotulos["total"] == 10 and _estado(p.nome, p.valor) == "DEGRADADO"
    # custo por processo: trace do gateway na pasta de dados de teste
    import sqlite3
    monkeypatch.setenv("JFN_DATA_DIR", str(tmp_path))
    t = sqlite3.connect(tmp_path / "llm_trace.db")
    t.execute("CREATE TABLE llm_trace(ts TEXT, origem TEXT, pago INT, custo_usd REAL)")
    t.commit()
    c = S.g_custo_processo(_ctx(con, "vm1"))[0]
    assert c.valor is None and "gateway sem chamada" in c.motivo            # trace vazio ≠ custo zero
    mes = datetime.now(timezone.utc).strftime("%Y-%m")
    t.execute("INSERT INTO llm_trace VALUES (?, 'gateway', 1, 1.5), (?, 'gateway', 0, 9.0)",
              (f"{mes}-02 10:00:00", f"{mes}-02 11:00:00"))
    t.commit()
    t.close()
    evid.execute("INSERT INTO leituras VALUES ('p1', %s), ('p2', %s), ('p2', %s)",
                 (f"{mes}-02 10:00:00",) * 3)
    c = S.g_custo_processo(_ctx(con, "vm1"))[0]
    assert c.valor == 0.75 and c.rotulos["processos_lidos"] == 2           # só o pago, ÷ processos distintos


@precisa_pg
def test_espera_p50_p95_por_tipo_e_fila_vazia_medida(con):
    ctx = _ctx(con, "vm1")
    v = {x.nome: x for x in S.g_fila(ctx) if "por_tipo" not in x.nome}
    assert v["fila.espera_p95_s"].valor == 0.0 and v["fila.espera_p95_s"].rotulos["fila_vazia"]
    for i, h in enumerate((1, 2, 3, 4, 100)):
        con.execute("INSERT INTO jobs(tipo, chave, estado, disponivel_em) VALUES ('a', %s, 'fila', now() - "
                    "make_interval(secs => %s))", (f"a:{i}", h * 60))
    con.execute("INSERT INTO jobs(tipo, chave, estado, disponivel_em) VALUES ('b', 'b:1', 'fila', now() - "
                "interval '10 seconds'), ('a', 'a:futuro', 'fila', now() + interval '1 hour')")
    ls = S.g_fila(ctx)
    g = {x.nome: x for x in ls if "por_tipo" not in x.nome}
    assert g["fila.espera_p95_s"].rotulos["jobs"] == 6                      # o futuro não é elegível
    assert g["fila.espera_p50_s"].valor == pytest.approx(150, abs=5)
    por = {(x.nome, x.rotulos["tipo"]): x.valor for x in ls if "por_tipo" in x.nome and "espera" in x.nome}
    assert por[("fila.espera_p50_s.por_tipo", "a")] == pytest.approx(180, abs=5)
    assert por[("fila.espera_p95_s.por_tipo", "a")] > 3000 and por[("fila.espera_p95_s.por_tipo", "b")] < 60
    assert _estado("fila.espera_p95_s", g["fila.espera_p95_s"].valor) in ("DEGRADADO", "ATRASADO")


@precisa_pg
def test_restauracao_lida_de_fluxo_metricas_e_nao_mais_nunca_rodou(con, tmp_path):
    ctx = S.Ctx(no="vm1", con=con, agora=datetime.now(timezone.utc), raiz=tmp_path)
    assert S._restauracao_metricas(con, time.time()) is None
    from tools import restauracao_semanal as R
    res = {"ok": True, "quando_epoch": time.time() - 3 * 3600, "pasta": "x", "host": "h", "falhas": [], "partes": {}}
    assert R.gravar(res, "itcampo", con)["conferidas"] == 2
    r = [x for x in S.g_backup(ctx) if x.nome == "restauracao.pg_idade_h"][0]
    assert r.valor == pytest.approx(3.0, abs=0.05) and r.rotulos["resultado"] == "ok"
    assert _estado(r.nome, r.valor, r.forcado) == "SAUDAVEL"
    R.gravar({**res, "ok": False, "falhas": ["sqlite"], "quando_epoch": time.time() - 60}, "itcampo", con)
    r = [x for x in S.g_backup(ctx) if x.nome == "restauracao.pg_idade_h"][0]
    assert r.forcado == "BLOQUEADO" and _estado(r.nome, r.valor, r.forcado) == "BLOQUEADO"


@precisa_pg
def test_tendencia_de_disco_no_pg_e_no_no_sem_psycopg(con):
    # série de disco.livre_pct do itcampo caindo 2 pp/dia (uso subindo)
    for h, livre in ((48, 60.0), (24, 58.0)):
        con.execute("INSERT INTO metricas(no, nome, valor, quando) VALUES ('itcampo', 'disco.livre_pct', %s, "
                    "now() - make_interval(hours => %s))", (livre, h))
    t = S.tendencia_disco(con, "itcampo", 56.0, time.time())
    assert t.valor == pytest.approx(2.0, abs=0.01) and _estado(t.nome, t.valor) == "DEGRADADO"
    assert S.tendencia_disco(con, "vm2", 50.0, time.time()).valor is None   # sem série: INDISPONIVEL
    # nó sem psycopg mede sem PG; quem grava completa a tendência pela série
    m = S.medir(None, "itcampo", SLOS, grupos=["disco"])
    linhas = {ln[1]: ln for ln in m["linhas"]}
    assert math.isnan(linhas["disco.tendencia_pp_dia"][2])
    r = S.gravar_medidas(con, json.loads(json.dumps(m)), SLOS)
    assert r["gravadas"] == r["conferidas"] == 2
    v, rot = con.execute("SELECT valor, rotulos FROM metricas WHERE nome = 'disco.tendencia_pp_dia' AND "
                         "rotulos->>'coleta' = %s", (m["coleta"],)).fetchone()
    assert not math.isnan(v) and rot["medido_sem_pg"] is True and rot["estado"] in S.ORDEM


@precisa_pg
def test_estagio_handler_e_efeito_pelo_contrato(con, esquema_tmp, monkeypatch):
    from compliance_agent.aplicacao.estagios import Contexto
    from compliance_agent.fluxo.fila import ENV_ESQUEMA, Resultado
    monkeypatch.setenv(ENV_ESQUEMA, esquema_tmp)
    monkeypatch.setattr(S, "GRUPOS", {"t": S.Grupo(lambda c: [S.Leitura("fila.espera_p95_s", 7000.0),
                                                              S.nao_mediu("captura.util_pct", "fonte fora")],
                                                   ("fila.espera_p95_s", "captura.util_pct"))})
    ctx = Contexto(no="vm2", tipo="observar", chave="observar:vm2", ficha=11, tentativa=1)
    r = O.ESTAGIO.handler({}, ctx)
    assert r.efeito["coleta"] == "observar:vm2#11" and r.efeito["gravadas"] == 2
    assert r.eventos == [{"fonte": "observar", "tipo": "metricas", "chave": "observar:vm2#11"}]
    assert O.ESTAGIO.efeito({}, ctx, r) is True
    assert O.ESTAGIO.efeito({}, ctx, Resultado(efeito={**r.efeito, "gravadas": 3})) is False
    est = {i["slo"]: i for i in S.estado_slos(S.ler_ultimos(con, SLOS), SLOS)["itens"]}
    assert est["fila_espera_p95"]["estado"] == "ATRASADO"                  # estourou o degradado (3600 s)
    assert est["captura_util"]["estado"] == "INDISPONIVEL" and est["captura_util"]["motivo"] == "fonte fora"
