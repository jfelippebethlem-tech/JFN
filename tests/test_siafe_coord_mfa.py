# -*- coding: utf-8 -*-
"""Portas do código MFA do SIAFE: set_mfa grava as duas que os coletores leem; o pedido aberto só vale
na janela e até chegar código (é o que autoriza o Yoda a aceitar um código solto)."""
import json

import pytest

import compliance_agent.siafe_coord as sc


@pytest.fixture
def portas(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "_MFA_FLAG", tmp_path / "siafe_mfa.json")
    monkeypatch.setattr(sc, "_MFA_PEDIDO", tmp_path / "siafe_mfa_pedido.json")
    monkeypatch.setattr(sc, "_MFA_CODE_FILE", tmp_path / ".mfa_code")
    return tmp_path


def test_set_mfa_grava_as_duas_portas(portas):
    sc.set_mfa(" 4ZuteXbN ")
    assert json.loads((portas / "siafe_mfa.json").read_text())["codigo"] == "4ZuteXbN"
    assert (portas / ".mfa_code").read_text() == "4ZuteXbN"
    assert sc.get_mfa() == "4ZuteXbN"


def test_sem_pedido_nao_ha_pedido_aberto(portas):
    assert sc.pedido_mfa_aberto() is False


def test_pedido_abre_e_fecha_quando_chega_codigo(portas, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(sc.time, "time", lambda: t[0])
    sc.marcar_pedido_mfa()
    t[0] += 30
    assert sc.pedido_mfa_aberto() is True
    sc.set_mfa("123456")
    assert sc.pedido_mfa_aberto() is False


def test_pedido_expira_na_janela(portas, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(sc.time, "time", lambda: t[0])
    sc.marcar_pedido_mfa()
    t[0] += 901
    assert sc.pedido_mfa_aberto(janela_s=900) is False
