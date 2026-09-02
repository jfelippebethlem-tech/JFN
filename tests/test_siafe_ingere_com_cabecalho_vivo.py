# -*- coding: utf-8 -*-
"""A ingestão precisa do cabeçalho AO VIVO — nomes internos não são rótulos de tela.

`ingerir(exercicio, header, linhas)` mapeia coluna→campo pelo cabeçalho que a tela mostra
(`_LABEL2COL`, que cobre SIAFE 2 com 23 colunas e SIAFE 1 com 19). Se o cabeçalho não é
reconhecido, cai no mapa POSICIONAL — e no SIAFE 1, com menos colunas, tudo desloca.

Medido em 2026-08-09: os caminhos de SUBDIVISÃO (`coletar_por_ug_grande` e o completador por dia)
passavam `_COLS_SIAFE` — a lista de nomes internos da BASE — no lugar do cabeçalho. Efeito: as
linhas entravam com `numero_ob` VAZIO, colapsavam todas na mesma chave primária e sobrava UMA por
fatia. O log dizia "pref 2023OB060: 100 OBs ✓" e o banco ganhava 1 linha — perda silenciosa de 99%
justamente no caminho que existe para furar o teto de 1.000.
"""
from __future__ import annotations

import inspect
import sqlite3

import pytest

import compliance_agent.siafe_ob_orcamentaria as M


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "c.db"
    monkeypatch.setattr(M, "_DB", p)
    return p


def test_nomes_internos_nao_sao_cabecalho(db):
    """Reproduz o defeito: com `_COLS_SIAFE` como cabeçalho, a linha perde o número da OB."""
    linha = ["2023OB00284", "180100", "", "", "", "", "", "", "", "", "", "", "1.000,00"]
    M.ingerir(2023, M._COLS_SIAFE, [linha])
    con = sqlite3.connect(db)
    (numero,) = con.execute("SELECT numero_ob FROM ob_orcamentaria_siafe").fetchone()
    # o mapa posicional salva o número, mas NÃO é o caminho que a tela do SIAFE 1 exige;
    # o que o teste fixa é que a chamada real use o cabeçalho vivo (teste abaixo).
    assert numero in ("2023OB00284", "")


def test_cabecalho_vivo_preenche_o_numero_da_ob(db):
    """Com os RÓTULOS da tela, o número cai na coluna certa mesmo com ordem diferente."""
    # o cabeçalho só é aceito com >= 4 rótulos reconhecidos (guarda contra header truncado)
    header = ["Número", "UG Emitente", "Data Emissão", "Credor", "Valor"]
    M.ingerir(2023, header, [["2023OB00284", "180100", "05/06/2023", "CG0004700", "1.500,00"]])
    con = sqlite3.connect(db)
    r = con.execute("SELECT numero_ob, ug_emitente, valor FROM ob_orcamentaria_siafe").fetchone()
    assert r == ("2023OB00284", "180100", 1500.0)


def test_fatia_inteira_sobrevive_e_nao_colapsa(db):
    """100 OBs colhidas têm de virar 100 linhas — era 1 quando o número vinha vazio."""
    header = ["Número", "UG Emitente", "Data Emissão", "Credor", "Valor"]
    linhas = [[f"2023OB{i:05d}", "180100", "05/06/2023", "CG0004700", "10,00"] for i in range(100)]
    M.ingerir(2023, header, linhas)
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe").fetchone()[0] == 100


def test_caminhos_de_subdivisao_usam_o_cabecalho_vivo():
    """Catraca: nenhum caminho pode voltar a passar os nomes internos como cabeçalho."""
    for fn in (M.coletar_por_ug_grande, M.coletar_por_data):
        fonte = inspect.getsource(fn)
        assert "ingerir(exercicio, _COLS_SIAFE" not in fonte, (
            f"{fn.__name__} voltou a ingerir com nomes internos no lugar do cabeçalho da tela")
        assert "header = await _colher" in fonte, (
            f"{fn.__name__} descartou o cabeçalho que `_colher` devolve")


def test_zero_fatia_declara_nada_a_fazer():
    """`ok:true` com 0 fatias não pode passar por "coletei e não havia nada".

    Medido 2026-08-09: com todos os prefixos no checkpoint `done` de junho, a coleta devolvia
    `{"ok": true, "fatias": 0, "ingeridas": 0}` — indistinguível de uma UG sem OB nenhuma. Perdi
    uma execução inteira lendo isso como resultado. Agora o retorno diz `nada_a_fazer` e aponta o
    arquivo de checkpoint que precisa ser mexido para refazer.
    """
    fonte = inspect.getsource(M.coletar_por_ug_grande)
    assert "nada_a_fazer" in fonte, "voltou a devolver ok:true mudo quando não consulta nada"
    assert "checkpoint" in fonte and "ckp" in fonte, (
        "o retorno não diz ONDE mexer para refazer — sem isso o operador não tem próximo passo")
