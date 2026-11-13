# -*- coding: utf-8 -*-
"""CEIS/CNEP: guardar abrangência, esfera do sancionador e data de publicação (revisão cética 13/11/2026 —
a Enge Prat-like tinha "No órgão sancionador" no CEIS e o sistema leu como vedação ao Estado)."""
from __future__ import annotations

import sqlite3

from tools import ingerir_ceis_cnep as I

# linha sintética no formato do CSV da CGU (o cabeçalho real grafa "ABRAGÊNCIA")
LINHA = {
    "CPF OU CNPJ DO SANCIONADO": "11.111.111/0001-11", "NOME DO SANCIONADO": "EMPRESA FICTICIA LTDA",
    "CATEGORIA DA SANÇÃO": "Suspensão", "DATA INÍCIO SANÇÃO": "25/03/2026", "DATA FINAL SANÇÃO": "25/03/2027",
    "DATA PUBLICAÇÃO": "26/03/2026", "ABRAGÊNCIA DA SANÇÃO": "No órgão sancionador",
    "ÓRGÃO SANCIONADOR": "INSTITUTO FEDERAL FICTICIO", "UF ÓRGÃO SANCIONADOR": "RJ",
    "ESFERA ÓRGÃO SANCIONADOR": "FEDERAL", "NÚMERO DO PROCESSO": "1/2026", "FUNDAMENTAÇÃO LEGAL": "LEI 8666 - ART. 87, III",
}


def test_registro_guarda_abrangencia_esfera_e_publicacao():
    r = I.registro(LINHA, "ceis")
    assert r["abrangencia"] == "No órgão sancionador"
    assert r["esfera_sancionador"] == "FEDERAL"
    assert r["data_publicacao"] == "2026-03-26"
    assert r["cpf_cnpj"] == "11111111000111" and r["data_inicio"] == "2026-03-25"


def test_registro_aceita_cabecalho_com_grafia_correta_e_sem_informacao():
    ln = {k.replace("ABRAGÊNCIA", "ABRANGÊNCIA"): v for k, v in LINHA.items()}
    ln["DATA PUBLICAÇÃO"] = "Sem informação"
    r = I.registro(ln, "cnep")
    assert r["abrangencia"] == "No órgão sancionador" and r["data_publicacao"] is None


def test_migracao_idempotente_nao_apaga_dado(tmp_path):
    db = tmp_path / "s.db"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE sancoes_federais (cadastro TEXT NOT NULL, cpf_cnpj TEXT NOT NULL, nome TEXT,
        categoria TEXT, data_inicio TEXT, data_fim TEXT, orgao TEXT, uf TEXT, processo TEXT, fundamentacao TEXT)""")
    con.execute("INSERT INTO sancoes_federais (cadastro, cpf_cnpj) VALUES ('CEIS','22222222000122')")
    I.migrar(con)
    I.migrar(con)                                     # segunda vez não falha nem duplica coluna
    cols = [r[1] for r in con.execute("PRAGMA table_info(sancoes_federais)")]
    assert {"abrangencia", "esfera_sancionador", "data_publicacao"} <= set(cols)
    assert cols.count("abrangencia") == 1
    assert con.execute("SELECT COUNT(*) FROM sancoes_federais").fetchone()[0] == 1
    con.close()
