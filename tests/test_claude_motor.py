# -*- coding: utf-8 -*-
"""Motor Claude: todo teste usa um EXECUTOR DUBLÊ — nenhum chama o `claude` de verdade."""
import json
import subprocess

import pytest

from compliance_agent.llm import claude_motor as M


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("JFN_CLAUDE_CWD", str(tmp_path / "cwd"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-nao-pode-vazar")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-nao-pode-vazar")
    for v in ("JFN_CLAUDE_MOTOR", "JFN_CLAUDE_MAX_CHAMADAS_DIA", "JFN_CLAUDE_MAX_SEGUNDOS_DIA"):
        monkeypatch.delenv(v, raising=False)
    yield


class Duble:
    def __init__(self, resultado="ok", is_error=False, rc=0, saida=None, erro=""):
        self.chamadas = []
        self.resultado, self.is_error, self.rc, self.saida, self.erro = resultado, is_error, rc, saida, erro

    def __call__(self, cmd, entrada, env, cwd, timeout):
        self.chamadas.append({"cmd": cmd, "entrada": entrada, "env": env, "cwd": cwd, "timeout": timeout})
        if self.saida is not None:
            return self.rc, self.saida, self.erro
        return self.rc, json.dumps({"type": "result", "subtype": "success", "is_error": self.is_error,
                                    "result": self.resultado}), self.erro


def test_comando_usa_assinatura_sem_bare_e_sem_chave():
    d = Duble("resposta")
    r = M.pensar("pericia_execucao", "PROMPT-SECRETO", executar=d, espera=0)
    assert r and r.texto == "resposta" and r.modelo == M.MODELO_VOLUME
    c = d.chamadas[0]
    assert "--bare" not in c["cmd"]
    for flag in ("-p", "--output-format", "--strict-mcp-config", "--setting-sources", "--no-session-persistence"):
        assert flag in c["cmd"]
    assert c["cmd"][c["cmd"].index("--tools") + 1] == ""          # sem ferramenta nenhuma por padrão
    assert c["cmd"][:3] == ["nice", "-n", "10"]
    assert "ANTHROPIC_API_KEY" not in c["env"] and "ANTHROPIC_AUTH_TOKEN" not in c["env"]
    assert "PROMPT-SECRETO" in c["entrada"] and "PROMPT-SECRETO" not in " ".join(c["cmd"])   # prompt pela entrada
    assert "JFN" not in str(c["cwd"]) or "worktrees" not in str(c["cwd"])


def test_ferramentas_e_modelo_de_juizo():
    d = Duble()
    M.pensar("parecer_juridico", "x", modelo=M.MODELO_JUIZO, ferramentas=("Read",), executar=d, espera=0)
    cmd = d.chamadas[0]["cmd"]
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-5"
    assert cmd[cmd.index("--tools") + 1] == "Read"


@pytest.mark.parametrize("duble,trecho", [
    (Duble(is_error=True, resultado="algo deu errado"), "erro"),
    (Duble(resultado="   "), "erro"),
    (Duble(saida="isto não é json", rc=1), "sem JSON"),
])
def test_corpo_invalido_vira_none_com_motivo(duble, trecho):
    assert M.pensar("pericia_execucao", "p", executar=duble, espera=0) is None
    assert trecho in M.ultimo_motivo
    u = M.ler_uso()
    assert u["total"]["erros"] == 1 and u["ultimo_erro"]["tarefa"] == "pericia_execucao"


def test_erro_de_limite_pausa_o_motor():
    d = Duble(is_error=True, resultado="Claude AI usage limit reached|1731500000")
    assert M.pensar("pericia_execucao", "p", executar=d, espera=0) is None
    assert "limite" in M.ultimo_motivo
    assert M.motivo_desligado().startswith("limite de uso")
    d2 = Duble()
    assert M.pensar("pericia_execucao", "p", executar=d2, espera=0) is None
    assert d2.chamadas == []                      # nem chamou: está em pausa


def test_teto_por_tarefa_e_total(monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_MAX_PERICIA_EXECUCAO", "2")
    d = Duble()
    assert M.pensar("pericia_execucao", "a", executar=d, espera=0)
    assert M.pensar("pericia_execucao", "b", executar=d, espera=0)
    assert M.pensar("pericia_execucao", "c", executar=d, espera=0) is None
    assert "teto diário da tarefa" in M.ultimo_motivo
    assert len(d.chamadas) == 2
    monkeypatch.setenv("JFN_CLAUDE_MAX_CHAMADAS_DIA", "3")
    assert M.pensar("triagem_alertas", "d", executar=d, espera=0)
    assert M.pensar("triagem_alertas", "e", executar=d, espera=0) is None
    assert "teto diário total" in M.ultimo_motivo


def test_teto_de_segundos(monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_MAX_SEGUNDOS_DIA", "5")
    M._mutar_uso(lambda d: d["total"].__setitem__("segundos", 6.0))
    assert M.pensar("pericia_execucao", "a", executar=Duble(), espera=0) is None
    assert "tempo" in M.ultimo_motivo


def test_kill_switch_env_e_arquivo(monkeypatch, tmp_path):
    monkeypatch.setenv("JFN_CLAUDE_MOTOR", "0")
    assert M.pensar("x", "p", executar=Duble(), espera=0) is None
    monkeypatch.delenv("JFN_CLAUDE_MOTOR")
    M._pausa_arq().parent.mkdir(parents=True, exist_ok=True)
    M._pausa_arq().touch()
    assert M.pensar("x", "p", executar=Duble(), espera=0) is None
    assert "pausado" in M.ultimo_motivo


def test_trava_ocupada_devolve_none(tmp_path):
    with M._flock(M._trava_arq(), 0):
        assert M.pensar("x", "p", executar=Duble(), espera=0) is None
    assert "ocupado" in M.ultimo_motivo


def test_prazo_estourado():
    def lento(*a, **k):
        raise subprocess.TimeoutExpired("claude", 1)
    assert M.pensar("x", "p", executar=lento, espera=0) is None
    assert "prazo" in M.ultimo_motivo


def test_schema_extrai_json_e_confere_chaves():
    d = Duble('Claro:\n```json\n{"risco": "alto", "citacao": "x"}\n```')
    r = M.pensar("investigacao_risco", "p", schema={"required": ["risco"]}, executar=d, espera=0)
    assert r.dados == {"risco": "alto", "citacao": "x"}
    assert "JSON" in d.chamadas[0]["entrada"]
    d2 = Duble('{"outra": 1}')
    assert M.pensar("investigacao_risco", "p", schema={"required": ["risco"]}, executar=d2, espera=0) is None
    assert "faltam risco" in M.ultimo_motivo


def test_uso_nao_guarda_prompt_nem_resposta():
    M.pensar("pericia_execucao", "CPF 12345678901 segredo", executar=Duble("RESPOSTA-SIGILOSA"), espera=0)
    M.pensar("pericia_execucao", "CPF 12345678901 segredo", executar=Duble(is_error=True, resultado="CPF 12345678901 segredo"), espera=0)
    bruto = M._uso_arq().read_text() + M._log_arq().read_text()
    assert "12345678901" not in bruto and "RESPOSTA-SIGILOSA" not in bruto


def test_executor_que_explode_nao_derruba():
    def bomba(*a, **k):
        raise ValueError("x")
    assert M.pensar("x", "p", executar=bomba, espera=0) is None


def test_canario_ok_falha_e_religa():
    avisos = []
    r = M.canario(executar=Duble("OK"), avisar=avisos.append)
    assert r["ok"] and avisos == [] and M.motivo_desligado() is None
    r = M.canario(executar=Duble(is_error=True, resultado="Invalid API key · Please run /login"), avisar=avisos.append)
    assert not r["ok"] and len(avisos) == 1 and "desligado" in avisos[0]
    assert M.motivo_desligado().startswith("desligado pelo canário")
    assert M.pensar("pericia_execucao", "p", executar=Duble(), espera=0) is None
    r = M.canario(executar=Duble("OK."), avisar=avisos.append)
    assert r["ok"] and "religado" in avisos[-1] and M.motivo_desligado() is None


def test_painel_resume_sem_conteudo():
    M.pensar("triagem_alertas", "p", executar=Duble(), espera=0)
    p = M.painel()
    assert p["hoje"] == 1 and p["por_tarefa"]["triagem_alertas"]["teto"] == M.TETOS_TAREFA["triagem_alertas"]
    assert p["teto"] == M.TETO_CHAMADAS_DIA and p["ligado"] is True
