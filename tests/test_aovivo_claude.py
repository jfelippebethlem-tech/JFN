# -*- coding: utf-8 -*-
"""AO VIVO: o motor "Claude · co-motor" e as rotas de uso/cruzamento — arquivos em tmp, nenhum `claude`."""
import json

import pytest

from compliance_agent.aovivo import api, coleta
from compliance_agent.llm import claude_motor as M


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "d"))
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "cruz.db"))


def _duble(resultado="ok", is_error=False):
    return lambda *a, **k: (0, json.dumps({"is_error": is_error, "result": resultado}), "")


def test_catalogo_tem_o_motor_claude_com_uso_trava_e_efeito():
    m = {x["id"]: x for x in coleta.catalogo()}["claude"]
    assert m["uso"] == "claude_motor" and m["trava"].endswith("claude_motor.lock")
    assert m["efeito"]["chave"] == "ultima_ok_iso"


def test_uso_mostra_chamadas_por_tarefa_teto_e_ultimo_erro_saneado():
    M.pensar("triagem_alertas", "p", executar=_duble(), espera=0)
    M.pensar("pericia_execucao", "p", executar=_duble("token=abc123segredo falhou", True), espera=0)
    u = coleta.ler_uso("claude_motor")
    assert u["hoje"] == 2 and u["teto"] == M.teto_total()
    assert u["por_tarefa"]["triagem_alertas"]["chamadas"] == 1
    assert u["ultimo_erro"]["tarefa"] == "pericia_execucao" and "abc123segredo" not in u["ultimo_erro"]["motivo"]
    assert coleta.ler_uso("qualquer_outra") is None


def test_rotas_claude_e_cruzamento():
    assert api.ao_vivo_claude()["teto"] == M.teto_total()
    r = api.ao_vivo_cruzamento()
    assert r["medido"] is False and r["revisao_pendente"] == 0


def test_efeito_do_motor_le_a_ultima_resposta():
    M.pensar("triagem_alertas", "p", executar=_duble(), espera=0)
    ef = coleta.medir_efeito({"json": str(M._estado_arq()), "chave": "ultima_ok_iso"})
    assert ef is not None
