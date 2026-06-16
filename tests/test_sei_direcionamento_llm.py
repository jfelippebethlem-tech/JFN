# -*- coding: utf-8 -*-
"""DIRECIONAMENTO on-demand (Fase 4) — LLM (gemini) só nos TOP-SCORE + SURFACE persistido.

Cobre `tools.sei_direcionamento_llm` SEM rede (injeta `gerar` fake):
  • `_texto_das_arvores` — concatena os dossiês consolidados das árvores do fornecedor (bounded).
  • `avaliar_fornecedor`/`avaliar_top` — roda o cérebro e PERSISTE o parecer ao lado do score.
  • cache de 30d (não reavalia salvo --forcar).
  • `parecer_fornecedor` — leitura p/ o surface no Lex (None quando ainda não avaliado).

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_sei_direcionamento_llm.py -q
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from tools import sei_direcionamento_llm as dl

# Dossiê que PARECE edital de licitação (passa o gate `edital_de_licitacao` do cérebro): >1500 chars e
# >=3 menções a marcadores (edital/atestado/qualificac/habilitac/pregão/licitac/proposta).
_DOSSIE = ("DOSSIÊ DE PROCESSO SEI — SEI-1/1/2024\n" + ("=" * 40) + "\n"
           "OBJETO: contratação via PREGÃO ELETRÔNICO (edital) de serviços.\n"
           "MODALIDADE: pregão. RED FLAGS: atestado de qualificação técnica restritivo; habilitação.\n"
           "A licitação trouxe exigência de atestado idêntico ao objeto e a proposta vencedora subiu.\n"
           + ("Texto de habilitação e qualificação técnica do edital de licitação. " * 40))


def _seed_db(db_path, *, llm_em=None):
    con = sqlite3.connect(str(db_path))
    con.execute("CREATE TABLE sei_arvore (numero_sei TEXT PRIMARY KEY, txt_path TEXT)")
    con.execute("""CREATE TABLE sei_direcionamento (
        fornecedor_cnpj TEXT PRIMARY KEY, fornecedor_nome TEXT, score INTEGER, arvores TEXT)""")
    con.commit()
    con.close()


async def _fake_gerar(messages):
    """LLM fake — devolve o JSON do schema do cérebro (determinístico, sem rede)."""
    return json.dumps({
        "grau": "amarelo", "resumo": "Indício de exigência restritiva a verificar.",
        "raciocinio": "O atestado idêntico ao objeto pode restringir a competição.",
        "exigencias_restritivas": [{"trecho": "atestado idêntico ao objeto",
                                    "por_que_restringe": "limita concorrentes", "jurisprudencia": "Súmula TCU 263"}],
        "cascata": [{"licitante": "EMP A", "ordem_preco": 1, "situacao": "desclassificado", "motivo": "atestado"}],
        "dados_suficientes": True})


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "compliance.db"
    _seed_db(p)
    # dossiê em arquivo
    dossie = tmp_path / "SEI_1_1_2024.txt"
    dossie.write_text(_DOSSIE, encoding="utf-8")
    con = sqlite3.connect(str(p))
    con.execute("INSERT INTO sei_arvore (numero_sei, txt_path) VALUES (?,?)", ("SEI-1/1/2024", str(dossie)))
    con.execute("INSERT INTO sei_direcionamento (fornecedor_cnpj, fornecedor_nome, score, arvores) VALUES (?,?,?,?)",
                ("12345678000190", "FORNEC X", 55, json.dumps(["SEI-1/1/2024"])))
    con.commit(); con.close()
    monkeypatch.setattr(dl, "DB", p)
    return p


def test_texto_das_arvores_concatena(db):
    con = dl._conectar()
    try:
        txt = dl._texto_das_arvores(con, ["SEI-1/1/2024"])
    finally:
        con.close()
    assert "PREGÃO" in txt and len(txt) > 1500


def test_avaliar_top_persiste_e_surface(db):
    r = dl.avaliar_top(top_n=10, gerar=_fake_gerar)
    assert r["avaliados"] == 1 and r["pulados"] == 0
    assert r["top"][0]["grau"] == "amarelo"
    # surface: parecer_fornecedor lê o que foi persistido
    par = dl.parecer_fornecedor("12.345.678/0001-90")  # tolera CNPJ formatado
    assert par is not None
    assert par["grau"] == "amarelo"
    assert par["score"] == 55
    assert par["detalhe"]["cascata"][0]["situacao"] == "desclassificado"


def test_cache_nao_reavalia_recente(db):
    dl.avaliar_top(top_n=10, gerar=_fake_gerar)            # 1ª: avalia
    r2 = dl.avaliar_top(top_n=10, gerar=_fake_gerar)       # 2ª: cache fresco → pula
    assert r2["avaliados"] == 0 and r2["pulados"] == 1
    r3 = dl.avaliar_top(top_n=10, gerar=_fake_gerar, forcar=True)  # --forcar reavalia
    assert r3["avaliados"] == 1


def test_parecer_fornecedor_none_quando_nao_avaliado(db):
    assert dl.parecer_fornecedor("99999999000199") is None  # existe? nem está na tabela → None


def test_sem_dossie_reporta_indisponivel(db, monkeypatch):
    # remove o txt_path → sem dossiê → 'dados insuficientes', honesto (não chama o LLM)
    con = sqlite3.connect(str(db))
    con.execute("UPDATE sei_arvore SET txt_path='' WHERE numero_sei='SEI-1/1/2024'")
    con.commit(); con.close()
    r = dl.avaliar_top(top_n=10, gerar=_fake_gerar)
    assert r["avaliados"] == 1
    par = dl.parecer_fornecedor("12345678000190")
    assert par["detalhe"]["dados_suficientes"] is False
