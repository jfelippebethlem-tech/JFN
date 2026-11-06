# -*- coding: utf-8 -*-
"""Orçamento de DOCUMENTOS da cadeia de relacionados — o teto que faltava.

O `max_rel` limitava processos relacionados, não documentos, e um só relacionado pode trazer mil.
Medido na VM-2 em 2026-08-30: três processos de ~50 docs arrastaram cadeias de 948, 968 e 881
documentos (652 s, 588 s, 524 s) contra `timeout 900` do disparo — a máquina caiu de 21
processos/dia para ZERO.
"""
import asyncio

import pytest


class _FakePage:
    """Página que devolve N documentos por relacionado, sem browser."""

    def __init__(self, docs_por_proc):
        self.docs_por_proc = docs_por_proc
        self.frames = []
        self.visitados = []

    async def goto(self, url, **kw):
        self.visitados.append(url)

    async def wait_for_load_state(self, *a, **kw):
        pass

    async def wait_for_timeout(self, *a, **kw):
        pass


def _rodar(monkeypatch, docs_por_proc, n_rel, max_docs):
    from tools import sei_reader as R

    pg = _FakePage(docs_por_proc)
    monkeypatch.setattr(R, "_extrair_de_todos_frames",
                        lambda p: _corrotina({"texto": "x" * 100,
                                              "documentos": [{"i": i} for i in range(docs_por_proc)]}))
    monkeypatch.setattr(R, "eh_licitacao", lambda t: False)
    rel = [{"url": f"https://sei/x?id_procedimento={i}", "titulo": f"rel {i}"}
           for i in range(1, n_rel + 1)]
    return asyncio.run(R.seguir_relacionados(pg, "https://sei/base", rel, max_rel=15,
                                             max_docs_cadeia=max_docs))


async def _corrotina(v):
    return v


def test_para_ao_atingir_o_orcamento(monkeypatch):
    """Três relacionados de 400 docs com teto 300: só o primeiro é aberto."""
    cadeia = _rodar(monkeypatch, docs_por_proc=400, n_rel=3, max_docs=300)
    abertos = [c for c in cadeia if c.get("n_docs")]
    assert len(abertos) == 1, f"abriu {len(abertos)} relacionados apesar do teto"
    assert sum(c["n_docs"] for c in abertos) == 400


def test_corte_e_DECLARADO_nao_silencioso(monkeypatch):
    """Cadeia truncada não pode ser lida como cadeia completa — INDISPONÍVEL != 0."""
    cadeia = _rodar(monkeypatch, docs_por_proc=400, n_rel=3, max_docs=300)
    truncadas = [c for c in cadeia if c.get("truncada")]
    assert truncadas, "cortou em silêncio: nenhum item marcado como truncada"
    assert "orçamento" in truncadas[0]["motivo"]


def test_sem_teto_mantem_comportamento_antigo(monkeypatch):
    """`None` preserva o comportamento anterior — o teto é opt-in."""
    cadeia = _rodar(monkeypatch, docs_por_proc=400, n_rel=3, max_docs=None)
    assert len([c for c in cadeia if c.get("n_docs")]) == 3
    assert not [c for c in cadeia if c.get("truncada")]


def test_cadeia_pequena_passa_inteira(monkeypatch):
    """99% das cadeias têm menos de 300 docs: o teto não pode encurtá-las."""
    cadeia = _rodar(monkeypatch, docs_por_proc=20, n_rel=5, max_docs=300)
    assert len([c for c in cadeia if c.get("n_docs")]) == 5
    assert not [c for c in cadeia if c.get("truncada")]


def test_teto_do_sweep_vem_da_medicao():
    """300 preserva 99% das cadeias: mediana 19, p75 41, p90 65 em 3.156 processos."""
    from tools.sei_sweep import MAX_DOCS_CADEIA
    assert MAX_DOCS_CADEIA == 300
