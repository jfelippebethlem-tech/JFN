# -*- coding: utf-8 -*-
"""Testes da visão agregada de benefícios dos sócios/admin (laranja) p/ os relatórios. DB temp, sem rede."""
import sqlite3

from compliance_agent.reporting import beneficios_view as bv


def _db(tmp_path, socios, beneficios):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome TEXT, "
                "socio_nome_norm TEXT, socio_doc TEXT, qualificacao TEXT, ingerido_em TEXT)")
    con.executemany("INSERT INTO socios_fornecedor (cnpj,razao,socio_nome,socio_nome_norm,socio_doc,qualificacao) "
                    "VALUES (?,?,?,?,?,?)", socios)
    con.execute("CREATE TABLE socio_beneficio (socio_nome_norm TEXT, socio_doc TEXT, resolvido INT, "
                "verificado INT, recebe_beneficio INT, fonte TEXT, beneficios_json TEXT)")
    con.executemany("INSERT INTO socio_beneficio (socio_nome_norm,socio_doc,resolvido,verificado,"
                    "recebe_beneficio,fonte,beneficios_json) VALUES (?,?,?,?,?,?,?)", beneficios)
    con.commit()
    con.close()
    return p


def test_agrega_indicio_e_afastado_e_indisponivel(tmp_path):
    socios = [
        ("C1", "ALFA LTDA", "JOAO ADM", "JOAO ADM", "***111111**", "Administrador"),
        ("C1", "ALFA LTDA", "MARIA SOCIA", "MARIA SOCIA", "***222222**", "Sócio"),
        ("C2", "BETA SA", "PEDRO PEND", "PEDRO PEND", "***333333**", "Sócio-Administrador"),  # não varrido
    ]
    beneficios = [
        ("JOAO ADM", "***111111**", 1, 1, 1, "tse_doadores", '["Bolsa Família"]'),  # indício (gestão)
        ("MARIA SOCIA", "***222222**", 1, 1, 0, "favorecidos_pf", "[]"),            # AFASTADO
        # PEDRO não tem linha em socio_beneficio → INDISPONÍVEL (varredura pendente)
    ]
    p = _db(tmp_path, socios, beneficios)
    agg = bv.agregar_por_cnpjs(["C1", "C2"], db_path=p)
    assert agg["total_qsa"] == 3 and agg["n_varridos"] == 2 and agg["n_verificados"] == 2
    assert agg["n_com_beneficio"] == 1 and agg["n_pessoas_beneficio"] == 1
    assert agg["n_indisponivel"] == 1  # PEDRO pendente
    assert agg["itens"][0]["nome"] == "JOAO ADM" and agg["itens"][0]["gestao"] is True
    assert "Bolsa Família" in agg["itens"][0]["tipos"]


def test_leitura_indicio_prosa(tmp_path):
    socios = [("C1", "ALFA LTDA", "JOAO ADM", "JOAO ADM", "***111111**", "Administrador")]
    beneficios = [("JOAO ADM", "***111111**", 1, 1, 1, "tse_doadores", '["BPC"]')]
    p = _db(tmp_path, socios, beneficios)
    txt = bv.leitura(bv.agregar_por_cnpjs(["C1"], db_path=p))
    assert "indício" in txt.lower() and "337-F" in txt and "gestão" in txt.lower()


def test_leitura_afastado(tmp_path):
    socios = [("C1", "ALFA LTDA", "MARIA", "MARIA", "***222222**", "Sócio")]
    beneficios = [("MARIA", "***222222**", 1, 1, 0, "favorecidos_pf", "[]")]
    p = _db(tmp_path, socios, beneficios)
    txt = bv.leitura(bv.agregar_por_cnpjs(["C1"], db_path=p))
    assert "AFASTADO" in txt and "INDISPONÍVEL" in txt


def test_vazio_sem_cnpjs():
    assert bv.agregar_por_cnpjs([])["total_qsa"] == 0


def test_db_ausente_indisponivel_honesto(tmp_path):
    agg = bv.agregar_por_cnpjs(["C1"], db_path=tmp_path / "nao_existe.db")
    assert agg == bv._vazio()
