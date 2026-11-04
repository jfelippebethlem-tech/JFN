# -*- coding: utf-8 -*-
"""DEA (elemento 92) a fornecedor privado: recorrência = serviço prestado sem empenho prévio."""
import sqlite3

from compliance_agent.dea_recorrente import dea_recorrente


def _bases(tmp_path):
    db, est = tmp_path / "c.db", tmp_path / "e.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE ne_siafe(numero,ug_emitente,exercicio,ano_ne,data_emissao,status,credor,nome_credor,"
              "natureza,processo,tipo_reconhecimento_passivo,valor)")
    c.executemany("INSERT INTO ne_siafe VALUES (?,'166100',2025,2025,'10/05/2025',?,?,?,?,?,"
                  "'Passivo reconhecido previamente',?)", [
        ("2025NE1", "Contabilizado", "11111111000101", "CLINICA X", "339092", "SEI-1", 1e6),
        ("2025NE2", "Contabilizado", "11111111000101", "CLINICA X", "339092", "SEI-2", 2e6),
        ("2025NE3", "Contabilizado", "11111111000101", "CLINICA X", "339092", "SEI-3", 5e5),   # 3 processos
        ("2025NE4", "Contabilizado", "22222222000101", "OBRA Y", "449092", "SEI-9", 3e6),       # 1 processo
        ("2025NE5", "Anulado", "33333333000101", "ANULADA", "339092", "SEI-7", 9e9),
        ("2025NE6", "Contabilizado", "44444444000101", "SERVICO NORMAL", "339039", "SEI-8", 7e6),  # não é DEA
        ("2025NE7", "Contabilizado", "55555555000101", "ESTATAL", "339092", "SEI-6", 4e6),
        ("2025NE8", "Contabilizado", "CG0004700", "FOLHA", "319092", "SEI-5", 8e6),            # não é CNPJ
    ])
    c.commit()
    c.close()
    e = sqlite3.connect(est)
    e.execute("CREATE TABLE empresas(cnpj_basico,natureza_cod)")
    e.executemany("INSERT INTO empresas VALUES (?,?)", [("11111111", "2062"), ("22222222", "2062"),
                                                        ("33333333", "2062"), ("44444444", "2062"),
                                                        ("55555555", "1031")])
    e.commit()
    e.close()
    return db, est


def test_dea_recorrente_e_forte_e_o_resto_fica_fora(tmp_path):
    db, est = _bases(tmp_path)
    r = dea_recorrente(db, est)
    por = {a["credor"][:8]: a for a in r["achados"]}
    assert por["11111111"]["forca"] == "forte" and por["11111111"]["n_processos"] == 3
    assert por["11111111"]["valor"] == 3.5e6
    assert por["22222222"]["forca"] == "fraco"          # DEA única: legal pelo art. 37, só conferir
    assert {"33333333", "44444444", "55555555"}.isdisjoint(por)   # anulada, não-DEA, ente público
    assert r["achados"][0]["credor"].startswith("1111")
    assert "art. 37" in r["nota"]
