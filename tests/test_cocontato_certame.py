# -*- coding: utf-8 -*-
"""Dois participantes do MESMO certame dividindo contato — e as guardas que impedem o alarme falso.

Medido em 2026-08-07: dos 16.509 certames com resultado, 4.517 têm dois ou mais fornecedores
distintos (25.562 pares, 5.624 CNPJs). Cruzados contra os 6,17 milhões de estabelecimentos da
Receita: **44 pares dividem contato**, dos quais 28 sem explicação, 14 por contato de serviço e 2
por grupo econômico aparente. 0,6% dos certames — a taxa que separa.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_cocontato_certame.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

_SCHEMA_PNCP = """
CREATE TABLE pncp_resultado (certame TEXT, orgao_cnpj TEXT, orgao_nome TEXT, uf TEXT,
  municipio TEXT, modalidade TEXT, objeto TEXT, data_pub TEXT, item TEXT, fornecedor_cnpj TEXT,
  fornecedor_nome TEXT, valor_homologado REAL, ordem_classificacao INTEGER, porte_fornecedor TEXT,
  coletado_em TEXT, unidade_codigo TEXT, unidade_nome TEXT, item_descricao TEXT,
  unidade_medida TEXT, valor_unitario REAL, quantidade REAL);
"""
_SCHEMA_ESTAB = """
CREATE TABLE estabelecimentos (cnpj TEXT, cnpj_basico TEXT, telefone1 TEXT, telefone2 TEXT,
  correio_eletronico TEXT);
CREATE TABLE empresas (cnpj_basico TEXT, razao_social TEXT, natureza_cod TEXT);
"""


@pytest.fixture()
def cenario(tmp_path):
    est = tmp_path / "estab.db"
    ce = sqlite3.connect(est)
    ce.executescript(_SCHEMA_ESTAB)
    ce.executemany("INSERT INTO estabelecimentos VALUES (?,?,?,?,?)", [
        # dois participantes, MESMO telefone, raízes distintas
        ("11111111000100", "11111111", "2133334444", "", "compras@alfa.com.br"),
        ("22222222000100", "22222222", "2133334444", "", "compras@beta.com.br"),
        # matriz e filial da MESMA empresa — não é elo
        ("33333333000100", "33333333", "2155556666", "", "x@gama.com.br"),
        ("33333333000278", "33333333", "2155556666", "", "x@gama.com.br"),
        # contabilidade com domínio livre
        ("44444444000100", "44444444", "", "", "silvacontabilidade@gmail.com"),
        ("55555555000100", "55555555", "", "", "silvacontabilidade@gmail.com"),
    ])
    ce.executemany("INSERT INTO empresas VALUES (?,?,?)", [
        ("11111111", "ALFA COMERCIO LTDA", "2062"), ("22222222", "BETA COMERCIO LTDA", "2062"),
        ("33333333", "GAMA LTDA", "2062"),
        ("44444444", "DELTA SERVICOS LTDA", "2062"), ("55555555", "EPSILON SERVICOS LTDA", "2062"),
    ])
    ce.commit(); ce.close()

    con = sqlite3.connect(":memory:")
    con.executescript(_SCHEMA_PNCP)
    def linha(cert, cnpj, nome):
        return (cert, "", "ORGAO X", "RJ", "RIO", "PREGAO", "objeto", "2024-01-01", "1",
                cnpj, nome, 100.0, 1, "", "", "", "", "", "", 100.0, 1.0)
    con.executemany("INSERT INTO pncp_resultado VALUES (%s)" % ",".join("?" * 21), [
        linha("C1", "11111111000100", "ALFA"), linha("C1", "22222222000100", "BETA"),
        linha("C2", "33333333000100", "GAMA MATRIZ"), linha("C2", "33333333000278", "GAMA FILIAL"),
        linha("C3", "44444444000100", "DELTA"), linha("C3", "55555555000100", "EPSILON"),
    ])
    con.commit()
    yield con, est
    con.close()


def test_par_com_mesmo_telefone_no_mesmo_certame_e_achado(cenario):
    from compliance_agent.osint.cocontato_certame import levantar

    con, est = cenario
    r = levantar(con, estab=est)
    achados = [p for p in r["pares"] if p["certame"] == "C1"]
    assert len(achados) == 1, "o par com telefone idêntico no mesmo certame não foi achado"
    assert achados[0]["tipo"] == "mesmo_telefone"
    assert achados[0]["contato_de_servico"] is False


def test_matriz_e_filial_nunca_entram(cenario):
    """Filial não é outra empresa — se entrasse, todo grupo com duas unidades viraria cartel."""
    from compliance_agent.osint.cocontato_certame import levantar

    con, est = cenario
    r = levantar(con, estab=est)
    assert not [p for p in r["pares"] if p["certame"] == "C2"]


def test_contabilidade_com_dominio_livre_e_classificada_como_servico(cenario):
    """`silvacontabilidade@gmail.com` — a regra antiga via só o domínio e chamaria isso de elo."""
    from compliance_agent.osint.cocontato_certame import levantar

    con, est = cenario
    r = levantar(con, estab=est)
    c3 = [p for p in r["pares"] if p["certame"] == "C3"]
    assert len(c3) == 1 and c3[0]["contato_de_servico"] is True
    assert c3[0]["tipo"] == "mesmo_contador", "o tipo deve cair para a força 0,30"


def test_sem_base_de_contato_devolve_vazio_e_diz_por_que(cenario, tmp_path):
    """Base ausente é lacuna declarada, nunca 'nenhum achado'."""
    from compliance_agent.osint.cocontato_certame import levantar

    con, _ = cenario
    r = levantar(con, estab=tmp_path / "nao_existe.db")
    assert r["pares"] == [] and "erro" in r
