from tools.sei_sweep import max_recaptura_adaptativo


def _r(i, antes, depois):
    return {"antes": antes, "depois": depois, "em": f"2026-11-{i:02d}T10:00:00"}


def test_rendimento_baixo_cede_o_slot_mas_segue_sondando():
    feitos = {str(i): _r(1 + i % 28, 40, 40) for i in range(30)}
    feitos["x"] = _r(29, 40, 45)                      # 1 ganho em 30 = 3% < 15%
    assert max_recaptura_adaptativo(feitos, 5) == 1


def test_rendimento_bom_ou_historico_curto_mantem_o_maximo():
    bons = {str(i): _r(1 + i % 28, 10, 20 if i % 2 else 10) for i in range(30)}   # 50% ganham
    assert max_recaptura_adaptativo(bons, 5) == 5
    assert max_recaptura_adaptativo({"a": _r(1, 1, 1)}, 5) == 5                   # poucos registros: não julga
