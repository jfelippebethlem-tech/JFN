# -*- coding: utf-8 -*-
"""Co-motor Claude × cascata — Claude e cascata DUBLÊS; nenhuma rede, nenhum `claude`."""
import json

import pytest

from compliance_agent import direcionamento_cerebro as dc
from compliance_agent.llm import comotor as CM
from compliance_agent.llm import cruzamento as C
from compliance_agent.llm.claude_motor import Pensamento


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "cruz.db"))
    monkeypatch.setattr(dc, "ultimo_provedor", "", raising=False)
    monkeypatch.setattr(dc, "ultimo_modelo", "", raising=False)


def _pensar(texto):
    chamadas = []

    def f(tarefa, prompt, **kw):
        chamadas.append({"tarefa": tarefa, "prompt": prompt, **kw})
        if texto is None:
            return None
        return Pensamento(texto=texto, modelo=kw.get("modelo", "claude-sonnet-5-5"), segundos=1.0, tarefa=tarefa)
    f.chamadas = chamadas
    return f


def _cascata(texto, erro=False):
    vistos = []

    def f(prompt, sistema="", timeout=45.0, json_saida=True):
        vistos.append(prompt)
        if erro:
            raise RuntimeError("cascata fora")
        return texto
    f.vistos = vistos
    return f


EXEC_VERMELHO = json.dumps({"execucao_comprovada": "nao", "nota_risco_execucao": 8})
EXEC_VERDE = json.dumps({"execucao_comprovada": "sim", "nota_risco_execucao": 1})


def test_os_dois_rodam_exibe_claude_e_grava_lado_a_lado():
    p, c = _pensar(EXEC_VERMELHO), _cascata(EXEC_VERDE)
    g = CM.juizo("pericia_execucao", pensar=p, cascata=c, sorteio=lambda: 1.0)
    assert g("PROMPT", "SYS", 60.0) == EXEC_VERMELHO
    assert len(p.chamadas) == 1 and len(c.vistos) == 1
    u = CM.ultima_chamada()
    assert u["exibido"].startswith("claude:") and u["outro"] == "cascata" and u["grave"] is True
    assert dc.ultimo_provedor == "claude"
    assert C.revisoes_pendentes()[0]["nivel_claude"] == 2
    assert CM.proveniencia().startswith("claude:claude-sonnet-5-5 (+")


def test_sem_claude_so_a_cascata_marcada():
    g = CM.juizo("pericia_execucao", pensar=_pensar(None), cascata=_cascata(EXEC_VERDE), sorteio=lambda: 1.0)
    assert g("p") == EXEC_VERDE
    con = C.conectar()
    linhas = con.execute("SELECT motor, modelo, veredito, nivel FROM veredito ORDER BY motor").fetchall()
    assert linhas[0][0] == "cascata" and linhas[0][3] == 0
    assert linhas[1][:2] == ("claude", "indisponivel") and linhas[1][2].startswith("sem_claude") and linhas[1][3] is None


def test_cascata_fora_claude_responde():
    g = CM.juizo("pericia_execucao", pensar=_pensar(EXEC_VERDE), cascata=_cascata("", erro=True), sorteio=lambda: 1.0)
    assert g("p") == EXEC_VERDE


def test_os_dois_fora_levanta_como_gerar_sync():
    g = CM.juizo("pericia_execucao", pensar=_pensar(None), cascata=_cascata("", erro=True), sorteio=lambda: 1.0)
    with pytest.raises(RuntimeError):
        g("p")


def test_few_shot_entra_so_no_braco_sorteado_e_fica_marcado():
    C.cruzar("pericia_execucao", "antigo", C.Lado("claude", "m", "nao/nota 8", 2),
             C.Lado("cascata", "gemini", "sim/nota 1", 0), entrada_resumo="CASO ANTIGO")
    c = _cascata(EXEC_VERDE)
    CM.juizo("pericia_execucao", pensar=_pensar(EXEC_VERDE), cascata=c, sorteio=lambda: 0.0)("NOVO")
    CM.juizo("pericia_execucao", pensar=_pensar(EXEC_VERDE), cascata=c, sorteio=lambda: 0.99)("NOVO2")
    assert "CASO ANTIGO" in c.vistos[0] and "NOVO" in c.vistos[0]
    assert "CASO ANTIGO" not in c.vistos[1]
    con = C.conectar()
    fs = dict(con.execute("SELECT item, com_exemplos FROM veredito WHERE motor='cascata' AND item!='antigo'").fetchall())
    assert sorted(fs.values()) == [0, 1]


def test_claude_nunca_recebe_os_exemplos():
    C.cruzar("pericia_execucao", "antigo", C.Lado("claude", "m", "x", 2), C.Lado("cascata", "g", "y", 0),
             entrada_resumo="CASO ANTIGO")
    p = _pensar(EXEC_VERDE)
    CM.juizo("pericia_execucao", pensar=p, cascata=_cascata(EXEC_VERDE), sorteio=lambda: 0.0)("NOVO")
    assert "CASO ANTIGO" not in p.chamadas[0]["prompt"]


def test_tarefa_sem_normalizador_nao_gasta_a_cascata_a_toa():
    c = _cascata("prosa da cascata")
    g = CM.juizo("parecer_juridico", pensar=_pensar("prosa do claude"), cascata=c)
    assert g("p") == "prosa do claude" and c.vistos == []
    g2 = CM.juizo("parecer_juridico", pensar=_pensar(None), cascata=c)
    assert g2("p") == "prosa da cascata" and len(c.vistos) == 1


def test_modelo_e_sistema_chegam_ao_claude():
    p = _pensar("{}")
    CM.juizo("parecer_juridico", modelo="claude-opus-5-5", pensar=p, cascata=_cascata("x"))("p", "SISTEMA-X")
    assert p.chamadas[0]["modelo"] == "claude-opus-5-5" and p.chamadas[0]["sistema"] == "SISTEMA-X"


def test_placar_prefere_provedor_que_mais_concorda(monkeypatch):
    chamado = []
    monkeypatch.setattr(C, "preferido", lambda t: "groq")
    monkeypatch.setattr(CM, "_chamar_provedor", lambda p, prompt, s: chamado.append(p) or EXEC_VERDE)
    monkeypatch.setattr(CM, "_gerar_sync_padrao", lambda *a, **k: pytest.fail("não devia cair na cascata fixa"))
    g = CM.juizo("pericia_execucao", pensar=_pensar(EXEC_VERDE), sorteio=lambda: 1.0)
    g("p")
    assert chamado == ["groq"]
    con = C.conectar()
    assert con.execute("SELECT modelo FROM veredito WHERE motor='cascata'").fetchone()[0] == "groq"


@pytest.mark.parametrize("fn,txt,nivel", [
    (CM.norm_execucao, '{"execucao_comprovada":"parcial","nota_risco_execucao":5}', 1),
    (CM.norm_execucao, '{"execucao_comprovada":"indeterminado"}', None),
    (CM.norm_fachada, '{"veredito":"FACHADA_PROVAVEL","confianca":"ALTA"}', 2),
    (CM.norm_fachada, '{"veredito":"INSUFICIENTE"}', 0),
    (CM.norm_risco, '{"risco":"médio"}', 1),
    (CM.norm_adversarial, '{"refuta": true}', 0),
    (CM.norm_adversarial, '{"refuta": false}', 2),
    (CM.norm_adversarial, 'sem json', None),
    (CM.norm_triagem, '{"prioridade":"aprofundar","nota":8}', 2),
])
def test_normalizadores(fn, txt, nivel):
    assert fn(txt)[1] == nivel
