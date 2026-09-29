"""Comissionados 2025–2026 × candidatos: classificação do cargo e confiança do casamento por nome."""
import sqlite3

from compliance_agent.pcrj import comissionados_2025_2026 as M


def _base(tmp_path):
    db = tmp_path / "pcrj.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tse_candidatura (nome_norm, nome_tse, nome_urna, ano, cargo, municipio, partido, "
                "situacao, resultado, eleito, outra_cidade)")
    con.execute("CREATE TABLE pcrj_folha_pref (nome_norm, nome, matricula, sigla_ua, orgao, tipo_folha, "
                "remun_bruta, competencia)")
    M._criar_tabelas(con)
    for nn in ("JOAO PEDRO ALVES MOREIRA", "ANA LIMA COSTA"):
        con.execute("INSERT INTO tse_candidatura VALUES (?,?,'',2024,'VEREADOR','NITEROI','PSD','','SUPLENTE',0,1)",
                    (nn, nn))
    rows = [("JOAO PEDRO ALVES MOREIRA", "0123", "ESPECIAL"),
            ("ANA LIMA COSTA", "0456", "AGENTE DE APOIO A EDUCACAO ESPECIAL")]
    for nn, mat, cargo in rows:
        for comp in ("202501", "202608"):
            con.execute("INSERT INTO pcrj_folha_pref VALUES (?,?,?,'UA','SMS','NORMAL','1.000,50',?)",
                        (nn, nn, mat, comp))
        con.execute("INSERT INTO pcrj_cargo_portal VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (nn, "202608", mat.lstrip("0"), nn, cargo, "L", "02/01/2025", "", "F", "", "x"))
        con.execute("INSERT INTO pcrj_cargo_portal_consulta VALUES (?,?,1,'x')", (nn, "202608"))
    con.commit()
    return con


def test_so_comissionado_entra_e_educacao_especial_fica_fora(tmp_path):
    con = _base(tmp_path)
    ps, cob = M.pessoas(con)
    assert [p["nn"] for p in ps] == ["JOAO PEDRO ALVES MOREIRA"]
    v = ps[0]["vinculos"][0]
    assert v["meses"] == 2 and abs(v["bruto"] - 2001.0) < 0.01     # remun_bruta é TEXTO pt-BR
    assert cob["consultas_feitas"] == cob["consultas"] == 2


def test_confianca_rebaixa_nome_comum_e_homonimo():
    assert M._confianca("JOAO PEDRO ALVES MOREIRA", set(), [], 1)[0] == "ALTA"
    assert M._confianca("MARIA DA SILVA", {"MARIA", "SILVA"}, [], 1)[0] == "BAIXA"
    cands = [{"cidade": c} for c in ("RIO", "NITEROI", "MAGE")]
    conf, motivos = M._confianca("JOAO PEDRO ALVES MOREIRA", set(), cands, 1)
    assert conf == "MÉDIA" and motivos


def test_saida_da_folha_em_junho_2026_vai_ao_capitulo_da_desincompatibilizacao(tmp_path):
    con = _base(tmp_path)
    nn = "CARLOS EDUARDO MOTTA RIBEIRO"
    con.execute("INSERT INTO tse_candidatura VALUES (?,?,'',2024,'VEREADOR','RIO DE JANEIRO','PL','','SUPLENTE',0,0)",
                (nn, nn))
    for comp in ("202501", "202606"):
        con.execute("INSERT INTO pcrj_folha_pref VALUES (?,?,'0789','UA','SMS','NORMAL','500,00',?)", (nn, nn, comp))
    con.execute("INSERT INTO pcrj_cargo_portal VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (nn, "202606", "789", nn, "ESPECIAL", "L", "02/01/2025", "", "F", "", "x"))
    con.commit()
    con.close()
    ctx = M.montar_ctx(tmp_path / "pcrj.db")
    titulos = [s["titulo"] for s in ctx["secoes"]]
    assert any(t.startswith("6. Exonerados") and t.endswith("(1)") for t in titulos)
    assert any(t.startswith("7. Continuam nomeados") and t.endswith("(1)") for t in titulos)
    cap6 = next(s["html"] for s in ctx["secoes"] if s["titulo"].startswith("6."))
    assert "CARLOS EDUARDO MOTTA RIBEIRO" in cap6 and "saiu da folha em 06/2026" in cap6
