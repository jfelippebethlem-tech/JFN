# -*- coding: utf-8 -*-
"""LEX PESQUISA-INTERNET (Fase 5) — pesquisa as dúvidas, aprende e re-ajusta.

Sem rede: o LLM (`gerar`) e o OSINT (`osint_fn`) são injetados; o DB é um tmp; o vault é um tmp via env.

Cobre:
  • extrair_duvidas — junta red_flags da sei_direcionamento + sei_ficha (dedup, bounded).
  • pesquisar — monta o parecer com LLM+OSINT injetados, persiste no DB e grava a nota no vault; honesto
    quando não há dúvidas (status sem_duvidas) e quando o LLM cai (não fabrica).
  • parecer_pesquisa — SURFACE só leitura do que foi persistido.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_lex_pesquisa_internet.py -q
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3

import pytest


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    """Carrega o módulo apontando DB e VAULT p/ tmp (recarrega p/ reler os globais de path)."""
    db = tmp_path / "compliance.db"
    vault = tmp_path / "vault"
    vault.mkdir()  # vault precisa existir (o módulo NÃO cria um vault do zero — guard intencional)
    monkeypatch.setenv("VAULT_DIR", str(vault))
    import tools.lex_pesquisa_internet as m
    importlib.reload(m)
    monkeypatch.setattr(m, "DB", db)
    # cria as tabelas-fonte mínimas
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE sei_direcionamento (fornecedor_cnpj TEXT PRIMARY KEY, fornecedor_nome TEXT, "
                "red_flags TEXT, arvores TEXT, score INTEGER, llm_json TEXT)")
    con.execute("CREATE TABLE sei_ficha (numero_sei TEXT PRIMARY KEY, cnpjs TEXT, red_flags TEXT, analise TEXT)")
    con.commit(); con.close()
    return m


def _seed_fornecedor(m, cnpj="12345678000190", nome="EMPRESA X", red_flags=None, score=50):
    con = sqlite3.connect(str(m.DB))
    con.execute("INSERT INTO sei_direcionamento (fornecedor_cnpj, fornecedor_nome, red_flags, arvores, score, llm_json) "
                "VALUES (?,?,?,?,?,?)",
                (cnpj, nome, json.dumps(["atestado restritivo — verificar"] if red_flags is None else red_flags),
                 json.dumps(["SEI-1/2024"]), score, ""))
    con.commit(); con.close()


# ───────────────────────── extrair_duvidas ─────────────────────────
def test_extrair_duvidas_junta_e_dedup(mod):
    _seed_fornecedor(mod, red_flags=["dispensa reiterada", "atestado restritivo"])
    con = sqlite3.connect(str(mod.DB))
    con.execute("INSERT INTO sei_ficha VALUES (?,?,?,?)",
                ("SEI-1/2024", "12345678000190", json.dumps(["atestado restritivo", "preço acima da mediana"]), "x"))
    con.commit()
    nome, duvidas = mod.extrair_duvidas("12345678000190", con)
    con.close()
    assert nome == "EMPRESA X"
    assert "atestado restritivo" in duvidas
    assert "preço acima da mediana" in duvidas
    assert len(duvidas) == len(set(duvidas))  # dedup


# ───────────────────────── pesquisar (LLM + OSINT injetados) ─────────────────────────
async def _osint_fake(nome, cnpj):
    return {"evidencia": json.dumps({"web": {"resumo": "nada relevante"}}),
            "fontes": ["https://exemplo/news/1"], "blocos": {}, "erros": []}


async def _gerar_fake(messages):
    return json.dumps({
        "achados": [{"duvida": "atestado restritivo — verificar", "veredito": "inconclusivo",
                     "nota": "sem evidência pública conclusiva", "fontes": ["https://exemplo/news/1"]}],
        "resumo": "Indício mantido; nada novo na web (INDISPONÍVEL ≠ irregular).",
        "reajuste": "Mantém o grau; recomenda diligência no edital."})


def test_pesquisar_persiste_e_grava_vault(mod):
    _seed_fornecedor(mod)
    res = asyncio.run(mod.pesquisar("12345678000190", gerar=_gerar_fake, osint_fn=_osint_fake))
    assert res["nome"] == "EMPRESA X"
    assert res["achados"][0]["veredito"] == "inconclusivo"
    assert res["reajuste"]
    # vault gravado
    assert res["vault_path"] and (mod.VAULT / "aprendizados").exists()
    txt = open(res["vault_path"], encoding="utf-8").read()
    assert "INCONCLUSIVO" in txt and "ai-first: true" in txt
    # DB persistido → surface lê
    p = mod.parecer_pesquisa("12.345.678/0001-90")  # tolera CNPJ formatado
    assert p and p["resumo"].startswith("Indício mantido")
    assert p["n_fontes"] == 1


def test_pesquisar_sem_duvidas_nao_fabrica(mod):
    _seed_fornecedor(mod, red_flags=[])  # sem red_flags e sem ficha → sem dúvidas
    res = asyncio.run(mod.pesquisar("12345678000190", gerar=_gerar_fake, osint_fn=_osint_fake))
    assert res["status"] == "sem_duvidas"
    assert mod.parecer_pesquisa("12345678000190") is None  # nada persistido


def test_pesquisar_llm_indisponivel_honesto(mod):
    _seed_fornecedor(mod)

    async def _gerar_quebra(messages):
        raise RuntimeError("429 limite")

    res = asyncio.run(mod.pesquisar("12345678000190", gerar=_gerar_quebra, osint_fn=_osint_fake))
    assert res["achados"] == []
    assert "indisponível" in res["resumo"].lower()
    # ainda persiste (a coleta valeu) e não inventa achados
    p = mod.parecer_pesquisa("12345678000190")
    assert p is not None and p["achados"] == []


def test_parecer_pesquisa_sem_tabela_retorna_none(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "DB", tmp_path / "vazio.db")
    sqlite3.connect(str(mod.DB)).close()
    assert mod.parecer_pesquisa("12345678000190") is None
