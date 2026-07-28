# -*- coding: utf-8 -*-
"""Rota `/api/responsaveis` — devolve a ficha e, faltando, DECLARA a lacuna.

O erro que estes testes impedem é o mais caro desta funcionalidade: tratar ausência de
responsável identificado como ausência de responsável designado. Em 97% dos processos do
acervo o ato de designação não integra o processo de pagamento — dizer "processo sem fiscal"
por causa disso seria acusação falsa de violação do art. 117.
"""
from __future__ import annotations

import sqlite3

import pytest

from rotas.produtos import _responsaveis_payload


@pytest.fixture(autouse=True)
def banco(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE agente_processo (processo TEXT, nome TEXT, papel TEXT, id_funcional TEXT,
            matricula TEXT, cargo TEXT, origem TEXT, documento TEXT, contexto TEXT,
            visto_em TEXT);
        CREATE TABLE agente_lacuna (processo TEXT, tipo TEXT, descricao TEXT, visto_em TEXT);
    """)
    c.execute("INSERT INTO agente_processo VALUES ('030001_004724_2026','Nívea Dias Moreira "
              "Salgado','ordenador_despesa','5098630-9',NULL,'Assessora Especial','assinatura',"
              "'d.txt','ctx','2026-07-28')")
    c.execute("INSERT INTO agente_lacuna VALUES ('030001_004724_2026','art_117',"
              "'Execução sem fiscal identificado','2026-07-28')")
    c.commit()
    c.close()
    monkeypatch.setenv("JFN_DB", str(db))
    return db


def test_devolve_a_ficha_com_id_funcional():
    r = _responsaveis_payload("SEI-030001/004724/2026")
    assert r["ok"] and r["n"] == 1
    assert "Nívea Dias Moreira Salgado" in r["texto"]
    assert "5098630-9" in r["texto"], "sem ID funcional não se individualiza o responsável"


def test_aceita_as_duas_grafias_do_numero():
    a = _responsaveis_payload("SEI-030001/004724/2026")
    b = _responsaveis_payload("030001_004724_2026")
    assert a["texto"] == b["texto"]


def test_traz_as_lacunas_apontadas():
    r = _responsaveis_payload("SEI-030001/004724/2026")
    assert "Execução sem fiscal identificado" in r["texto"]


def test_processo_sem_agente_declara_lacuna_e_nao_afirma_inexistencia():
    """O invariante que mais importa aqui."""
    r = _responsaveis_payload("SEI-999999/999999/9999")
    assert r["ok"] and r["n"] == 0
    t = r["texto"]
    assert "lacuna de captura" in t
    assert "NÃO afirmação" in t
    assert "sem responsável designado" in t


def test_numero_devolvido_e_normalizado_para_a_grafia_oficial():
    assert _responsaveis_payload("030001_004724_2026")["processo"] == "SEI-030001/004724/2026"


def test_tabela_ausente_nao_quebra(tmp_path, monkeypatch):
    vazio = tmp_path / "vazio.db"
    sqlite3.connect(vazio).close()
    monkeypatch.setenv("JFN_DB", str(vazio))
    r = _responsaveis_payload("SEI-030001/004724/2026")
    assert r["ok"] and r["n"] == 0
