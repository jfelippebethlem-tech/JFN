# -*- coding: utf-8 -*-
"""economia_potencial — refeita em 2026-11-13 ("não pode ter margem pra erro em nada").

Só soma compra que (1) está em grupo HOMOGÊNEO de preço normalizado, (2) tem indício de
sobrepreço (≥2× a mediana, fora da banda robusta), (3) foi VERIFICADA no PNCP e (4) não é
ata de registro de preços (quantidade de ata é estimativa — vai para o teto, rotulado).
Sintéticos (repositório público).
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import comparador_precos as CP

_DDL = """CREATE TABLE pncp_resultado (item_descricao TEXT, unidade_medida TEXT,
    valor_unitario REAL, quantidade REAL, orgao_nome TEXT, unidade_nome TEXT, municipio TEXT,
    fornecedor_nome TEXT, fornecedor_cnpj TEXT, ordem_classificacao INTEGER, data_pub TEXT,
    certame TEXT, item INTEGER, modalidade INTEGER, objeto TEXT)"""


def _db(tmp_path, linhas, nome="t.db"):
    p = str(tmp_path / nome)
    con = sqlite3.connect(p)
    con.execute(_DDL)
    con.executemany(
        "INSERT INTO pncp_resultado (item_descricao, unidade_medida, valor_unitario, quantidade, "
        "orgao_nome, unidade_nome, fornecedor_nome, fornecedor_cnpj, ordem_classificacao, "
        "certame, item, modalidade, objeto) VALUES (?,?,?,?,?,?,?,?,1,?,1,?,?)", linhas)
    con.commit()
    con.close()
    return p


def _base(desc="Cadeira", un="UN", precos=(10, 10, 10, 11, 9)):
    return [(desc, un, p, 10, f"O{i}", f"O{i}", "F1", "11111111000111", f"c{i}", 6, "")
            for i, p in enumerate(precos)]


CARA = ("Cadeira", "UN", 30.0, 100, "D", "D", "F2", "22222222000122", "cX", 6, "")
_KW = dict(esfera="todas", min_amostra=5, min_orgaos=2, min_certames=3)


def _v(estado="VERIFICADO", cert="cX", cnpj="22222222000122"):
    return {(cert, 1, cnpj): {"estado": estado}}


def test_soma_so_compra_verificada_fora_de_ata(tmp_path):
    db = _db(tmp_path, _base() + [CARA])
    d = CP.economia_potencial(db_path=db, verificacao=_v(), info_certames={"cX": {"srp": False}},
                              **_KW)
    assert d["economia_total"] == pytest.approx((30 - 10) * 100)
    assert d["n_compras_acima_mediana"] == 1
    assert d["por_fornecedor"][0]["fornecedor_cnpj"] == "22222222000122"


def test_nao_verificada_fica_pendente_e_fora_da_manchete(tmp_path):
    db = _db(tmp_path, _base() + [CARA])
    d = CP.economia_potencial(db_path=db, verificacao={}, info_certames={}, **_KW)
    assert d["economia_total"] == 0
    assert d["economia_pendente"] == pytest.approx(2000)
    assert d["por_orgao"] == []                 # quebras só com o que se sustenta


def test_ata_de_registro_de_precos_vai_para_o_teto(tmp_path):
    db = _db(tmp_path, _base() + [CARA])
    d = CP.economia_potencial(db_path=db, verificacao=_v(), info_certames={"cX": {"srp": True}},
                              **_KW)
    assert d["economia_total"] == 0 and d["economia_ata_teto"] == pytest.approx(2000)


def test_divergente_no_pncp_sai_da_conta(tmp_path):
    db = _db(tmp_path, _base() + [CARA])
    d = CP.economia_potencial(db_path=db, verificacao=_v("DIVERGENTE"),
                              info_certames={"cX": {"srp": False}}, **_KW)
    assert d["economia_total"] == 0 and d["economia_divergente"] == pytest.approx(2000)


def test_acima_da_mediana_mas_abaixo_de_2x_nao_e_economia(tmp_path):
    """Pagar 1,5× a mediana é variação de mercado, não sobrepreço identificado."""
    linha = ("Cadeira", "UN", 15.0, 100, "D", "D", "F2", "22222222000122", "cX", 6, "")
    db = _db(tmp_path, _base() + [linha])
    d = CP.economia_potencial(db_path=db, verificacao=_v(), info_certames={"cX": {"srp": False}},
                              **_KW)
    assert d["economia_total"] == 0


def test_salto_de_preco_nao_vira_economia(tmp_path):
    """500× a mediana não é sobrepreço comparável: é unidade/produto diferente (antes era
    'capado' em 10× e SOMADO)."""
    linha = ("Cadeira", "UN", 5000.0, 2, "D", "D", "F2", "22222222000122", "cX", 6, "")
    db = _db(tmp_path, _base() + [linha])
    d = CP.economia_potencial(db_path=db, verificacao=_v(), info_certames={"cX": {"srp": False}},
                              **_KW)
    assert d["economia_total"] == 0 and d["economia_pendente"] == 0


def test_inexigibilidade_e_agricultura_familiar_ficam_fora(tmp_path):
    inex = CARA[:9] + (9, "")
    agri = CARA[:8] + ("cY", 6, "Chamada pública da agricultura familiar - PNAE")
    db = _db(tmp_path, _base() + [inex, agri])
    v = {**_v(), **_v(cert="cY")}
    d = CP.economia_potencial(db_path=db, verificacao=v,
                              info_certames={"cX": {"srp": False}, "cY": {"srp": False}}, **_KW)
    assert d["economia_total"] == 0


def test_comodato_fica_fora(tmp_path):
    """Água 20 L 'em comodato' (conferido no PNCP em 13/11/2026): o preço inclui o equipamento."""
    linha = CARA[:9] + (8, "Aquisição de água mineral 20 L, em comodato")
    db = _db(tmp_path, _base() + [linha])
    d = CP.economia_potencial(db_path=db, verificacao=_v(), info_certames={"cX": {"srp": False}},
                              **_KW)
    assert d["economia_total"] == 0 and d["economia_pendente"] == 0


def test_unidade_ambigua_nao_entra(tmp_path):
    """Mesma descrição, unidade 'Caixa' sem quantidade declarada: INDETERMINADO."""
    linha = ("Cadeira", "Caixa", 30.0, 100, "D", "D", "F2", "22222222000122", "cX", 6, "")
    db = _db(tmp_path, _base() + [linha])
    d = CP.economia_potencial(db_path=db, verificacao=_v(), info_certames={"cX": {"srp": False}},
                              **_KW)
    assert d["economia_total"] == 0


def test_caixa_com_quantidade_e_normalizada_antes_de_comparar(tmp_path):
    """'Caixa 10 UN' a R$ 300 = R$ 30/un — compara com a unidade avulsa (mediana R$ 10)."""
    linha = ("Cadeira", "Caixa 10,00 UN", 300.0, 10, "D", "D", "F2", "22222222000122", "cX", 6, "")
    db = _db(tmp_path, _base() + [linha])
    d = CP.economia_potencial(db_path=db, verificacao=_v(), info_certames={"cX": {"srp": False}},
                              **_KW)
    # (30 − 10) × (10 caixas × 10 un) = 2.000
    assert d["economia_total"] == pytest.approx(2000)


def test_ressalva_declara_que_nao_e_ob(tmp_path):
    db = _db(tmp_path, _base())
    d = CP.economia_potencial(db_path=db, **_KW)
    assert "OB" in d["ressalva"] and "Indício" in d["ressalva"]
