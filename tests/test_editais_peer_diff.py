# -*- coding: utf-8 -*-
"""T5 — peer-diff (raridade no grupo × força E7)."""
from compliance_agent.editais import peer_diff


def test_raridade():
    # 'X' aparece em 1 de 4 editais → raridade 0.75
    clau = [("e1", "X"), ("e2", "Y"), ("e3", "Y"), ("e4", "Y")]
    assert peer_diff.raridade("X", clau) == 0.75
    assert peer_diff.raridade("Y", clau) == 0.25


def test_forca_e7_por_subtipo():
    nivel, sumula = peer_diff.forca_e7("marca")
    assert nivel == "forte" and "270" in sumula
    nivel2, _ = peer_diff.forca_e7("indices")
    assert nivel2 == "medio"
    nivel3, _ = peer_diff.forca_e7("desconhecido")
    assert nivel3 == "fraco"


def test_score_candidatura():
    # rara (0.75) × forte (1.0) = 0.75
    assert abs(peer_diff._score(0.75, "forte") - 0.75) < 1e-9
    assert abs(peer_diff._score(0.75, "medio") - 0.45) < 1e-9
