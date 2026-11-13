# -*- coding: utf-8 -*-
"""Cruzamento Claude × cascata: banco próprio em tmp, dados sintéticos."""
import pytest

from compliance_agent.llm import cruzamento as C
from compliance_agent.llm.cruzamento import Lado


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "cruz.db"))


def _cl(n, v="x"):
    return Lado("claude", "claude-sonnet-5-5", v, n, latencia_ms=100)


def _out(n, modelo="gemini:gemini-3-flash-preview", v="y", fs=False):
    return Lado("cascata", modelo, v, n, latencia_ms=50, com_exemplos=fs)


def test_acordo_nao_gera_exemplo_nem_revisao():
    r = C.cruzar("t", "i1", _cl(1), _out(1), entrada_resumo="entrada")
    assert r == {"par": r["par"], "divergencia": False, "grave": False}
    con = C.conectar()
    assert con.execute("SELECT COUNT(*) FROM veredito").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM exemplo").fetchone()[0] == 0


def test_divergencia_vira_exemplo_mascarado_e_grave_vira_revisao():
    r = C.cruzar("t", "i1", _cl(2, "vermelho"), _out(0, v="verde"),
                 entrada_resumo="sócio CPF 123.456.789-01 e 98765432100 no contrato")
    assert r["divergencia"] and r["grave"]
    ex = C.exemplos("t")
    assert len(ex) == 1 and "123.456.789-01" not in ex[0]["entrada"] and "98765432100" not in ex[0]["entrada"]
    assert "vermelho" in ex[0]["referencia"]
    rv = C.revisoes_pendentes()
    assert rv[0]["veredito_claude"] == "vermelho" and rv[0]["veredito_outro"] == "verde"


def test_divergencia_leve_nao_vai_para_revisao():
    r = C.cruzar("t", "i", _cl(2), _out(1), entrada_resumo="e")
    assert r["divergencia"] and not r["grave"] and C.revisoes_pendentes() == []


def test_lado_ausente_ou_indeterminado_nao_conta_como_discordancia():
    C.cruzar("t", "a", None, _out(1))                     # sem cota: só a cascata, marcado
    C.cruzar("t", "b", _cl(None), _out(2))
    c = C.concordancia()
    ln = c["por_tarefa_modelo"][0]
    assert ln["n"] == 0 and ln["indeterminados"] == 1


def test_concordancia_matriz_e_ab_do_few_shot():
    for i in range(4):
        C.cruzar("t", f"s{i}", _cl(1), _out(1 if i < 2 else 0))          # sem exemplos: 2/4
    for i in range(4):
        C.cruzar("t", f"c{i}", _cl(1), _out(1 if i < 3 else 2, fs=True))  # com exemplos: 3/4
    ln = C.concordancia()["por_tarefa_modelo"][0]
    assert ln["n"] == 8 and ln["acordos"] == 5
    assert ln["taxa_sem_exemplos"] == 0.5 and ln["taxa_com_exemplos"] == 0.75
    m = C.concordancia()["matriz"]["t"]
    assert m["🟡×🟡"] == 5 and m["🟡×⚪"] == 2 and m["🟡×🔴"] == 1


def test_exemplos_rotativos():
    for i in range(5):
        C.cruzar("t", f"i{i}", _cl(2), _out(1), entrada_resumo=f"entrada {i}")
    a = {e["entrada"] for e in C.exemplos("t", k=3)}
    b = {e["entrada"] for e in C.exemplos("t", k=3)}
    assert len(a) == 3 and (a | b) == {f"entrada {i}" for i in range(5)}


def test_preferido_exige_amostra_e_margem():
    for i in range(25):
        C.cruzar("t", f"g{i}", _cl(1), _out(1 if i < 15 else 0, modelo="gemini:m1"))   # 60 %
    for i in range(5):
        C.cruzar("t", f"q{i}", _cl(1), _out(1, modelo="groq"))                           # 100 %, n=5
    assert C.preferido("t") is None                    # groq sem amostra mínima
    for i in range(20):
        C.cruzar("t", f"q2{i}", _cl(1), _out(1, modelo="groq"))
    assert C.placar("t")["groq"]["taxa"] == 1.0
    assert C.preferido("t") == "groq"


def test_resumo_painel_sem_banco_nao_quebra(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "nao_existe" / "x.db"))
    r = C.resumo_painel()
    assert r["medido"] is False and r["revisao_pendente"] == 0


def test_banco_nao_guarda_texto_do_prompt():
    C.cruzar("t", "i", _cl(1), _out(1), entrada_resumo="TEXTO-DO-PROMPT")
    con = C.conectar()
    linhas = con.execute("SELECT * FROM veredito").fetchall()
    assert "TEXTO-DO-PROMPT" not in repr(linhas)
