import sqlite3

import pytest

from compliance_agent import comissao_pecas as P


@pytest.fixture
def c():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE siconfi_rgf (exercicio INT, periodo INT, periodicidade TEXT, co_poder TEXT, instituicao TEXT,"
                " anexo TEXT, rotulo TEXT, coluna TEXT, cod_conta TEXT, conta TEXT, valor REAL, coletado_em TEXT)")
    def ins(inst, poder, coluna, conta, valor, anexo="RGF-Anexo 01", per=2):
        con.execute("INSERT INTO siconfi_rgf VALUES (2026,?, 'Q', ?, ?, ?, '', ?, '', ?, ?, '')",
                    (per, poder, inst, anexo, coluna, conta, valor))
    for inst, poder, dtp, p, mx, pr, al in [
            ("Governo do Estado do Rio de Janeiro", "E", 47.0e9, 46.71, 49.0, 46.55, 44.1),
            ("Assembleia Legislativa do Estado do RJ", "L", 0.88e9, 0.83, 1.68, 1.60, 1.51),
            ("Tribunal de Contas do Estado do RJ", "L", 0.91e9, 1.30, 1.31, 1.24, 1.18)]:
        ins(inst, poder, "Valor", "DESPESA TOTAL COM PESSOAL - DTP (VI) = (III a + III b)", dtp)
        ins(inst, poder, "% sobre a RCL Ajustada", "DESPESA TOTAL COM PESSOAL - DTP (VI) = (III a + III b)", p)
        ins(inst, poder, "% sobre a RCL Ajustada", "LIMITE MÁXIMO (VII) (incisos I, II e III, art. 20 da LRF)", mx)
        ins(inst, poder, "% sobre a RCL Ajustada", "LIMITE PRUDENCIAL (VIII) = (0,95 x VII)", pr)
        ins(inst, poder, "% sobre a RCL Ajustada", "LIMITE DE ALERTA (IX) = (0,90 x VII)", al)
    ins("Defensoria Pública do Estado do RJ", "D", "TOTAL (c = a + b)", "DESPESA BRUTA COM PESSOAL (I)", 1.4e9)
    ins("Defensoria Pública do Estado do RJ", "D", "TOTAL (c = a + b)", "DESPESAS NÃO COMPUTADAS (§ 1º do art. 19 da LRF) (II)", 0.2e9)
    ins("Defensoria Pública do Estado do RJ", "D", "<MR>", "DESPESA BRUTA COM PESSOAL (I)", 0.1e9)   # mês: ignora
    ins("Governo do Estado do Rio de Janeiro", "E", "Valor", "= RECEITA CORRENTE LÍQUIDA AJUSTADA PARA CÁLCULO DOS LIMITES DA DESPESA COM PESSOAL", 100e9)
    for col, conta, v in [("Até o 2º Quadrimestre", "DÍVIDA CONSOLIDADA LÍQUIDA (DCL) (III) = (I - II)", 225e9),
                          ("Até o 2º Quadrimestre", "% da DCL sobre a RCL AJUSTADA (III/VI)", 211.18),
                          ("Até o 1º Quadrimestre", "% da DCL sobre a RCL AJUSTADA (III/VI)", 219.04),
                          ("Até o 2º Quadrimestre", "RECEITA CORRENTE LÍQUIDA - RCL (IV)", 106.6e9)]:
        ins("Governo do Estado do Rio de Janeiro", "E", col, conta, v, anexo="RGF-Anexo 02")
    return con


def test_situacao_de_cada_poder_contra_os_limites(c):
    r = {d["curta"]: d for d in P.pessoal(c, 2026, 2)}
    assert r["Executivo"]["situacao"] == "acima do limite prudencial"
    assert r["ALERJ"]["situacao"] == "dentro dos limites"
    assert r["TCE-RJ"]["situacao"] == "acima do limite prudencial"           # 1,30 > 1,24 e ≤ 1,31
    assert r["Defensoria (DPRJ)"]["situacao"].startswith("sem limite LRF próprio")
    assert [d["curta"] for d in P.pessoal(c, 2026, 2)][:3] == ["Executivo", "ALERJ", "TCE-RJ"]
    assert r["Defensoria (DPRJ)"]["dtp"] == pytest.approx(1.2e9) and r["Defensoria (DPRJ)"]["dtp_pct"] == 1.2


def test_divida_le_so_a_coluna_do_quadrimestre(c):
    d = P.divida(c, 2026, 2)
    assert d["dcl_pct"] == 211.18 and d["dcl"] == 225e9 and d["rcl"] == 106.6e9


def test_catalogo_tem_18_pecas_e_geradores_existem():
    assert [p["id"] for p in P.CATALOGO] == [f"P{i}" for i in range(1, 19)]
    for p in P.CATALOGO:
        assert (p["gerador"] in P.GERADORES) if p["gerador"] else p.get("falta")


def test_rreo_acha_coluna_com_acento():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE siconfi_rreo (exercicio INT, periodo INT, periodicidade TEXT, co_poder TEXT, instituicao TEXT,"
                " anexo TEXT, rotulo TEXT, coluna TEXT, cod_conta TEXT, conta TEXT, valor REAL, coletado_em TEXT)")
    con.execute("INSERT INTO siconfi_rreo VALUES (2026,4,'B','E','G','RREO-Anexo 01','','Até o Bimestre (c)','',"
                "'RECEITAS (EXCETO INTRA-ORÇAMENTÁRIAS) (I)',70e9,'')")
    assert P._v(con, 2026, 4, "RREO-Anexo 01", "RECEITAS (EXCETO INTRA-ORÇAMENTÁRIAS)", "Até o Bimestre") == 70e9
