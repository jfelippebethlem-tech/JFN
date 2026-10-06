# -*- coding: utf-8 -*-
"""O membro em recuperação judicial entra pelo CONSÓRCIO — e era assim que sumia.

Medido em 2026-08-09, a partir do relatório da CGE sobre a SECID: seis consórcios da UG 660100
carregam a MESMA empresa em recuperação judicial no quadro societário, somando **R$ 415,5 mi
pagos**. Nenhum deles é, ele próprio, uma empresa em recuperação — por isso a busca pelo nome do
CREDOR não via nada, e a casa só havia usado este sinal uma vez, à mão, num dossiê.

Participar não é vedado; o que se mede é ONDE conferir a habilitação econômico-financeira. Estes
testes travam as três propriedades que fazem a lista ser honesta: pega o consórcio pelo membro,
pega o credor direto, e nunca some com quem não tem o rótulo.
"""
from __future__ import annotations

import sqlite3

import pytest

import tools.screen_recuperacao_judicial as S


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, nome_credor TEXT, valor REAL,"
                " status TEXT, ug_emitente TEXT, data_emissao TEXT)")
    con.execute("CREATE TABLE socios_receita (cnpj_basico TEXT, nome_socio TEXT)")

    def ob(credor, nome, valor, ug="660100", ano="2025", status="Contabilizado"):
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?)",
                    (credor, nome, valor, status, ug, f"15/12/{ano}"))

    ob("49298100000135", "CONSORCIO VIEIRA BOM RETIRO", 135_566_974.77)
    ob("07792269000105", "LYTORANEA S A - EM RECUPERACAO JUDICIAL", 28_943_166.89)
    ob("11111111000191", "EMPRESA COMUM LTDA", 50_000_000.00)
    ob("22222222000122", "CONSORCIO PEQUENO", 10_000.00)     # abaixo do piso de valor
    ob("33333333000133", "CANCELADA EM RECUPERACAO JUDICIAL", 90_000_000.0, status="Excluído")
    # o consórcio carrega a empresa em recuperação NO QSA; o consórcio pequeno também
    con.executemany("INSERT INTO socios_receita VALUES (?,?)", [
        ("49298100", "R C VIEIRA ENGENHARIA LTDA EM RECUPERACAO JUDICIAL"),
        ("49298100", "F P VIEIRA ENGENHARIA LTDA"),
        ("22222222", "OUTRA EM RECUPERACAO JUDICIAL"),
        ("11111111", "SOCIO QUALQUER")])
    con.commit()
    con.close()
    return str(p)


def test_pega_o_consorcio_pelo_MEMBRO(db):
    r = {x["raiz"]: x for x in S.medir(db=db)}
    assert "49298100" in r, "o consórcio some se a busca olhar só o nome do credor"
    assert r["49298100"]["via"] == "membro do consórcio"
    assert "R C VIEIRA ENGENHARIA LTDA EM RECUPERACAO JUDICIAL" in \
        r["49298100"]["membros_em_recuperacao"]


def test_pega_o_credor_direto(db):
    r = {x["raiz"]: x for x in S.medir(db=db)}
    assert r["07792269"]["via"] == "credor", "quem carrega o rótulo no próprio nome também conta"


def test_nao_acusa_quem_nao_tem_o_rotulo(db):
    assert "11111111" not in {x["raiz"] for x in S.medir(db=db)}


def test_piso_de_valor(db):
    assert "22222222" not in {x["raiz"] for x in S.medir(db=db)}
    assert "22222222" in {x["raiz"] for x in S.medir(db=db, min_valor=1_000.0)}


def test_ob_cancelada_nao_conta(db):
    """OB excluída não é pagamento — a regra vale aqui como em todo lugar."""
    assert "33333333" not in {x["raiz"] for x in S.medir(db=db, min_valor=1.0)}


def test_ordena_por_valor(db):
    assert [x["raiz"] for x in S.medir(db=db)][:2] == ["49298100", "07792269"]


def test_base_sem_as_tabelas_devolve_vazio(tmp_path):
    p = tmp_path / "vazio.db"
    sqlite3.connect(p).close()
    assert S.medir(db=str(p)) == []


def test_ressalva_declara_que_nao_e_vedado_e_que_e_piso():
    assert "NÃO impede contratar" in S.RESSALVA
    assert "PISO" in S.RESSALVA
    assert "data" in S.RESSALVA, "o rótulo sem data é a armadilha do anacronismo — tem de sair dito"
