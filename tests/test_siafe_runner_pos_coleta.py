# -*- coding: utf-8 -*-
"""Pós-coleta do diário do SIAFE: recoleta de status das OBs intermediárias e Guias de Devolução, na MESMA janela
de sessão do diário (só roda depois de um login que deu certo — nunca pede MFA a ninguém de madrugada)."""
import asyncio

from compliance_agent import siafe_runner as R


def test_pos_coleta_roda_status_e_gd_com_prazo_comum(monkeypatch):
    vistos = {}

    async def status(ano, max_dias, prazo):
        vistos["status"] = (ano, max_dias, prazo)
        return {"ok": True, "dias": [{"data": "01/09/2026"}], "viraram_erro_no_pagamento": 2}

    async def gd(ano, max_ugs, ate):
        vistos["gd"] = (ano, max_ugs, ate)
        return {"ok": True, "ugs": [{"ug": "100100", "ingeridas": 7}]}
    monkeypatch.delenv("JFN_SIAFE_POS_DIARIO", raising=False)
    r = asyncio.run(R.pos_coleta(2026, minutos=40, _status=status, _gd=gd, _relogio=lambda: 1_000.0))
    assert vistos["status"] == (2026, R.POS_MAX_DIAS, 1_000.0 + 40 * 60)
    assert vistos["gd"][0:2] == (2026, R.POS_MAX_UGS_GD) and "T" in vistos["gd"][2]
    assert r["status"]["viraram_erro_no_pagamento"] == 2 and r["gd"]["ugs"][0]["ingeridas"] == 7


def test_pos_coleta_desligavel_e_erro_de_uma_etapa_nao_derruba_a_outra(monkeypatch):
    async def quebra(*a):
        raise TimeoutError("browser_lock")

    async def gd(*a):
        return {"ok": True, "ugs": []}
    monkeypatch.setenv("JFN_SIAFE_POS_DIARIO", "0")
    assert asyncio.run(R.pos_coleta(2026, _status=quebra, _gd=gd)) == {"ok": True, "pulado": "JFN_SIAFE_POS_DIARIO=0"}
    monkeypatch.delenv("JFN_SIAFE_POS_DIARIO")
    r = asyncio.run(R.pos_coleta(2026, _status=quebra, _gd=gd))
    assert r["status"]["ok"] is False and "TimeoutError" in r["status"]["erro"]
    assert r["gd"] == {"ok": True, "ugs": []}
