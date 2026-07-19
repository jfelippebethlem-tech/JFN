# -*- coding: utf-8 -*-
"""Testes da ingestão do dump Estabelecimentos (RFB) — tudo em tmp_path."""
import csv
import io
import sqlite3
import zipfile

from compliance_agent.receita.ingest_estabelecimentos import (
    LAYOUT, deve_ingerir, ingerir, parse_linha,
)


def _linha(**over):
    """Linha crua de 30 campos no layout oficial, com overrides por nome."""
    base = {c: "" for c in LAYOUT}
    base.update({
        "cnpj_basico": "12345678", "cnpj_ordem": "0001", "cnpj_dv": "95",
        "matriz_filial": "1", "nome_fantasia": "PADARIA TESTE",
        "situacao_cadastral": "02", "data_situacao": "20200101",
        "motivo_situacao": "00", "data_inicio_atividade": "20150301",
        "cnae_principal": "4721102", "cnae_secundaria": "4712100",
        "tipo_logradouro": "RUA", "logradouro": "SÃO JOÃO", "numero": "10",
        "bairro": "CENTRO", "cep": "20.040-002", "uf": "RJ",
        "municipio": "6001", "ddd1": "21", "telefone1": "99887766",
        "ddd2": "21", "telefone2": "3344-5566",
        "correio_eletronico": "  Contato@Empresa.COM.BR ",
    })
    base.update(over)
    return [base[c] for c in LAYOUT]


# ── parse_linha ──────────────────────────────────────────────────────────────

def test_parse_linha_cnpj_telefone_cep_email():
    row = parse_linha(_linha())
    assert row["cnpj"] == "12345678000195"
    assert row["telefone1"] == "2199887766"
    assert row["telefone2"] == "2133445566"
    assert row["cep"] == "20040002"
    assert row["correio_eletronico"] == "contato@empresa.com.br"


def test_parse_linha_endereco_norm_sem_acento_e_colapsado():
    row = parse_linha(_linha(logradouro="  SÃo   JOÃO  "))
    assert row["endereco_norm"] == "RUA SAO JOAO 10 CENTRO 20040002"


def test_parse_linha_situacao_baixada():
    assert parse_linha(_linha(situacao_cadastral="08"))["situacao_cadastral"] == "BAIXADA"
    assert parse_linha(_linha(situacao_cadastral="02"))["situacao_cadastral"] == "ATIVA"


def test_parse_linha_malformada_retorna_none():
    assert parse_linha(_linha()[:20]) is None


# ── deve_ingerir ─────────────────────────────────────────────────────────────

def test_deve_ingerir_rj_sempre():
    assert deve_ingerir({"uf": "RJ", "cnpj_basico": "99999999"}, set())


def test_deve_ingerir_sp_fora_das_raizes_nao():
    assert not deve_ingerir({"uf": "SP", "cnpj_basico": "99999999"}, {"11111111"})


def test_deve_ingerir_sp_na_raiz_sim():
    assert deve_ingerir({"uf": "SP", "cnpj_basico": "11111111"}, {"11111111"})


# ── ingerir (zip sintético) ──────────────────────────────────────────────────

def test_ingerir_zip_sintetico(tmp_path):
    linhas = [
        _linha(),                                                    # RJ → entra
        _linha(cnpj_basico="22222222", cnpj_dv="11", uf="SP"),       # SP raiz → entra
        _linha(cnpj_basico="33333333", cnpj_dv="22", uf="MG"),       # MG fora → não
    ]
    buf = io.StringIO()
    csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL).writerows(linhas)
    zpath = tmp_path / "Estabelecimentos0.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("K3241.ESTABELE", buf.getvalue().encode("latin-1"))
    raizes = tmp_path / "raizes.txt"
    raizes.write_text("22222222\n\n", encoding="utf-8")
    db = tmp_path / "compliance.db"

    resumo = ingerir(str(tmp_path / "Estabelecimentos*.zip"), str(db), str(raizes))
    assert resumo == {"lidas": 3, "ingeridas": 2, "arquivos": 1}

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    assert conn.execute("SELECT COUNT(*) FROM estabelecimentos").fetchone()[0] == 2
    r = conn.execute("SELECT * FROM estabelecimentos WHERE cnpj='12345678000195'").fetchone()
    assert r["uf"] == "RJ"
    assert r["situacao_cadastral"] == "ATIVA"
    assert r["telefone1"] == "2199887766"
    assert r["endereco_norm"] == "RUA SAO JOAO 10 CENTRO 20040002"
    assert conn.execute("SELECT cnpj FROM estabelecimentos WHERE uf='SP'").fetchone()[0] \
        == "22222222000111"
    conn.close()
