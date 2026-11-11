# -*- coding: utf-8 -*-
"""Execução: a REGRA decide se há o que julgar; o LLM julga o TEXTO do atesto/medição, não o resumo da ficha.

Medido em 11/11/2026 (`lex_execucao`, 4.839 linhas): 2.020 "indeterminado" (41,7%), concentrados onde há menos
de 5 docs (1.314 de 2.739) — juízo que uma regra resolve sem LLM: sem documento de execução nos autos
capturados não há execução a avaliar. E quando há, o prompt levava só `tipo`+`ponto` da ficha (resumo de até
40 itens), enquanto `data/sei_arquivo/` do mesmo processo tem o texto do atesto. Higiene: 21 notas entre 70 e
100 (pré-clamp) e 2 `'não'` acentuados contaminavam agregados; o clamp atual transformava 75 em 10.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from compliance_agent.sei import manifesto_norm
from tools import lex_execucao as L

NS = "SEI-270001/000123/2025"


@pytest.fixture(autouse=True)
def _isolar(monkeypatch, tmp_path):
    monkeypatch.setattr(L, "_regras_calibracao", lambda: "(teste)")
    monkeypatch.setattr(manifesto_norm, "_BASE", tmp_path / "sei_arquivo")


def _arquivo(tmp_path, docs):
    pasta = tmp_path / "sei_arquivo" / "270001_000123_2025"
    (pasta / "texto").mkdir(parents=True)
    man = {"processo": NS, "docs": []}
    for i, (titulo, texto) in enumerate(docs):
        rel = f"texto/{i:03d}.txt"
        (pasta / rel).write_text(texto, encoding="utf-8")
        man["docs"].append({"i": i, "titulo": titulo, "tipo": "", "fase": "", "texto": rel})
    (pasta / "manifest.json").write_text(json.dumps(man), encoding="utf-8")


def _con():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE lex_execucao (numero_sei TEXT PRIMARY KEY, objeto TEXT, tem_prestacao_contas INT, "
                "tem_fiscalizacao INT, tem_relatorio_fotografico INT, tem_atesto_recebimento INT, tem_nota_fiscal INT, "
                "tem_medicao INT, execucao_comprovada TEXT, coerencia TEXT, nota_risco INT, indicios TEXT, "
                "duvidas TEXT, resumo TEXT, modelo TEXT, em TEXT)")
    return con


def _proibido(*a):
    raise AssertionError("sem documento de execução o LLM NÃO pode ser chamado")


def test_arquivo_sem_documento_de_execucao_nao_vai_ao_llm(tmp_path):
    _arquivo(tmp_path, [("Nota de Empenho 2025NE001", "empenho"), ("Despacho de encaminhamento", "segue")])
    con = _con()
    res = L.avaliar_processo(con, NS, "obj", "", [{"tipo": "despacho", "ponto": "encaminha"}], [], _proibido)
    assert res["verdict"]["execucao_comprovada"] == "sem_documento_execucao"
    exec_, nota, modelo = con.execute("select execucao_comprovada, nota_risco, modelo from lex_execucao").fetchone()
    assert exec_ == "sem_documento_execucao" and nota is None and modelo.startswith("regra")


def test_sem_arquivo_e_ficha_sem_execucao_tambem_e_regra():
    con = _con()
    res = L.avaliar_processo(con, NS, "obj", "", [{"tipo": "empenho", "ponto": "Nota de empenho emitida"}],
                             [], _proibido)
    assert res["verdict"]["execucao_comprovada"] == "sem_documento_execucao"


def test_regra_nao_sobrescreve_veredito_do_llm_ja_dado():
    con = _con()
    con.execute(f"insert into lex_execucao (numero_sei, execucao_comprovada, nota_risco) values ('{NS}','sim',2)")
    assert L.avaliar_processo(con, NS, "obj", "", [], [], _proibido) is None
    assert con.execute("select execucao_comprovada from lex_execucao").fetchone()[0] == "sim"


def test_com_atesto_o_llm_recebe_o_texto_do_documento(tmp_path):
    _arquivo(tmp_path, [("Nota de Empenho", "empenho"),
                        ("Atestado de Recebimento de Materiais", "Atesto que recebi 1.000 resmas de papel A4."),
                        ("Boletim de Medição nº 3", "Medição: 40% dos serviços executados.")])
    vistos = []

    def _g(prompt, sys_, t=None):
        vistos.append(prompt)
        return '{"execucao_comprovada":"sim","nota_risco_execucao":2}'

    L.avaliar_processo(_con(), NS, "obj", "", [], [], _g)
    assert "Atesto que recebi 1.000 resmas de papel A4." in vistos[0]
    assert "Medição: 40% dos serviços executados." in vistos[0]
    bloco = vistos[0].split("TEXTO DOS DOCUMENTOS DE EXECUÇÃO")[1]
    assert "Nota de Empenho" not in bloco, "só a peça de execução vai como texto — o resto segue pela ficha"


@pytest.mark.parametrize("bruto,esperado", [
    (7, 7), ("7", 7), (0, 0), (10, 10), ("7/10", 7), ("7,4", 7), (6.6, 7),
    (75, None), (100, None), (-1, None), ("alto", None), (None, None), (True, None),
])
def test_nota_fora_de_0_a_10_e_rejeitada_nao_clampada(bruto, esperado):
    assert L._nota_0a10(bruto) == esperado


def test_nao_acentuado_vira_nao():
    con = _con()

    def _g(*a):
        return '{"execucao_comprovada":"Não","nota_risco_execucao":75}'

    res = L.avaliar_processo(con, NS, "obj", "", [{"tipo": "aceite", "ponto": "Termo de recebimento definitivo"}],
                             [], _g)
    assert res["verdict"]["execucao_comprovada"] == "nao"
    exec_, nota = con.execute("select execucao_comprovada, nota_risco from lex_execucao").fetchone()
    assert (exec_, nota) == ("nao", None), "75 não é 10: escala desconhecida, nota descartada"


def test_veredito_da_regra_nao_consome_vaga_do_llm(monkeypatch):
    """--top 4 por passada (32/dia): se o "sem documento" comesse a vaga, a vazão de LLM cairia junto."""
    import sys

    import compliance_agent.direcionamento_cerebro as DC

    class _SemFechar:
        def __init__(self, c):
            self._c = c

        def __getattr__(self, k):
            return getattr(self._c, k)

        def close(self):
            return None

    con = _con()
    con.execute("CREATE TABLE sei_ficha (numero_sei TEXT, objeto TEXT, valores TEXT, documentos TEXT, "
                "red_flags TEXT, n_docs INT)")
    sem = json.dumps([{"tipo": "empenho", "ponto": "nota de empenho"}])
    com = json.dumps([{"tipo": "aceite", "ponto": "Termo de recebimento definitivo"}])
    for ns, docs, n in (("SEI-1/1/2025", sem, 9), ("SEI-1/2/2025", sem, 8), ("SEI-1/3/2025", com, 7),
                        ("SEI-1/4/2025", com, 6)):
        con.execute("INSERT INTO sei_ficha VALUES (?,?,?,?,?,?)", (ns, "o", "", docs, "[]", n))
    chamadas = []
    monkeypatch.setattr(DC, "gerar_sync", lambda p, s, t=None: chamadas.append(1) or '{"execucao_comprovada":"sim"}')
    monkeypatch.setattr(L, "_con", lambda: _SemFechar(con))
    monkeypatch.setattr(L, "mapa_obs_siafe", lambda c, ns: {})
    monkeypatch.setattr(sys, "argv", ["lex_execucao", "--top", "1"])
    L.main()
    got = dict(con.execute("select numero_sei, execucao_comprovada from lex_execucao").fetchall())
    assert got == {"SEI-1/1/2025": "sem_documento_execucao", "SEI-1/2/2025": "sem_documento_execucao",
                   "SEI-1/3/2025": "sim"}
    assert len(chamadas) == 1
