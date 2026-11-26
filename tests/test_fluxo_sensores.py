# -*- coding: utf-8 -*-
"""Sensores do E18 `observar` (O8.1): funções puras, contrato dos SLOs e coleta gravando em fluxo.metricas.

As partes de PG rodam SEMPRE num esquema temporário (tests/fluxo_pg.py) — nunca no `fluxo` real."""
import json
import math
import time
from datetime import datetime, timedelta, timezone

import pytest

from compliance_agent.fluxo import grafo as G
from compliance_agent.fluxo import sensores as S
from tests.fluxo_pg import DSN, con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures

PSI = "some avg10=1.50 avg60=42.00 avg300=3.00 total=1\nfull avg10=0.00 avg60=6.00 avg300=0.00 total=0\n"
MEMINFO = "MemTotal: 12000000 kB\nMemAvailable: 2097152 kB\nSwapTotal: 4194304 kB\nSwapFree: 1048576 kB\n"


def _slo(**kw):
    base = dict(sensor="x.y", descricao="teste de slo", unidade="u", sentido="max", saudavel=10, degradado=20,
                pior="ATRASADO", janela_s=600, escopo="maquina", nos=["vm1"], dono="t", severidade="media",
                fonte="teste", runbook="nenhum", remediar="nada a fazer")
    base.update(kw)
    return S.Slo(**base)


def _slos(**slos):
    return S.Slos(versao=1, slos=slos)


# ── puras ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_psi_le_avg60_e_ausencia_nao_vira_zero():
    assert S.psi(PSI, "some") == 42.0 and S.psi(PSI, "full") == 6.0
    assert S.psi("", "some") is None                                        # kernel sem PSI: não mediu
    assert S.psi("some avg10=1.0 avg60=2.0", "full") is None                # /proc/pressure/cpu antigo sem `full`


def test_meminfo_swap_e_memoria():
    m = S.meminfo(MEMINFO)
    assert S.swap_pct(m) == 75.0 and S.mem_disponivel_gb(m) == 2.0
    assert S.swap_pct(S.meminfo("MemAvailable: 1 kB")) is None               # sem SwapTotal: INDISPONIVEL, não 0
    assert S.swap_pct(S.meminfo("SwapTotal: 0 kB\nSwapFree: 0 kB")) == 0.0   # sem swap configurado é 0 medido


def test_tendencia_exige_serie_e_da_pp_por_dia():
    t0 = 1_800_000_000
    assert S.tendencia_pp_dia([(t0, 50.0)]) is None
    assert S.tendencia_pp_dia([(t0, 50.0), (t0 + 60, 51.0)]) is None        # janela < 1 h
    assert S.tendencia_pp_dia([(t0, 50.0), (t0 + 43200, 51.0), (t0 + 86400, 52.0)]) == pytest.approx(2.0)


def test_avaliar_limites_sentido_e_forcado():
    s = _slo()
    assert S.avaliar(s, 5)[0] == "SAUDAVEL" and S.avaliar(s, 15)[0] == "DEGRADADO" and S.avaliar(s, 25)[0] == "ATRASADO"
    assert S.avaliar(s, None)[0] == "INDISPONIVEL" and S.avaliar(s, float("nan"))[0] == "INDISPONIVEL"
    assert S.avaliar(s, 0)[0] == "SAUDAVEL"                                  # zero MEDIDO é valor, não ausência
    assert S.avaliar(s, 5, "BLOQUEADO")[0] == "BLOQUEADO"                    # o sensor afirma pior: prevalece
    assert S.avaliar(s, 25, "DEGRADADO")[0] == "ATRASADO"                    # forçado nunca melhora
    m = _slo(sentido="min", saudavel=25, degradado=10, pior="BLOQUEADO")
    assert [S.avaliar(m, v)[0] for v in (30, 12, 5)] == ["SAUDAVEL", "DEGRADADO", "BLOQUEADO"]
    with pytest.raises(ValueError):
        _slo(sentido="min", saudavel=10, degradado=20)                       # limite do lado errado


def test_logs_de_backup():
    pg = ("2026-11-23 02:40:02 dump ok: 10 bytes\n2026-11-23 02:40:51 armazenamento rc=0\n"
          "2026-11-24 02:40:02 dump ok: 10 bytes\n2026-11-24 02:41:00 armazenamento rc=1\n")
    assert S.ultimo_dump_guardado(pg) == datetime(2026, 11, 23, 2, 40, 2)    # dump sem cópia guardada não conta
    assert S.ultimo_dump_guardado("2026-11-24 02:40:02 pg_dump falhou") is None
    cb = ("[backup] ✓ off-box: b2:x/compliance/compliance-20261115-035001.db.gz (rotação)\n"
          "[backup] ✓ off-box: b2:x/compliance/compliance-20261122-035001.db.gz (rotação)\n")
    assert S.ultimo_backup_compliance(cb) == datetime(2026, 11, 22, 3, 50, 1)
    # 25/11/2026: o backup sobe cifrado (.db.gz.age) — o sensor continua vendo a data
    cb += "[backup] ✓ off-box: gdrive+r2:vm1/JFN/data/backups/compliance-20261125-031501.db.gz.age (porta única, cifrado)\n"
    assert S.ultimo_backup_compliance(cb) == datetime(2026, 11, 25, 3, 15, 1)


def test_restauracao_nunca_rodou_falhou_e_ok(tmp_path):
    agora = datetime(2026, 11, 24, 12, 0, 0)
    assert S._restauracao(tmp_path / "nada.json", agora).valor is None
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"estado": "falhou", "em": "2026-11-24 10:00:00", "detalhe": "contagem divergiu"}))
    r = S._restauracao(p, agora)
    assert r.valor == 2.0 and r.forcado == "BLOQUEADO" and "FALHOU" in r.motivo
    p.write_text(json.dumps({"estado": "ok", "em": "2026-11-20 12:00:00", "detalhe": {}}))
    assert S._restauracao(p, agora).valor == 96.0 and S._restauracao(p, agora).forcado is None


def test_razao_opus_e_custo_do_mes():
    assert S.razao_opus(100, 50)[0] == 0.5 and S.razao_opus(0, 0)[0] == 1.0
    v, partes, _ = S.custo_mes(None, 0, 5.0, {"desde": "2026-11-13T16:38:34", "total_usd": 45.0}, "2026-11")
    assert v == 50.0 and partes["claude_api_usd"] == 45.0
    v, _, motivo = S.custo_mes(None, 0, 5.0, {"desde": "2026-10-02T00:00:00", "total_usd": 90.0}, "2026-11")
    assert v is None and "cumulativo" in motivo                              # não separável: não mediu, nunca 5,0
    assert S.custo_mes(12.0, 3, 1.0, {"desde": "2026-11-01", "total_usd": 99}, "2026-11")[0] == 13.0  # sem dupla


def test_estado_slos_global_honesto_janela_e_aplica_se():
    agora = 1_800_000_000.0
    slos = _slos(a=_slo(sensor="a.x"), b=_slo(sensor="b.x", nos=["vm1", "vm2"]),
                 c=_slo(sensor="c.x", sentido="min", saudavel=1, degradado=None, pior="ATRASADO", escopo="global",
                        aplica_se={"sensor": "a.x", "maior_que": 0}))
    linha = lambda no, nome, v, idade=0, **r: {"no": no, "nome": nome, "valor": v, "quando": agora - idade,  # noqa: E731
                                                "rotulos": r}
    # nada medido ⇒ INDISPONIVEL global
    assert S.estado_slos([], slos, agora)["estado"] == "INDISPONIVEL"
    # tudo saudável mas b@vm2 sem medida ⇒ DEGRADADO (não dá para dizer saudável sem olhar tudo)
    r = S.estado_slos([linha("vm1", "a.x", 0), linha("vm1", "b.x", 1), linha("vm1", "c.x", 0)], slos, agora)
    assert r["estado"] == "DEGRADADO" and r["nao_medidos"] == ["b@vm2"]
    itens = {(i["slo"], i["no"]): i for i in r["itens"]}
    assert itens[("c", "vm1")]["estado"] == "SAUDAVEL" and "não se aplica" in itens[("c", "vm1")]["motivo"]
    # a.x > 0 ⇒ c vale; c.x = 0 < 1 ⇒ ATRASADO; medida velha ⇒ INDISPONIVEL; NaN ⇒ INDISPONIVEL com o motivo
    r = S.estado_slos([linha("vm1", "a.x", 5), linha("vm1", "c.x", 0), linha("vm1", "b.x", 1, idade=601),
                       linha("vm2", "b.x", float("nan"), motivo="psi ausente")], slos, agora)
    itens = {(i["slo"], i["no"]): i for i in r["itens"]}
    assert itens[("c", "vm1")]["estado"] == "ATRASADO" and r["estado"] == "ATRASADO"
    assert itens[("b", "vm1")]["estado"] == "INDISPONIVEL" and "velha" in itens[("b", "vm1")]["motivo"]
    assert itens[("b", "vm2")]["estado"] == "INDISPONIVEL" and itens[("b", "vm2")]["valor"] is None
    assert itens[("b", "vm2")]["motivo"] == "psi ausente"
    # a última linha vence; o forçado do rótulo prevalece
    r = S.estado_slos([linha("vm1", "a.x", 50, idade=100), linha("vm1", "a.x", 1, forcado="BLOQUEADO")], slos, agora)
    assert {(i["slo"], i["no"]): i for i in r["itens"]}[("a", "vm1")]["estado"] == "BLOQUEADO"


# ── contrato real ──────────────────────────────────────────────────────────────────────────────────────────────
def test_slos_reais_cobrem_todo_sensor_e_todo_sensor_tem_slo():
    slos = S.carregar_slos()
    julgados = set(slos.por_sensor())
    prometidos = {n for g in S.GRUPOS.values() for n in g.nomes}
    assert julgados == prometidos, (julgados ^ prometidos)
    for sid, s in slos.slos.items():
        assert s.remediar and s.runbook and s.fonte, sid
        assert s.janela_s >= max(g.intervalo_s for g in S.GRUPOS.values() if s.sensor in g.nomes), sid
    # o mínimo da O8.1
    for nome in ("psi.cpu_some", "psi.mem_full", "psi.io_some", "disco.livre_pct", "disco.tendencia_pp_dia",
                 "swap.uso_pct", "fila.idade_max_s", "fila.quarentena", "fila.orfaos", "fila.conclusoes_h",
                 "frescor.fontes_atrasadas", "llm.custo_mes_usd", "pericia.cobertura_chars",
                 "opus.saida_por_entrada_7d", "wal.pg_arquivo_atraso_s", "restauracao.pg_idade_h",
                 "db.integridade"):
        assert nome in julgados, nome


def test_grupos_por_no_vem_do_yaml():
    slos = S.carregar_slos()
    vm2 = S.grupos_do_no("vm2", slos)
    assert "psi" in vm2 and "fila" in vm2 and "integridade" not in vm2      # compliance.db só na VM-1
    assert "integridade" in S.grupos_do_no("vm1", slos)


def test_rotinas_observar_no_fluxo_yaml_inativas_ate_a_o90():
    g = G.carregar()
    for no in ("vm1", "vm2", "itcampo"):
        r = g.rotinas[f"observar_{no}"]
        assert r.estagio == "E18" and not r.ativa and "O9.0" in (r.bloqueio or "")
        assert r.nos == [no] and r.comando[-1] == no and r.agenda
        assert r.efeito.log_contem
    assert not [x for x in g.agenda_linhas() if x["id"].startswith("observar_")]   # nada entra na agenda ativa


def test_estagio_observar_registrado():
    from compliance_agent.aplicacao.estagios import estagio_de
    e = estagio_de("observar")
    assert e is not None and e.recursos == ["cpu_leve"]


def test_grupo_que_falha_vira_indisponivel_sem_derrubar(monkeypatch):
    def quebra(ctx):
        raise OSError("sem /proc")
    ctx = S.Ctx(no="vm1", con=None, agora=datetime.now(timezone.utc))
    ls = S._medir_grupo("x", S.Grupo(quebra, ("a.b", "c.d")), ctx)
    assert [(x.nome, x.valor) for x in ls] == [("a.b", None), ("c.d", None)] and "OSError" in ls[0].motivo
    ls = S._medir_grupo("y", S.Grupo(lambda c: [S.Leitura("a.b", 1.0)], ("a.b", "c.d")), ctx)
    assert ls[1].valor is None and "não devolveu" in ls[1].motivo


def test_psi_de_um_proc_falso(tmp_path):
    (tmp_path / "pressure").mkdir()
    (tmp_path / "pressure" / "cpu").write_text("some avg10=0 avg60=12.5 avg300=0 total=0\n")
    (tmp_path / "pressure" / "memory").write_text(PSI)
    ctx = S.Ctx(no="vm1", con=None, agora=datetime.now(timezone.utc), proc=str(tmp_path))
    v = {x.nome: x.valor for x in S.g_psi(ctx)}
    assert v["psi.cpu_some"] == 12.5 and v["psi.mem_full"] == 6.0
    assert v["psi.io_some"] is None and v["psi.io_full"] is None             # io ausente: INDISPONIVEL, não 0


# ── PG (esquema temporário) ────────────────────────────────────────────────────────────────────────────────────
SLOS_T = _slos(a=_slo(sensor="t.a"), b=_slo(sensor="t.b"), caro=_slo(sensor="t.caro", janela_s=7200))


def _grupos_teste(monkeypatch, contador):
    def caro(ctx):
        contador.append(1)
        return [S.Leitura("t.caro", 3.0)]
    monkeypatch.setattr(S, "GRUPOS", {"ok": S.Grupo(lambda c: [S.Leitura("t.a", 15.0, rotulos={"k": 1})], ("t.a",)),
                                      "cego": S.Grupo(lambda c: [S.nao_mediu("t.b", "fonte fora")], ("t.b",)),
                                      "caro": S.Grupo(caro, ("t.caro",), intervalo_s=3600)})


@precisa_pg
def test_coletar_grava_nan_para_indisponivel_e_confere_pela_etiqueta(con, monkeypatch):
    chamadas = []
    _grupos_teste(monkeypatch, chamadas)
    r = S.coletar(con, "vm1", SLOS_T)
    assert r["gravadas"] == 3 and r["conferidas"] == 3 and S.contar_coleta(con, r["coleta"]) == 3
    linhas = {n: (v, rot) for n, v, rot in con.execute("SELECT nome, valor, rotulos FROM metricas")}
    assert linhas["t.a"][0] == 15.0 and linhas["t.a"][1]["estado"] == "DEGRADADO" and linhas["t.a"][1]["k"] == 1
    v, rot = linhas["t.b"]
    assert math.isnan(v) and rot["estado"] == "INDISPONIVEL" and rot["motivo"] == "fonte fora"   # nunca 0
    # o caro é espaçado pela série: 2ª coleta pula, --forcar mede
    r2 = S.coletar(con, "vm1", SLOS_T)
    assert "caro" in r2["pulados"] and len(chamadas) == 1 and r2["gravadas"] == 2
    assert S.coletar(con, "vm1", SLOS_T, forcar=True)["gravadas"] == 3 and len(chamadas) == 2
    # a leitura do painel julga pela última linha
    est = S.estado_slos(S.ler_ultimos(con, SLOS_T), SLOS_T)
    assert {i["slo"]: i["estado"] for i in est["itens"]} == {"a": "DEGRADADO", "b": "INDISPONIVEL", "caro": "SAUDAVEL"}


@precisa_pg
def test_sensores_de_fila_e_tendencia_no_pg(con):
    con.execute("INSERT INTO jobs(tipo, chave, estado, disponivel_em) VALUES ('x', 'x:1', 'fila', now() - interval "
                "'2 hours'), ('x', 'x:2', 'quarentena', now()), ('y', 'y:1', 'feito', now())")
    con.execute("UPDATE jobs SET concluido_em = now() WHERE chave = 'y:1'")
    con.execute("INSERT INTO jobs(tipo, chave, estado, prazo, ficha) VALUES ('z', 'z:1', 'reservado', "
                "now() - interval '1 minute', 1)")
    con.execute("INSERT INTO nos(no, capacidades, slots, heartbeat_em) VALUES ('vm2', '{}', '{}', now())")
    ctx = S.Ctx(no="vm1", con=con, agora=datetime.now(timezone.utc))
    v = {x.nome: x for x in S.g_fila(ctx)}
    assert v["fila.elegiveis"].valor == 1 and v["fila.idade_max_s"].valor >= 7100
    assert v["fila.quarentena"].valor == 1 and v["fila.orfaos"].valor == 1 and v["fila.conclusoes_h"].valor == 1
    assert v["fluxo.nos_sem_heartbeat"].valor == 2 and v["fluxo.nos_sem_heartbeat"].rotulos["fora"] == ["vm1", "itcampo"]
    # tendência: série de disco.livre_pct do próprio nó caindo 2 pp/dia
    for h, livre in ((48, 60.0), (24, 58.0)):
        con.execute("INSERT INTO metricas(no, nome, valor, quando) VALUES ('vm1', 'disco.livre_pct', %s, "
                    "now() - make_interval(hours => %s))", (livre, h))
    pontos = [(time.time() - 48 * 3600, 40.0), (time.time() - 24 * 3600, 42.0)]
    assert S.tendencia_pp_dia(pontos) == pytest.approx(2.0, rel=1e-3)
    t = {x.nome: x for x in S.g_disco(ctx)}["disco.tendencia_pp_dia"]
    assert t.valor is not None and t.rotulos["pontos"] == 3


@precisa_pg
def test_estagio_observar_handler_e_efeito(con, esquema_tmp, monkeypatch):
    from compliance_agent.aplicacao.estagios import Contexto, estagio_de
    from compliance_agent.fluxo.fila import ENV_ESQUEMA, Resultado
    monkeypatch.setenv(ENV_ESQUEMA, esquema_tmp)
    _grupos_teste(monkeypatch, [])
    monkeypatch.setattr(S, "carregar_slos", lambda caminho=None: SLOS_T)
    e = estagio_de("observar")
    ctx = Contexto(no="vm1", tipo="observar", chave="observar:vm1", ficha=7, tentativa=1)
    r = e.handler({}, ctx)
    assert r.efeito["coleta"] == "observar:vm1#7" and r.efeito["gravadas"] == 3
    assert e.efeito({}, ctx, r) is True
    # efeito que não houve (declarou mais linhas que existem, ou outra coleta) não confere
    assert e.efeito({}, ctx, Resultado(efeito={**r.efeito, "gravadas": 4})) is False
    assert e.efeito({}, ctx, Resultado(efeito={"coleta": "outra", "gravadas": 3})) is False
    assert con.execute("SELECT count(*) FROM metricas WHERE rotulos->>'coleta' = 'observar:vm1#7'").fetchone()[0] == 3


@precisa_pg
def test_conectar_leitura_recusa_escrita(con, esquema_tmp):
    import psycopg
    c = S.conectar_leitura(DSN, esquema_tmp)
    try:
        assert c.execute("SELECT count(*) FROM metricas").fetchone()[0] == 0
        with pytest.raises(psycopg.Error):
            c.execute("INSERT INTO metricas(no, nome, valor) VALUES ('vm1', 'x', 1)")
    finally:
        c.close()


def test_idade_h():
    agora = datetime(2026, 11, 24, 12, 0)
    assert S.idade_h(agora - timedelta(hours=5), agora) == 5.0 and S.idade_h(None, agora) is None


def test_backup_lido_tambem_do_log_do_motor(tmp_path):
    """26/11/2026: na religação a rotina grava em data/logs/fluxo/<rotina>.log; o sensor lia só o log do cron
    (parado desde 25/11) e acusava backup de 31 h com o backup de hoje feito, cifrado e conferido."""
    (tmp_path / "logs" / "fluxo").mkdir(parents=True)
    (tmp_path / "backup_compliance_cron.log").write_text(
        "[backup] ✓ off-box: gdrive:vm1/compliance-20261125-031501.db.gz.age (porta única, cifrado)\n", encoding="utf-8")
    (tmp_path / "logs" / "fluxo" / "backup_compliance.log").write_text(
        "[backup] ✓ off-box: dropbox+gdrive:vm1/compliance-20261126-035008.db.gz.age (porta única, cifrado)\n",
        encoding="utf-8")
    txt = S.texto_dos_logs(tmp_path, "backup_compliance_cron.log", "backup_compliance")
    assert S.ultimo_backup_compliance(txt) == datetime(2026, 11, 26, 3, 50, 8)
    assert S.texto_dos_logs(tmp_path, "nao_existe.log", "nao_existe") is None
