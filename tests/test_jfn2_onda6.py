# -*- coding: utf-8 -*-
"""Testes da Onda 6 (Radar 24/7): watchlist, alertas idempotentes, ciclo de vigilância."""
from __future__ import annotations

import pytest


@pytest.fixture
def radar(tmp_path, monkeypatch):
    from compliance_agent import radar as R
    monkeypatch.setattr(R, "_DB", tmp_path / "r.db")
    return R


def test_vigiar_e_status(radar):
    r = radar.vigiar("11111111000111", "cnpj")
    assert r["ok"] is True and r["total_watchlist"] == 1
    radar.vigiar("270042", "ug")
    st = radar.status()
    alvos = {w["alvo"] for w in st["watchlist"]}
    assert "11111111000111" in alvos and "270042" in alvos


def test_vigiar_tipo_invalido(radar):
    assert radar.vigiar("x", "tipo_errado")["ok"] is False
    assert radar.vigiar("", "cnpj")["ok"] is False


def test_vigiar_idempotente(radar):
    radar.vigiar("11111111000111", "cnpj")
    r2 = radar.vigiar("11111111000111", "cnpj")  # mesmo alvo
    assert r2["total_watchlist"] == 1  # não duplica


def test_alerta_idempotente(radar):
    assert radar._registrar_alerta("a", "cnpj", "motivo", "ref1", "alta") is True
    assert radar._registrar_alerta("a", "cnpj", "motivo", "ref1", "alta") is False  # repetido
    assert len(radar.alertas_recentes()) == 1


def test_parar_de_vigiar(radar):
    radar.vigiar("11111111000111", "cnpj")
    radar.parar_de_vigiar("11111111000111", "cnpj")
    assert radar.listar_watch() == []


def test_ciclo_gera_alerta_de_edital_aberto_restritivo(radar, monkeypatch):
    """Ciclo: edital ABERTO com red flag → alerta novo (sem rede; sem Telegram)."""
    import asyncio

    from compliance_agent.collectors import pncp

    async def fake_abertos(*a, **k):
        return [{"id_pncp": "X/2025", "objeto": "obra", "data_encerramento": "2026-06-20", "link": "u"}]

    async def fake_docs(ref, *a, **k):
        # texto com marca sem 'ou equivalente' => R7
        return [{"texto": "Pregão. Exige marca ABC e atestado de capacidade técnica."}]

    monkeypatch.setattr(pncp, "buscar_contratacoes", fake_abertos)
    monkeypatch.setattr(pncp, "baixar_documentos", fake_docs)
    monkeypatch.setattr(radar, "_avisar_telegram", lambda *_: None)

    radar.vigiar("270042", "ug")
    out = asyncio.run(radar.ciclo(avisar=False))
    assert out["ok"] is True and out["n"] >= 1
    assert any("R7" in a["motivo"] for a in out["novos_alertas"])
    # 2ª rodada não re-alerta o mesmo (idempotente)
    out2 = asyncio.run(radar.ciclo(avisar=False))
    assert out2["n"] == 0


def test_capabilities_radar_pronto():
    from compliance_agent.skilltree import SkillTree

    st = SkillTree()
    st.reload()
    for cid in ("vigiar", "radar_status"):
        cap = st.capacidades.get(cid)
        assert cap is not None and cap["status"] == "PRONTO"
    assert st.validate() == []
