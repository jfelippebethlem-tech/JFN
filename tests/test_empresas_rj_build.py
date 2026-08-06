# -*- coding: utf-8 -*-
"""Razão social das 5,86 milhões de empresas — o carregador e as duas coisas que ele não pode errar.

A base tinha 6.171.766 estabelecimentos e a razão social de nenhum: pedido para procurar uma
empresa pelo NOME, a casa respondia "não encontrei" quando a resposta certa era "não tenho como
procurar". O que estes testes travam é o recorte (só raiz que já tem estabelecimento — o resto do
país não responde pergunta desta casa) e a leitura do capital em formato brasileiro, que é indício
de fachada e viraria lixo silencioso se lido como float de locale inglês.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_empresas_rj_build.py -q
"""
from __future__ import annotations

import sqlite3
import subprocess
import zipfile

import pytest

from tools.empresas_rj_build import _capital, construir, medir, raizes_conhecidas

_LINHAS = [
    # raiz conhecida, associação privada (3999) — o terceiro setor que o caso das ONGs exige ver
    '"11111111";"ASSOCIACAO DE APOIO AO TESTE";"3999";"16";"0,00";"05";""',
    # raiz conhecida, LTDA com capital em formato brasileiro
    '"22222222";"6MAX SPORTS E GESTAO ESPORTIVA LTDA";"2062";"49";"500.000,00";"05";""',
    # raiz DESCONHECIDA: existe no dump nacional e não tem estabelecimento nosso — não entra
    '"99999999";"EMPRESA DE OUTRO ESTADO LTDA";"2062";"49";"1.000,00";"01";""',
]


@pytest.fixture()
def cenario(tmp_path, monkeypatch):
    estab = tmp_path / "estab.db"
    con = sqlite3.connect(estab)
    con.execute("CREATE TABLE estabelecimentos (cnpj TEXT, cnpj_basico TEXT, uf TEXT)")
    con.executemany("INSERT INTO estabelecimentos VALUES (?,?,'RJ')",
                    [("11111111000100", "11111111"), ("22222222000100", "22222222")])
    con.commit()
    con.close()

    dump = tmp_path / "dump"
    dump.mkdir()
    csv = tmp_path / "Empresas.csv"
    csv.write_text("\n".join(_LINHAS) + "\n", encoding="latin1")
    with zipfile.ZipFile(dump / "Empresas0.zip", "w") as z:
        z.write(csv, "Empresas0.csv")

    monkeypatch.setattr("tools.empresas_rj_build._DUMP", dump)
    return estab


def test_so_entra_raiz_que_ja_tem_estabelecimento(cenario):
    """O recorte É a decisão: 63 milhões de linhas nacionais sem endereço não respondem nada aqui."""
    assert raizes_conhecidas(cenario) == {"11111111", "22222222"}
    r = construir(estab=cenario)
    assert r["gravadas"] == 2 and r["linhas_lidas"] == 3

    con = sqlite3.connect(cenario)
    nomes = {x[0] for x in con.execute("SELECT razao_social FROM empresas")}
    con.close()
    assert "EMPRESA DE OUTRO ESTADO LTDA" not in nomes
    assert "6MAX SPORTS E GESTAO ESPORTIVA LTDA" in nomes


def test_busca_por_nome_passa_a_existir(cenario):
    """O motivo do módulo: procurar empresa pelo NOME, que antes era impossível nesta base."""
    construir(estab=cenario)
    con = sqlite3.connect(cenario)
    achado = con.execute(
        "SELECT cnpj_basico, natureza_cod FROM empresas WHERE razao_social LIKE '%6MAX%'"
    ).fetchall()
    terceiro = con.execute(
        "SELECT COUNT(*) FROM empresas WHERE substr(natureza_cod,1,1)='3'").fetchone()[0]
    con.close()
    assert achado == [("22222222", "2062")]
    assert terceiro == 1, "associação privada (3999) tem de ser reconhecível como terceiro setor"


def test_capital_em_formato_brasileiro_nao_vira_lixo():
    """`500.000,00` lido como float inglês daria 500,0 — capital de fachada onde há meio milhão."""
    assert _capital("500.000,00") == 500000.0
    assert _capital("0,00") == 0.0
    assert _capital("") == 0.0, "vazio é NÃO INFORMADO, e 0.0 é como esta tabela o representa"


def test_medir_declara_a_cobertura(cenario):
    construir(estab=cenario)
    m = medir(cenario)
    assert m["empresas"] == 2 and m["raizes_com_estabelecimento"] == 2
    assert m["cobertura_pct"] == 100.0


def test_sem_zip_falha_dizendo_o_que_fazer(tmp_path, monkeypatch):
    """Falha silenciosa aqui produziria uma tabela vazia indistinguível de 'não há empresas'."""
    monkeypatch.setattr("tools.empresas_rj_build._DUMP", tmp_path)
    with pytest.raises(SystemExit, match="baixar_receita_dump"):
        construir(estab=tmp_path / "x.db")


def test_unzip_disponivel():
    """O carregador depende de `unzip` no PATH — sem ele o stream morre sem linha alguma."""
    assert subprocess.run(["unzip", "-v"], capture_output=True).returncode == 0
