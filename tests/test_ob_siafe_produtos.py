# -*- coding: utf-8 -*-
"""OB dos PRODUTOS (/relatorio, /orgao, dossiê, grafo, C9/TAC) = SIAFE pela régua única `_ob_paga`; fora da cobertura =
INDISPONÍVEL/PARCIAL, nunca o espelho. Irmã de `test_ob_siafe_ferramentas_caso.py` (decisão 2 da revisão crítica de
20/11/2026, D4: ~40 somas de `ordens_bancarias.valor` eram publicadas como "pago" nos produtos mais vistos).

Dados sintéticos (CNPJ/UG fictícios); nenhum CPF real.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CNPJ = "00000000000191"
CNPJ_FILIAL = "00000000000272"


def _base(tmp_path) -> Path:
    """SIAFE: matriz com 1 OB paga 2022 (100) + devolvida + anulada + complementar; filial com 1 OB paga (40).
    Espelho: a mesma OB paga com valor ERRADO (999) e observação de TAC; duas OB de 2020 numa UG que o SIAFE nunca
    leu (o espelho é o único que as lista: devem virar INDISPONÍVEL, com contagem e sem valor)."""
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT,"
                " status_envio TEXT, tipo_regularizacao TEXT, credor TEXT, nome_credor TEXT, valor REAL,"
                " exercicio INTEGER)")
    con.execute("CREATE TABLE ordens_bancarias (id INTEGER PRIMARY KEY, numero_ob TEXT, ug_codigo TEXT, ug_nome TEXT,"
                " data_emissao TEXT, data_pagamento TEXT, favorecido_cpf TEXT, favorecido_nome TEXT, valor REAL,"
                " exercicio INTEGER, observacao TEXT, numero_processo TEXT, numero_sei TEXT)")
    s = [("2022OB00001", "240100", "10/03/2022", "Contabilizado", "", "", CNPJ, "EMPRESA X", 100.0, 2022),
         ("2022OB00002", "240100", "11/03/2022", "Contabilizado", "Erro no Pagamento", "", CNPJ, "EMPRESA X", 50.0,
          2022),
         ("2022OB00003", "240100", "12/03/2022", "Anulado", "", "", CNPJ, "EMPRESA X", 30.0, 2022),
         ("2022OB00004", "240100", "13/03/2022", "Contabilizado", "", "Pagamento Complementar", CNPJ, "EMPRESA X",
          7.0, 2022),
         ("2022OB00005", "240100", "14/03/2022", "Contabilizado", "", "", CNPJ_FILIAL, "EMPRESA X FILIAL", 40.0,
          2022),
         # não-terceiros que só o SIAFE lista: encargo/folha ('CG…') e repasse a outra UG — fora do "pago pela UG"
         ("2022OB00006", "240100", "15/03/2022", "Contabilizado", "", "", "CG0000017", "ENCARGOS", 500.0, 2022),
         ("2022OB00007", "240100", "16/03/2022", "Contabilizado", "", "", "240200", "FUNDO Z", 600.0, 2022)]
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?)", s)
    t = [("2022OB00001", "240100", "SECRETARIA X", "2022-03-10", "2022-03-10", CNPJ, "EMPRESA X", 999.0, 2022,
          "TERMO DE AJUSTE DE CONTAS 1/2022", "", ""),
         ("2020OB00028", "530100", "SECRETARIA Y", "2020-03-13", "2020-03-13", CNPJ, "EMPRESA X", 4_000_000.0, 2020,
          "", "", ""),
         ("2020OB00029", "530100", "SECRETARIA Y", "2020-03-13", "2020-03-13", CNPJ, "EMPRESA X", 16_400_000.0, 2020,
          "", "", "")]
    con.executemany("INSERT INTO ordens_bancarias (numero_ob, ug_codigo, ug_nome, data_emissao, data_pagamento,"
                    " favorecido_cpf, favorecido_nome, valor, exercicio, observacao, numero_processo, numero_sei)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", t)
    con.commit()
    con.close()
    return p


@pytest.fixture
def base(tmp_path, monkeypatch):
    p = _base(tmp_path)
    monkeypatch.setenv("JFN_DB", str(p))
    import compliance_agent.reporting.intel_dados as D
    import compliance_agent.reporting.inteligencia_orgao as O
    monkeypatch.setattr(D, "_DB", p)
    monkeypatch.setattr(O, "_DB", p)
    return p


# ── régua de cobertura do recorte ────────────────────────────────────────────────────────────────────────────
def test_lacunas_do_recorte_conta_o_espelho_e_nao_soma(base):
    from compliance_agent.reporting.cobertura_siafe import lacunas_do_recorte, resumo_lacunas
    con = sqlite3.connect(base)
    lac = lacunas_do_recorte(con, credor_raiz=CNPJ[:8], db=base)
    assert lac == [{"ug": "530100", "ano": "2020", "rotulo": "INDISPONÍVEL", "obs_espelho": 2, "pct_ausente": 100.0}]
    r = resumo_lacunas(lac, n_siafe=2)
    assert r["estado"] == "PARCIAL" and r["anos_indisponiveis"] == ["2020"] and r["obs_espelho_fora"] == 2
    assert resumo_lacunas(lac, n_siafe=0)["estado"] == "INDISPONÍVEL"          # nada lido: não é "R$ 0,00"
    assert resumo_lacunas([])["estado"] == "VERIFICADO"


# ── /relatorio ───────────────────────────────────────────────────────────────────────────────────────────────
def test_relatorio_soma_so_a_ob_paga_do_siafe_da_raiz(base):
    from compliance_agent.reporting.intel_dados import consultar_pagamentos
    p = consultar_pagamentos(CNPJ)
    assert (p["n_geral"], p["total_geral"]) == (2, 140.0)          # matriz 100 + filial 40; nem 999, nem 20,4 mi
    assert list(p["por_ano"]) == [2022]                            # 2020 não vira linha "0" nem o valor do espelho
    assert p["por_ano"][2022]["linhas"][0]["data"] == "2022-03-10"
    assert p["cobertura"]["estado"] == "PARCIAL" and p["cobertura"]["lacunas"][0]["obs_espelho"] == 2


def test_relatorio_md_declara_a_lacuna_sem_valor_do_espelho(base):
    from compliance_agent.reporting.intel_dados import consultar_pagamentos
    from compliance_agent.reporting.intel_md import _cobertura_ob_md
    linhas: list[str] = []
    _cobertura_ob_md(linhas.append, consultar_pagamentos(CNPJ))
    md = "\n".join(linhas)
    assert "INDISPONÍVEL" in md and "530100" in md and "4.000.000" not in md and "20.400.000" not in md


def test_candidatos_trazem_o_pago_do_siafe(base):
    from compliance_agent.reporting.intel_dados import buscar_candidatos
    con = sqlite3.connect(base)
    con.execute("CREATE TABLE empresas (id INTEGER PRIMARY KEY, cnpj TEXT, razao_social TEXT)")
    con.commit()
    c = buscar_candidatos("empresa x")
    assert c and c[0]["total_pago"] == 100.0 and c[0]["n_obs"] == 1   # OB paga do SIAFE; nunca 20,4 mi do espelho


# ── /orgao ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_orgao_soma_so_a_ob_paga_do_siafe(base):
    from compliance_agent.reporting.inteligencia_orgao import consultar_orgao, dados_contratos_fornecedor
    p = consultar_orgao("240100")
    assert (p["n_geral"], p["total_geral"], p["n_fornecedores"]) == (2, 140.0, 2)
    assert p["cobertura"]["estado"] == "VERIFICADO"
    q = consultar_orgao("530100")                                  # só o espelho conhece: INDISPONÍVEL, não zero
    assert not q["tem_dados"] and q["cobertura"]["estado"] == "INDISPONÍVEL"
    con = sqlite3.connect(base)
    con.execute("CREATE TABLE contratos_tcerj (cnpj TEXT, objeto TEXT, processo TEXT, ano_processo TEXT,"
                " valor_contrato REAL, valor_pago REAL, status TEXT, vig_inicio TEXT, vig_fim TEXT,"
                " criterio_julgamento TEXT, unidade TEXT)")
    con.commit()
    d = dados_contratos_fornecedor("240100")
    assert sorted(x["pago"] for x in d["sem_contrato"]) == [40.0, 100.0]


def test_catalogo_de_ugs_diz_indisponivel_onde_o_siafe_nao_tem(base):
    from compliance_agent.reporting.inteligencia_orgao import listar_ugs
    u = {x["ug"]: x for x in listar_ugs()["ugs"]}
    assert u["240100"]["total"] == 140.0 and u["530100"]["total"] is None
    assert "INDISPONÍVEL" in listar_ugs("530100")["texto"] and "20.400.000" not in listar_ugs("530100")["texto"]


# ── dossiê ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_dossie_resumo_ob_e_o_pago_do_siafe(base):
    from compliance_agent.dossie import _resumo_ob
    r = _resumo_ob(CNPJ)
    assert (r["n_ob"], r["total_ob"], r["n_ugs"]) == (1, 100.0, 1)            # o dossiê é do CNPJ exato
    assert r["cobertura"]["anos_indisponiveis"] == ["2020"]


# ── C9 / TAC ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_tac_valor_do_siafe_observacao_do_espelho(base):
    from compliance_agent.reporting import detector_tac as dt
    m = dt.tac_por_cnpj(CNPJ, db_path=base)
    assert (m["n"], m["total"], m["total_tac"]) == (2, 140.0, 100.0)          # 999 do espelho não entra
    assert m["cobertura_siafe"]["anos_indisponiveis"] == ["2020"]
    u = dt.tac_por_ug("240100", db_path=base)
    assert (u["total"], u["total_tac"], u["ug_nome"]) == (140.0, 100.0, "SECRETARIA X")
    assert dt._ugs_do_cnpj(CNPJ, base) == [("240100", "", 140.0)]
    assert dt.medir_emergencial("240100", db_path=base)["total"] == 140.0


# ── grafo de poder ───────────────────────────────────────────────────────────────────────────────────────────
def test_grafo_pago_por_e_o_pago_do_siafe(base):
    from compliance_agent import grafo_poder as G
    con = sqlite3.connect(base)
    e = [x for x in G._expandir(con, f"cnpj:{CNPJ}", True) if x[1] == "pago_por"]
    assert [(x[0], x[2]["total_ob"]) for x in e] == [("ug:240100", 100.0)]
    e = [x for x in G._expandir(con, "ug:240100", True) if x[1] == "pago_por"]
    assert sorted(x[2]["total_ob"] for x in e) == [40.0, 100.0]


# ── catraca: nenhum produto tira VALOR do espelho ────────────────────────────────────────────────────────────
PRODUTOS = ["compliance_agent/reporting/intel_dados.py", "compliance_agent/reporting/intel_md.py",
            "compliance_agent/reporting/intel_pdf.py", "compliance_agent/reporting/intel_analise.py",
            "compliance_agent/reporting/inteligencia.py", "compliance_agent/reporting/inteligencia_orgao.py",
            "compliance_agent/reporting/detector_tac.py", "compliance_agent/reporting/anomalia_receita.py",
            "compliance_agent/dossie.py", "compliance_agent/grafo_poder.py", "compliance_agent/grafo_cartel.py",
            "compliance_agent/cruzamento.py", "compliance_agent/investigacao_orgao_dd.py"]
_FROM_ESPELHO = re.compile(r"FROM\s+(?:db\.)?ordens_bancarias\b", re.I)
MARCA = "espelho-fora-do-produto"   # comentário que declara: derivado do espelho que o produto não publica como pago


def test_produtos_nao_somam_valor_do_espelho_tfe():
    """O espelho só pode dar TEXTO (observação, nome da UG/favorecido) ou CONTAGEM — `valor` dele, não."""
    achados = []
    for rel in PRODUTOS:
        txt = (RAIZ / rel).read_text(encoding="utf-8")
        for m in _FROM_ESPELHO.finditer(txt):
            antes = txt[max(0, m.start() - 400):m.start()]
            i = antes.upper().rfind("SELECT")
            if i < 0 or re.search(r"\bFROM\b", antes[i:], re.I) or MARCA in antes:
                continue
            if re.search(r"\bvalor\b", antes[i:], re.I):
                achados.append(f"{rel}:{txt.count(chr(10), 0, m.start()) + 1}: {antes[i:].strip()[:90]}")
    assert not achados, "valor do espelho TFE usado como pago — use ob_orcamentaria_siafe + _ob_paga:\n" + \
        "\n".join(achados)
