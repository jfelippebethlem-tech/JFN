# -*- coding: utf-8 -*-
"""MFA do SIAFE: aviso ao dono ANTES do disparo e retentativa só em horário em que ele responde.

Laudo de motores 13/11/2026 (4.5): o diário das 05:00 espera 15 min pelo código MFA via Telegram;
sem resposta (o dono dorme), o dia fica sem OB — falhou em 10, 12 e 13/11. As retentativas do remédio
automático também disparavam de madrugada, pedindo código a ninguém.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from compliance_agent import siafe_runner as R

HOJE_10H = datetime(2026, 11, 13, 10, 0)


def _ultimo(tmp_path, monkeypatch, **campos):
    monkeypatch.setattr(R, "ULTIMO", tmp_path / "ultimo.json")
    if campos:
        R.ULTIMO.write_text(json.dumps(campos))


def test_falha_de_mfa_de_madrugada_retenta_de_dia(tmp_path, monkeypatch):
    _ultimo(tmp_path, monkeypatch, ok=False, erro="mfa_sem_codigo", iso="2026-11-13T08:15:30+00:00",
            ultimo_ok_iso="2026-11-11T08:02:38+00:00")
    assert R.decidir_retentativa(HOJE_10H) == (True, "")


def test_nao_retenta_de_madrugada(tmp_path, monkeypatch):
    _ultimo(tmp_path, monkeypatch, ok=False, erro="mfa_sem_codigo", ultimo_ok_iso="2026-11-11T08:02:38+00:00")
    pode, motivo = R.decidir_retentativa(datetime(2026, 11, 13, 3, 40))
    assert pode is False and "horário" in motivo


def test_nao_retenta_se_o_diario_de_hoje_ja_deu_certo(tmp_path, monkeypatch):
    ok_hoje = datetime(2026, 11, 13, 5, 14).astimezone().astimezone(timezone.utc).isoformat()
    _ultimo(tmp_path, monkeypatch, ok=True, ultimo_ok_iso=ok_hoje, ultimo_efeito_iso=ok_hoje)
    pode, motivo = R.decidir_retentativa(HOJE_10H)
    assert pode is False and "hoje" in motivo


def test_senha_recusada_nao_retenta(tmp_path, monkeypatch):
    """Rodar de novo com senha errada é mais um login recusado — o caminho do bloqueio da conta."""
    _ultimo(tmp_path, monkeypatch, ok=False, erro="senha_incorreta", ultimo_ok_iso="2026-11-11T08:02:38+00:00")
    pode, motivo = R.decidir_retentativa(HOJE_10H)
    assert pode is False and "senha" in motivo


def test_aviso_sai_antes_do_disparo(tmp_path, monkeypatch):
    _ultimo(tmp_path, monkeypatch, ok=False, erro="mfa_sem_codigo", ultimo_ok_iso="2026-11-11T08:02:38+00:00")
    ordem = []
    from compliance_agent import siafe_coord
    monkeypatch.setattr(siafe_coord, "notificar", lambda t: ordem.append(("aviso", t)) or True)

    async def _diario(exercicio=None, maxn=1000):
        ordem.append(("diario", None))
        return {"ok": True}

    async def _dorme(s):
        ordem.append(("espera", s))
    monkeypatch.setattr(R, "atualizar_diario", _diario)
    r = asyncio.run(R.retentar(antecedencia_min=10, _sleep=_dorme, _agora=lambda: HOJE_10H))
    assert [o[0] for o in ordem] == ["aviso", "espera", "diario"] and ordem[1][1] == 600
    assert "10 min" in ordem[0][1] and "código" in ordem[0][1]
    assert r["ok"] is True


def test_retentativa_pulada_nao_avisa_nem_dispara(tmp_path, monkeypatch):
    _ultimo(tmp_path, monkeypatch, ok=False, erro="mfa_sem_codigo", ultimo_ok_iso="2026-11-11T08:02:38+00:00")
    from compliance_agent import siafe_coord
    avisos = []
    monkeypatch.setattr(siafe_coord, "notificar", lambda t: avisos.append(t) or True)

    async def _diario(exercicio=None, maxn=1000):
        raise AssertionError("não devia disparar")
    monkeypatch.setattr(R, "atualizar_diario", _diario)
    r = asyncio.run(R.retentar(_sleep=None, _agora=lambda: datetime(2026, 11, 13, 2, 0)))
    assert r["pulado"] and avisos == []
