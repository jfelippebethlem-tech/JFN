# -*- coding: utf-8 -*-
"""Alertas de emendas com o NOME do parlamentar → segundo cérebro (decisão do dono, 14/11/2026: parlamentar é pessoa
pública no exercício do mandato). Só vai o alerta com triagem VERIFICADA (duas leituras + Opus), sempre com fonte,
estado e a ressalva "indício não é acusação"; nunca CPF; repetir não duplica. Tudo em memória/`tmp_path`, sem rede."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from compliance_agent import propagacao as P
from compliance_agent.emendas import cerebro_alertas as E

RAIZ = Path(__file__).resolve().parents[1]

D2_DESC = ("Indício de concentração territorial: 100% da carteira de emendas de FULANO DE TAL (R$ 18.574.778,00 "
           "empenhados no recorte coletado) destina-se a DUQUE DE CAXIAS - RJ (R$ 18.574.778,00). Concentração não é "
           "ilícito por si. (fonte: API Portal da Transparência, /emendas)")
D6_DESC = ("Indício de anúncio sem execução: emenda 201927760009 (2019, autor BELTRANO SILVA, destino RIO DE JANEIRO "
           "(UF)) teve R$ 100.000,00 empenhados, R$ 0,00 liquidados e R$ 0,00 pagos. Empenho não é pagamento. "
           "(fonte: API Portal da Transparência, /emendas)")


def _base(path: Path) -> Path:
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE alertas(id INTEGER PRIMARY KEY, tipo TEXT, severidade TEXT, titulo TEXT, descricao TEXT,
          evidencias TEXT, status TEXT, pessoa_id INTEGER);
        CREATE TABLE alertas_triagem(alerta_id INTEGER, prioridade TEXT, nota INTEGER, proximo_passo TEXT, em TEXT,
          estado TEXT, verificado_por TEXT);
        CREATE TABLE emendas(codigo TEXT, autor_raw TEXT, autor_norm TEXT);
    """)
    c.execute("INSERT INTO emendas VALUES ('201927760009', 'Beltrano Silva', 'BELTRANO SILVA')")
    linhas = [
        # id, tipo, titulo, descricao, evidencias, pessoa_id, prioridade, estado, verificado_por
        (1, "emendas_d2_concentracao_autor", "Concentração de emendas — FULANO DE TAL → DUQUE DE CAXIAS - RJ", D2_DESC,
         {"autor": "FULANO DE TAL", "destino": "DUQUE DE CAXIAS - RJ"}, None, "monitorar", "VERIFICADO", "claude-opus-5-5"),
        (2, "emendas_d6_empenho_sem_pagamento", "Empenho sem execução — emenda 201927760009", D6_DESC,
         {"empenhado": 100000.0}, None, "aprofundar", "VERIFICADO", "claude-opus-5-5"),
        (3, "emendas_d2_concentracao_autor", "Concentração de emendas — CICLANO → NITERÓI - RJ", D2_DESC,
         {"autor": "CICLANO"}, None, "monitorar", "PENDENTE", None),                       # não verificado
        (4, "emendas_d2_concentracao_autor", "Concentração de emendas — DEUTRANO → MARICÁ - RJ", D2_DESC,
         {"autor": "DEUTRANO"}, None, "provavel_falso_positivo", "VERIFICADO", "claude-opus-5-5"),  # descartado
        (5, "emendas_d4_favorecido_fantasma", "Sinais de fachada — ONG X", "Indício de favorecido sem substância.",
         {"cnpj": "03686998000118"}, None, "aprofundar", "VERIFICADO", "claude-opus-5-5"),  # sem parlamentar
        (6, "emendas_d2_concentracao_autor", "Concentração de emendas — PESSOA → RIO - RJ", D2_DESC,
         {"autor": "PESSOA"}, 77, "monitorar", "VERIFICADO", "claude-opus-5-5"),            # pessoa física vinculada
        (7, "emendas_d2_concentracao_autor", "Concentração de emendas — SEM LEITURA OPUS → RIO - RJ", D2_DESC,
         {"autor": "SEM LEITURA OPUS"}, None, "monitorar", "VERIFICADO", None),             # sem verificação do Opus
    ]
    for i, tipo, tit, desc, ev, pid, prio, est, ver in linhas:
        c.execute("INSERT INTO alertas VALUES (?,?,?,?,?,?,?,?)", (i, tipo, "alta", tit, desc, json.dumps(ev), "novo", pid))
        c.execute("INSERT INTO alertas_triagem VALUES (?,?,?,?,?,?,?)", (i, prio, 4, "", "2026-11-13T17:54:04", est, ver))
    c.commit()
    c.close()
    return path


@pytest.fixture()
def src(tmp_path):
    c = sqlite3.connect(_base(tmp_path / "compliance.db"))
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def test_so_vai_alerta_verificado_com_parlamentar_e_sem_pessoa_vinculada(src):
    chaves = [k for k, _t, _a in E.descobertas(src)]
    assert chaves == ["emenda:1", "emenda:2"]


def test_texto_tem_nome_fonte_estado_e_ressalva(src):
    d = {k: (t, a) for k, t, a in E.descobertas(src)}
    texto, assunto = d["emenda:1"]
    assert "FULANO DE TAL" in texto and "FULANO DE TAL" in assunto
    assert "Fonte: API Portal da Transparência, /emendas" in texto
    assert "Estado: VERIFICADO" in texto and "indício" in texto.lower()
    assert "Indício não é acusação" in texto
    assert "(fonte:" not in texto                     # a fonte sai uma vez só, rotulada


def test_d6_tira_o_autor_da_tabela_de_emendas(src):
    d = {k: t for k, t, _a in E.descobertas(src)}
    assert "Parlamentar autor da emenda: BELTRANO SILVA" in d["emenda:2"]


def test_texto_e_estavel_entre_rodadas(src):
    assert E.descobertas(src) == E.descobertas(src)


def test_cpf_no_texto_nunca_sai(src, tmp_path, monkeypatch):
    src.execute("UPDATE alertas SET descricao = descricao || ' Sócio CPF 123.456.789-09.' WHERE id = 1")
    monkeypatch.setattr(P, "DATA", tmp_path)
    reg = P.conectar(tmp_path / "p.db")
    try:
        assert all("123.456.789-09" not in t for _k, t, _a in E.descobertas(src))   # recorta o CPF
        st = {k: P.cerebro.registrar(k, t, "semantica", a, con=reg) for k, t, a in E.descobertas(src)}
        assert set(st.values()) == {"novo"}
    finally:
        reg.close()


def test_bloco_funcao_da_propagacao_e_idempotente(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    _base(tmp_path / "data" / "compliance.db")
    monkeypatch.setattr(P, "RAIZ", tmp_path)
    monkeypatch.setattr(P, "DATA", tmp_path)
    reg = P.conectar(tmp_path / "p.db")
    cfg = {"cerebro": [{"id": "emendas_parlamentar", "kind": "semantica",
                        "funcao": "compliance_agent.emendas.cerebro_alertas:descobertas"}]}
    try:
        assert P.descobertas_sql(reg, cfg) == 2
        assert P.descobertas_sql(reg, cfg) == 0         # repetir não duplica
        n = reg.execute("SELECT COUNT(*) FROM cerebro WHERE chave LIKE 'emenda:%'").fetchone()[0]
        assert n == 2
    finally:
        reg.close()


def test_mapa_de_producao_liga_emendas_e_triagem_geral_nao_duplica():
    cfg = P.carregar(RAIZ / "config" / "propagacao.yaml")
    blocos = {b["id"]: b for b in cfg["cerebro"]}
    assert blocos["emendas_parlamentar"]["funcao"] == "compliance_agent.emendas.cerebro_alertas:descobertas"
    sql = blocos["triagem_verificada"]["sql"]
    for tipo in E.TIPOS:
        assert tipo.split("_")[1] in sql                # o alerta com parlamentar vai só pelo bloco próprio


def test_texto_curto_e_o_que_distingue_vem_primeiro(src):
    """O cérebro funde memórias com similaridade > 0,96: com o texto longo, 3 parlamentares viraram 1 memória."""
    for _k, t, _a in E.descobertas(src):
        assert t.startswith("Parlamentar autor da emenda: ") and len(t) <= 600
        assert "Concentração não é ilícito por si" not in t and "Indício de " not in t[:80]
