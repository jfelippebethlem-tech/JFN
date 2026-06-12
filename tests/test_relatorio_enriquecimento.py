# -*- coding: utf-8 -*-
"""
Testes do ENRIQUECIMENTO do relatório de fornecedor (P1.1 do QA):
timeout ampliado (~90s) + retry com backoff + cache por CNPJ (TTL 7 dias).

Tudo STUBADO (sem rede): substituímos `relatorio_riscos.gerar_relatorio_risco` por um fake controlável
e validamos o comportamento de cache/retry/timeout de forma determinística.

Como rodar:
    cd ~/JFN && .venv/bin/python -m pytest tests/test_relatorio_enriquecimento.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from compliance_agent.reporting import inteligencia as I  # noqa: E402
from relatorio_riscos.collectors import cache as _cache  # noqa: E402

CNPJ = "19088605000104"


@pytest.fixture
def cache_isolado(tmp_path, monkeypatch):
    """Aponta o cache do enriquecimento para um SQLite temporário e o limpa."""
    monkeypatch.setattr(_cache, "_CACHE_PATH", tmp_path / "coleta_cache.db")
    yield


@pytest.fixture(autouse=True)
def backoff_rapido(monkeypatch):
    """Backoff de 0s para os testes não pendurarem (validamos a CONTAGEM de tentativas, não o tempo)."""
    monkeypatch.setattr(I, "_ENRIQUECE_BACKOFF", 0.0)


def _stub_gerar(monkeypatch, fn):
    """Substitui a função importada DENTRO de _enriquecer (import local `from relatorio_riscos import ...`)."""
    import relatorio_riscos
    monkeypatch.setattr(relatorio_riscos, "gerar_relatorio_risco", fn, raising=True)


# ───────────────────────────── configuração ─────────────────────────────

def test_timeout_default_ampliado():
    # P1.1: subiu de 35s para ~90s (o relatório é assíncrono/push, pode esperar mais p/ §5/§6 popularem).
    assert I._ENRIQUECE_TIMEOUT >= 90
    assert I._ENRIQUECE_TENTATIVAS >= 2


# ───────────────────────────── retry com backoff ─────────────────────────────

def test_retry_em_timeout_e_depois_sucesso(cache_isolado, monkeypatch):
    """Primeira tentativa estoura timeout; a segunda devolve REAL. Deve retornar REAL (1 retry)."""
    chamadas = {"n": 0}

    async def fake(cnpj, **kw):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise asyncio.TimeoutError()
        return {"ok": True, "empresa": "ALVO", "score": 10, "risco": "BAIXO"}

    _stub_gerar(monkeypatch, fake)
    monkeypatch.setattr(I, "_ENRIQUECE_TENTATIVAS", 2)
    res = asyncio.run(I._enriquecer(CNPJ))
    assert res["ok"] is True
    assert res["_fonte"] == "REAL"
    assert chamadas["n"] == 2  # tentou de novo após o timeout


def test_degrada_honesto_apos_esgotar_tentativas(cache_isolado, monkeypatch):
    """Todas as tentativas falham → INDISPONÍVEL (nunca inventa) e tentou _ENRIQUECE_TENTATIVAS vezes."""
    chamadas = {"n": 0}

    async def fake(cnpj, **kw):
        chamadas["n"] += 1
        raise asyncio.TimeoutError()

    _stub_gerar(monkeypatch, fake)
    monkeypatch.setattr(I, "_ENRIQUECE_TENTATIVAS", 2)
    res = asyncio.run(I._enriquecer(CNPJ))
    assert res["ok"] is False
    assert res["_fonte"] == "INDISPONIVEL"
    assert "timeout" in res["_motivo"]
    assert chamadas["n"] == 2


def test_erro_deterministico_nao_retenta(cache_isolado, monkeypatch):
    """ok=False com erro (ex.: CNPJ inválido) é determinístico — não adianta repetir (1 chamada só)."""
    chamadas = {"n": 0}

    async def fake(cnpj, **kw):
        chamadas["n"] += 1
        return {"ok": False, "erro": "CNPJ inválido"}

    _stub_gerar(monkeypatch, fake)
    monkeypatch.setattr(I, "_ENRIQUECE_TENTATIVAS", 3)
    res = asyncio.run(I._enriquecer(CNPJ))
    assert res["ok"] is False
    assert res["_fonte"] == "INDISPONIVEL"
    assert chamadas["n"] == 1  # não retentou erro determinístico


# ───────────────────────────── cache por CNPJ (TTL 7 dias) ─────────────────────────────

def test_cache_evita_segundo_egress(cache_isolado, monkeypatch):
    """Primeira chamada bate no upstream e cacheia; a segunda serve do cache SEM novo egress."""
    chamadas = {"n": 0}

    async def fake(cnpj, **kw):
        chamadas["n"] += 1
        return {"ok": True, "empresa": "ALVO", "score": 42, "risco": "MÉDIO"}

    _stub_gerar(monkeypatch, fake)
    monkeypatch.setattr(I, "_ENRIQUECE_CACHE_TTL", 7 * 86400)

    r1 = asyncio.run(I._enriquecer(CNPJ))
    assert r1["_fonte"] == "REAL" and chamadas["n"] == 1
    r2 = asyncio.run(I._enriquecer(CNPJ))
    assert r2["_fonte"] == "CACHE"  # servido do cache (REAL, transparente)
    assert r2["score"] == 42
    assert chamadas["n"] == 1  # NÃO repetiu o egress


def test_falha_nao_e_cacheada(cache_isolado, monkeypatch):
    """Falha transitória NUNCA é cacheada por 7 dias — o próximo relatório tenta de novo (e pode dar REAL)."""
    estado = {"n": 0}

    async def fake(cnpj, **kw):
        estado["n"] += 1
        if estado["n"] <= 2:  # esgota as 2 tentativas da 1ª chamada
            raise asyncio.TimeoutError()
        return {"ok": True, "empresa": "ALVO", "score": 5, "risco": "BAIXO"}

    _stub_gerar(monkeypatch, fake)
    monkeypatch.setattr(I, "_ENRIQUECE_TENTATIVAS", 2)
    monkeypatch.setattr(I, "_ENRIQUECE_CACHE_TTL", 7 * 86400)

    r1 = asyncio.run(I._enriquecer(CNPJ))
    assert r1["_fonte"] == "INDISPONIVEL"  # falhou e NÃO cacheou
    r2 = asyncio.run(I._enriquecer(CNPJ))
    assert r2["_fonte"] == "REAL"  # tentou de novo e agora deu certo


def test_cache_desligado_quando_ttl_zero(cache_isolado, monkeypatch):
    """TTL=0 desliga o cache (testes determinísticos): cada chamada bate no upstream."""
    chamadas = {"n": 0}

    async def fake(cnpj, **kw):
        chamadas["n"] += 1
        return {"ok": True, "empresa": "ALVO", "score": 1, "risco": "BAIXO"}

    _stub_gerar(monkeypatch, fake)
    monkeypatch.setattr(I, "_ENRIQUECE_CACHE_TTL", 0)

    asyncio.run(I._enriquecer(CNPJ))
    asyncio.run(I._enriquecer(CNPJ))
    assert chamadas["n"] == 2  # sem cache, dois egress
