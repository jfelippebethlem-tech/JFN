# -*- coding: utf-8 -*-
"""Alcance da sanção sobre o comprador DA CASA (Estado do RJ × Prefeitura do Rio), pela régua de esfera (20/11/2026).

O comparador (economia_vedada, caro_e_suspeito) tirava a esfera do comprador do esferaId do PNCP, presumia
"estadual" quando faltava e testava o município só por UF — impedimento da Prefeitura de Niterói "vedava" compra
da Prefeitura do Rio, e comprador sem cadastro no PNCP virava Estado.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import comparador_precos as CP
from compliance_agent.sancao_abrangencia import veda_comprador_rj

IMP = "Impedimento/proibição de contratar com prazo determinado"


def _s(orgao, esfera, categoria=IMP, uf="RJ", fund="LEI 14133 - ART. 156, III"):
    return {"categoria": categoria, "orgao": orgao, "uf": uf, "fundamentacao": fund, "cadastro": "CEIS",
            "abrangencia": "Em todos os Poderes da Esfera do órgão sancionador", "esfera_sancionador": esfera,
            "data_inicio": "2025-01-01", "data_fim": "2027-01-01"}


@pytest.mark.parametrize("sancao,casa,veda", [
    (_s("Secretaria de Estado de Fazenda", "ESTADUAL"), "estado", True),                 # Estado do RJ → Estado
    (_s("Secretaria de Estado de Fazenda", "ESTADUAL"), "prefeitura", False),            # Estado não veda a Prefeitura
    (_s("Prefeitura da Cidade do Rio de Janeiro", "MUNICIPAL"), "prefeitura", True),     # o próprio Município
    (_s("Prefeitura Municipal de Niterói", "MUNICIPAL"), "prefeitura", False),           # outro município do RJ
    (_s("Prefeitura da Cidade do Rio de Janeiro", "MUNICIPAL"), "estado", False),        # Município não veda o Estado
    (_s("Secretaria de Estado de Fazenda", "ESTADUAL", uf="SP"), "estado", False),       # outro estado
    (_s("Controladoria-Geral da União", "FEDERAL", categoria="Declaração de Inidoneidade com prazo determinado",
        uf="DF", fund="LEI 14133 - ART. 156, IV") | {"abrangencia": "Todas as Esferas em todos os Poderes"},
     "prefeitura", True),                                                                # inidoneidade: todos
    (_s("Secretaria de Estado de Fazenda", "ESTADUAL"), "federal", False),               # fora do escopo: não afirma
])
def test_veda_comprador_rj(sancao, casa, veda):
    assert veda_comprador_rj(sancao, casa)["veda"] is veda


def _db(tmp_path, orgao_sancionador: str, esfera_sancionador: str) -> str:
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE pncp_resultado (item_descricao TEXT, unidade_medida TEXT, valor_unitario REAL,
        quantidade REAL, orgao_cnpj TEXT, orgao_nome TEXT, unidade_nome TEXT, uf TEXT, municipio TEXT,
        fornecedor_nome TEXT, fornecedor_cnpj TEXT, ordem_classificacao INTEGER, data_pub TEXT, certame TEXT);
    CREATE TABLE sancoes_federais (cpf_cnpj TEXT, nome TEXT, cadastro TEXT, categoria TEXT, data_inicio TEXT,
        data_fim TEXT, orgao TEXT, uf TEXT, fundamentacao TEXT, abrangencia TEXT, esfera_sancionador TEXT);
    CREATE TABLE pncp_ente (cnpj TEXT, nome TEXT, esfera_id TEXT, poder_id TEXT, natureza_juridica TEXT, coletado_em TEXT);
    """)
    PCRJ, SANC, LIMP = "42498733000148", "99999999000199", "11111111000111"
    ins = ("INSERT INTO pncp_resultado VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)")
    for i, (preco, forn) in enumerate([(10.0, LIMP), (10.0, LIMP), (11.0, LIMP), (9.0, LIMP), (30.0, SANC)]):
        con.execute(ins, ("Cadeira 45 cm", "UN", preco, 10, PCRJ, "MUNICIPIO DE RIO DE JANEIRO", "SMS", "RJ",
                          "Rio de Janeiro", "F", forn, f"2025-06-{i + 1:02d}", f"{PCRJ}-1-{i + 1:06d}/2025"))
    con.execute("INSERT INTO pncp_ente VALUES (?,?,?,?,?,?)", (PCRJ, "MUNICIPIO DE RIO DE JANEIRO", "M", "E", "", ""))
    con.execute("INSERT INTO sancoes_federais VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (SANC, "SANC", "CEIS", IMP, "2025-01-01", "2027-01-01", orgao_sancionador, "RJ",
                 "LEI 14133 - ART. 156, III", "Em todos os Poderes da Esfera do órgão sancionador", esfera_sancionador))
    con.commit()
    con.close()
    return p


def test_economia_vedada_impedimento_de_niteroi_nao_veda_a_prefeitura_do_rio(tmp_path):
    d = CP.economia_vedada(db_path=_db(tmp_path, "Prefeitura Municipal de Niterói", "MUNICIPAL"),
                           min_amostra=5, min_orgaos=1, min_certames=3)
    assert d["economia_vedada_total"] == 0.0


def test_economia_vedada_impedimento_do_proprio_municipio_veda(tmp_path):
    """Controle positivo: mesma compra, sanção do Município do Rio — (30−10)×10 = 200."""
    d = CP.economia_vedada(db_path=_db(tmp_path, "Prefeitura da Cidade do Rio de Janeiro", "MUNICIPAL"),
                           min_amostra=5, min_orgaos=1, min_certames=3)
    assert d["economia_vedada_total"] == pytest.approx(200.0)
