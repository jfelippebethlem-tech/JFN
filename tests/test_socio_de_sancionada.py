# -*- coding: utf-8 -*-
"""Sócio de contratada que é sócio de sancionada: só conta OB na janela, e só sanção que alcança o RJ."""
import sqlite3

from compliance_agent.socio_de_sancionada import socio_de_sancionada


def _bases(tmp_path):
    db, est = tmp_path / "c.db", tmp_path / "e.db"
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE sancoes_federais(cadastro,cpf_cnpj,nome,categoria,data_inicio,data_fim,orgao,uf,processo,fundamentacao);
    CREATE TABLE socio_historico(cnpj_basico,doc_socio,nome_norm,qualificacao,data_entrada,visto_de,visto_ate,saiu_entre,status,janela_confiavel);
    CREATE TABLE ob_orcamentaria_siafe(credor,status,valor,data_emissao);
    """)
    c.executemany("INSERT INTO sancoes_federais VALUES (?,?,?,?,?,?,?,?,?,?)", [
        ("CEIS", "11111111000105", "INIDONEA", "Declaração de Inidoneidade", "2021-08-13", None, "TJRJ", "RJ", "", ""),
        ("CEIS", "33333333000105", "IMPEDIDA FED", "Impedimento/proibição de contratar", "2024-01-01", "2027-01-01",
         "Ministério da Saúde", "", "", "Lei 14.133, art. 156, III"),
    ])
    c.executemany("INSERT INTO socio_historico VALUES (?,?,?,?,?,?,?,?,?,1)", [
        ("11111111", "***572427**", "LUCAS", "49", "20190516", "2023-03", "2026-07", None, "ativo"),
        ("22222222", "***572427**", "LUCAS", "49", "20251008", "2025-10", "2026-07", None, "ativo"),
        ("33333333", "***000001**", "ANA", "49", "20100101", "2023-03", "2026-07", None, "ativo"),
        ("44444444", "***000001**", "ANA", "49", "20100101", "2023-03", "2026-07", None, "ativo"),
    ])
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?)", [
        ("22222222000155", "Contabilizado", 1000.0, "15/10/2025"),   # na janela (Lucas já entrou)
        ("22222222000155", "Contabilizado", 500.0, "15/09/2025"),    # antes de Lucas entrar: não conta
        ("22222222000155", "Cancelado", 9999.0, "20/10/2025"),       # OB não paga: não conta
        ("44444444000155", "Contabilizado", 7000.0, "10/05/2025"),   # sanção federal não alcança o RJ
    ])
    c.commit(); c.close()
    e = sqlite3.connect(est)
    e.executescript("""CREATE TABLE estabelecimentos(cnpj_basico,matriz_filial,cnae_principal,endereco_norm,telefone1);
                       CREATE TABLE empresas(cnpj_basico,razao_social);""")
    e.executemany("INSERT INTO estabelecimentos VALUES (?,?,?,?,?)", [
        ("11111111", "1", "4639701", "ESTRADA DA CACUIA 661", "24667416"),
        ("22222222", "1", "4639701", "ESTRADA DA CACUIA 661", "99999999")])
    e.executemany("INSERT INTO empresas VALUES (?,?)", [("11111111", "M L"), ("22222222", "GUARAILHA")])
    e.commit(); e.close()
    return str(db), str(est)


def test_padrao_guarailha_forte_e_so_a_janela(tmp_path):
    db, est = _bases(tmp_path)
    r = socio_de_sancionada(db, est, hoje="2026-11-03")
    assert r["ok"] and r["n"] == 1
    a = r["achados"][0]
    assert (a["contratada"], a["sancionada"]) == ("22222222", "11111111")
    assert a["pago_janela"] == 1000.0 and a["n_obs"] == 1
    assert a["janela"][0] == "2025-10-08"
    assert a["forca"] == "forte" and a["mesmo"] == {"cnae": True, "endereco": True, "telefone": False}
    assert a["socio_doc"].startswith("***")             # CPF segue mascarado
