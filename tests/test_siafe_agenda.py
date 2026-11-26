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


def test_no_fluxo_espera_a_coleta_no_proprio_grupo(tmp_path, monkeypatch):
    """O9.0 frente B: pelo motor (`--esperar`) a coleta NÃO é destacada — fica no grupo/teto do job e segura o slot
    `siafe_sessao` até o fim; antes o job saía em segundos e a coleta de 80–130 min seguia órfã, fora da reserva."""
    monkeypatch.setattr(A, "_REPO", tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(A, "decidir", lambda nome, agora: (80, None))
    chamado = {}

    class P:
        pid = 4243

        def wait(self):
            chamado["esperou"] = True
            return 7

    def popen(argv, **kw):
        chamado.update(argv=argv, kw=kw)
        return P()
    r = A.disparar("documentos", agora=DIA, _popen=popen, esperar=True)
    assert chamado["esperou"] and r["rc"] == 7 and r["esperou"] is True
    assert chamado["kw"].get("start_new_session", False) is False
    assert chamado["argv"][:4] == ["timeout", "-k", "120", str(80 * 60 + 1800)]


def test_main_esperar_devolve_o_rc_da_coleta(monkeypatch):
    import sys
    from compliance_agent import host_siafe
    monkeypatch.setattr(host_siafe, "exigir_autorizacao", lambda: None)
    vistos = {}
    monkeypatch.setattr(A, "disparar", lambda nome, esperar=False: vistos.update(nome=nome, esperar=esperar)
                        or {"tarefa": nome, "rc": 3, "esperou": esperar})
    monkeypatch.setattr(sys, "argv", ["siafe_agenda", "status", "--esperar"])
    try:
        A.main()
        rc = 0
    except SystemExit as e:
        rc = e.code
    assert vistos == {"nome": "status", "esperar": True} and rc == 3
