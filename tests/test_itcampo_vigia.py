"""Vigia do it-campo: só dispara com duas leituras ociosas seguidas e memória medida para o lote."""
from tools import itcampo_vigia as V


def _m(t, cpu, disp=8.0, ok=True):
    return {"t": f"2026-11-22 {t}:00", "ok": ok, "win_cpu": cpu, "wsl_disp_gb": disp}


def test_dispara_so_com_duas_ociosas_seguidas():
    assert V.decidir(_m("03:15", 30), _m("03:00", 30))["disparar"] is True
    assert V.decidir(_m("03:15", 30), _m("03:00", 70))["disparar"] is False      # a anterior estava ocupada
    assert V.decidir(_m("03:15", 70), _m("03:00", 30))["disparar"] is False      # a de agora está ocupada
    assert V.decidir(_m("03:15", 30), None)["disparar"] is False                 # 1ª leitura
    assert V.decidir(_m("03:45", 30), _m("03:00", 30))["disparar"] is False      # anterior velha (45 min)


def test_indisponivel_nunca_e_ocioso():
    assert V.decidir(_m("03:15", None, ok=False), _m("03:00", 30))["motivo"] == "sem medida"
    assert V.ociosa({"ok": True, "win_cpu": None, "wsl_cpu": None}) is False
    assert V.ociosa({"ok": True, "win_cpu": None, "wsl_cpu": 20}) is True        # sem a do Windows, vale a do WSL


def test_processos_cabem_na_memoria_medida():
    assert V.decidir(_m("03:15", 30, disp=4.0), _m("03:00", 30))["disparar"] is False   # < freio 3 + pico 1,5
    assert V.decidir(_m("03:15", 30, disp=4.6), _m("03:00", 30))["k"] == 1
    assert V.decidir(_m("03:15", 30, disp=7.6), _m("03:00", 30))["k"] == 3
    assert V.decidir(_m("03:15", 30, disp=19.0), _m("03:00", 30))["k"] == V.MAX_PROC
