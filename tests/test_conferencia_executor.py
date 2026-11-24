# -*- coding: utf-8 -*-
"""O1.9 — 2º executor da conferência do Opus (it-campo | VM-2) com a MESMA trava de ritmo.
Tudo com dublês: nenhum ssh, nenhum `claude`, nenhum PostgreSQL de verdade."""
import json
import subprocess
import sys

import pytest

from compliance_agent.llm import claude_motor as M
from compliance_agent.llm import conferencia_executor as E
from compliance_agent.llm import conferencia_opus as Q
from compliance_agent.llm.claude_motor import Pensamento


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("JFN_CLAUDE_CWD", str(tmp_path / "cwd"))
    monkeypatch.setenv("JFN_CONFERENCIA_DB", str(tmp_path / "conf.db"))
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "cruz.db"))
    monkeypatch.setenv("JFN_CLAUDE_API", "0")
    for v in ("JFN_CONFERENCIA_EXECUTOR", "JFN_CLAUDE_MOTOR", "JFN_CLAUDE_CONTINGENCIA", "JFN_EVIDENCIAS_DSN"):
        monkeypatch.delenv(v, raising=False)
    yield


def _sonda(vivos):
    chamadas = []

    def s(nome):
        chamadas.append(nome)
        return nome in vivos
    s.chamadas = chamadas
    return s


# ── escolha ──────────────────────────────────────────────────────────────────────────────────────────
def test_heartbeat_fresco_do_itcampo_escolhe_itcampo_sem_sondar():
    s = _sonda(set())
    assert E.escolher(hb={"itcampo": 30.0, "vm2": 10.0}, sondar=s)[0] == "itcampo" and s.chamadas == []


def test_sem_itcampo_cai_na_vm2():
    s = _sonda({"vm2"})
    nome, porque = E.escolher(hb={"itcampo": 9999.0}, sondar=s)
    assert nome == "vm2" and "itcampo indisponível" in porque and s.chamadas == ["itcampo", "vm2"]


def test_sem_pg_o_teste_rapido_decide():
    assert E.escolher(hb=None, sondar=_sonda({"itcampo"}), ler_hb=lambda: None)[0] == "itcampo"
    assert E.escolher(hb={}, sondar=_sonda({"vm2"}))[0] == "vm2"


def test_negativo_nenhum_disponivel_nao_escolhe():
    nome, porque = E.escolher(hb={}, sondar=_sonda(set()))
    assert nome is None and "vm2 indisponível" in porque


def test_forcado_pela_variavel(monkeypatch):
    monkeypatch.setenv("JFN_CONFERENCIA_EXECUTOR", "vm2")
    assert E.escolher(hb={"itcampo": 1.0}, sondar=_sonda(set()))[0] == "vm2"
    monkeypatch.setenv("JFN_CONFERENCIA_EXECUTOR", "nuvem")
    assert E.escolher(hb={}, sondar=_sonda({"vm2"}))[0] is None


# ── execução ─────────────────────────────────────────────────────────────────────────────────────────
def _cmd():
    return M.montar_comando("claude-opus-5-5", "SISTEMA 'com aspas' e\nquebra", ())


def test_vm2_manda_args_e_prompt_pela_entrada_padrao_sem_bare():
    visto = {}

    def rodar(cmd, entrada, env, cwd, timeout):
        visto.update(cmd=cmd, entrada=entrada, timeout=timeout)
        return 0, "{}", ""
    E.executar_em("vm2", rodar)(_cmd(), "PROMPT SIGILOSO", {}, "/tmp", 600.0)
    assert visto["cmd"][-3:] == ["vm2", "python3", "-"]
    assert all("PROMPT" not in c and "SISTEMA" not in c for c in visto["cmd"])     # nada no argv do ssh
    assert "PROMPT SIGILOSO" in visto["entrada"] and "--bare" not in visto["entrada"]
    assert "ANTHROPIC_API_KEY" in visto["entrada"]                                  # o receptor tira a chave


def test_receptor_vm2_roda_localmente_com_binario_dublê(tmp_path):
    """O script que vai à VM-2 executa de verdade (com um `claude` falso no HOME) e devolve stdout/rc do CLI."""
    casa = tmp_path / "casa"
    b = casa / ".local" / "bin"
    b.mkdir(parents=True)
    falso = b / "claude"
    falso.write_text("#!/bin/sh\ncat >/dev/null\necho \"{\\\"args\\\": \\\"$1 $2 $3\\\", \\\"key\\\": \\\"${ANTHROPIC_API_KEY:-}\\\"}\"\n")
    falso.chmod(0o755)
    capturado = {}

    def rodar(cmd, entrada, env, cwd, timeout):
        capturado["script"] = entrada
        return 0, "", ""
    E.executar_em("vm2", rodar)(_cmd(), "oi", {}, str(tmp_path), 60.0)
    r = subprocess.run([sys.executable, "-"], input=capturado["script"], capture_output=True, text=True, timeout=60,
                       env={"HOME": str(casa), "PATH": "/usr/bin:/bin", "ANTHROPIC_API_KEY": "nao-pode"})
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["args"] == "-p --model claude-opus-5-5" and d["key"] == ""


def test_itcampo_troca_so_o_binario_pelo_wrapper():
    visto = {}
    E.executar_em("itcampo", lambda cmd, *a: visto.update(cmd=cmd) or (0, "", ""))(_cmd(), "x", {}, "/tmp", 60.0)
    assert visto["cmd"][3].endswith("tools/claude_no_itcampo.sh") and visto["cmd"][4] == "-p"


# ── trava de ritmo ───────────────────────────────────────────────────────────────────────────────────
def test_ritmo_do_pg_prevalece(monkeypatch):
    from compliance_agent.fluxo import ritmo
    monkeypatch.setattr(ritmo, "motivo", lambda con, t: "ritmo semanal da assinatura — contido")
    assert E.motivo_ritmo("conferencia_opus", con_pg=object()).startswith("ritmo semanal")
    monkeypatch.setattr(ritmo, "motivo", lambda con, t: None)
    assert E.motivo_ritmo("conferencia_opus", con_pg=object()) is None


def test_sem_pg_vale_o_arquivo_local_e_sem_medicao_a_porta_fecha():
    medido = lambda nivel: (lambda: {"medido": True, "nivel": nivel, "motivo": nivel})   # noqa: E731
    assert E.motivo_ritmo("conferencia_opus", nivel_local=medido("normal")) is None
    assert E.motivo_ritmo("conferencia_opus", nivel_local=medido("economia")) is None    # RESERVA_OPUS
    assert E.motivo_ritmo("conferencia_opus", nivel_local=medido("contido")).startswith("ritmo semanal")
    m = E.motivo_ritmo("conferencia_opus", nivel_local=lambda: {"medido": False, "motivo": "sem medição"})
    assert m.startswith("porta fechada")


# ── integração com a fila ────────────────────────────────────────────────────────────────────────────
def _fila_um():
    con = Q.conectar()
    Q.enfileirar("pericia_execucao", "sei:SEI-1/1/2025", "entrada",
                 motor="groq", resposta=json.dumps({"execucao_comprovada": "sim", "nota_risco_execucao": 1}), con=con)
    return con


def test_conferir_usa_o_executor_escolhido_e_registra():
    con = _fila_um()
    kw = {}

    def opus(t, e, **k):
        kw.update(k)
        return Pensamento(texto=json.dumps({"execucao_comprovada": "sim", "nota_risco_execucao": 1}),
                          modelo="claude-opus-5-5", segundos=1.0, tarefa=t)
    sentinela = object()
    f = Q.conferir(1, pensar=opus, con=con, ritmo=lambda t: None, escolher=lambda: ("vm2", "teste"),
                   executar_em=lambda nome: sentinela, piso=False)
    assert kw["executar"] is sentinela and kw["backend"] == "cli" and f[0]["executor"] == "vm2"


def test_negativo_ritmo_contido_nao_chama_o_opus_em_executor_nenhum():
    con = _fila_um()
    chamou = []
    f = Q.conferir(1, pensar=lambda *a, **k: chamou.append(1), con=con, ritmo=lambda t: "ritmo semanal — contido",
                   escolher=lambda: ("vm2", "x"), piso=False)
    assert f == [] and chamou == [] and Q.pendente("pericia_execucao", "sei:SEI-1/1/2025", con=con)


def test_negativo_sem_executor_a_fila_espera():
    con = _fila_um()
    chamou = []
    f = Q.conferir(1, pensar=lambda *a, **k: chamou.append(1), con=con, ritmo=lambda t: None,
                   escolher=lambda: (None, "ninguém"), piso=False)
    assert f == [] and chamou == []
