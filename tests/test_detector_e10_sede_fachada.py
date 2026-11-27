# -*- coding: utf-8 -*-
"""E10 `e10.c_sede_fachada` (O5.3 fatia 2): sede de fachada só com DOIS sinais gravados convergentes (sede real
apurável + endereço ou foto adversa), contraprova de foto comercial afasta, insumo ausente = INDISPONÍVEL. Sem rede."""
import sqlite3

import pytest

from compliance_agent.aplicacao.detectores import sede_fachada as SF

A, B = "11111111000111", "22222222000122"


@pytest.fixture()
def fonte(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE ob_orcamentaria_siafe(numero_ob, ug_emitente, exercicio, credor, valor, status, status_envio);
    CREATE TABLE verificacao_sede_real(cnpj, veredito, apuravel, score_suspeita, sinais);
    CREATE TABLE endereco_verificacao(cnpj, status, nivel, evidencia);
    CREATE TABLE verificacao_sede(cnpj, visual_classe, coerencia_google, predio_key, visual_fonte);
    """)
    for i, d in enumerate((A, B)):
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?)",
                    (f"OB{i}", "010100", 2025, d, 1000.0, "Contabilizado", ""))
    con.commit()
    return con, p


def _carga(con, p, e9="E"):
    con.commit()
    itens = SF.carregar(sqlite3.connect(f"file:{p}?mode=ro", uri=True)).itens
    for c in itens:
        c["e9"] = e9
    return itens


def test_positivo_sede_suspeita_e_endereco_com_indicio(fonte):
    con, p = fonte
    con.execute("INSERT INTO verificacao_sede_real VALUES (?,?,?,?,?)", (A, "forte_suspeita", 1, 80, "sala"))
    con.execute("INSERT INTO endereco_verificacao VALUES (?,?,?,?)", (A, "INDICIO", "ALTO", "baldio no OSM"))
    ds = SF.detectar(_carga(con, p))
    assert [d.chave for d in ds] == [A] and ds[0].valores["segundo_sinal"] == ["endereco"]
    assert ds[0].estado == "INDICIO" and len(ds[0].evidencias) == 2


def test_negativo_um_sinal_so_nao_dispara(fonte):
    con, p = fonte
    con.execute("INSERT INTO verificacao_sede_real VALUES (?,?,?,?,?)", (A, "suspeita", 1, 60, ""))
    con.execute("INSERT INTO endereco_verificacao VALUES (?,?,?,?)", (B, "INDICIO", "ALTO", "baldio"))  # sem base
    itens = _carga(con, p)
    assert SF.detectar(itens) == [] and SF.resumo(itens, [])["um_sinal_so"] == 2


def test_negativo_foto_comercial_e_contraprova(fonte):
    con, p = fonte
    con.execute("INSERT INTO verificacao_sede_real VALUES (?,?,?,?,?)", (A, "suspeita", 1, 60, ""))
    con.execute("INSERT INTO endereco_verificacao VALUES (?,?,?,?)", (A, "INDICIO", "ALTO", "x"))
    con.execute("INSERT INTO verificacao_sede VALUES (?,?,?,?,?)", (A, "comercial_industrial", "confirma", "k", "sv"))
    assert SF.detectar(_carga(con, p)) == []


def test_inapuravel_e_osm_ausente_sao_indisponiveis(fonte):
    con, p = fonte
    con.execute("INSERT INTO verificacao_sede_real VALUES (?,?,?,?,?)", (A, "inapuravel", 0, None, ""))
    con.execute("INSERT INTO endereco_verificacao VALUES (?,?,?,?)", (A, "INDISPONIVEL", "—", "sem OSM"))
    con.execute("INSERT INTO verificacao_sede VALUES (?,?,?,?,?)", (A, "terreno_baldio", None, "k", "sv"))
    itens = _carga(con, p)
    assert SF.sinais(itens[0]) == {"sede": None, "endereco": None, "foto": True}
    assert SF.detectar(itens) == []                                    # foto sozinha, sem sede apurável


def test_inelegivel_na_e9_nao_dispara(fonte):
    con, p = fonte
    con.execute("INSERT INTO verificacao_sede_real VALUES (?,?,?,?,?)", (A, "suspeita", 1, 60, ""))
    con.execute("INSERT INTO verificacao_sede VALUES (?,?,?,?,?)", (A, "casa_residencial", None, "k", "sv"))
    assert SF.detectar(_carga(con, p)) and SF.detectar(_carga(con, p, "I:ENTE_PUBLICO")) == []


def test_foto_sem_endereco_confiavel_nao_e_sinal(fonte):
    """27/11/2026 — regra única #70 (força da evidência, ex-`fachada_visual_sweep`): só imagem confiável do endereço
    acusa. A captura marca `sem_foto_confiavel:endereco_impreciso` (67 CNPJs com classe adversa assim, medido) — a
    foto pode nem ser do imóvel: INDISPONÍVEL, nunca 2º sinal."""
    con, p = fonte
    con.execute("INSERT INTO verificacao_sede_real VALUES (?,?,?,?,?)", (A, "forte_suspeita", 1, 80, "sala"))
    con.execute("INSERT INTO verificacao_sede VALUES (?,?,?,?,?)",
                (A, "terreno_baldio", None, "p1", "sem_foto_confiavel:endereco_impreciso"))
    (c,) = [x for x in _carga(con, p) if x["cnpj"] == A]
    assert SF.sinais(c)["foto"] is None and SF.detectar([c]) == []
    con.execute("UPDATE verificacao_sede SET visual_fonte = 'Google Street View' WHERE cnpj = ?", (A,))
    (c,) = [x for x in _carga(con, p) if x["cnpj"] == A]
    assert SF.sinais(c)["foto"] is True and SF.detectar([c])                   # controle: a confiável dispara
