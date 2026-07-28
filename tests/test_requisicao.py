# -*- coding: utf-8 -*-
"""Minuta de requisição: pede, não acusa.

As duas listas produzidas pela varredura — processos com acesso restrito e processos conhecidos
e não capturados — não abrem nenhum processo sozinhas. Ofício abre. Estes testes travam as três
propriedades que fazem a peça ser assinável: agrupamento certo, fundamento citado, e nenhuma
palavra de juízo.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.reporting.requisicao import (
    PALAVRAS_VEDADAS, markdown, minutas, nome_orgao,
)


@pytest.fixture()
def con(tmp_path):
    c = sqlite3.connect(tmp_path / "t.db")
    c.executescript("""
        CREATE TABLE sei_sigilo (numero_sei TEXT, sei_norm TEXT, cadeado INTEGER,
            n_docs_restritos INTEGER, arvore_carregou INTEGER, n_docs INTEGER,
            tem_texto_local INTEGER, fonte TEXT, visto_em TEXT);
        CREATE TABLE sei_fila_captura (numero_sei TEXT, sei_norm TEXT, motivo TEXT,
            total_pago REAL, n_docs INTEGER, visto_em TEXT);
    """)
    c.executemany("INSERT INTO sei_sigilo VALUES (?,?,?,?,?,?,?,?,?)", [
        ("SEI-080002/018782/2024", "0800020187822024", 1, 3, 1, 12, 0, "f", "2026-07-28"),
        ("SEI-080002/011406/2024", "0800020114062024", 1, 0, 1, 8, 0, "f", "2026-07-28"),
        ("SEI-270006/036795/2025", "2700060367952025", 1, 1, 5, 5, 0, "f", "2026-07-28"),
        ("SEI-030001/000029/2026", "0300010000292026", 0, 0, 1, 82, 0, "f", "2026-07-28"),
    ])
    c.executemany("INSERT INTO sei_fila_captura VALUES (?,?,?,?,?,?)", [
        ("SEI-080002/000001/2024", "0800020000012024", "nunca_capturado", 250000.0, 0, "x"),
        ("SEI-080002/000002/2024", "0800020000022024", "nunca_capturado", 0.0, 0, "x"),
    ])
    c.commit()
    return c


def test_agrupa_por_orgao(con):
    m = {x["orgao"]: x for x in minutas(con)}
    assert set(m) == {"080002", "270006"}
    assert m["080002"]["n_restritos"] == 2
    assert m["080002"]["n_fila"] == 2


def test_processo_sem_cadeado_nao_entra(con):
    """O marcador de cadeado é o critério; processo aberto não é objeto de requisição."""
    todos = " ".join(markdown(x) for x in minutas(con))
    assert "SEI-030001/000029/2026" not in todos


def test_minuta_cita_o_fundamento_legal(con):
    txt = markdown(minutas(con)[0])
    for base in ("art. 5º, XXXIII", "12.527/2011", "14.133/2021", "art. 70 e 71"):
        assert base in txt, f"falta citar {base}"


def test_pede_o_fundamento_da_restricao_e_nao_so_o_processo(con):
    """Restringir acesso é ato administrativo, e ato administrativo se motiva."""
    txt = markdown(minutas(con)[0])
    assert "fundamento legal da restrição" in txt


def test_nao_contem_palavra_de_juizo(con):
    """Requisição de informação não acusa — presunção de legitimidade."""
    txt = markdown(minutas(con)[0]).lower()
    achadas = [p for p in PALAVRAS_VEDADAS if p in txt]
    assert not achadas, f"palavra de juízo na minuta: {achadas}"


def test_declara_a_presuncao_de_legitimidade(con):
    assert "presunção de legitimidade" in markdown(minutas(con)[0])


def test_valor_ausente_vira_nao_informado_e_nunca_zero(con):
    """INDISPONÍVEL ≠ 0. R$ 0,00 afirmaria que não houve pagamento."""
    txt = markdown(minutas(con)[0])
    assert "não informado" in txt
    assert "R$ 0,00" not in txt


def test_valor_presente_sai_formatado(con):
    assert "R$ 250.000,00" in markdown(minutas(con)[0])


def test_passa_no_gate_de_neutralidade(con):
    from compliance_agent.reporting.neutralidade import termos_proibidos
    assert termos_proibidos(markdown(minutas(con)[0])) == []


def test_orgao_desconhecido_nao_ganha_nome_inventado():
    assert nome_orgao("999999") == "Unidade 999999"


def test_tabela_ausente_nao_quebra(tmp_path):
    c = sqlite3.connect(tmp_path / "vazio.db")
    assert minutas(c) == []
