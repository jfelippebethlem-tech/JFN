# -*- coding: utf-8 -*-
"""O2.3 — decisões do dono (D1 navegador transitório na VM-1, D2 ritmo também na agenda, D3 intervalo de certeza e
conformidade), reserva com a fila cheia, ritmo da assinatura no PG (porta fechada sem medição), histórico de eventos
(retenção mínima 7 dias), religação O9.0 estágio por estágio (tools/religar_o90.py) e a paridade do que se aposenta
(propagacao.ciclo, tools/pesado.sh, os 14 vigias → E18). Banco SEMPRE em esquema temporário (tests/fluxo_pg.py)."""
import copy
import json
import sqlite3

import pytest
import yaml

from compliance_agent.fluxo import fila, governador, grafo as G, planejador as P, ritmo, supervisor as S
from tests.fluxo_pg import DSN, chave_lock, con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures
from tests.test_fluxo_o22 import NAVEGADOR_NA_VM1, base  # noqa: F401 — fixture e a lista congelada da O2.2
from tools import religar_o90 as R

REAL = G.carregar()


# ── D1: navegador transitório na VM-1 ─────────────────────────────────────────────────────────────────
def test_catraca_transitorio_navegador_vm1_so_a_lista_declarada():
    """A lista só pode DIMINUIR (portar rotina para fora da VM-1); nó, recurso, 1 slot e o prazo O3.3 são fixos."""
    assert set(REAL.transitorios) == {"navegador_vm1"}
    t = REAL.transitorios["navegador_vm1"]
    assert (t.maquina, t.recurso, t.slots, t.transitorio_ate) == ("vm1", "navegador", 1, "O3.3")
    assert set(t.rotinas) <= NAVEGADOR_NA_VM1
    assert G.rotinas_sem_slot(REAL) == []


def test_slot_transitorio_so_serve_as_rotinas_listadas():
    assert REAL.restritos_do_no("vm1") == {"navegador": sorted(G.tipo_da_rotina(r)
                                                               for r in REAL.transitorios["navegador_vm1"].rotinas)}
    assert REAL.restritos_do_no("vm2") == {} and REAL.slots_do_no("vm2") == governador.SLOTS_INICIAIS["vm2"]


def _com_transitorio(base, **kw):
    d = copy.deepcopy(base)
    d["rotinas"]["nv"] = {"estagio": "E2", "descricao": "navegador legado", "comando": ["bash", "tools/x.sh"],
                          "nos": ["vm1"], "recursos": ["navegador"], "agenda": [{"cron": "0 * * * *"}],
                          "efeito": {"descricao": "arquivo regravado", "arquivo": "data/n.json"}}
    d["transitorios"] = {"t": {"maquina": "vm1", "recurso": "navegador", "slots": 1, "transitorio_ate": "O3.3",
                               "motivo": "teste do transitório", "rotinas": ["nv"], **kw}}
    return d


def test_transitorio_recusa_no_com_slot_rotina_que_nao_precisa_e_prazo_sem_onda(base):
    g = G.validar_dict(_com_transitorio(base))
    assert G.rotinas_sem_slot(g) == [] and g.slots_do_no("vm1")["navegador"] == 1
    with pytest.raises(ValueError, match="já tem navegador"):
        G.validar_dict(_com_transitorio(base, maquina="vm2"))
    with pytest.raises(ValueError, match="não precisa"):
        G.validar_dict(_com_transitorio(base, rotinas=["nv", "up"]))             # up é cpu_leve
    with pytest.raises(ValueError, match="não existe"):
        G.validar_dict(_com_transitorio(base, rotinas=["fantasma"]))
    with pytest.raises(ValueError):
        G.validar_dict(_com_transitorio(base, transitorio_ate="dezembro"))


# ── D2 / D3 ───────────────────────────────────────────────────────────────────────────────────────────
def test_d2_ritmo_nas_agendas_das_4_fundidas_e_estagio_em_todo_payload():
    ag = REAL.agenda_linhas()
    assert {x["payload"]["rotina"]: x["payload"]["ritmo"] for x in ag if "ritmo" in x["payload"]} == {
        "lex_execucao_fila": "lex_execucao", "sei_fichas_fila": "sei_ficha", "triagem_lote": "triagem",
        "conferencia_opus_fila": "conferencia_opus",
        "automelhoria_executor": "automelhoria_executor"}   # 26/11: o executor (Opus) pela trava de ritmo
    assert all(x["payload"]["estagio"] == REAL.rotinas[x["payload"]["rotina"]].estagio for x in ag)


def test_d3_certeza_e_conformidade_com_o_dobro_do_intervalo():
    assert REAL.rotinas["certeza"].evento.intervalo_min_s == 7200
    assert REAL.rotinas["conformidade"].evento.intervalo_min_s == 7200
    texto = (G.CAMINHO).read_text(encoding="utf-8")
    assert texto.count("intervalo_min_s: 7200   # D3") == 2                    # o motivo fica no yaml


# ── aposentadoria: paridade ───────────────────────────────────────────────────────────────────────────
def test_paridade_propagacao_derivados_fontes_e_ponte():
    """Tudo o que o `propagacao.ciclo` fazia tem dono no fluxo: os 43 derivados (mesmas dependências), as 36 fontes
    e — o que não é despacho — sondas/avisar/descobertas/cérebro na rotina `propagacao_ponte` (E18, mesmo horário)."""
    from compliance_agent import propagacao
    cfg = propagacao.carregar()
    assert set(cfg["fontes"]) == set(REAL.fontes)
    for did, d in cfg["derivados"].items():
        assert set(REAL.rotinas[did].evento.depende) == set(d["depende"]), did
    p = REAL.rotinas["propagacao_ponte"]
    assert p.estagio == "E18" and p.comando[-1] == "ponte-fluxo" and [a.cron for a in p.agenda] == ["2-59/5 * * * *"]
    assert any("propagacao_ponte" in f.motivo for f in REAL.fora if f.origem == ["vm1-cron-compliance-agent-propagacao-ciclo"])


def test_paridade_pesado_sh_vira_slot_cpu_pesado():
    for rid in ("gitnexus_refresh", "ocr_contratos_imagem", "sei_compactar"):
        assert REAL.contrato_da_rotina(rid)["recursos"] == ["cpu_pesado"], rid
    assert "cpu_pesado" in governador.PESADOS                   # só reserva com folga de PSI (o antigo semáforo)


# os 14 vigias do plano (§3.2 E18: ronda, painel_vigia, guardiao, keepalive, handoff-watcher, vm_guard,
# automelhoria_geral, pipelines_slo + os do inventário O1.1) → rotina E18 do yaml, ou `fora` com o motivo
VIGIAS = {"ronda": "ronda", "keepalive": "keepalive", "handoff_watcher": "handoff_watcher",
          "vm_guard": "vm_guard_navegador", "guardiao_db_malformed": "remediar_painel_shm",   # O8.1: sensor + remédio
          "automelhoria_geral": "automelhoria_geral", "pipelines_slo": "pipelines_slo",
          "sentinela_integridade": "sentinela_integridade", "yoda_autoauditoria": "yoda_autoauditoria",
          "claude_motor_canario": "claude_motor_canario", "ritmo_assinatura": "ritmo_assinatura",
          "painel_vigia": "remediar_painel_travado"}                     # O8.1 (dono 24/11): saiu do `fora`
VIGIAS_FORA = {"itcampo_vigia": "vm1-cron-tools-itcampo-vigia"}
VIGIAS_JA_DESLIGADOS = {"guardiao_failover"}        # comentado no crontab antes da parada (inventário O1.1)


def test_os_14_vigias_viram_sensores_e18_ou_tem_motivo():
    assert len(VIGIAS) + len(VIGIAS_FORA) + len(VIGIAS_JA_DESLIGADOS) == 14
    for v, rid in VIGIAS.items():
        assert REAL.rotinas[rid].estagio == "E18" and REAL.rotinas[rid].ativa, v
    origens_fora = {o for f in REAL.fora for o in f.origem}
    assert set(VIGIAS_FORA.values()) <= origens_fora


def test_aposentados_avisam_que_foram_substituidos():
    from compliance_agent import propagacao
    assert "SUBSTITUÍDO" in propagacao.ciclo.__doc__ and "SUBSTITUÍDO" in propagacao.__doc__
    assert "SUBSTITUÍDO PELO MOTOR DE FLUXO" in (G.RAIZ / "tools" / "pesado.sh").read_text(encoding="utf-8")


# ── religação O9.0 (puro) ─────────────────────────────────────────────────────────────────────────────
def test_plano_de_religacao_segue_a_ordem_da_secao_1_1():
    ids = [p.id for p in R.plano_religar(REAL, ["pausa"])]
    assert ids[:6] == ["R0", "R1", "R2", "R3", "R4", "R5"]
    assert [i[2:] for i in ids[6:]] == ["E17", "E18", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "E10",
                                        "E11", "E12", "E13", "E14", "E15", "E16"]
    assert any("agenda sincronizar" in c for _n, c in R.plano_religar(REAL, [])[3].cmds)


def test_primeira_volta_nunca_roda_semanal_ou_mensal_fora_do_horario():
    pv = R.primeira_volta(REAL, "E17")
    assert "zelador_vm1_aplicar" not in pv and "checkpoint_wal" in pv
    assert "backup_compliance" in pv                          # diário desde 24/11/2026: entra na primeira volta


def test_desfazer_cobre_crontab_timers_tarefas_e_pausas(tmp_path):
    (tmp_path / "vm1").mkdir()
    (tmp_path / "vm1" / "timers_parados.txt").write_text("jfn-ronda\njfn-sancoes\n")
    (tmp_path / "vm1" / "services_parados.txt").write_text("jfn-bombeiros-supervisor chrome-jfn\n")
    (tmp_path / "vm1" / "pausas_criadas.txt").write_text(".pause_deploy\n")
    passos = {p.id: p for p in R.plano_desfazer(tmp_path, ["sei-pcrj"])}
    txt = json.dumps({k: [c for _n, c in p.cmds] + p.sql for k, p in passos.items()}, ensure_ascii=False)
    for esperado in ("s/^#PARADA-20261124 //", "jfn-ronda.timer jfn-sancoes.timer", "chrome-jfn", "sei-pcrj.timer",
                     "JFN-SEI-Paralelo", "/ENABLE", "data/.pause_deploy", "UPDATE agenda SET ativo = false",
                     "disable --now jfn-fluxo@vm1"):
        assert esperado in txt, esperado
    assert passos["D9"].cmds == []                                  # snapshot nunca é automático


def test_executar_sem_confirmacao_recusa(monkeypatch, capsys):
    monkeypatch.setattr(R, "ler_lista_vm2", lambda *a, **k: [])
    assert R.main(["--executar"]) == 2
    assert "confirmo-dono-avisado" in capsys.readouterr().err


def test_ensaio_imprime_sem_executar(monkeypatch, capsys):
    monkeypatch.setattr(R, "preliminares", lambda g: ["medido"])
    chamado = []
    monkeypatch.setattr(R, "rodar_cmd", lambda *a, **k: chamado.append(a) or 0)
    assert R.main(["--ensaio"]) == 0
    out = capsys.readouterr().out
    assert "ENSAIO (nada foi executado)" in out and "[R-E16]" in out and not chamado


# ── PG: reserva, liberação, transitório, eventos, ritmo, religação ────────────────────────────────────
@precisa_pg
def test_reserva_so_sai_estagio_liberado(con, base):
    g = G.validar_dict(base)
    c = g.contrato_da_rotina("up")
    fila.enfileirar(con, "legado:up", "legado:up", g.payload("up"), recursos=c["recursos"])
    fila.enfileirar(con, "eco", "eco:1")                                     # sem estágio: o portão não segura
    assert fila.reservar(con, "vm1", {"cpu_leve": 2}, liberacao=True).tipo == "eco"
    assert fila.reservar(con, "vm1", {"cpu_leve": 2}, liberacao=True) is None
    con.execute("INSERT INTO liberacao(estagio) VALUES ('E10')")
    assert fila.reservar(con, "vm1", {"cpu_leve": 2}, liberacao=True).tipo == "legado:up"


@precisa_pg
def test_slot_restrito_recusa_rotina_fora_da_lista(con):
    fila.enfileirar(con, "legado:nova", "legado:nova", {}, recursos=["navegador"])
    fila.enfileirar(con, "legado:sweep_sei", "legado:sweep_sei", {}, recursos=["navegador"], prioridade=200)
    r = {"navegador": ["legado:sweep_sei"]}
    assert fila.reservar(con, "vm1", {"navegador": 1}, restritos=r).tipo == "legado:sweep_sei"
    assert fila.reservar(con, "vm1", {"navegador": 1}, restritos=r) is None   # a nova não usa o transitório
    assert fila.reservar(con, "vm2", {"navegador": 1}).tipo == "legado:nova"  # num slot de verdade, sim


@precisa_pg
def test_eventos_guardam_7_dias_e_so_arquivam_o_processado(con):
    import psycopg
    for dias, proc in ((10, True), (10, False), (3, True)):
        con.execute("INSERT INTO eventos(fonte, tipo, quando, processado_em) VALUES ('f', 't', now() - "
                    "make_interval(days => %s), CASE WHEN %s THEN now() END)", (dias, proc))
    with pytest.raises(psycopg.errors.RaiseException, match="7 dias"):
        con.execute("SELECT arquivar_eventos(6)")
    assert con.execute("SELECT arquivar_eventos(7)").fetchone()[0] == 1      # só o processado de 10 dias
    assert con.execute("SELECT count(*) FROM eventos").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM eventos_arquivo").fetchone()[0] == 1


def _medida(pct, dias_ate_virada=6.0):
    import time
    from datetime import datetime
    agora = time.time()
    return {"em": "x", "medido_ts": agora, "sessao_pct": 1.0, "sessao_volta": None, "semana_pct": pct,
            "semana_volta": datetime.fromtimestamp(agora + dias_ate_virada * 86400).strftime("%Y-%m-%dT%H:%M:%S")}


@precisa_pg
def test_ritmo_no_pg_porta_fechada_sem_medicao_ou_velha(con):
    assert ritmo.motivo(con, "triagem").startswith("porta fechada")         # nada publicado
    ritmo.publicar(con, _medida(1.0))
    assert ritmo.motivo(con, "triagem") is None                              # normal
    con.execute("UPDATE metricas SET quando = now() - interval '3 hours' WHERE nome = %s", (ritmo.NOME,))
    assert "velha" in ritmo.motivo(con, "triagem")
    ritmo.publicar(con, _medida(95.0))                                       # acima do teto: contido
    assert "ritmo semanal" in ritmo.motivo(con, "triagem") and ritmo.motivo(con, "canario") is None


@precisa_pg
def test_medir_e_publicar_nao_publica_medicao_que_falhou(con, monkeypatch):
    from compliance_agent.llm import ritmo_assinatura
    assert ritmo.medir_e_publicar(con, medir=lambda: {"nivel": "normal", "erro": "URLError"})["publicado"] is False
    monkeypatch.setattr(ritmo_assinatura, "ler", lambda: _medida(2.0))
    assert ritmo.medir_e_publicar(con, medir=lambda: {"nivel": "normal"})["publicado"] is True
    assert ritmo.ler(con)[0]["semana_pct"] == 2.0


@precisa_pg
def test_supervisor_sem_ritmo_injetado_le_o_pg_e_fecha_a_porta(esquema_tmp, monkeypatch):
    monkeypatch.setattr(S, "motivo_ritmo", lambda t: None)                  # guarda local aberto
    sup = S.Supervisor(no="vm1", dsn=DSN, esquema=esquema_tmp, isolamento="subprocesso",
                       chave_lideranca=chave_lock(), medir=lambda: governador.Medida())
    try:
        sup.con.execute("TRUNCATE metricas")                                 # só o esquema temporário
        assert sup.ritmo("triagem").startswith("porta fechada")
        assert sup.slots["navegador"] == 1 and sup.restritos == REAL.restritos_do_no("vm1")
    finally:
        sup.fechar()


@precisa_pg
def test_religacao_libera_confere_e_propaga_bloqueio(con):
    P.sincronizar_agenda(con, REAL.agenda_linhas())
    assert con.execute("SELECT count(*) FILTER (WHERE ativo) FROM agenda").fetchone()[0] == 0
    chaves = R.liberar_estagio(con, REAL, "E17")
    assert len(chaves) == len(R.primeira_volta(REAL, "E17")) > 0
    assert con.execute("SELECT count(*) FROM agenda WHERE ativo AND payload->>'estagio' <> 'E17'").fetchone()[0] == 0
    assert R.conferir_estagio(con, "E17", chaves)["ok"] is False                     # ainda em fila
    con.execute("UPDATE jobs SET estado = 'feito', concluido_em = now() WHERE chave = ANY(%s)", (chaves,))
    assert R.conferir_estagio(con, "E17", chaves)["ok"] is True
    e1 = R.liberar_estagio(con, REAL, "E1", R.PARADA)
    assert con.execute("SELECT payload->>'desde' FROM jobs WHERE chave = %s", (e1[0],)).fetchone()[0] == R.PARADA
    con.execute("TRUNCATE jobs, liberacao, agenda, metricas")
    # E1 não confere no prazo (fica em fila) ⇒ BLOQUEADO; E2 depende dele e não é liberado; E18 não depende
    r = R.religar_estagios(con, REAL, espera_max_s=0, so=["E18", "E1", "E2"], dormir=lambda s: None, log=lambda *a: 0)
    assert r["E1"]["ok"] is False and "pulado" in r["E2"]
    assert {x[0] for x in con.execute("SELECT estagio FROM liberacao")} == {"E18", "E1"}
    assert con.execute("SELECT count(*) FROM metricas WHERE nome = 'religacao_estagio'").fetchone()[0] == 2


@precisa_pg
def test_ponte_entrega_eventos_do_propagacao_ao_fluxo(con, tmp_path, monkeypatch):
    from compliance_agent import propagacao
    monkeypatch.setattr(propagacao, "DATA", tmp_path)
    cfg = {"fontes": {"f1": {"nome": "fonte sem sonda (só avisar)"}}, "derivados": {}, "cerebro": []}
    db = tmp_path / "propagacao.db"
    r = propagacao.ponte_fluxo(cfg, db, con_fluxo=con)                       # 1ª rodada: marca o começo
    assert r["ponte_fluxo"]["entregues"] == 0
    pc = propagacao.conectar(db)
    propagacao.emitir(pc, cfg, "f1", "OB nova")
    propagacao.emitir(pc, cfg, "f1", "outra")
    pc.close()
    r = propagacao.ponte_fluxo(cfg, db, con_fluxo=con)
    assert r["ponte_fluxo"]["entregues"] == 2
    assert [x[0] for x in con.execute("SELECT fonte FROM eventos ORDER BY id")] == ["f1", "f1"]
    assert propagacao.ponte_fluxo(cfg, db, con_fluxo=con)["ponte_fluxo"]["entregues"] == 0   # não reentrega
    assert sqlite3.connect(db).execute("SELECT v FROM meta WHERE k = ?", (propagacao.CHAVE_PONTE,)).fetchone()


def test_yaml_valida_com_pydantic_e_o_arquivo_cru_tem_as_secoes():
    cru = yaml.safe_load(G.CAMINHO.read_text(encoding="utf-8"))
    assert "transitorios" in cru and cru["transitorios"]["navegador_vm1"]["maquina"] == "vm1"


def test_catraca_ninguem_poda_fluxo_eventos_fora_do_arquivamento():
    """Histórico de eventos sem poda por contagem (sombra §6 item 9): o único DELETE em `eventos` é o de
    `arquivar_eventos` (fluxo_002.sql), que recusa menos de 7 dias e só move evento processado."""
    import subprocess
    achados = subprocess.run(["git", "grep", "-n", "-i", "-E", r"DELETE FROM eventos\b", "--", "*.py", "*.sql"],
                             cwd=G.RAIZ, capture_output=True, text=True).stdout.splitlines()
    fora = [a for a in achados if not a.startswith(("tests/", "deploy/vm2/postgres/fluxo_002.sql"))]
    assert fora == []
