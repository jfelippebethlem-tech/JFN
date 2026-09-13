# -*- coding: utf-8 -*-
"""A fonte canônica de pagamento estava truncada e nada avisava.

A tela de OB Orçamentária do SIAFE-Rio 2 devolve no máximo 1.000 registros por consulta. Uma
coleta feita só com `--por-ug` numa UG grande para exatamente nesse número, em silêncio. Medido em
2026-08-04: **23 pares (UG, ano) de 642** param em 1.000 — enquanto outros chegam a 6.836. Nesses
23, o SIAFE conhece R$ 8,46 bi e o espelho TFE registra R$ 19,26 bi (137.654 OBs a mais).

Apareceu perseguindo um achado C3/C5 do IDESI (INAPTA na Receita): o espelho mostrava 5,5× mais
pagamento ao mesmo fornecedor, tudo na UG 294200 (Fundação Saúde), cujos exercícios 2022 e 2023
tinham exatamente 1.000 OBs cada.
"""
import sqlite3

import pytest

from compliance_agent.reporting import cobertura_siafe as C


def _base(tmp_path, siafe, tfe=()):
    """siafe/tfe: sequências de (ug, ano, n_obs). Valor é 1,00 por OB — o que se afere é a contagem."""
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (ug_emitente TEXT, data_emissao TEXT, "
                "valor REAL, status TEXT, processo TEXT, credor TEXT)")
    con.execute("CREATE TABLE ordens_bancarias (ug_codigo TEXT, data_emissao TEXT, valor REAL)")
    for ug, ano, n in siafe:                       # SIAFE: data_emissao é TEXTO DD/MM/AAAA
        con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?)",
                        [(ug, f"15/06/{ano}", 1.0, "Contabilizado", "SEI-x", "0") for _ in range(n)])
    for ug, ano, n in tfe:                         # espelho TFE: ISO
        con.executemany("INSERT INTO ordens_bancarias VALUES (?,?,?)",
                        [(ug, f"{ano}-06-15", 1.0) for _ in range(n)])
    con.commit(); con.close()
    return p


def test_par_que_para_em_exatamente_1000_e_declarado_truncado(tmp_path):
    r = C.medir(db=_base(tmp_path, [("294200", "2023", 1000)], [("294200", "2023", 12390)]))
    assert r["pares_truncados"] == 1
    t = r["truncados"][0]
    assert (t["ug"], t["exercicio"]) == ("294200", "2023")
    assert t["obs_faltando_ao_menos"] == 11390
    assert "--ug-grande" in t["recoletar"]


def test_par_abaixo_do_teto_nao_e_truncado(tmp_path):
    """999 é coleta completa; chamar de truncado inventaria trabalho e desconfiança."""
    r = C.medir(db=_base(tmp_path, [("133100", "2024", 999)]))
    assert r["pares_truncados"] == 0


def test_o_ano_sai_dos_QUATRO_ULTIMOS_digitos_da_data(tmp_path):
    """`data_emissao` do SIAFE é TEXTO DD/MM/AAAA — ler os 4 primeiros daria o dia+mês e
    espalharia um mesmo exercício por dezenas de 'anos' falsos, escondendo o teto."""
    r = C.medir(db=_base(tmp_path, [("294200", "2022", 1000)]))
    assert r["truncados"][0]["exercicio"] == "2022"


def test_sem_espelho_ainda_declara_o_truncamento(tmp_path):
    """A prova é o 1.000 exato, não a diferença para o TFE: sem espelho o par continua truncado,
    só não se dimensiona o que falta."""
    r = C.medir(db=_base(tmp_path, [("296100", "2021", 1000)]))
    assert r["pares_truncados"] == 1
    assert r["truncados"][0]["obs_faltando_ao_menos"] == 0


def test_sem_a_tabela_canonica_e_INDISPONIVEL_nunca_zero(tmp_path):
    p = tmp_path / "vazia.db"
    sqlite3.connect(p).close()
    r = C.medir(db=p)
    assert r["indisponivel"] is True and "ausente" in r["motivo"]


def test_base_inexistente_nao_levanta(tmp_path):
    assert C.medir(db=tmp_path / "nao_existe.db")["indisponivel"] is True


@pytest.mark.slow
def test_base_real_mantem_o_diagnostico(tmp_path):
    """Catraca: se alguém recoletar as UGs grandes, este número CAI — e o teste avisa para
    atualizar a doutrina em vez de deixar a prosa mentir."""
    import pathlib
    db = pathlib.Path.home() / "JFN" / "data" / "compliance.db"
    if not db.exists():
        pytest.skip("compliance.db ausente")
    r = C.medir(db=db)
    assert r["ok"] and not r["indisponivel"]
    assert r["pares_truncados"] <= 23, "truncamento AUMENTOU — nova coleta parou no teto"
