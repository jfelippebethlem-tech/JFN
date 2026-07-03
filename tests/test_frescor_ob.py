# -*- coding: utf-8 -*-
"""Frescor por OB (2026-07-03): OB nova no SIAFE 1/2 → processo SEI andou → re-ler."""
from tools.sei_sweep import _iso, _ob_desatualizada


def test_iso_tfe_e_siafe():
    assert _iso("2024-01-15") == "2024-01-15"
    assert _iso("27/02/2026") == "2026-02-27"
    assert _iso("") == "" and _iso("lixo") == ""


def test_ob_nova_dispara_releitura():
    # OB de 2026-03 depois de leitura em 2026-01 → re-ler
    assert _ob_desatualizada("2026-03-01", "2026-01-10T02:00:00") is True


def test_ob_antiga_nao_dispara():
    assert _ob_desatualizada("2024-05-01", "2026-07-02T01:00:00") is False


def test_mesmo_dia_nao_dispara():
    # OB no mesmo dia da leitura → não re-ler (>, não >=)
    assert _ob_desatualizada("2026-07-02", "2026-07-02T09:00:00") is False


def test_faltando_dado_nao_dispara():
    assert _ob_desatualizada("", "2026-01-01") is False
    assert _ob_desatualizada("2026-05-01", "") is False
