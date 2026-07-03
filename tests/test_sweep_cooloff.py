# -*- coding: utf-8 -*-
"""Cooloff de janela do sei_sweep (fix constância 2026-07-03): falha recente não re-tenta na mesma janela."""
from datetime import datetime, timedelta

from tools.sei_sweep import _falha_recente


def _em(dt):
    return dt.isoformat(timespec="seconds")


def test_falha_recente_true_dentro_da_janela():
    f = {"n_docs": 0, "tentativas": 1, "em": _em(datetime.now() - timedelta(hours=1))}
    assert _falha_recente(f) is True


def test_falha_antiga_libera_retry():
    f = {"n_docs": 0, "tentativas": 2, "em": _em(datetime.now() - timedelta(hours=5))}
    assert _falha_recente(f) is False


def test_sucesso_nunca_entra_em_cooloff():
    f = {"n_docs": 8, "em": _em(datetime.now())}
    assert _falha_recente(f) is False


def test_sem_registro_ou_sem_em_nao_bloqueia():
    assert _falha_recente(None) is False
    assert _falha_recente({"n_docs": 0, "tentativas": 1}) is False
    assert _falha_recente({"n_docs": 0, "em": "lixo"}) is False
