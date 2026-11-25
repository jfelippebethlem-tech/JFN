# -*- coding: utf-8 -*-
"""O10.7 — globo com arcos da aba Orçamento por órgão: o MESMO número que a tabela, e nada inventado.

Servidor (sintético, nenhum credor real): a soma dos arcos de cada UG é o `pago_siafe` da linha da UG na tabela, no
centavo; a soma de tudo é o total do Estado; OB devolvida, anulada, sem número e de restos a pagar fica fora dos dois;
CPF vira balde sem ponto e sem nome; CNPJ fora da Receita vira INDISPONÍVEL (tracejado), nunca um ponto.
Front (Node, sem navegador): `static/js/src/v71/globo/dados.js` filtra e agrega sem mudar a soma, e acusa quando o
globo e a tabela não batem.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from compliance_agent import orcamento_globo as G
from compliance_agent import orcamento_orgao as O
from tests.test_orcamento_orgao import _ALERJ, _SINT, _abertos

RAIZ = Path(__file__).resolve().parents[1]
SRC = RAIZ / "static" / "js" / "src"
NODE = shutil.which("node")

_CNPJ_RJ, _CNPJ_SP, _CNPJ_FORA, _CPF = "11111111000191", "22222222000191", "33333333000191", "12345678901"
# (numero, ug, data, status, tipo_ob, valor, gd, status_envio, exercicio, credor, nome_credor)
_OBS = [
    ("2024OB00001", "500100", "10/02/2024", "Contabilizado", "Orçamentária", 300.10, "", "Processado e Pago", 2024, _CNPJ_RJ, "EMPRESA RJ"),
    ("2024OB00002", "500100", "15/08/2024", "Contabilizado", "Orçamentária", 250.33, "", "Enviado Manualmente", 2024, _CNPJ_SP, "EMPRESA SP"),
    ("2024OB00003", "500100", "16/08/2024", "Contabilizado", "Orçamentária", 99.99, "", "Enviado Manualmente", 2024, _CPF, "FULANO DE TAL"),
    ("2024OB00004", "500100", "17/08/2024", "Contabilizado", "Orçamentária", 70.01, "", "Enviado Manualmente", 2024, "CG0004700", "FOLHA DE PAGAMENTOS"),
    ("2024OB00005", "500100", "18/08/2024", "Contabilizado", "Orçamentária", 12.34, "", "Enviado Manualmente", 2024, _CNPJ_FORA, "SEM CADASTRO"),
    # controles negativos: não são pago do orçamento — fora da tabela e fora dos arcos
    ("2024OB00006", "500100", "20/03/2024", "Contabilizado", "Orçamentária", 9000.0, "2024GD00007", "Erro no Pagamento", 2024, _CNPJ_RJ, "X"),
    ("2024OB00007", "500100", "21/03/2024", "Anulado", "Orçamentária", 8000.0, "", "", 2024, _CNPJ_RJ, "X"),
    ("", "500100", "23/03/2024", "Contabilizado", "Orçamentária", 6000.0, "", "", 2024, _CNPJ_RJ, "X"),
    ("2024OB00008", "500100", "24/03/2024", "Contabilizado", "RPP", 50.0, "", "Processado e Pago", 2024, _CNPJ_RJ, "X"),
    ("2024OB00010", "600100", "05/05/2024", "Contabilizado", "Orçamentária", 4100.0, "", "Processado e Pago", 2024, "500100", "SECRETARIA A"),
    ("2024OB00011", "010100", "05/05/2024", "Contabilizado", "Orçamentária", 1283172078.64, "", "Processado e Pago", 2024, _CNPJ_RJ, "EMPRESA RJ"),
]


@pytest.fixture
def bases(tmp_path):
    ab, db, rf = tmp_path / "ab.db", tmp_path / "c.db", tmp_path / "rf.db"
    _abertos(ab, _ALERJ + _SINT)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT, "
                "tipo_ob TEXT, valor REAL, gd TEXT, status_envio TEXT, exercicio INTEGER, credor TEXT, nome_credor TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?,?)", _OBS)
    con.commit(); con.close()
    con = sqlite3.connect(rf)
    con.execute("CREATE TABLE estabelecimentos (cnpj TEXT PRIMARY KEY, uf TEXT, municipio TEXT)")
    con.executemany("INSERT INTO estabelecimentos VALUES (?,?,?)", [(_CNPJ_RJ, "RJ", "5801"), (_CNPJ_SP, "SP", "7107")])
    con.commit(); con.close()
    return {"db": db, "db_abertos": ab, "db_receita": rf, "db_achados": tmp_path / "nao-existe.db"}


def _globo(bases, mes=None):
    d = O.montar(O.carregar(2024, bases["db"], bases["db_abertos"]), mes, O.exercicios(bases["db"], bases["db_abertos"]))
    g = G.montar(G.carregar(2024, bases["db"], bases["db_receita"], bases["db_achados"]), d)
    return d, g


def test_soma_dos_arcos_e_o_pago_siafe_da_tabela_por_ug_e_no_total(bases):
    d, g = _globo(bases)
    assert g["ok"] and not g["divergentes"]
    por_ug = {}
    for ln in g["linhas"]:
        por_ug[ln["ug"]] = round(por_ug.get(ln["ug"], 0) + ln["v"], 2)
    tab = {x["ug"]: x["pago_siafe"] for o in d["orgaos"] for x in o["ugs"] if x["espera_ob"] and x["pago_siafe"] is not None}
    assert por_ug == tab
    assert round(sum(ln["v"] for ln in g["linhas"]), 2) == d["total"]["pago_siafe"]
    # a UG 500100: 300,10 + 250,33 + 99,99 + 70,01 + 12,34 — devolvida, anulada, sem número e RPP fora
    assert tab["500100"] == 732.77


def test_destinos_sem_ponto_inventado_e_sem_pessoa(bases):
    _d, g = _globo(bases)
    d500 = {ln["d"]: ln["v"] for ln in g["linhas"] if ln["ug"] == "500100"}
    assert d500 == {"M:3300100": 300.10, "U:SP": 250.33, "X:pf": 99.99, "X:generico": 70.01, "X:sem_cadastro": 12.34}
    assert [ln["d"] for ln in g["linhas"] if ln["ug"] == "600100"] == ["X:ug"]
    texto = json.dumps(g, ensure_ascii=False)
    for proibido in (_CPF, "FULANO", "FOLHA DE PAGAMENTOS", _CNPJ_RJ):
        assert proibido not in texto, proibido          # nem CPF, nem nome de credor, nem CNPJ no payload do globo
    assert "X:sem_cadastro" not in g["lugares"] and "X:pf" not in g["lugares"]   # balde não é lugar
    assert g["lugares"]["M:3300100"] == {"nome": "Angra dos Reis", "tipo": "municipio"}


def test_recorte_por_mes_segue_a_tabela(bases):
    d, g = _globo(bases, mes=1)                  # só janeiro: nenhuma OB orçamentária válida da 500100
    tab = {x["ug"]: x["pago_siafe"] for o in d["orgaos"] for x in o["ugs"] if x["espera_ob"]}
    soma = {}
    for ln in g["linhas"]:
        soma[ln["ug"]] = round(soma.get(ln["ug"], 0) + ln["v"], 2)
    assert all(soma.get(u, None) == v for u, v in tab.items() if v is not None)
    assert "500100" not in soma


def test_tier1_so_com_detector_tier1_calculado(bases, tmp_path, monkeypatch):
    ach = tmp_path / "ach.db"
    con = sqlite3.connect(ach)
    con.execute("CREATE TABLE achado_execucao (contrato TEXT, detector TEXT, fornecedor TEXT, status TEXT)")
    con.executemany("INSERT INTO achado_execucao VALUES (?,?,?,?)",
                    [("c1", "X1", _CNPJ_SP, "confirmado"), ("c2", "X2", _CNPJ_RJ, "descartado")])
    con.commit(); con.close()
    bases = {**bases, "db_achados": ach}
    monkeypatch.setattr(G, "tier1_detectores", lambda hoje=None: set())
    _d, g = _globo(bases)
    assert all(ln["t1"] == 0 for ln in g["linhas"])                # hoje: nenhum detector Tier 1 → nada realça
    monkeypatch.setattr(G, "tier1_detectores", lambda hoje=None: {"X1", "X2"})
    _d, g = _globo(bases)
    t1 = {ln["d"]: ln["t1"] for ln in g["linhas"] if ln["t1"]}
    assert t1 == {"U:SP": 250.33}                                   # descartado não realça


def test_tabela_sem_coluna_credor_nao_quebra_o_pago(tmp_path):
    """`_iter_ob` serve as duas leituras: base antiga sem `credor` segue dando o mesmo pago na tabela."""
    from tests.test_orcamento_orgao import _OBS as OBS_ANTIGAS, _siafe
    ab, db = tmp_path / "ab.db", tmp_path / "c.db"
    _abertos(ab, _ALERJ + _SINT)
    _siafe(db, OBS_ANTIGAS)
    d = O.calcular(2024, db=db, db_abertos=ab)
    g = G.montar(G.carregar(2024, db, tmp_path / "rf.db", tmp_path / "a.db"), d)
    assert round(sum(ln["v"] for ln in g["linhas"]), 2) == d["total"]["pago_siafe"]
    assert {ln["d"] for ln in g["linhas"]} == {"X:generico"}         # sem credor: nenhum ponto


# ── front: o modelo do globo (Node, sem navegador) ─────────────────────────────────────────────────────────────
def _node(codigo: str):
    if not NODE:
        pytest.fail("node ausente — estes testes exigem Node (VM-1, VM-2 e it-campo têm)")
    r = subprocess.run([NODE, "--experimental-default-type=module", "--input-type=module", "-e", codigo],
                       capture_output=True, text=True, timeout=60, cwd=RAIZ)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _modelo_js(g: dict, orgaos: list, maximo: int = 80):
    return _node(f"""
const m = await import('{(SRC / "v71/globo/dados.js").as_uri()}');
const g = {json.dumps(g)}, orgaos = {json.dumps(orgaos)};
console.log(JSON.stringify(m.modelo(g, orgaos, {{max: {maximo}}})));""")


def test_modelo_js_confere_com_a_tabela_e_agrega_sem_mudar_a_soma(bases):
    d, g = _globo(bases)
    m = _modelo_js(g, d["orgaos"])
    assert m["confere"] is True and m["soma"] == round(d["total"]["pago_siafe"] * 100)
    assert m["soma_tracejado"] == 1234 and {f["k"] for f in m["fora"]} == {"X:pf", "X:generico", "X:ug"}
    assert all("12345678901" not in a["rotulo"] for a in m["arcos"])
    sp = [a for a in m["arcos"] if a["d"] == "U:SP"][0]
    assert sp["rotulo"].endswith("R$ 250,33") and "sede fora do RJ" in sp["rotulo"]
    # teto de 1 arco: agrega (origem única, depois "demais municípios") e a soma é a mesma
    m1 = _modelo_js(g, d["orgaos"], 1)
    assert m1["agregado"] != "nenhum" and m1["confere"] is True and m1["soma"] == m["soma"]


def test_modelo_js_segue_o_filtro_e_acusa_divergencia(bases):
    d, g = _globo(bases)
    so50 = [o for o in d["orgaos"] if o["orgao"] == "50"]
    m = _modelo_js(g, so50)
    assert m["confere"] is True and m["total_tabela"] == round(so50[0]["pago_siafe"] * 100)
    assert m["n_linhas"] == sum(1 for ln in g["linhas"] if ln["orgao"] == "50")
    adulterado = [{**so50[0], "pago_siafe": so50[0]["pago_siafe"] + 0.01}]
    assert _modelo_js(g, adulterado)["confere"] is False           # 1 centavo a mais na tabela: o globo não desenha
