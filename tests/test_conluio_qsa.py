# -*- coding: utf-8 -*-
"""conluio_qsa — vencedor × perdedora do MESMO certame com sócio em comum (QSA Receita).
Perdedora = tem ordem>1 no certame e nunca venceu item nele (ordem NULL = registro só-de-vencedor)."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.cruzamentos_intel import conluio_qsa


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE pncp_resultado (
        certame TEXT, orgao_cnpj TEXT, orgao_nome TEXT, uf TEXT, municipio TEXT,
        modalidade TEXT, objeto TEXT, data_pub TEXT, item INTEGER,
        fornecedor_cnpj TEXT, fornecedor_nome TEXT, valor_homologado REAL,
        ordem_classificacao INTEGER, porte_fornecedor TEXT);
    CREATE TABLE socios_receita (
        cnpj_basico TEXT, ident INTEGER, nome_socio TEXT, nome_norm TEXT, doc_socio TEXT,
        qualificacao_cod TEXT, qualificacao_txt TEXT, data_entrada TEXT,
        faixa_etaria TEXT, fonte_mes TEXT);
    CREATE TABLE edital_documento (
        numero_controle_pncp TEXT, ano INTEGER, orgao_cnpj TEXT, objeto TEXT,
        material_servico TEXT, valor_estimado REAL, texto TEXT, itens_json TEXT,
        documento_disponivel INTEGER, coletado_em TEXT);
    CREATE TABLE empresas_min (cnpj_basico TEXT, razao_social TEXT, natureza_cod TEXT,
        fonte_mes TEXT);
    """)
    ins_r = ("INSERT INTO pncp_resultado (certame, orgao_nome, objeto, data_pub, item, "
             "fornecedor_cnpj, fornecedor_nome, valor_homologado, ordem_classificacao) "
             "VALUES (?,?,?,?,?,?,?,?,?)")
    A, B = "11111111000111", "22222222000122"
    D, E = "44444444000144", "44444444000245"        # mesmo cnpj_basico (matriz × filial)
    F, G = "55555555000155", "66666666000166"
    rows = [
        # C1 e C2: A vence, B perde (ordem 2) — sócio em comum → par ALTA com 2 certames
        ("C1", "SES", "luvas", "2024-03-01", 1, A, "ALFA LTDA", 100000.0, 1),
        ("C1", "SES", "luvas", "2024-03-01", 1, B, "BETA LTDA", 0.0, 2),
        ("C2", "SES", "seringas", "2024-05-01", 1, A, "ALFA LTDA", 50000.0, 1),
        ("C2", "SES", "seringas", "2024-05-01", 1, B, "BETA LTDA", 0.0, 2),
        # C3: matriz vence, filial "concorre" e perde → MESMA_EMPRESA
        ("C3", "SEDUC", "merenda", "2024-06-01", 1, D, "DELTA MATRIZ", 80000.0, 1),
        ("C3", "SEDUC", "merenda", "2024-06-01", 1, E, "DELTA FILIAL", 0.0, 2),
        # C4: sem sócio em comum → não flagra
        ("C4", "SEFAZ", "papel", "2024-07-01", 1, F, "FOXTROT", 10000.0, 1),
        ("C4", "SEFAZ", "papel", "2024-07-01", 1, G, "GOLF", 0.0, 2),
        # C5: B vence item 1 E perde item 2 no MESMO certame → NÃO é perdedora em C5
        ("C5", "SES", "agulhas", "2024-08-01", 1, B, "BETA LTDA", 30000.0, 1),
        ("C5", "SES", "agulhas", "2024-08-01", 2, B, "BETA LTDA", 0.0, 2),
        # C6: nenhum dos dois tem QSA local → par INDISPONÍVEL (≠ inocente)
        ("C6", "SEFAZ", "toner", "2024-09-01", 1, "77777777000177", "HOTEL", 5000.0, 1),
        ("C6", "SEFAZ", "toner", "2024-09-01", 1, "88888888000188", "INDIA", 0.0, 2),
    ]
    con.executemany(ins_r, rows)
    ins_s = ("INSERT INTO socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio, "
             "qualificacao_txt) VALUES (?,?,?,?,?)")
    con.executemany(ins_s, [
        ("11111111", "Joao da Silva Xavier", "JOAO DA SILVA XAVIER", "***123456**", "Sócio-Administrador"),
        ("22222222", "JOAO DA SILVA XAVIER", "JOAO DA SILVA XAVIER", "***123456**", "Sócio"),
        # homônimo com CPF conflitante em F×G — NÃO pode flagrar
        ("55555555", "Maria Souza", "MARIA SOUZA", "***111111**", "Sócio"),
        ("66666666", "Maria Souza", "MARIA SOUZA", "***999999**", "Sócio"),
        # sócio da vencedora da ATA C7 — mesmo dono da perdedora B
        ("99999999", "Joao da Silva Xavier", "JOAO DA SILVA XAVIER", "***123456**",
         "Sócio-Administrador"),
    ])
    # ata C7: ZULU vence, BETA inabilitada (só existe no corpus de atas, não no PNCP)
    ata = ("ATA DE JULGAMENTO. A empresa ZULU COMERCIO LTDA, CNPJ 99.999.999/0001-99, foi "
           "declarada vencedora do certame. A empresa BETA LTDA, CNPJ 22.222.222/0001-22, "
           "foi inabilitada por descumprir o item 9.1 do edital. " + "x" * 1500)
    con.execute("INSERT INTO edital_documento (numero_controle_pncp, orgao_cnpj, texto) "
                "VALUES ('C7', '00000000000191', ?)", (ata,))
    con.execute("INSERT INTO empresas_min VALUES ('99999999', 'ZULU COMERCIO LTDA', '2062', '')")
    con.commit()
    con.close()
    return p


def test_detecta_par_alta_com_2_certames(db):
    d = conluio_qsa(db_path=db)
    assert d["ok"] is True
    alta = [p for p in d["pares"] if p["tier"] == "ALTA"
            and p["vencedor"]["cnpj"] == "11111111000111"]
    assert len(alta) == 1
    par = alta[0]
    assert par["perdedora"]["cnpj"] == "22222222000122"
    assert par["n_certames"] == 2
    assert par["valor_vencido"] == pytest.approx(150000.0)
    assert par["socios_comuns"][0]["nome"] == "Joao da Silva Xavier"


def test_matriz_filial_no_mesmo_certame(db):
    d = conluio_qsa(db_path=db)
    mesma = [p for p in d["pares"] if p["tier"] == "MESMA_EMPRESA"]
    assert len(mesma) == 1
    assert mesma[0]["vencedor"]["cnpj"][:8] == mesma[0]["perdedora"]["cnpj"][:8]


def test_homonimo_com_cpf_conflitante_descartado(db):
    d = conluio_qsa(db_path=db)
    cnpjs_flagrados = {p["vencedor"]["cnpj"] for p in d["pares"]}
    assert "55555555000155" not in cnpjs_flagrados


def test_vencedor_de_um_item_nao_e_perdedora_do_certame(db):
    d = conluio_qsa(db_path=db)
    # B venceu item em C5 — C5 não pode aparecer como certame de conluio
    for p in d["pares"]:
        assert "C5" not in [c["certame"] for c in p["certames"]]


def test_ata_gera_par_alta_com_nome_de_empresas_min(db):
    d = conluio_qsa(db_path=db)
    par_ata = [p for p in d["pares"] if p["vencedor"]["cnpj"] == "99999999000199"]
    assert len(par_ata) == 1
    assert par_ata[0]["tier"] == "ALTA"
    assert par_ata[0]["perdedora"]["cnpj"] == "22222222000122"
    assert par_ata[0]["vencedor"]["nome"] == "ZULU COMERCIO LTDA"
    assert par_ata[0]["certames"][0]["fonte"] == "ata"
    assert d["cobertura"]["certames_por_fonte"].get("ata") == 1


def test_incluir_atas_false_ignora_corpus(db):
    d = conluio_qsa(db_path=db, incluir_atas=False)
    assert all(p["vencedor"]["cnpj"] != "99999999000199" for p in d["pares"])


def test_ressalva_e_cobertura_presentes(db):
    d = conluio_qsa(db_path=db)
    assert "ressalva" in d and "Indício" in d["ressalva"]
    cob = d["cobertura"]
    assert cob["certames_com_perdedora"] >= 3
    assert cob["pares_sem_qsa"] >= 1        # F ou G etc. sem QSA dos dois lados
