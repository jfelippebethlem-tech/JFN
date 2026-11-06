# -*- coding: utf-8 -*-
"""OB paga antes da competência que ela quita: antecipação (art. 145 L.14.133) ou registro errado."""
import sqlite3

from compliance_agent.pagamento_competencia_futura import pagamento_competencia_futura


def _bases(tmp_path):
    db, est = tmp_path / "c.db", tmp_path / "e.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE ob_orcamentaria_siafe(numero_ob,ug_emitente,credor,nome_credor,status,valor,"
              "data_emissao,competencia,processo)")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?)", [
        ("OB1", "036100", "11111111000101", "CONSTRUTORA X", "Contabilizado", 1000.0, "10/03/2024", "06/2024", "SEI-1"),
        ("OB2", "036100", "11111111000101", "CONSTRUTORA X", "Contabilizado", 500.0, "10/03/2024", "05/2024", "SEI-1"),
        ("OB3", "294200", "22222222000101", "MEDICOS Y", "Contabilizado", 6e6, "01/11/2024", "08/2027", "SEI-2"),
        ("OB4", "036100", "33333333000101", "EMPRESA 1M", "Contabilizado", 10.0, "10/03/2024", "04/2024", ""),
        ("OB5", "296100", "44444444000101", "OS SAUDE", "Contabilizado", 9e6, "27/03/2025", "04/2025", ""),
        ("OB6", "036100", "55555555000101", "LIGHT", "Contabilizado", 70.0, "10/03/2024", "09/2024", ""),
        ("OB7", "036100", "66666666000101", "SECRETARIA", "Contabilizado", 80.0, "10/03/2024", "09/2024", ""),
        ("OB8", "036100", "11111111000101", "CONSTRUTORA X", "Anulado", 9e9, "10/03/2024", "09/2024", ""),
        ("OB9", "036100", "11111111000101", "CONSTRUTORA X", "Contabilizado", 7.0, "10/03/2024", "03/2024", ""),
        ("OBA", "036100", "123400", "UG PUBLICA", "Contabilizado", 7.0, "10/03/2024", "09/2024", ""),
        # pago em fev/2025 com competência 12/2025: RP de 12/2024 com o ano trocado, não antecipação
        ("OBB", "036100", "77777777000101", "RP ANO TROCADO", "Contabilizado", 900.0, "10/02/2025", "12/2025", ""),
    ])
    c.commit()
    c.close()
    e = sqlite3.connect(est)
    e.execute("CREATE TABLE empresas(cnpj_basico,razao_social,natureza_cod,capital_social,porte_cod,fonte_mes)")
    e.execute("CREATE TABLE estabelecimentos(cnpj_basico,matriz_filial,cnae_principal)")
    e.executemany("INSERT INTO empresas VALUES (?,?,?,0,0,'')", [
        ("11111111", "CONSTRUTORA X", "2062"), ("22222222", "MEDICOS Y", "2062"), ("33333333", "EMPRESA 1M", "2062"),
        ("44444444", "OS SAUDE", "3999"), ("55555555", "LIGHT", "2054"), ("66666666", "SECRETARIA", "1031"),
        ("77777777", "RP ANO TROCADO", "2062")])
    e.executemany("INSERT INTO estabelecimentos VALUES (?,'1',?)", [
        ("11111111", "4120400"), ("22222222", "8621601"), ("33333333", "4751201"), ("44444444", "8610101"),
        ("55555555", "3514000"), ("66666666", "8411600"), ("77777777", "4120400")])
    e.commit()
    e.close()
    return db, est


def test_classifica_por_antecedencia_e_exclui_o_que_nao_e_fornecedor(tmp_path):
    db, est = _bases(tmp_path)
    r = pagamento_competencia_futura(db, est)
    por = {a["credor_cnpj"][:8]: a for a in r["achados"]}
    assert por["11111111"]["forca"] == "forte"           # 3 meses à frente
    assert por["11111111"]["valor"] == 1500.0             # OB2 (2 meses) soma; anulada e mesma competência não
    assert por["11111111"]["meses_max"] == 3
    assert por["22222222"]["forca"] == "medio"           # 33 meses: implausível — registro ou antecipação
    assert por["33333333"]["forca"] == "fraco"           # 1 mês
    assert "44444444" not in por                         # OS a 1 mês: repasse do contrato de gestão
    assert "55555555" not in por                         # concessionária (CNAE 35): exceção do Dec. 49.134 art. 9º
    assert "66666666" not in por                         # ente público
    assert r["achados"][0]["forca"] == "forte"
    assert "indício" in r["nota"].lower()


def test_rp_com_ano_trocado_nao_vira_antecipacao(tmp_path):
    """04/11/2026: 39 de 57 OBs a 10–12 meses eram pagas em jan–mar com competência out–dez do MESMO ano —
    Restos a Pagar com o ano digitado errado, não pagamento antecipado."""
    db, est = _bases(tmp_path)
    a = next(x for x in pagamento_competencia_futura(db, est)["achados"] if x["credor_cnpj"].startswith("7777"))
    assert a["forca"] == "fraco" and a["provavel_ano_trocado"] is True


def test_ob_de_ano_trocado_nao_puxa_a_forca_do_grupo(tmp_path):
    db, est = _bases(tmp_path)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('OBC','036100','33333333000101','EMPRESA 1M',"
              "'Contabilizado',50.0,'16/01/2024','12/2024','')")      # 11 meses, mas é ano trocado
    c.commit()
    c.close()
    a = next(x for x in pagamento_competencia_futura(db, est)["achados"] if x["credor_cnpj"].startswith("3333"))
    assert a["forca"] == "fraco" and a["meses_max"] == 1
