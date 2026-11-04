# -*- coding: utf-8 -*-
"""Ingestão da Nota de Empenho: coluna pelo NOME do cabeçalho, nunca pela posição."""
import sqlite3

from compliance_agent import siafe_documento as N

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


_HEADER_NL = ["Número", "UG Emitente", "Data Emissão", "Doc. Alt.", "Tipo Alt.", "Status", "NE", "NL Rec.",
              "Status Comp.", "Credor", "Nome do Credor", "GD", "Precatório", "Processo", "Valor Retido",
              "Assinatura Eletrônica", "Valor"]


def test_nl_grava_a_ne_vinculada_e_o_valor_retido(tmp_path):
    db = tmp_path / "c.db"
    linha = ["2026NL04226", "123400", "27/10/2026", "", "", "Contabilizado", "2026NE03532", "",
             "Passivo reconhecido e Liquidado", "CG0006025", "RIOPREV/PENSIONISTA", "", "Não",
             "SEI-040014/000956/2026", "16.320.192,87", "Não Solicitado", "100.830.023,49"]
    r = N.ingerir(2026, _HEADER_NL, [linha], db=db, tipo="NL")
    assert r["ingeridas"] == 1
    assert sqlite3.connect(db).execute("SELECT ne, ano_nl, valor_retido, valor, status_comp FROM nl_siafe").fetchone() \
        == ("2026NE03532", 2026, 16320192.87, 100830023.49, "Passivo reconhecido e Liquidado")


def test_numero_de_ne_nao_entra_como_nl(tmp_path):
    db = tmp_path / "c.db"
    linha = ["2026NE03532"] + [""] * 16
    assert N.ingerir(2026, _HEADER_NL, [linha], db=db, tipo="NL")["ingeridas"] == 0


def test_limite_decidido_pelo_rotulo_e_nao_pelo_id():
    """NE/NL: "Limite de 1000 registros" marcado = limite ATIVO (166100 parou em 1.000 achando o contrário)."""
    assert N._acao_limite("Limite de 1000 registros.", True) == "clicar"
    assert N._acao_limite("Limite de 1000 registros.", False) == "nada"
    assert N._acao_limite("Remover limite", False) == "clicar"
    assert N._acao_limite("Remover limite", True) == "nada"
    assert N._acao_limite("", True) == "desconhecido"


def test_fatia_no_teto_subdivide_ate_tres_digitos():
    assert N._subdividir("2025NE0", 1000, len("2025NE")) == [f"2025NE0{d}" for d in range(10)]
    assert N._subdividir("2025NE0", 400, len("2025NE")) == []
    assert N._subdividir("2025NE012", 1000, len("2025NE")) == []       # profundidade máxima: declara capada
