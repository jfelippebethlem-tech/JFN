# -*- coding: utf-8 -*-
"""Ingestão da Nota de Empenho: coluna pelo NOME do cabeçalho, nunca pela posição."""
import sqlite3

from compliance_agent import siafe_ne as N

_HEADER = ["Número", "UG Emitente", "Data Emissão", "Doc. Alt.", "Tipo Alt.", "Status", "Credor", "Nome do Credor",
           "Fonte", "Natureza", "Precatório", "Processo", "Tipo de reconhecimento de passivo",
           "Assinatura Eletrônica", "Valor"]
_LINHA = ["2026NE03532", "123400", "27/10/2026", "", "", "Contabilizado", "CG0006025", "RIOPREV/PENSIONISTA",
          "801", "319003", "Não", "SEI-040014/000956/2026", "Passivo a ser reconhecido", "Não Solicitado",
          "100.830.023,49"]


def test_ingere_pelo_nome_do_cabecalho(tmp_path):
    db = tmp_path / "c.db"
    r = N.ingerir(2026, _HEADER, [_LINHA, ["Total", "", "", ""]], db=db)
    assert r["ok"] and r["ingeridas"] == 1
    row = sqlite3.connect(db).execute("SELECT numero, fonte, natureza, processo, tipo_reconhecimento_passivo, "
                                      "valor FROM ne_siafe").fetchone()
    assert row == ("2026NE03532", "801", "319003", "SEI-040014/000956/2026", "Passivo a ser reconhecido",
                   100830023.49)


def test_ordem_das_colunas_diferente_nao_desloca(tmp_path):
    db = tmp_path / "c.db"
    ordem = list(range(len(_HEADER)))[::-1]
    N.ingerir(2026, [_HEADER[i] for i in ordem], [[_LINHA[i] for i in ordem]], db=db)
    assert sqlite3.connect(db).execute("SELECT fonte, valor FROM ne_siafe").fetchone() == ("801", 100830023.49)


def test_cabecalho_sem_numero_nao_grava_nada(tmp_path):
    assert N.ingerir(2026, ["Fonte", "Valor"], [["801", "1,00"]], db=tmp_path / "c.db")["ok"] is False


def test_ne_com_sufixo_p_e_aceita(tmp_path):
    db = tmp_path / "c.db"
    linha = list(_LINHA)
    linha[0] = "2026NE00744P"
    assert N.ingerir(2026, _HEADER, [linha], db=db)["ingeridas"] == 1


def test_ano_da_ne_vem_do_numero_e_nao_da_consulta(tmp_path):
    """A tela consultada em 2025 lista RP de anos anteriores: a NE de 2002 não é empenho de 2025."""
    db = tmp_path / "c.db"
    linha = list(_LINHA)
    linha[0] = "2002NE00011"
    N.ingerir(2025, _HEADER, [linha], db=db)
    assert sqlite3.connect(db).execute("SELECT exercicio, ano_ne FROM ne_siafe").fetchone() == (2025, 2002)
