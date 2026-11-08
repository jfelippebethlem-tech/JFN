# -*- coding: utf-8 -*-
"""O que separa achado de anacronismo neste screen é a DATA do vínculo.

Medido em 2026-08-09: sem filtro de vigência, os dois maiores pares eram ROMA×MEDKA (16 certames)
e DROGAFONTE×LYF (10) — e nos dois o administrador comum entrou no ano SEGUINTE ao dos certames.
Com o filtro, ambos somem e sobe MEDH×CANNABR, cujo elo (Eduardo Dias Hermeto Filho e Evandro
Nader, cada um presente em exatamente 2 empresas da base) já existia. Mesma lição de
`situacao-cadastral-vigencia-na-data`, onde 78,7% das acusações eram anacrônicas.

O outro erro que este teste trava é de CONTAGEM: dois elos distintos ligando o mesmo par no mesmo
certame contam UMA vez. A primeira medição dobrou 6 certames em 12 exatamente assim.
"""
from __future__ import annotations

import sqlite3

import pytest

import tools.screen_coparticipacao_relacionados as S


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE nome_cnpj_resolvido (nome_norm TEXT, cnpj_basico TEXT)")
    con.execute("CREATE TABLE tcerj_licitante (ente TEXT, ano INT, processo TEXT, participante "
                "TEXT, resultado TEXT, qtd_participantes INT, valor_homologacao REAL, "
                "valor_estimado REAL, data_homologacao TEXT)")
    con.execute("CREATE TABLE socios_receita (cnpj_basico TEXT, doc_socio TEXT, "
                "data_entrada TEXT, nome_socio TEXT)")

    empresas = {"ALFA LTDA": "11111111", "BETA LTDA": "22222222",
                "TARDIA LTDA": "33333333", "AVULSA LTDA": "44444444"}
    for nome, raiz in empresas.items():
        con.execute("INSERT INTO nome_cnpj_resolvido VALUES (?,?)", (S._norm(nome), raiz))

    def certame(ente, proc, nomes, valor=1_000_000.0, estimado=1_200_000.0, dh="2024-06-10"):
        for n in nomes:
            con.execute("INSERT INTO tcerj_licitante VALUES (?,?,?,?,?,?,?,?,?)",
                        (ente, 2024, proc, n, "PERDEDOR", len(nomes), valor, estimado, dh))

    # ALFA e BETA disputam três certames em dois municípios; elo vigente desde 2019
    certame("MACAE", "1/2024", ["ALFA LTDA", "BETA LTDA", "AVULSA LTDA"])
    certame("MACAE", "2/2024", ["ALFA LTDA", "BETA LTDA"])
    certame("VALENCA", "3/2024", ["ALFA LTDA", "BETA LTDA"])
    # ALFA e TARDIA disputam dois — mas o elo só nasce em 2025
    certame("MACAE", "4/2024", ["ALFA LTDA", "TARDIA LTDA"])
    certame("VALENCA", "5/2024", ["ALFA LTDA", "TARDIA LTDA"])

    for raiz, doc, entrada, nome in (
            ("11111111", "***111111**", "20190101", "SOCIO COMUM"),
            ("22222222", "***111111**", "20190101", "SOCIO COMUM"),
            # segundo elo do MESMO par: não pode dobrar a contagem de certames
            ("11111111", "***222222**", "20190101", "OUTRO COMUM"),
            ("22222222", "***222222**", "20190101", "OUTRO COMUM"),
            # elo POSTERIOR aos certames de 2024
            ("11111111", "***333333**", "20250701", "SOCIO TARDIO"),
            ("33333333", "***333333**", "20250701", "SOCIO TARDIO")):
        con.execute("INSERT INTO socios_receita VALUES (?,?,?,?)", (raiz, doc, entrada, nome))
    con.commit()
    con.close()
    return str(p)


def test_pega_o_par_com_elo_vigente(db):
    r = S.medir(db=db)
    assert len(r) == 1, f"esperado só ALFA×BETA, veio {[(x['nome_a'], x['nome_b']) for x in r]}"
    assert {r[0]["cnpj_a"], r[0]["cnpj_b"]} == {"11111111", "22222222"}
    assert r[0]["municipios"] == 2


def test_elo_posterior_ao_certame_nao_conta(db):
    """Sócio que entrou em 2025 não descreve certame de 2024 — foi assim que ROMA×MEDKA caiu."""
    pares = {frozenset((x["cnpj_a"], x["cnpj_b"])) for x in S.medir(db=db)}
    assert frozenset(("11111111", "33333333")) not in pares


def test_dois_elos_no_mesmo_certame_contam_uma_vez(db):
    """A primeira medição dobrou 6 certames em 12 porque somava por elo, não por certame."""
    assert S.medir(db=db)[0]["certames"] == 3
    assert len(S.medir(db=db)[0]["elos"]) == 2, "os dois elos aparecem, mas não multiplicam"


def test_elo_onipresente_e_descartado(db, monkeypatch):
    """Pessoa em muitas empresas é administrador profissional ou colisão de máscara."""
    monkeypatch.setattr(S, "MAX_EMPRESAS_POR_ELO", 1)
    assert S.medir(db=db) == []


def test_piso_de_certames(db):
    assert S.medir(db=db, min_certames=4) == []


def test_base_sem_as_tabelas_devolve_vazio(tmp_path):
    p = tmp_path / "vazio.db"
    sqlite3.connect(p).close()
    assert S.medir(db=str(p)) == []


def test_ressalva_nao_afirma_ilicito():
    assert "não é vedado" in S.RESSALVA or "não vedada" in S.RESSALVA
    assert "piso" in S.RESSALVA, "a cobertura parcial precisa sair declarada"


def test_valor_implausivel_da_fonte_nao_entra_na_soma(db):
    """Homologado > 10× o estimado é defeito da fonte, não negócio.

    Medido em 2026-08-09 nas 125.060 linhas com os dois campos: 1,10% passam de 10× e carregam
    **87,4% da soma** do campo. O extremo é uma compra de gaze em Macaé com R$ 2,21 bi
    homologados contra R$ 2,95 mi estimados. Somando cru, o par COTTON×IMPÉRIO aparecia com
    R$ 2,2 bilhões; com a poda, R$ 7,5 mi.
    """
    con = sqlite3.connect(db)
    con.execute("INSERT INTO tcerj_licitante VALUES "
                "('MACAE',2024,'99/2024','ALFA LTDA','PERDEDOR',2,2_209_760_960.0,2_945_789.05,"
                "'2024-06-10')")
    con.execute("INSERT INTO tcerj_licitante VALUES "
                "('MACAE',2024,'99/2024','BETA LTDA','PERDEDOR',2,2_209_760_960.0,2_945_789.05,"
                "'2024-06-10')")
    con.commit(); con.close()
    r = S.medir(db=db)[0]
    assert r["certames"] == 4, "o certame conta; o que não conta é o VALOR impossível"
    assert r["valor"] < 10_000_000, f"valor implausível entrou na soma: R$ {r['valor']:,.2f}"
