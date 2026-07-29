# -*- coding: utf-8 -*-
"""Histórico societário — entrada, saída e a recusa de responder fora da janela observada.

O que este teste trava é o oposto do que normalmente se trava: não é a capacidade de responder
"fulano era sócio", é a **capacidade de dizer INDISPONÍVEL** quando a série não cobre a data. A
casa já pagou caro por ler ausência de registro como ausência de fato (17.128 certames "limpos"
sem ninguém olhar; 282 manifests "sem contexto" tratados como limpos).

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_historico_societario.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.osint.historico_societario import (
    criar_schema,
    diff_snapshots,
    historico_do_socio,
    registrar_snapshot,
    snapshots_ingeridos,
    trocas_perto_de,
    vinculo_na_data,
)


def _socio(raiz: str, doc: str, nome: str, qualif: str = "Sócio", entrada: str = "20190101") -> dict:
    return {"cnpj_basico": raiz, "doc_socio": doc, "nome_socio": nome, "ident": "2",
            "qualificacao_txt": qualif, "data_entrada": entrada}


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    criar_schema(c)
    yield c
    c.close()


def _serie_com_saida(con) -> None:
    """MARIA sai da ALFA entre 2024-02 e 2024-03; JOAO permanece; PEDRO entra em 2024-03."""
    maria = _socio("11111111", "***111111**", "MARIA DA SILVA")
    joao = _socio("11111111", "***222222**", "JOAO SOUZA")
    pedro = _socio("11111111", "***333333**", "PEDRO LIMA", entrada="20240301")
    registrar_snapshot(con, "2024-01", [maria, joao], origem="espelho")
    registrar_snapshot(con, "2024-02", [maria, joao], origem="espelho")
    registrar_snapshot(con, "2024-03", [joao, pedro], origem="espelho")


def test_detecta_saida_entre_meses_consecutivos(con):
    _serie_com_saida(con)
    r = diff_snapshots(con)
    assert r["ok"] and r["n_meses"] == 3
    assert r["n_sairam"] == 1 and r["n_ativos"] == 2

    h = historico_do_socio(con, nome="MARIA DA SILVA")[0]
    assert h["status"] == "saiu"
    assert h["saiu_entre"] == "2024-02..2024-03"
    assert h["janela_confiavel"] == 1, "meses consecutivos: a janela é de um mês"


def test_buraco_na_serie_derruba_a_confianca_mas_nao_a_saida(con):
    """Sócio ausente num mês NÃO ingerido não saiu naquele mês — o mês não foi observado."""
    maria = _socio("11111111", "***111111**", "MARIA DA SILVA")
    joao = _socio("11111111", "***222222**", "JOAO SOUZA")
    registrar_snapshot(con, "2024-01", [maria, joao], origem="espelho")
    registrar_snapshot(con, "2024-09", [joao], origem="espelho")  # 8 meses de buraco
    diff_snapshots(con)

    h = historico_do_socio(con, nome="MARIA DA SILVA")[0]
    assert h["status"] == "saiu"
    assert h["janela_confiavel"] == 0, (
        "com 8 meses não observados entre os snapshots, a saída não tem precisão mensal"
    )


def test_pergunta_fora_da_serie_e_indisponivel_nunca_nao(con):
    """A pergunta que fecha caso de direcionamento — 'era sócio no dia do certame?' — não pode
    receber 'NAO' quando a série nem cobre a data."""
    _serie_com_saida(con)
    r = vinculo_na_data(con, "11111111", "2021-06-15", nome="MARIA DA SILVA")
    assert r["resposta"] == "INDISPONIVEL"
    assert "não é ausência de vínculo" in r["motivo"]
    assert r["diligencia"]["orgao"].startswith("JUCERJA")


def test_responde_sim_dentro_da_serie(con):
    _serie_com_saida(con)
    r = vinculo_na_data(con, "11111111", "2024-02-20", nome="MARIA DA SILVA")
    assert r["resposta"] == "SIM"
    assert r["mes_observado"] == "2024-02"
    assert r["defasagem_meses"] == 0
    assert r["socios"][0]["nome"] == "MARIA DA SILVA"


def test_responde_nao_com_ressalva_de_defasagem(con):
    """'NAO' dentro da série ainda vem com a ressalva: a Receita publica mensalmente, e alteração
    contratual dentro da janela não aparece."""
    _serie_com_saida(con)
    r = vinculo_na_data(con, "11111111", "2024-03-28", nome="MARIA DA SILVA")
    assert r["resposta"] == "NAO"
    assert "ficha cadastral da junta comercial" in r["ressalva"]
    assert r["diligencia"] is not None, "resposta negativa tem de vir com a diligência que a confirma"


def test_troca_de_quadro_perto_da_data(con):
    """Sócio que entra logo depois da homologação é o padrão que a linha do tempo sempre quis ler."""
    _serie_com_saida(con)
    diff_snapshots(con)
    t = trocas_perto_de(con, "11111111", "2024-03-10", meses_janela=2)
    assert t["ok"]
    assert t["n_saidas"] == 1, "a saída de MARIA está na janela"
    assert "igualmente compatível com" in t["leitura"], "o achado tem de carregar a hipótese inocente"


def test_serie_vazia_nao_inventa_resposta(con):
    assert snapshots_ingeridos(con) == []
    r = vinculo_na_data(con, "11111111", "2024-02-20")
    assert r["resposta"] == "INDISPONIVEL"
    assert diff_snapshots(con)["ok"] is False
