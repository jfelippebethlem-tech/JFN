# -*- coding: utf-8 -*-
"""OB das ferramentas de caso = SIAFE pela régua única `_ob_paga`; fora da cobertura = INDISPONÍVEL, nunca o espelho.

Regra da casa (CLAUDE.md, NÃO REINVENTAR nº 1): pagamento é a OB do SIAFE (`ob_orcamentaria_siafe`), nunca o espelho
TFE (`ordens_bancarias`). O untangle de 20/11/2026 achou sete ferramentas somando o espelho como "pago" — uma delas
(`relatorio_engeprat_yoda`) o rotulava "SIAFE". Medido no banco real no mesmo dia: o espelho não tinha OBs pagas de
dezembro (ONG Con-tato/SEAS: R$ 71,34 mi no espelho × R$ 93,62 mi no SIAFE) e o SIAFE da casa não cobre 2019–2020
(só a ALERJ) — ali o número é INDISPONÍVEL, não zero e não o do espelho.

Dados sintéticos (CNPJ/UG fictícios); nenhum CPF real.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CNPJ = "00000000000191"


def _base(tmp_path) -> Path:
    """SIAFE: 1 OB paga 2022 + 1 devolvida pelo banco + 1 anulada + 1 complementar (só a 1ª é pagamento).
    Espelho: a mesma OB paga com valor ERRADO (999), e duas OB de 2020 numa UG que o SIAFE nunca leu."""
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT,"
                " status_envio TEXT, tipo_regularizacao TEXT, credor TEXT, nome_credor TEXT, valor REAL,"
                " exercicio INTEGER)")
    con.execute("CREATE TABLE ordens_bancarias (numero_ob TEXT, ug_codigo TEXT, ug_nome TEXT, data_emissao TEXT,"
                " data_pagamento TEXT, favorecido_cpf TEXT, favorecido_nome TEXT, valor REAL, exercicio INTEGER,"
                " observacao TEXT)")
    s = [("2022OB00001", "240100", "10/03/2022", "Contabilizado", "", "", CNPJ, "ONG X", 100.0, 2022),
         ("2022OB00002", "240100", "11/03/2022", "Contabilizado", "Erro no Pagamento", "", CNPJ, "ONG X", 50.0, 2022),
         ("2022OB00003", "240100", "12/03/2022", "Anulado", "", "", CNPJ, "ONG X", 30.0, 2022),
         ("2022OB00004", "240100", "13/03/2022", "Contabilizado", "", "Pagamento Complementar", CNPJ, "ONG X", 7.0,
          2022)]
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?)", s)
    t = [("2022OB00001", "240100", "SEAS", "2022-03-10", "2022-03-10", CNPJ, "ONG X", 999.0, 2022, "CONTRATO 1/2021"),
         ("2020OB00028", "530100", "CIDADES", "2020-03-13", "2020-03-13", CNPJ, "ONG X", 4_000_000.0, 2020, ""),
         ("2020OB00029", "530100", "CIDADES", "2020-03-13", "2020-03-13", CNPJ, "ONG X", 16_400_000.0, 2020, "")]
    con.executemany("INSERT INTO ordens_bancarias VALUES (?,?,?,?,?,?,?,?,?,?)", t)
    con.commit()
    con.close()
    return p


# ── régua de cobertura (compliance_agent.reporting.cobertura_siafe) ────────────────────────────────────────────
def test_estados_dos_pares_rotula_nunca_lido_como_indisponivel(tmp_path):
    from compliance_agent.reporting.cobertura_siafe import estados_dos_pares
    e = estados_dos_pares({("240100", "2022"), ("530100", "2020")}, db=_base(tmp_path))
    assert e[("240100", "2022")]["rotulo"] == "VERIFICADO"
    assert e[("530100", "2020")]["rotulo"] == "INDISPONÍVEL" and e[("530100", "2020")]["amostra"] == 2


# ── dossiê Emendatio ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def emendatio(tmp_path, monkeypatch):
    import tools.dossie_emendatio as D
    p = _base(tmp_path)
    monkeypatch.setattr(D, "DB", p)
    return D, sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def test_dossie_soma_so_a_ob_paga_do_siafe(emendatio):
    D, con = emendatio
    assert D._total(con, CNPJ) == (1, 100.0)                      # nem 999 do espelho, nem devolvida/anulada/complementar
    assert D._ob_por_ano(con, CNPJ) == [("2022", 1, 100.0)]       # 2020 não vira linha "0" nem o valor do espelho
    assert D._ob_por_ug(con, CNPJ)[0][:4] == ("240100", "SEAS", 1, 100.0)
    assert D._ob_por_ug(con, CNPJ)[0][4:] == ("2022-03-10", "2022-03-10")


def test_dossie_aponta_o_par_fora_do_siafe_como_indisponivel(emendatio):
    D, con = emendatio
    lac = D._lacunas(con, CNPJ)
    assert lac == [{"ug": "530100", "ano": "2020", "rotulo": "INDISPONÍVEL", "obs_espelho": 2,
                    "pct_ausente": 100.0}]
    html = D._html_lacunas(lac, "ONG X")
    assert "INDISPONÍVEL" in html and "4.000.000" not in html and "20.400.000" not in html   # contagem, nunca valor


def test_dossie_mascara_cpf_no_pad04():
    from tools.dossie_emendatio import _pad04
    assert _pad04("***111222**") == "***.111.222-**" == _pad04("***.111.222-**")
    assert _pad04("") == "***"


# ── sweeps de sede ───────────────────────────────────────────────────────────────────────────────────────────
def test_sweep_sede_real_ordena_pelo_pago_do_siafe(tmp_path):
    from tools import sweep_sede_real as R
    con = sqlite3.connect(_base(tmp_path))
    con.execute("CREATE TABLE verificacao_sede_real (cnpj TEXT)")
    con.execute("INSERT INTO ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, credor, valor) "
                "VALUES ('2022OB00009','240100','01/04/2022','Contabilizado','00000000000272',150.0)")
    # credor que só o espelho conhece (2020) não entra; CPF (11) e código de folha também não
    con.execute("INSERT INTO ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, credor, valor) "
                "VALUES ('2022OB00010','240100','01/04/2022','Contabilizado','CG0004700xxxxx',9e9)")
    assert R._alvos(con, None, True) == ["00000000000272", CNPJ]


def test_sweep_sede_google_total_recebido_e_o_pago_do_siafe(tmp_path):
    from tools import sweep_sede_google as G
    con = sqlite3.connect(_base(tmp_path))
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE endereco_fornecedor (cnpj TEXT, razao TEXT, endereco TEXT, municipio TEXT, uf TEXT,"
                " cep TEXT)")
    con.execute("CREATE TABLE verificacao_sede (cnpj TEXT)")
    con.execute("INSERT INTO endereco_fornecedor VALUES (?,?,?,?,?,?)", (CNPJ, "ONG X", "RUA A, 1", "RIO", "RJ", "1"))
    assert [(x["cnpj"], x["total_recebido"]) for x in G._alvos(con, 0)] == [(CNPJ, 100.0)]


# ── scorecard ────────────────────────────────────────────────────────────────────────────────────────────────
def test_scorecard_golden_vem_do_siafe(tmp_path, monkeypatch):
    import tools.scorecard as S
    monkeypatch.setattr(S, "DB", _base(tmp_path))
    g = S._golden()
    assert g["fonte_ob"].startswith("SIAFE") and g["ob_pagas"] == 1 and g["pct_ob_a_cnpj"] == 100.0
    md = S.render_md({"stamp": "t", "ruff_errors": 0, "arquivos_py": 1, "loc_py": 1, "arquivos_teste": 1,
                      "god_files_loc": {}, "golden": {"erro": "db ausente"}}, None)
    assert "INDISPONÍVEL" in md                                   # sem banco: dito, não zero


# ── catraca: nenhuma destas ferramentas tira VALOR do espelho ────────────────────────────────────────────────
FERRAMENTAS = ["tools/dossie_emendatio.py", "tools/relatorio_bombeiros.py", "tools/relatorio_engeprat_yoda.py",
               "tools/scorecard.py", "tools/sweep_sede_google.py", "tools/sweep_sede_real.py",
               "tools/tac_ranking_ugs.py"]
_FROM_ESPELHO = re.compile(r"FROM\s+ordens_bancarias", re.I)


def test_ferramentas_de_caso_nao_somam_valor_do_espelho_tfe():
    """O espelho só pode dar TEXTO (observação, nome da UG) ou CONTAGEM para apontar lacuna — `valor`/SUM dele, não."""
    achados = []
    for rel in FERRAMENTAS:
        txt = (RAIZ / rel).read_text(encoding="utf-8")
        for m in _FROM_ESPELHO.finditer(txt):
            antes = txt[max(0, m.start() - 400):m.start()]
            i = antes.upper().rfind("SELECT")
            if i < 0 or re.search(r"\bFROM\b", antes[i:], re.I):
                continue                                          # fragmento sem o SELECT ao lado (ex.: subconsulta)
            lista = antes[i:]
            if re.search(r"\bvalor\b|SUM\s*\(", lista, re.I):
                achados.append(f"{rel}:{txt.count(chr(10), 0, m.start()) + 1}: {lista.strip()[:90]}")
    assert not achados, "valor do espelho TFE usado como pago — use ob_orcamentaria_siafe + _ob_paga:\n" + \
        "\n".join(achados)
