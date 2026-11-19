# -*- coding: utf-8 -*-
"""Disparo das coletas longas do SIAFE pelo despachante: janela livre, MFA só pelo fluxo do diário, sessão única."""
from datetime import datetime

from compliance_agent import siafe_agenda as A

DIA = datetime(2026, 11, 19, 10, 0)


def test_madrugada_e_do_diario_e_dos_crons():
    for h in (datetime(2026, 11, 19, 5, 0), datetime(2026, 11, 19, 23, 30), datetime(2026, 11, 19, 3, 15)):
        m, motivo = A.decidir("status", h, _logou=lambda a: True, _ocupado=lambda: None)
        assert m == 0 and "janela livre" in motivo


def test_orcamento_corta_no_fim_do_dia():
    assert A.minutos_livres(datetime(2026, 11, 19, 22, 30), 100) == 45
    assert A.minutos_livres(DIA, 80) == 80


def test_sem_login_do_diario_hoje_nao_dispara():
    m, motivo = A.decidir("documentos", DIA, _logou=lambda a: False, _ocupado=lambda: None)
    assert m == 0 and "MFA" in motivo


def test_siafe_ocupado_nao_dispara():
    m, motivo = A.decidir("documentos", DIA, _logou=lambda a: True, _ocupado=lambda: "lock do runner: diario")
    assert m == 0 and "ocupado" in motivo


def test_disparo_em_segundo_plano_grava_o_efeito(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "_REPO", tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(A, "decidir", lambda nome, agora: (80, None))
    chamado = {}

    class P:
        pid = 4242

    def popen(argv, **kw):
        chamado.update(argv=argv, kw=kw)
        return P()
    r = A.disparar("status", agora=DIA, _popen=popen)
    assert r["disparado"] and r["pid"] == 4242 and (tmp_path / "data" / "siafe_agenda_status.json").exists()
    assert chamado["argv"][:4] == ["timeout", "-k", "120", str(80 * 60 + 1800)]
    assert chamado["argv"][-2:] == ["--minutos", "80"]
    assert chamado["kw"]["close_fds"] is False and chamado["kw"]["start_new_session"] is True
