# -*- coding: utf-8 -*-
"""Testes da âncora setorial por CNAE (CNES/RNTRC/ANVISA/INEP) — dumps em tmp_path, zero rede.

Regra de honestidade: dump ausente → presente=None (INDISPONÍVEL), nunca False sem dado; False
(risco alto) só com o dump local na mão e o CNPJ fora dele."""
import sqlite3

from compliance_agent.enriquecimento.ancora_setorial import checar_ancora

CNPJ = "12345678000195"


def _dump_cnes(tmp_path, cnpjs):
    db = tmp_path / "cnes.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE cnes_estabelecimentos (cnpj TEXT, nome TEXT, municipio TEXT, uf TEXT)")
    conn.executemany("INSERT INTO cnes_estabelecimentos VALUES (?,?,?,?)",
                     [(c, "HOSPITAL TESTE", "RIO DE JANEIRO", "RJ") for c in cnpjs])
    conn.commit()
    conn.close()
    return str(db)


def test_cnae_saude_espera_cnes(tmp_path):
    out = checar_ancora(CNPJ, "8610101", "", db_path=str(tmp_path / "nao_existe.db"))
    assert out["esperado_em"] == "CNES"


def test_dump_ausente_presente_none_indisponivel(tmp_path):
    out = checar_ancora(CNPJ, "8610101", "", db_path=str(tmp_path / "nao_existe.db"))
    assert out["presente"] is None  # INDISPONÍVEL ≠ ausente do cadastro
    assert "não baixado" in out["detalhe"]


def test_cnpj_no_dump_presente_true(tmp_path):
    db = _dump_cnes(tmp_path, [CNPJ])
    out = checar_ancora(CNPJ, "8610-1/01", "", db_path=db)
    assert out["esperado_em"] == "CNES" and out["presente"] is True
    assert out["risco"] == "baixo"


def test_cnpj_fora_do_dump_presente_false_risco_alto(tmp_path):
    db = _dump_cnes(tmp_path, ["99999999000191"])
    out = checar_ancora(CNPJ, "8610101", "", db_path=db)
    assert out["presente"] is False and out["risco"] == "alto"


def test_cnae_sem_regulador_esperado_none():
    out = checar_ancora(CNPJ, "6201500", "desenvolvimento de software")
    assert out["esperado_em"] is None and out["presente"] is None


def test_objeto_forca_regulador_com_cnae_generico(tmp_path):
    # CNAE genérico (consultoria) mas objeto de serviços hospitalares → cobra CNES mesmo assim
    db = _dump_cnes(tmp_path, [])
    out = checar_ancora(CNPJ, "7020400", "prestação de serviços hospitalares na rede estadual",
                        db_path=db)
    assert out["esperado_em"] == "CNES" and out["presente"] is False


def test_transporte_de_carga_espera_rntrc(tmp_path):
    out = checar_ancora(CNPJ, "4930202", "", db_path=str(tmp_path / "nao_existe.db"))
    assert out["esperado_em"] == "RNTRC"


def test_farma_industria_espera_anvisa(tmp_path):
    out = checar_ancora(CNPJ, "2110600", "", db_path=str(tmp_path / "nao_existe.db"))
    assert out["esperado_em"] == "ANVISA"
