# -*- coding: utf-8 -*-
"""O SIAFE aceita UMA sessão por IP — a trava que impede a segunda máquina de derrubar a primeira.

FATO OPERACIONAL (dono, 2026-07-28): SIAFE-1 e SIAFE-2 só permitem login de um IP por vez, e a
segunda máquina não apenas falha — ela DERRUBA a sessão da primeira. Numa coleta noturna de
horas isso perde a janela inteira, e o sintoma chega como "coletou zero" no dia seguinte.

A restrição é invisível no código: com a carga sendo distribuída entre VM-1 e VM-2, um rsync do
repositório e um cron copiado bastam para quebrá-la. Regra que depende de alguém lembrar é regra
que vai ser esquecida — por isso virou trava.

O ponto delicado: **ausência de marcador é AUTORIZAÇÃO**, não bloqueio. Uma instalação nova não
pode ficar sem coletar por causa de um arquivo que ninguém criou ainda.
"""
from __future__ import annotations

import pytest

from compliance_agent import host_siafe as H


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "MARCADOR", tmp_path / ".siafe_host")
    return tmp_path


def test_sem_marcador_autoriza(isolar, monkeypatch):
    """Ausência não é proibição: instalação nova tem de conseguir coletar."""
    ok, motivo = H.pode_coletar()
    assert ok is True
    assert "nenhum host designado" in motivo


def test_host_designado_coleta(isolar, monkeypatch):
    monkeypatch.setattr(H, "host_atual", lambda: "jfn-core")
    H.designar("jfn-core")
    assert H.pode_coletar()[0] is True


def test_outra_maquina_e_bloqueada(isolar, monkeypatch):
    """O caso perigoso, e o único em que se bloqueia."""
    H.designar("jfn-core")
    monkeypatch.setattr(H, "host_atual", lambda: "JFN-Agent-2")
    ok, motivo = H.pode_coletar()
    assert ok is False
    assert "jfn-core" in motivo and "JFN-Agent-2" in motivo


def test_a_mensagem_explica_a_CONSEQUENCIA_nao_so_a_regra():
    """Quem lê o erro às 3h da manhã precisa saber o que aconteceria, não só que 'não pode'."""
    H.designar("jfn-core")
    import unittest.mock as m
    with m.patch.object(H, "host_atual", return_value="outra"):
        _, motivo = H.pode_coletar()
    assert "uma sessão por IP" in motivo
    assert "DERRUBARIA" in motivo
    assert "--designar" in motivo, "tem de dizer como transferir de propósito"


def test_exigir_autorizacao_levanta_na_maquina_errada(isolar, monkeypatch):
    H.designar("jfn-core")
    monkeypatch.setattr(H, "host_atual", lambda: "outra")
    with pytest.raises(RuntimeError, match="BLOQUEADA"):
        H.exigir_autorizacao()


def test_exigir_autorizacao_passa_no_host_certo(isolar, monkeypatch):
    monkeypatch.setattr(H, "host_atual", lambda: "jfn-core")
    H.designar()
    H.exigir_autorizacao()          # não levanta


def test_marcador_vazio_conta_como_ausente(isolar):
    (isolar / ".siafe_host").write_text("   \n")
    assert H.host_autorizado() is None
    assert H.pode_coletar()[0] is True
