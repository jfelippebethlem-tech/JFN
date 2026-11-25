# -*- coding: utf-8 -*-
"""A trava de RITMO SEMANAL do `claude_motor` cede à autorização do dono SÓ no escopo do ensaio O8.5
(`JFN_ASSINATURA_ESCOPO=ensaio_o85` + `data/.assinatura_liberada_dono.json` + semana abaixo do teto). Fora disso,
nada muda. Nenhuma chamada real: só `motivo_desligado` e um executor dublê."""
import json

import pytest

from compliance_agent.llm import claude_motor as M
from compliance_agent.llm import contingencia, ritmo_assinatura

CONTIDO = "ritmo semanal da assinatura — assinatura em 68% da semana, acima do ritmo (49%)"


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    d = tmp_path / "dados"
    d.mkdir()
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(d))
    monkeypatch.delenv(M.ENV_ESCOPO, raising=False)
    monkeypatch.setattr(M, "_motivo_kill_switch", lambda: None)
    monkeypatch.setattr(contingencia, "motivo_bloqueio", lambda tarefa="": CONTIDO)
    monkeypatch.setattr(contingencia, "estado", lambda: {"ativa": True, "origem": "ritmo_semanal"})
    monkeypatch.setattr(ritmo_assinatura, "nivel", lambda: {"medido": True, "semana_pct": 68.0, "nivel": "contido"})
    return d


def _aut(d, escopo="passada --com-llm do ensaio O8.5 pela ASSINATURA (claude -p, backend cli); nunca API paga"):
    (d / M.LIBERACAO_DONO).write_text(json.dumps({"escopo": escopo, "teto_semana_pct": 80.0}), encoding="utf-8")


def test_sem_env_contido_recusa_como_antes(_isola):
    _aut(_isola)
    assert M.motivo_desligado(tarefa="conferencia_e12") == CONTIDO


def test_com_env_arquivo_e_abaixo_do_teto_passa(_isola, monkeypatch):
    _aut(_isola)
    monkeypatch.setenv(M.ENV_ESCOPO, M.ESCOPO_ENSAIO)
    assert M.motivo_desligado(tarefa="conferencia_e12") is None


def test_com_env_acima_do_teto_recusa(_isola, monkeypatch):
    _aut(_isola)
    monkeypatch.setenv(M.ENV_ESCOPO, M.ESCOPO_ENSAIO)
    monkeypatch.setattr(ritmo_assinatura, "nivel", lambda: {"medido": True, "semana_pct": 80.0})
    assert M.motivo_desligado(tarefa="conferencia_e12") == CONTIDO
    monkeypatch.setattr(ritmo_assinatura, "nivel", lambda: {"medido": False, "semana_pct": None})
    assert M.motivo_desligado(tarefa="conferencia_e12") == CONTIDO          # sem medição: na dúvida, recusa


def test_com_env_sem_arquivo_recusa(monkeypatch):
    monkeypatch.setenv(M.ENV_ESCOPO, M.ESCOPO_ENSAIO)
    assert M.motivo_desligado(tarefa="conferencia_e12") == CONTIDO


def test_outro_escopo_ou_arquivo_fora_do_escopo_recusa(_isola, monkeypatch):
    _aut(_isola)
    monkeypatch.setenv(M.ENV_ESCOPO, "outro_consumidor")
    assert M.motivo_desligado(tarefa="x") == CONTIDO
    monkeypatch.setenv(M.ENV_ESCOPO, M.ESCOPO_ENSAIO)
    _aut(_isola, escopo="qualquer coisa pela API paga")
    assert M.motivo_desligado(tarefa="x") == CONTIDO


def test_so_a_trava_de_ritmo_cede(_isola, monkeypatch):
    """Limite da conta, contingência forçada e kill switch não cedem à autorização."""
    _aut(_isola)
    monkeypatch.setenv(M.ENV_ESCOPO, M.ESCOPO_ENSAIO)
    monkeypatch.setattr(contingencia, "motivo_bloqueio", lambda tarefa="": "limite de uso da assinatura — pausa")
    monkeypatch.setattr(contingencia, "estado", lambda: {"ativa": True, "origem": "limite_assinatura"})
    assert M.motivo_desligado(tarefa="x") == "limite de uso da assinatura — pausa"
    monkeypatch.setattr(M, "_motivo_kill_switch", lambda: "kill switch ligado")
    assert M.motivo_desligado(tarefa="x") == "kill switch ligado"


def test_liberado_continua_so_pela_assinatura(_isola, monkeypatch):
    """Com o ritmo liberado, a chamada segue pelo CLI da assinatura (sem --bare, sem chave de API no ambiente)."""
    _aut(_isola)
    monkeypatch.setenv(M.ENV_ESCOPO, M.ESCOPO_ENSAIO)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "nao-pode-passar")
    visto = {}

    def executar(cmd, entrada, env, cwd, timeout):
        visto.update(cmd=cmd, env=env)
        return 0, json.dumps({"type": "result", "is_error": False, "result": "ok", "model": M.MODELO_JUIZO}), ""
    M.pensar("conferencia_e12", "p", modelo=M.MODELO_JUIZO, backend="cli", executar=executar)
    assert "--bare" not in visto["cmd"] and "ANTHROPIC_API_KEY" not in visto["env"]
