# -*- coding: utf-8 -*-
"""Cliente DataJud/CNJ — parsing e leitura. Sem rede: `resumo_processo` é testado
com o documento real capturado da API (fixture inline, encurtado)."""
import pytest

from compliance_agent.collectors import datajud as dj


def test_indice_do_tribunal():
    assert dj.indice("TJRJ") == "api_publica_tjrj"
    assert dj.indice(" tjsp ") == "api_publica_tjsp"


@pytest.mark.parametrize("entrada", [
    "0028391-26.2015.8.19.0004",
    "00283912620158190004",
    "processo nº 0028391-26.2015.8.19.0004 em trâmite",
])
def test_normaliza_numero_com_e_sem_mascara(entrada):
    assert dj.normalizar_numero(entrada) == "00283912620158190004"


def test_numero_invalido_nao_vira_chute():
    assert dj.normalizar_numero("SEI-260002/001234/2024") is None


def test_tribunal_deduzido_do_numero():
    assert dj.tribunal_do_numero("0028391-26.2015.8.19.0004") == "TJRJ"
    assert dj.tribunal_do_numero("1000000-00.2020.8.26.0100") == "TJSP"


def test_segmento_nao_estadual_devolve_none_em_vez_de_chutar():
    # J=4 (Justiça Federal): o par J.TR não mapeia para sigla sem tabela auxiliar.
    assert dj.tribunal_do_numero("0000001-00.2020.4.02.5101") is None


def test_extrai_numeros_cnj_sem_repetir():
    texto = ("vide autos 0028391-26.2015.8.19.0004, os mesmos 00283912620158190004 "
             "e ainda 1000000-00.2020.8.26.0100")
    assert dj.extrair_numeros_cnj(texto) == ["00283912620158190004", "10000000020208260100"]


_DOC = {
    "numeroProcesso": "00283912620158190004",
    "tribunal": "TJRJ",
    "grau": "G1",
    "nivelSigilo": 0,
    "dataAjuizamento": "20150707133412",
    "classe": {"codigo": 64, "nome": "Ação Civil de Improbidade Administrativa"},
    "orgaoJulgador": {"nome": "SAO GONCALO 7 VARA CIVEL", "codigoMunicipioIBGE": 3304904},
    "assuntos": [{"codigo": 9607, "nome": "Improbidade Administrativa"}],
    "movimentos": [
        {"codigo": 26, "nome": "Distribuição", "dataHora": "2015-07-07T13:34:12.000Z"},
        {"codigo": 219, "nome": "Procedência", "dataHora": "2024-02-01T10:00:00.000Z"},
        {"codigo": 11010, "nome": "Publicação", "dataHora": "2026-05-22T19:30:30.000Z"},
    ],
}


@pytest.fixture()
def sem_rede(monkeypatch):
    monkeypatch.setattr(dj, "consultar_processo", lambda *a, **k: _DOC)


def test_resumo_le_classe_vara_e_desfecho(sem_rede):
    r = dj.resumo_processo("0028391-26.2015.8.19.0004")
    assert r["encontrado"]
    assert r["classe"] == "Ação Civil de Improbidade Administrativa"
    assert r["e_classe_de_controle"] is True
    assert r["orgao_julgador"] == "SAO GONCALO 7 VARA CIVEL"
    assert r["qtd_movimentos"] == 3


def test_resumo_identifica_julgamento_e_ultimo_movimento(sem_rede):
    r = dj.resumo_processo("0028391-26.2015.8.19.0004")
    assert r["ja_julgado"] is True
    assert [d["codigo"] for d in r["desfechos"]] == [219]
    # último movimento é o mais RECENTE, não o último da lista por acaso
    assert r["ultimo_movimento"]["nome"] == "Publicação"


def test_processo_sem_desfecho_nao_e_dado_como_julgado(monkeypatch):
    doc = dict(_DOC, movimentos=[{"codigo": 26, "nome": "Distribuição",
                                  "dataHora": "2015-07-07T13:34:12.000Z"}])
    monkeypatch.setattr(dj, "consultar_processo", lambda *a, **k: doc)
    r = dj.resumo_processo("0028391-26.2015.8.19.0004")
    assert r["ja_julgado"] is False and r["desfechos"] == []


def test_nao_encontrado_declara_a_lacuna(monkeypatch):
    monkeypatch.setattr(dj, "consultar_processo", lambda *a, **k: None)
    r = dj.resumo_processo("0028391-26.2015.8.19.0004")
    assert r["encontrado"] is False and "não localizado" in r["observacao"]


def test_judicializacao_de_documento_percorre_todos_os_numeros(monkeypatch):
    monkeypatch.setattr(dj, "resumo_processo", lambda n, **k: {"numero": n, "encontrado": True})
    r = dj.judicializacao_de_documento("autos 0028391-26.2015.8.19.0004 e 1000000-00.2020.8.26.0100")
    assert [x["numero"] for x in r] == ["00283912620158190004", "10000000020208260100"]
