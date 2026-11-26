# -*- coding: utf-8 -*-
"""O9.0 — preparação da religação (tools/religar_o90.py, tools/e1_eventos.py, deploy/fluxo/producao.env):
  1. uma porta por trabalho: onde o estágio tem NATIVO, a rotina legada equivalente está desligada no grafo
     (`substituida_por`), toda rotina tem destino declarado, todo nativo tem produtor de entrada, nenhuma órfã;
  2. árvore por nó (drop-in da VM-1/VM-2, tarefa do it-campo), workers no SHA fixado, comandos do it-campo em
     PowerShell (base64, sem `&`);
  3. prova do `schema aplicar` num esquema de ensaio (nunca o `fluxo`);
  4. ambiente da produção: JFN_E3_DELTA=1, JFN_LEITURAS_REGISTRAR=1, sem JFN_ASSINATURA_ESCOPO; a faixa de
     manutenção sai LOGO depois do E15 conferido; aviso Telegram só conta com message_id."""
from __future__ import annotations

import base64
import json
import re
import sqlite3
import uuid

import pytest

from compliance_agent.fluxo import grafo as G
from tests.fluxo_pg import DSN, con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures
from tools import e1_eventos as E1
from tools import religar_o90 as R

REAL = G.carregar()
PORTAS_SEI_LEGADAS = {"sweep_sei", "sweep_sei_noturno", "varredura_sei_lane", "vm2_sweep_geral", "sei_integra_fila",
                      "integra_fila_dinheiro", "vm2_integras", "sei_integra_vm2_precalcular"}


# ── 1. uma porta por trabalho ─────────────────────────────────────────────────────────────────────────────────
def test_portas_sei_legadas_desligadas_e_substituidas_pelo_nativo():
    for r in PORTAS_SEI_LEGADAS:
        x = REAL.rotinas[r]
        assert not x.ativa and x.substituida_por == x.estagio and x.estagio in ("E2", "E3"), r
    assert not ({g for g in REAL.agenda_linhas() if g["id"].split("#")[0] in PORTAS_SEI_LEGADAS})
    assert not any(d["tipo"].split(":", 1)[1] in PORTAS_SEI_LEGADAS
                   for deps in REAL.grafo_planejador().values() for d in deps if d["tipo"].startswith("legado:"))


def test_catraca_estagio_com_nativo_nao_religa_legado_substituivel():
    """E4–E7 (O3.4) e E8 leitura (O6.3): nenhuma rotina legada ATIVA sobra onde o nativo tem paridade aceita."""
    ativas = {e: sorted(r for r, x in REAL.rotinas.items() if x.ativa and x.estagio == e) for e in ("E4", "E5", "E6",
                                                                                                    "E7")}
    assert ativas == {"E4": [], "E5": [], "E6": [], "E7": []}
    assert not REAL.rotinas["leitura_integral_assinatura"].ativa


def test_toda_rotina_tem_destino_declarado_e_legado_ligado_tem_motivo():
    mapa = R.mapa_legado(REAL)
    assert {m["rotina"] for m in mapa} == set(REAL.rotinas)
    assert [m["rotina"] for m in mapa if not m["motivo"]] == []
    assert all(m["destino"] == "legado" for m in mapa if REAL.rotinas[m["rotina"]].ativa)
    for m in mapa:
        if m["destino"] == "nativo":
            assert m["para"] in R.estagios_nativos(REAL), m


def test_todo_nativo_tem_produtor_de_entrada_e_nenhuma_rotina_fica_orfa():
    assert R.entradas_sem_produtor(REAL) == {}
    assert R.orfas(REAL) == []
    assert REAL.rotinas["e1_eventos"].ativa and REAL.rotinas["e1_eventos"].estagio == "E1"
    assert set(E1.EMITE) <= {r.evento for r in REAL.nativos.rotas}


def test_substituida_por_exige_rotina_desligada_e_estagio_com_nativo():
    import copy
    import yaml
    d = yaml.safe_load(G.CAMINHO.read_text(encoding="utf-8"))
    x = copy.deepcopy(d)
    x["rotinas"]["sweep_sei"]["ativa"] = True
    with pytest.raises(ValueError, match="substituida_por"):
        G.validar_dict(x)
    x = copy.deepcopy(d)
    x["rotinas"]["sweep_sei"]["substituida_por"] = "E1"            # E1 não tem nativo
    with pytest.raises(ValueError, match="não tem estágio nativo"):
        G.validar_dict(x)


def test_religadas_na_o90_deploy_vm2_e_materializar_painel():
    for r in ("deploy_vm2", "materializar_painel"):
        assert REAL.rotinas[r].ativa and "Religada na O9.0" in REAL.rotinas[r].nota


# ── 2. árvores, nós, it-campo ─────────────────────────────────────────────────────────────────────────────────
def test_plano_fixa_o_sha_e_atualiza_os_dois_workers():
    sha = "a" * 40
    p = {x.id: x for x in R.plano_religar(REAL, [], sha)}
    vm2 = [c for n, c in p["R1"].cmds if n == "vm2"][0]
    assert f"git merge --ff-only -q {sha}" in vm2 and f"deploy_worker --sha {sha}" in vm2 and "~/JFN-worker" in vm2
    itc = [c for n, c in p["R1"].cmds if n == "itcampo"][0]
    script = base64.b64decode(re.search(r"echo (\S+) \| base64", itc)[1]).decode()
    assert f"--sha {sha}" in script and "cd ~/JFN-worker" in script


def test_itcampo_sobe_pela_tarefa_de_boot_e_comandos_sao_powershell():
    p = {x.id: x for x in R.plano_religar(REAL, [], "b" * 40)}
    itc = [c for n, c in p["R4"].cmds if n == "itcampo"]
    assert any("schtasks /Change /TN \\JFN-Fluxo-Boot /ENABLE" in c for c in itc)
    assert not any("systemctl" in c and "itcampo" in c and "wsl -e" in c for c in itc)
    todos = [c for x in R.plano_religar(REAL, []) + R.plano_desfazer(R.BACKUPS, []) for n, c in x.cmds
             if n == "itcampo"]
    assert todos and not [c for c in todos if " & " in c]          # `&` é recusado pelo PowerShell 5.1


def test_wsl_leva_o_script_inteiro_em_base64():
    s = "cd ~/JFN-worker && test -z \"$(git status --porcelain -- . ':(exclude)data')\""
    c = R.wsl(s)
    assert "'" not in c.split("'", 1)[1].rsplit("'", 1)[0]          # só base64 dentro das aspas simples
    assert base64.b64decode(re.search(r"echo (\S+) \|", c)[1]).decode() == s


def test_desfazer_para_o_itcampo_e_devolve_o_cron_do_fluxo():
    d = {x.id: x for x in R.plano_desfazer(R.BACKUPS, [])}
    assert any("JFN-Fluxo-Boot /DISABLE" in c for _n, c in d["D1"].cmds)
    assert any("cron_para_fluxo --desfazer" in c for _n, c in d["D3"].cmds)
    assert any("cron_para_fluxo --timers --desfazer" in c for _n, c in d["D5"].cmds)


def test_ensaio_conta_ff_no_canonico_e_acusa_codigo_mexido(monkeypatch):
    head = "c" * 40

    class P:
        def __init__(self, rc, out):
            self.returncode, self.stdout = rc, out

    def rodar(argv, **k):
        if argv[:2] == ["git", "-C"]:
            return P(0, "")                                        # ancestral no canônico
        if "schtasks" in " ".join(argv):
            return P(0, '"\\JFN-Fluxo-Boot","N/A","Desabilitado"')
        return P(0, f"head={head}\nsujo=2\ndsn=0\n")
    nos = R.estado_nos("d" * 40, rodar)
    assert nos["vm2"]["ff"] and nos["itcampo"]["tarefa"] == "Desabilitado"
    pend = [t for t, dono in R.pendencias(REAL, nos, "d" * 40, None) if not dono]
    assert any("código mexido" in t for t in pend)


# ── 3. schema ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_provar_schema_recusa_o_fluxo_real():
    with pytest.raises(ValueError, match="ensaio_o90"):
        R.provar_schema(object(), "fluxo")


@precisa_pg
def test_provar_schema_de_fluxo_001_a_ok_idempotente():
    import psycopg
    nome = f"ensaio_o90_t{uuid.uuid4().hex[:8]}"
    c = psycopg.connect(DSN, autocommit=True)
    try:
        r = R.provar_schema(c, nome)
        existe = c.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (nome,)).fetchone()
    finally:
        c.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')
        c.close()
    assert r["ok"] and r["aplicar_1"] == ["fluxo_002"] and r["aplicar_2"] == [] and r["depois_1"] == r["depois_2"]
    assert "migração fluxo_002" in r["antes"]["faltando"] and existe is None


# ── 4. ambiente, manutenção, aviso ────────────────────────────────────────────────────────────────────────────
def test_catraca_ambiente_da_producao():
    assert R.catraca_ambiente() == []
    env = (R.RAIZ / R.AMBIENTE).read_text(encoding="utf-8")
    assert not re.search(r"(?m)^\s*JFN_ASSINATURA_ESCOPO\s*=", env)


def test_catraca_ambiente_acusa_escopo_do_ensaio(tmp_path):
    import shutil
    for rel in (R.AMBIENTE, R.PS1_ITCAMPO, *R.DROPIN.values()):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(R.RAIZ / rel, tmp_path / rel)
    (tmp_path / R.AMBIENTE).write_text("JFN_E3_DELTA=1\nJFN_LEITURAS_REGISTRAR=1\nJFN_ASSINATURA_ESCOPO=ensaio_o85\n")
    assert any("JFN_ASSINATURA_ESCOPO" in e for e in R.catraca_ambiente(tmp_path))


def test_e15_tira_a_faixa_e_confere_e_sabe_voltar():
    p = {x.id: x for x in R.plano_religar(REAL, [])}["R-E15"]
    txt = " ".join(c for _n, c in p.cmds)
    assert "#O90" in txt and "restart jfn.service" in txt and "jfn-manutencao" in txt and "jfn.service.antes-o90" in txt
    assert "#O90 (Environment" in p.nota                          # a volta está escrita no roteiro


def test_executar_roda_o_comando_do_e15_antes_do_e16(monkeypatch):
    ordem = []
    monkeypatch.setattr(R, "avisar", lambda *a, **k: True)
    monkeypatch.setattr(R, "rodar_cmd", lambda no, c, rodar=None: ordem.append(("cmd", c[:20])) or 0)

    def falso(con, g, espera, so=None, log=print, apos=None, **k):
        out = {}
        for e in so:
            ordem.append(("estagio", e))
            out[e] = {"ok": True}
            if apos:
                apos(e, out[e])
        return out
    monkeypatch.setattr(R, "religar_estagios", falso)
    passos = [x for x in R.plano_religar(REAL, []) if x.estagio in ("E15", "E16")]
    assert R.executar(passos, REAL, 0, con=object(), log=lambda *a: 0) == 0
    i15, i16 = ordem.index(("estagio", "E15")), ordem.index(("estagio", "E16"))
    assert any(k == "cmd" for k, _ in ordem[i15:i16])


def test_executar_sem_aviso_de_inicio_nao_faz_nada(monkeypatch):
    feito = []
    monkeypatch.setattr(R, "rodar_cmd", lambda no, c, rodar=None: feito.append(c) or 1)   # aviso falha
    assert R.executar(R.plano_religar(REAL, []), REAL, 0, con=None, log=lambda *a: 0) == 1
    assert len(feito) == 1 and "--avisar" in feito[0]


def test_aviso_telegram_so_conta_com_message_id(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    assert R.avisar_telegram("t", lambda u, d: {"ok": True}) is None               # ok sem message_id = silêncio
    assert R.avisar_telegram("t", lambda u, d: {"ok": False, "result": {"message_id": 9}}) is None
    assert R.avisar_telegram("t", lambda u, d: {"ok": True, "result": {"message_id": 9}}) == 9
    monkeypatch.delenv("TELEGRAM_CHAT_ID")
    assert R.avisar_telegram("t", lambda u, d: {"ok": True, "result": {"message_id": 9}}) is None


def test_ensaio_limpo_sem_preconcicao_aberta_fora_dos_criterios(monkeypatch, capsys):
    monkeypatch.setattr(R, "estado_nos", lambda sha, rodar=None: {
        n: {"medido": True, "head": sha, "sujo": 0, "ff": True, "dsn": True, "tarefa": "Desabilitado"}
        for n in ("vm2", "itcampo")})
    assert [t for t, dono in R.pendencias(REAL, R.estado_nos("e" * 40), "e" * 40, True) if not dono] == []


# ── e1_eventos ────────────────────────────────────────────────────────────────────────────────────────────────
def _coleta(tmp_path):
    db = tmp_path / "c.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, exercicio INT, processo TEXT, "
              "data_emissao TEXT, coletado_em TEXT)")
    c.execute("CREATE TABLE alertas_triagem (alerta_id INT, em TEXT)")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?)", [
        ("2026OB00010", "133100", 2026, "SEI-120001/000001/2026", "20/11/2026", "2026-11-20 10:00:00"),
        ("2026OB00011", "133100", 2026, "SEI-120001/000002/2026", "25/11/2026", "2026-11-25 10:00:00")])
    c.execute("INSERT INTO alertas_triagem VALUES (1, '2026-11-20T10:00:00')")
    c.commit()
    return db, c


def test_e1_primeira_rodada_sem_desde_so_marca(tmp_path):
    db, c = _coleta(tmp_path)
    ev, marca = E1.calcular(sqlite3.connect(f"file:{db}?mode=ro", uri=True), None, None)
    assert ev == [] and marca["ob_maiores"] == {"133100|2026": 11}


def test_e1_desde_pega_ob_emitida_desde_e_recoleta_nao_e_ob_nova(tmp_path):
    from compliance_agent.dominio import processo_id as PI
    db, c = _coleta(tmp_path)
    ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ev, marca = E1.calcular(ro, None, "2026-11-24")
    assert [k for f, t, k in ev if t == "ob_nova"] == [PI.chave_processo("SEI-120001/000002/2026")]
    assert ("coleta", "conferidos", "alertas_triagem") in ev and ("coleta", "fonte_mudou", "ob_siafe") in ev
    c.execute("UPDATE ob_orcamentaria_siafe SET coletado_em = '2026-11-26 01:00:00'")     # recoleta regrava tudo
    c.commit()
    ev2, marca2 = E1.calcular(ro, json.loads(json.dumps(marca)), None)
    assert [x for x in ev2 if x[1] == "ob_nova"] == [] and ("coleta", "fonte_mudou", "ob_siafe") in ev2
    c.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('2026OB00012','133100',2026,'SEI-120001/000003/2026',"
              "'26/11/2026','2026-11-26 02:00:00')")
    c.commit()
    ev3, _ = E1.calcular(ro, marca2, None)
    assert [k for f, t, k in ev3 if t == "ob_nova"] == [PI.chave_processo("SEI-120001/000003/2026")]
    assert ("coleta", "conferidos", "alertas_triagem") not in ev3


@precisa_pg
def test_e1_grava_eventos_e_so_depois_a_marca(tmp_path, con):
    db, _c = _coleta(tmp_path)
    marca = tmp_path / "m.json"
    r = E1.rodar(db, marca, desde="2026-11-24", con_fluxo=con)
    assert r["eventos"]["coleta/ob_nova"] == 1 and marca.exists()
    assert con.execute("SELECT count(*) FROM eventos WHERE fonte = 'coleta' AND tipo = 'ob_nova'").fetchone()[0] == 1
    assert E1.rodar(db, marca, con_fluxo=con)["eventos"] == {}                     # 2ª rodada: sem novidade


# ── ajustes do coordenador (25/11): credencial achada, semeador do E2, duas janelas ────────────────────────────
def test_r2_nao_copia_credencial_e_prova_que_nada_foi_gravado():
    p = {x.id: x for x in R.plano_religar(REAL, [], "f" * 40, 1)}
    txt = json.dumps([c for _n, c in p["R2"].cmds])
    assert "scp" not in txt and "install -D" not in txt and "pg.tmp" not in txt
    vm2 = [c for n, c in p["R2"].cmds if n == "vm2"][0]
    assert "credenciais onde JFN_EVIDENCIAS_DSN" in vm2 and "credenciais com JFN_EVIDENCIAS_DSN" in vm2
    assert "grep -rls '^JFN_EVIDENCIAS_DSN='" in vm2 and '= 0' in vm2
    ps = (R.RAIZ / R.PS1_ITCAMPO).read_text(encoding="utf-8")
    assert "pg_evidencias.env" not in ps.split("while ($true)")[1]       # o boot do it-campo não lê arquivo de DSN


def test_supervisor_acha_o_dsn_pelo_resolvedor_so_na_memoria(monkeypatch):
    from compliance_agent import credenciais, evidencias
    from compliance_agent.fluxo import __main__ as M
    monkeypatch.delenv(evidencias.ENV_DSN, raising=False)
    monkeypatch.setattr(evidencias, "dsn_vigente", lambda: __import__("os").environ.get(evidencias.ENV_DSN, ""))
    monkeypatch.setattr(credenciais, "obter", lambda n, **k: "postgresql://x@h/db")
    monkeypatch.setattr(credenciais, "onde", lambda n, **k: "vm1(vm1-ts):pg_evidencias.env")
    assert M.resolver_dsn() == "vm1(vm1-ts):pg_evidencias.env"
    assert __import__("os").environ[evidencias.ENV_DSN] == "postgresql://x@h/db"
    monkeypatch.delenv(evidencias.ENV_DSN)
    monkeypatch.setattr(credenciais, "obter", lambda n, **k: None)
    assert M.resolver_dsn() is None
    assert M.main(["supervisor", "--no", "vm2"]) == 2                          # sem DSN o supervisor não sobe


def test_duas_etapas_e8_nunca_na_primeira():
    e1 = [x.estagio for x in R.plano_religar(REAL, [], None, 1) if x.estagio]
    e2 = [x.estagio for x in R.plano_religar(REAL, [], None, 2) if x.estagio]
    assert e1 == ["E17", "E18", "E1", "E2", "E3", "E4", "E5", "E6", "E7"]
    assert e2 == ["E8", "E9", "E10", "E11", "E12", "E13", "E14", "E15", "E16"]
    assert R.plano_religar(REAL, [], None, 2)[0].id == "R6"
    assert {x.id for x in R.plano_religar(REAL, [], None, 1)} >= {"R0", "R1", "R2", "R3", "R4", "R5"}
    llm = {e for e, x in REAL.estagios.items() if "llm" in x.recursos}
    assert not llm & set(e1)                                                   # nada de LLM na 1ª janela


def test_wslconfig_na_primeira_janela_com_os_mistos_parados_antes_e_retomados_depois():
    cmds = [c for n, c in {x.id: x for x in R.plano_religar(REAL, [], None, 1)}["R4"].cmds if n == "itcampo"]
    dec = [base64.b64decode(m[1]).decode() if (m := re.search(r"echo (\S+) \| base64", c)) else c for c in cmds]
    i_parar = next(i for i, c in enumerate(dec) if "sombra_parar.sh" in c)
    i_cfg = next(i for i, c in enumerate(dec) if "wslconfig.proposto" in c)
    i_shut = next(i for i, c in enumerate(dec) if "wsl --shutdown" in c)
    i_volta = next(i for i, c in enumerate(dec) if "Start-ScheduledTask -TaskName JFN-O36-Mistos" in c)
    assert i_parar < i_cfg < i_shut < i_volta and ".wslconfig.antes-o90" in dec[i_cfg]


def test_executar_etapa_2_recusa_antes_da_virada_e_sem_etapa(monkeypatch, capsys):
    from datetime import datetime, timezone
    assert not R.virou_assinatura(datetime(2026, 11, 28, 21, 59, tzinfo=timezone.utc))
    assert R.virou_assinatura(datetime(2026, 11, 28, 22, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(R, "virou_assinatura", lambda agora=None: False)
    monkeypatch.setattr(R, "estado_nos", lambda sha, rodar=None: {})
    assert R.main(["--executar", "--confirmo-dono-avisado", "--etapa", "2"]) == 2
    assert R.main(["--executar", "--confirmo-dono-avisado"]) == 2
    assert "etapa" in capsys.readouterr().err


@precisa_pg
def test_etapa_2_herda_o_bloqueio_da_etapa_1(con):
    con.execute("INSERT INTO liberacao(estagio, por) SELECT unnest(%s::text[]), 't'", (R.ETAPAS[1],))
    for e in R.ETAPAS[1]:
        R.registrar(con, {"estagio": e, "ok": e != "E3"})
    assert R.bloqueados_da_etapa1(con) == {"E3"}
    r = R.religar_estagios(con, REAL, espera_max_s=0, so=["E8"], dormir=lambda s: None, log=lambda *a: 0,
                           bloqueados_iniciais={"E3"})
    assert "pulado" in r["E8"]                                                 # E8 depende de E4 → E3


# ── semeador do backlog do E2 ─────────────────────────────────────────────────────────────────────────────────
def _item(p, ob):
    from compliance_agent.aplicacao.estagios.arvore import Item
    return Item(p, ob_paga=ob)


def test_semeador_segue_a_ordem_unica_pula_quem_tem_arvore_e_respeita_o_teto():
    from tools import e2_semear as S
    ordem = [(_item("010001/000001/2025", 10.0), {"inteiro": 1}), (_item("010001/000002/2025", 0.0), {"inteiro": 2}),
             (_item("010001/000003/2025", 5.0), {"inteiro": 3}), (_item("010001/000004/2025", 0.0), {"inteiro": 4}),
             (_item("010001/000005/2025", 7.0), {"inteiro": 5})]
    extras = {"fila_antiga:x.json": {"SEI-010001/000004/2025"}}
    sel = S.selecionar(None, {"010001/000003/2025"}, 2, extras, lentes_res={}, fila=lambda *a, **k: ordem)
    assert [(it.processo, pos) for it, _e, pos in sel] == [("010001/000001/2025", 1), ("010001/000004/2025", 4)]


def test_semeador_usa_a_prioridade_unica_canonica():
    """Nada de reinventar: a ordem é arvore.fila → prioridade.ordenar (§3.7; Couto como reserva intercalada)."""
    import inspect
    from compliance_agent.aplicacao.estagios import arvore as A
    from tools import e2_semear as S
    assert "A.fila" in inspect.getsource(S.selecionar) and "ordenar(" in inspect.getsource(A.fila)
    assert REAL.rotinas["e2_semear"].ativa and REAL.rotinas["e2_semear"].estagio == "E2"
    assert "--teto" in REAL.rotinas["e2_semear"].comando


@precisa_pg
def test_semeador_enfileira_job_nativo_idempotente(con):
    from tools import e2_semear as S
    esc = [(_item("010001/000001/2025", 10.0), {"inteiro": 1, "sinais": {}}, 1)]
    assert S.semear(con, REAL, esc) == {"escolhidos": 1, "novos": 1}
    assert S.semear(con, REAL, esc) == {"escolhidos": 1, "novos": 0}
    tipo, p = con.execute("SELECT tipo, payload FROM jobs WHERE chave = 'arvore:010001/000001/2025'").fetchone()
    assert tipo == "arvore" and p["estagio"] == "E2" and p["processo"] == "010001/000001/2025"
    assert p["prioridade"]["posicao"] == 1 and p["origem"] == "e2_semear"


def test_so_estagios_pula_os_passos_de_maquina():
    """25/11/2026: repetir a conferência da janela 1 sem refazer R0–R5 (wsl --shutdown, deploy, cron → fluxo)."""
    passos = [R.Passo("R0", "pré"), R.Passo("R4", "nós"), R.Passo("R-E17", "E17", estagio="E17"),
              R.Passo("R-E1", "E1", estagio="E1")]
    assert [p.id for p in R.so_estagios(passos)] == ["R-E17", "R-E1"]


# ── etapa 2: estágios de LLM, porta do ritmo e log na hora (frente D, 26/11/2026) ─────────────────────────────
def test_estagios_de_llm_da_etapa_2():
    """LLM = o estágio pede `llm` ou alguma rotina da 1ª volta pede (E9 vinculo_ob_modelo, E10 cruzador/vm2_sweeps)."""
    assert {e for e in R.ETAPAS[2] if R.estagio_de_llm(REAL, e)} == {"E8", "E9", "E10", "E11", "E12", "E13"}


def _job(con, chave, estado, estagio="E8", erro=None):
    con.execute("INSERT INTO jobs(tipo, chave, estado, payload, erro_tipo, concluido_em) VALUES (%s, %s, %s, %s, %s, "
                "CASE WHEN %s = 'feito' THEN now() END)", ("t", chave, estado, json.dumps({"estagio": estagio}),
                                                           erro, estado))


@precisa_pg
def test_llm_aceita_primeira_volta_parcial_sem_erro_depois_da_espera_minima(con):
    """26/11/2026: na etapa 2 a 1ª volta INTEIRA não cabe em 7.200 s (E8 com dezenas de fatos retidos, ~58 fatias por
    processo; E10 com ~20.000 s de cpu_pesado em 1 slot da VM-1) — o estágio virava BLOQUEADO e travava E9–E16."""
    con.execute("INSERT INTO liberacao(estagio, por) VALUES ('E8', 't')")
    _job(con, "a", "feito")
    _job(con, "b", "fila")
    _job(con, "c", "reservado")
    ch = ["a", "b", "c"]
    assert not R.conferir_estagio(con, "E8", ch)["ok"]                                       # não-LLM: inteira
    assert not R.conferir_estagio(con, "E8", ch, parcial=True, decorrido_s=10)["ok"]         # cedo demais
    r = R.conferir_estagio(con, "E8", ch, parcial=True, decorrido_s=R.ESPERA_PARCIAL_S)
    assert r["ok"] and r["parcial"] and sorted(r["pendentes_chaves"]) == ["b", "c"]
    _job(con, "d", "fila", erro="falhou")                                                    # voltou à fila com erro
    assert not R.conferir_estagio(con, "E8", ch + ["d"], parcial=True, decorrido_s=1e9)["ok"]
    _job(con, "e", "fila", erro="adiado")                                                    # SemCota/ritmo: espera
    assert R.conferir_estagio(con, "E8", ch + ["e"], parcial=True, decorrido_s=1e9)["ok"]


@precisa_pg
def test_llm_parcial_exige_um_feito_e_zero_quarentena(con):
    con.execute("INSERT INTO liberacao(estagio, por) VALUES ('E8', 't')")
    _job(con, "b", "fila")
    assert not R.conferir_estagio(con, "E8", ["b"], parcial=True, decorrido_s=1e9)["ok"]     # nada provado
    _job(con, "a", "feito")
    _job(con, "q", "quarentena")
    assert not R.conferir_estagio(con, "E8", ["a", "b"], parcial=True, decorrido_s=1e9)["ok"]


@precisa_pg
def test_esperar_llm_decide_na_espera_minima_sem_estourar_o_prazo(con):
    con.execute("INSERT INTO liberacao(estagio, por) VALUES ('E8', 't')")
    _job(con, "a", "feito")
    _job(con, "b", "fila")
    t = [0.0]
    r = R.esperar_estagio(con, "E8", ["a", "b"], 7200, poll_s=60, dormir=lambda s: t.__setitem__(0, t[0] + s),
                          relogio=lambda: t[0], parcial=True)
    assert r["ok"] and r["parcial"] and not r["esgotou"] and t[0] == R.ESPERA_PARCIAL_S


def test_etapa_2_nao_libera_llm_com_a_porta_do_ritmo_fechada(monkeypatch):
    """Logo depois da virada a medição ainda é a de antes (97% → contido) ou está velha: liberar o E8 assim queimava
    7.200 s por estágio de LLM e (com um legado que roda pela cascata) podia até 'conferir' sem nenhuma leitura."""
    chamou = []
    monkeypatch.setattr(R, "avisar", lambda *a, **k: True)
    monkeypatch.setattr(R, "porta_llm", lambda con, g: "porta fechada: medição da assinatura velha")
    monkeypatch.setattr(R, "religar_estagios", lambda *a, **k: chamou.append(1) or {})
    passos = [x for x in R.plano_religar(REAL, [], None, 2) if x.estagio]
    assert R.executar(passos, REAL, 0, con=object(), log=lambda *a: 0, etapa=2) == 1
    assert chamou == []


def test_log_do_religar_sai_na_hora_com_stdout_em_arquivo(monkeypatch, tmp_path):
    """Janela 1: `> arquivo` só mostrava os [E…] no fim (stdout em bloco)."""
    import io
    f = io.TextIOWrapper(io.FileIO(str(tmp_path / "log"), "w"), encoding="utf-8")
    assert not f.line_buffering
    monkeypatch.setattr("sys.stdout", f)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    R.main(["--avisar", "x"])
    assert (tmp_path / "log").read_text(encoding="utf-8").startswith("aviso: NÃO entregue")


def test_e15_que_falha_recoloca_a_faixa(monkeypatch):
    """Pré-mortem da etapa 2 (frente D, 26/11): se o comando do E15 falha depois do sed, a faixa de manutenção
    VOLTA — nunca painel sem faixa com o estágio BLOQUEADO."""
    rodados = []
    monkeypatch.setattr(R, "avisar", lambda *a, **k: True)
    monkeypatch.setattr(R, "rodar_cmd", lambda no, c, rodar: (rodados.append(c), 1 if c == "tirar-faixa" else 0)[1])
    visto = {}

    def religar(con, g, espera, so=None, log=print, apos=None, bloqueados_iniciais=None):
        visto["E15"] = apos("E15", {})
        return {"E15": {"ok": False}}
    monkeypatch.setattr(R, "religar_estagios", religar)
    passos = [R.Passo("R-E15", "E15", cmds=[("vm1", "tirar-faixa")], estagio="E15")]
    R.executar(passos, None, 1, con=object(), log=lambda *_: None)
    assert visto["E15"]["ok"] is False and visto["E15"]["faixa_voltou_rc"] == 0
    assert rodados == ["tirar-faixa", R.manutencao_volta()]


@precisa_pg
def test_fora_de_alcance_nao_bloqueia_o_estagio(con):
    """26/11/2026: o E2 ficou BLOQUEADO por 2 processos RESTRITOS à unidade (quarentena «só sai por gente»). É resultado
    declarado do domínio (rota SIP/SeiWS do dono, P5), não falha do estágio: segue listado na quarentena."""
    con.execute("INSERT INTO liberacao(estagio, por) VALUES ('E2', 't')")
    _job(con, "a", "feito", estagio="E2")
    con.execute("INSERT INTO jobs(tipo, chave, estado, payload, erro_resumo) VALUES ('arvore', 'r', 'quarentena', %s, %s)",
                (json.dumps({"estagio": "E2"}), "[fora_de_alcance] SEI respondeu RESTRITO"))
    r = R.conferir_estagio(con, "E2", ["a"])
    assert r["ok"] and r["ruins"] == 0 and r["fora_de_alcance"] == 1
    con.execute("INSERT INTO jobs(tipo, chave, estado, payload, erro_resumo) VALUES ('arvore', 'x', 'quarentena', %s, %s)",
                (json.dumps({"estagio": "E2"}), "árvore vazia"))
    assert not R.conferir_estagio(con, "E2", ["a"])["ok"]


def test_conexao_reconecta_quando_o_pg_reinicia():
    """26/11/2026 03:04: o unattended-upgrades da VM-2 reiniciou o PG (needrestart) e a janela morreu com AdminShutdown
    no meio da conferência do E1. As operações do religar são idempotentes: reconectar e repetir."""
    import psycopg

    class Falha:
        def __init__(self, n):
            self.n = n

        def execute(self, *a, **k):
            if self.n:
                self.n -= 1
                raise psycopg.errors.AdminShutdown("terminating connection due to administrator command")
            return "ok"

        def close(self):
            pass
    abertas = []

    def abrir():
        abertas.append(Falha(0))
        return abertas[-1]
    c = R.ConexaoResiliente(abrir, primeira=Falha(1), dormir=lambda s: None)
    assert c.execute("SELECT 1") == "ok" and len(abertas) == 1


def test_estagios_de_fila_conferem_pela_volta_parcial():
    """26/11/2026: a 1ª volta do E2 tinha 2.239 árvores (eventos das coletas do E1 recuperando a lacuna da parada) —
    31 feitas, 72 fora de alcance, 0 erro, e mesmo assim BLOQUEADO por não drenar tudo em 7.200 s. Estágio que DRENA
    fila (E2–E7) confere como o de LLM: ≥ 1 feito, 0 erro, o resto esperando. E1/E17/E18/E14–E16: volta inteira."""
    assert {e for e in R.ETAPAS[1] if R.estagio_parcial(REAL, e)} == {"E2", "E3", "E4", "E5", "E6", "E7", "E18"}  # E18: LLM
    assert {e for e in R.ETAPAS[2] if R.estagio_parcial(REAL, e)} == {"E8", "E9", "E10", "E11", "E12", "E13"}


@precisa_pg
def test_fila_tolera_poucas_novas_tentativas_mas_barra_erro_sistematico(con):
    """26/11/2026: numa fila de 2.200 leituras no SEI sempre há alguma nova tentativa por rede (transitória; a falha
    real é a quarentena). Estágio de FILA tolera erro em nova tentativa até 10% dos feitos (mínimo 3); erro
    sistemático (a trava de navegador: 9 erros para 11 feitos) continua barrando. LLM segue com zero."""
    con.execute("INSERT INTO liberacao(estagio, por) VALUES ('E2', 't')")
    ch = []
    for i in range(30):
        _job(con, f"f{i}", "feito", estagio="E2"); ch.append(f"f{i}")
    for i in range(3):
        _job(con, f"e{i}", "fila", estagio="E2", erro="erro"); ch.append(f"e{i}")
    _job(con, "w", "fila", estagio="E2"); ch.append("w")
    assert R.conferir_estagio(con, "E2", ch, parcial=True, decorrido_s=1e9, fila=True)["ok"]
    for i in range(3, 9):
        _job(con, f"e{i}", "fila", estagio="E2", erro="erro"); ch.append(f"e{i}")
    assert not R.conferir_estagio(con, "E2", ch, parcial=True, decorrido_s=1e9, fila=True)["ok"]   # 9 > 3


@precisa_pg
def test_fora_de_alcance_da_primeira_volta_conta_como_decidido(con):
    """26/11/2026 12h25: o E2 não passava NUNCA — a soma feitos + pendentes não fechava com o total da 1ª volta porque
    os processos RESTRITOS (ForaDeAlcance, em quarentena) da própria volta não entravam em nenhuma das duas contas."""
    con.execute("INSERT INTO liberacao(estagio, por) VALUES ('E2', 't')")
    for i in range(20):
        _job(con, f"f{i}", "feito", estagio="E2")
    con.execute("INSERT INTO jobs(tipo, chave, estado, payload, erro_resumo) VALUES ('arvore', 'r1', 'quarentena', %s, %s)",
                (json.dumps({"estagio": "E2"}), "[fora_de_alcance] SEI respondeu RESTRITO"))
    _job(con, "w", "fila", estagio="E2")
    ch = [f"f{i}" for i in range(20)] + ["r1", "w"]
    assert R.conferir_estagio(con, "E2", ch, parcial=True, decorrido_s=1e9, fila=True)["ok"]
    con.execute("DELETE FROM jobs WHERE chave = 'w'")
    r = R.conferir_estagio(con, "E2", [c for c in ch if c != "w"])
    assert r["ok"] and r["pendentes"] == 0                                  # volta inteira: feitos + fora = total


@precisa_pg
def test_interrupcao_da_infraestrutura_nao_conta_como_erro_do_job(con):
    """26/11/2026 13h30: o E2 não fechava com 16 "erros" — 15 eram o próprio supervisor reiniciando (parada) e
    posse vencida nos reinícios (lease_vencido). Interrupção da infraestrutura não é falha do job."""
    con.execute("INSERT INTO liberacao(estagio, por) VALUES ('E2', 't')")
    ch = []
    for i in range(10):
        _job(con, f"f{i}", "feito", estagio="E2"); ch.append(f"f{i}")
    for i, t in enumerate(["parada"] * 9 + ["lease_vencido"] * 6 + ["pressao"] * 2):
        _job(con, f"i{i}", "fila", estagio="E2", erro=t); ch.append(f"i{i}")
    r = R.conferir_estagio(con, "E2", ch, parcial=True, decorrido_s=1e9, fila=True)
    assert r["ok"] and r["com_erro"] == 0
