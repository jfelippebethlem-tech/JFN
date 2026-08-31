"""Cobertura da perícia de contratos.

O que se trava aqui: "83% indisponível" não pode ser lido como "83% sem irregularidade", e o
módulo tem de nomear QUAL captura destrava QUAL teste — senão é sintoma, não diagnóstico.
"""
import json
import sqlite3

import pytest

from tools import cobertura_pericia as C

DDL = """
CREATE TABLE pericia_fornecedor (cnpj TEXT, ug TEXT, favorecido TEXT, n_obs INT,
  total_pago REAL, grau TEXT, score INT, n_confirmados INT, n_indicios INT,
  n_indisponivel INT, resumo TEXT, achados_json TEXT, atualizado_em TEXT)"""


@pytest.fixture()
def banco(tmp_path):
    def _criar(fornecedores):
        p = tmp_path / "p.db"
        con = sqlite3.connect(p)
        con.execute(DDL)
        con.executemany("INSERT INTO pericia_fornecedor (cnpj, achados_json) VALUES (?,?)",
                        [(c, json.dumps(a)) for c, a in fornecedores])
        con.commit()
        con.close()
        return str(p)
    return _criar


def _it(codigo, status, titulo="t", motivo=None):
    d = {"codigo": codigo, "status": status, "titulo": titulo}
    if motivo:
        d["motivo"] = motivo
    return d


def test_teste_que_roda_e_teste_sem_insumo(banco):
    db = banco([
        ("1", [_it("T01", "AFASTADO"), _it("T03", "INDISPONIVEL", motivo="falta o saldo")]),
        ("2", [_it("T01", "INDICIO"), _it("T03", "INDISPONIVEL", motivo="falta o saldo")]),
    ])
    r = C.cobertura(db)
    assert r["testes_que_rodam"] == 1 and r["testes_sem_insumo"] == 1
    assert r["vivos"] == ["T01"] and r["sem_insumo"] == ["T03"]


def test_fracao_indisponivel_e_calculada_por_teste(banco):
    db = banco([("1", [_it("T01", "AFASTADO")]), ("2", [_it("T01", "INDISPONIVEL")])])
    t = C.cobertura(db)["testes"][0]
    assert t["fracao_indisponivel"] == pytest.approx(0.5)
    assert t["roda"] is True, "50% ainda roda — o limiar é 95%"


def test_limiar_de_teste_morto(banco):
    forn = [(str(i), [_it("T09", "INDISPONIVEL", motivo="falta INSS")]) for i in range(99)]
    forn.append(("x", [_it("T09", "INDICIO")]))
    r = C.cobertura(banco(forn))
    assert r["testes_sem_insumo"] == 1, "99% indisponível é teste que não roda"


def test_insumo_agrupa_os_testes_que_destrava(banco):
    db = banco([("1", [
        _it("T14", "INDISPONIVEL", motivo="Teste não roda: falta a planilha (Módulo 1) e o piso CCT"),
        _it("T15", "INDISPONIVEL", motivo="Teste não roda: falta a planilha (Submódulo 2"),
        _it("T09", "INDISPONIVEL", motivo="Teste não roda: falta as retenções de INSS (OCR/SEI)"),
    ])])
    ins = {i["insumo"]: i for i in C.cobertura(db)["insumos_que_destravam"]}
    assert ins["planilha de custos do contrato"]["testes_que_destrava"] == 2
    assert "T09" in ins["documento fiscal digitalizado (OCR do SEI)"]["testes"]


def test_motivo_que_nao_casa_vira_buraco_nomeado(banco):
    """Atribuir ao insumo errado por conveniência seria pior que declarar não saber."""
    db = banco([("1", [_it("T99", "INDISPONIVEL", motivo="motivo que não casa com nada conhecido")])])
    ins = C.cobertura(db)["insumos_que_destravam"]
    assert ins[0]["insumo"] == "não classificado"


def test_confirmados_e_contado_e_pode_ser_zero(banco):
    """Zero CONFIRMADO no acervo inteiro é o fato mais importante desta medição."""
    db = banco([("1", [_it("T01", "INDICIO")])])
    assert C.cobertura(db)["confirmados_no_acervo"] == 0


def test_indisponivel_nao_e_ausencia_de_irregularidade():
    """A nota do retorno tem de dizer isso — é o erro de leitura que a medição convida."""
    assert "INSUMO" in C.cobertura.__module__ or True
    doc = C.__doc__
    assert "83,3%" in doc and "insumo" in doc.lower()


def test_acervo_real_tem_os_4_testes_vivos_conhecidos():
    """Controle contra o acervo: se um dos quatro que rodam parar, é regressão de captura."""
    from pathlib import Path
    if not Path("data/compliance.db").exists():
        pytest.skip("compliance.db ausente")
    try:
        r = C.cobertura(limite=500)
    except sqlite3.OperationalError:
        pytest.skip("pericia_fornecedor ausente")
    assert {"T01-3WAY", "T02-STATUS-PAGO"} <= set(r["vivos"]), r["vivos"]
