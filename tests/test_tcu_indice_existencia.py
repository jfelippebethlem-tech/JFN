# -*- coding: utf-8 -*-
"""Índice de existência do TCU — e a distinção que decide se um alarme é honesto.

`nao_confirmado` na Jurisprudência Selecionada NÃO é prova de inexistência: a Selecionada é um
recorte curado. Este índice cobre o acervo COMPLETO por ano, o que permite dizer três coisas
diferentes que antes eram uma só:

  · `confirmado` ............... o par (número, ano) existe e o colegiado bate;
  · `inexistente_no_ano` ....... o ano ESTÁ indexado e o número não consta — assinatura de
                                 citação fabricada, e agora afirmável;
  · `ano_nao_indexado` ......... lacuna de COBERTURA, não negativa. Confundir os dois faria o
                                 sistema declarar inexistente um acórdão que ninguém procurou.

Nenhum teste aqui toca a rede: a ingestão é exercitada com CSV em memória.
"""
from __future__ import annotations

import sqlite3

import pytest

from tools import tcu_indice_existencia as T


@pytest.fixture()
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "_DB", tmp_path / "t.db")
    c = T._conectar()
    yield c
    c.close()


def _grava(c, numero, ano, colegiado="Plenário", tipo="ACÓRDÃO"):
    c.execute("INSERT OR IGNORE INTO tcu_acordao_existencia"
              "(key,numero,ano,colegiado,tipo,titulo,ata,data_sessao,relator,situacao,processo)"
              " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (f"{ano}-{numero}-{colegiado}", numero, ano, colegiado, tipo,
               f"ACÓRDÃO {numero}/{ano}", "1/%d" % ano, "01/01/%d" % ano, "REL", "OFICIALIZADO",
               "000.000/2020-0"))
    c.execute("INSERT OR REPLACE INTO tcu_existencia_cobertura(ano,linhas,bytes,ingerido_em)"
              " VALUES(?,?,0,datetime('now'))", (ano, 1))
    c.commit()


# ─────────────── as três respostas, e por que não podem colapsar ──────────────────────────────

def test_acordao_existente_e_confirmado(con):
    _grava(con, 2622, 2013)
    r = T.conferir("Acórdão 2.622/2013-Plenário", con)
    assert r["status"] == "confirmado" and r["colegiado"] == "Plenário"


def test_numero_ausente_em_ano_INDEXADO_e_inexistente(con):
    """Só se pode afirmar inexistência quando o ano foi de fato varrido."""
    _grava(con, 100, 2013)
    r = T.conferir("Acórdão 9.999/2013-Plenário", con)
    assert r["status"] == "inexistente_no_ano"
    assert "fabricada" in r["nota"]


def test_ano_NAO_indexado_e_lacuna_e_nunca_negativa(con):
    r = T.conferir("Acórdão 3.243/2020-Plenário", con)
    assert r["status"] == "ano_nao_indexado"
    assert "NÃO negativa" in r["nota"]


def test_colegiado_divergente_nao_vira_inexistente(con):
    """O acórdão existe; quem errou foi a citação. São correções diferentes."""
    _grava(con, 871, 2023, colegiado="1ª Câmara")
    r = T.conferir("Acórdão 871/2023-Plenário", con)
    assert r["status"] == "colegiado_diverge" and r["colegiados_reais"] == ["1ª Câmara"]


def test_citacao_sem_colegiado_confirma_pelo_par_numero_ano(con):
    _grava(con, 871, 2023, colegiado="1ª Câmara")
    assert T.conferir("Acórdão 871/2023", con)["status"] == "confirmado"


def test_ponto_de_milhar_nao_atrapalha(con):
    _grava(con, 3243, 2020)
    assert T.conferir("Acórdão 3.243/2020-Plenário", con)["status"] == "confirmado"


def test_texto_sem_citacao_e_ilegivel_e_nao_inexistente(con):
    assert T.conferir("não há acórdão citado aqui", con)["status"] == "ilegivel"


# ─────────────── ingestão: contrato de colunas e 200 com corpo de erro ────────────────────────

class _Resp:
    """Resposta HTTP mínima com `iter_bytes`, como a do httpx."""

    def __init__(self, corpo: bytes, status: int = 200):
        self.status_code = status
        self._c = corpo

    def iter_bytes(self):
        yield self._c

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stream(corpo, status=200):
    return lambda *a, **k: _Resp(corpo, status)


_CAB_NOVO = (b'"KEY"|"TIPO"|"TITULO"|"NUMACORDAO"|"ANOACORDAO"|"NUMATA"|"COLEGIADO"|'
             b'"DATASESSAO"|"RELATOR"|"SITUACAO"|"PROC"\n')
_CAB_ANTIGO = (b'"TIPO"|"TITULO"|"NUMACORDAO"|"ANOACORDAO"|"NUMATA"|"COLEGIADO"|'
               b'"DATASESSAO"|"RELATOR"|"SITUACAO"|"PROC"\n')


def _ingerir(con, corpo, ano=2020, status=200, monkeypatch=None):
    import httpx
    monkeypatch.setattr(httpx, "stream", _stream(corpo, status))
    return T.ingerir_ano(ano, con, forcar=True)


def test_ingere_esquema_novo_com_KEY(con, monkeypatch):
    corpo = _CAB_NOVO + b'"K1"|"ACORDAO"|"T"|"3243"|"2020"|"1/2020"|"Plenario"|"d"|"r"|"s"|"p"\n'
    r = _ingerir(con, corpo, monkeypatch=monkeypatch)
    assert r["gravadas"] == 1
    assert T.conferir("Acórdão 3243/2020", con)["status"] == "confirmado"


def test_ingere_esquema_ANTIGO_sem_KEY(con, monkeypatch):
    """Medido em 2007: o acervo antigo não tem a coluna KEY. Exigi-la recusava o ano inteiro
    acusando '200 com corpo de erro' — o alarme certo disparando pelo motivo errado."""
    corpo = _CAB_ANTIGO + b'"ACORDAO"|"T"|"2622"|"2007"|"1/2007"|"Plenario"|"d"|"r"|"s"|"p"\n'
    r = _ingerir(con, corpo, ano=2007, monkeypatch=monkeypatch)
    assert r["gravadas"] == 1


def test_200_com_corpo_de_HTML_nao_grava_nada(con, monkeypatch):
    """A falha calada que já matou o Querido Diário — e que a API do TCU devolve hoje."""
    r = _ingerir(con, b"<html><body>Requisicao rejeitada</body></html>\n",
                 monkeypatch=monkeypatch)
    assert "erro" in r
    assert con.execute("SELECT COUNT(*) FROM tcu_acordao_existencia").fetchone()[0] == 0


def test_ano_com_erro_NAO_entra_na_cobertura(con, monkeypatch):
    """Marcar como coberto um ano que falhou transformaria a falha em 'inexistente'."""
    _ingerir(con, b"<html>erro</html>\n", monkeypatch=monkeypatch)
    assert con.execute("SELECT COUNT(*) FROM tcu_existencia_cobertura").fetchone()[0] == 0


def test_campo_gigante_nao_estoura_o_leitor(con, monkeypatch):
    """Voto e relatório passam de 1 MB; o limite padrão do módulo csv é 128 KB."""
    voto = b"x" * 200_000
    corpo = (_CAB_NOVO.rstrip() + b'|"VOTO"\n'
             + b'"K1"|"ACORDAO"|"T"|"1"|"2020"|"1"|"Plenario"|"d"|"r"|"s"|"p"|"' + voto + b'"\n')
    r = _ingerir(con, corpo, monkeypatch=monkeypatch)
    assert r["gravadas"] == 1


def test_ano_ja_ingerido_e_pulado(con, monkeypatch):
    corpo = _CAB_NOVO + b'"K1"|"ACORDAO"|"T"|"1"|"2020"|"1"|"Plenario"|"d"|"r"|"s"|"p"\n'
    _ingerir(con, corpo, monkeypatch=monkeypatch)
    import httpx
    monkeypatch.setattr(httpx, "stream", _stream(corpo))
    assert T.ingerir_ano(2020, con).get("pulado") is True


def test_faixa_de_anos_e_expandida():
    assert T._anos("2007,2012") == [2007, 2012]
    assert T._anos("2019-2021") == [2019, 2020, 2021]
    assert T._anos("2019-2020,2007") == [2007, 2019, 2020]
