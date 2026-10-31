# -*- coding: utf-8 -*-
"""Cotantes lidos dos autos para o P2: só documento próprio, endereço só com sala, contador não é e-mail comum."""
import sqlite3

from compliance_agent.detectores import REGISTRO
from compliance_agent.sei import cotacoes_acervo as C

GRANA, GUARA, ORZ1, ORZ2, QUAT, JESB = ("02768278000139", "10910334000156", "11111111000191", "22222222000191",
                                        "28747577000180", "30903337000170")


def _receita(p):
    con = sqlite3.connect(p)
    con.execute("create table estabelecimentos (cnpj text, cnpj_basico text, telefone1 text, correio_eletronico text,"
                " endereco_norm text, complemento text)")
    con.execute("create table empresas (cnpj_basico text, natureza_cod text, razao_social text)")
    linhas = [(GRANA, "2124667416", "", "RUA GRANA 298", "", "GRANA 298"),
              (GUARA, "2124667416", "", "RUA X 1", "", "GUARAILHA"),
              (QUAT, "21000", "a@q.com", "AV PASTOR MLK 126", "SAL 1301", "QUATTUOR"),
              (JESB, "21999", "b@j.com", "AV PASTOR MLK 126", "SAL 1316", "JESBAN"),
              ("42498717000155", "", "", "", "", "ESTADO DO RJ"),
              ("31736796000250", "2734216190", "registro@cmmcontabilidade.com.br", "RUA A 1", "", "FORTALEZA"),
              ("57768498000154", "2734216190", "registro@cmmcontabilidade.com.br", "RUA B 2", "", "PADUA")]
    for c, tel, em, end, comp, razao in linhas:
        con.execute("insert into estabelecimentos values (?,?,?,?,?,?)", (c, c[:8], tel, em, end, comp))
        con.execute("insert into empresas values (?,?,?)", (c[:8], "1236" if "ESTADO" in razao else "2062", razao))
    con.commit(); con.close()


def _doc(ref, *cnpjs, tipo="pesquisa_precos"):
    return {"ref": ref, "tipo": tipo, "texto": "Proposta " + " ".join(f"CNPJ {c}" for c in cnpjs)}


def test_cnpj_valido():
    assert C.cnpj_valido(GUARA) and not C.cnpj_valido("10910334000157") and not C.cnpj_valido("0" * 14)


def test_telefone_comum_entre_cotacoes_proprias_acende_p2(tmp_path):
    _receita(tmp_path / "r.db")
    cot = C.montar_cotacoes([_doc("Proposta GRANÁ", GRANA, "42498717000155"), _doc("Proposta GUARAILHA", GUARA)],
                            tmp_path / "r.db")
    assert [c["cnpj"] for c in cot] == [GRANA, GUARA], "órgão público (natureza 1xxx) não é cotante"
    r = REGISTRO["P2"].avaliar({"processo": "x", "cotacoes": cot})
    assert r.status == "confirmado" and "telefone" in str(r.evidencia)


def test_documento_com_dois_privados_nao_e_cotacao_de_ninguem(tmp_path):
    """Grupo Orzil: uma página de site com as duas empresas é UMA fonte, não duas cotações."""
    _receita(tmp_path / "r.db")
    assert C.montar_cotacoes([_doc("Pesquisa sites", GRANA, GUARA)], tmp_path / "r.db") == []


def test_mesmo_predio_salas_diferentes_nao_e_vinculo(tmp_path):
    _receita(tmp_path / "r.db")
    cot = C.montar_cotacoes([_doc("Proposta Q", QUAT), _doc("Proposta J", JESB)], tmp_path / "r.db")
    assert len(cot) == 2
    assert REGISTRO["P2"].avaliar({"processo": "x", "cotacoes": cot}).status != "confirmado"


def test_so_documento_de_pesquisa_ou_proposta(tmp_path):
    _receita(tmp_path / "r.db")
    assert C.montar_cotacoes([_doc("Nota de Empenho", GRANA, tipo="empenho"),
                              _doc("Despacho", GUARA, tipo="tramitacao")], tmp_path / "r.db") == []


def test_telefone_do_contador_e_vinculo_fraco(tmp_path):
    """FORTALEZA AMBIENTAL × ÁGUAS DE PÁDUA: o telefone comum é o da contabilidade que fez os dois cadastros."""
    _receita(tmp_path / "r.db")
    cot = C.montar_cotacoes([_doc("Proposta F", "31736796000250"), _doc("Proposta P", "57768498000154")],
                            tmp_path / "r.db")
    assert all(c["contato"]["telefone"] == "" and c["contador"] for c in cot)
    r = REGISTRO["P2"].avaliar({"processo": "x", "cotacoes": cot})
    assert r.score <= 0.3 and "contador" in r.motivo_refutacao     # fraco: exculpatória regional do P2
