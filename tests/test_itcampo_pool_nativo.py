"""Pool NATIVO do Windows no it-campo (19/11/2026): quantos trabalhadores cabem e quando pausa.

Regra do dono: aproveitar a máquina "sem quebrar ela" — o Windows nunca fica abaixo do PISO de memória disponível
(uso humano) e o pool cede a CPU quando o dono está usando a máquina e outra coisa já ocupa a CPU."""
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("psutil")
_ARQ = Path(__file__).resolve().parents[1] / "deploy" / "itcampo" / "nativo" / "pool_nativo.py"
_spec = importlib.util.spec_from_file_location("pool_nativo", _ARQ)
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)


def test_memoria_abaixo_do_piso_nao_lanca_nenhum():
    assert P.alvo(disp_gb=P.PISO_GB + 1.0, cpu_outros=5, ncpu=24, vivos=0) == 0


def test_memoria_e_cpu_folgadas_respeitam_o_teto():
    assert P.alvo(disp_gb=P.PISO_GB + 20, cpu_outros=0, ncpu=24, vivos=0) == P.MAX_TRAB


def test_cpu_ocupada_por_outros_limita():
    # 70% dos 24 núcleos ocupados por outros → sobram ~7,2 núcleos → 1 trabalhador (THREADS por trabalhador)
    assert P.alvo(disp_gb=P.PISO_GB + 20, cpu_outros=70, ncpu=24, vivos=0) == int(7.2 // P.THREADS)
    assert P.alvo(disp_gb=P.PISO_GB + 20, cpu_outros=95, ncpu=24, vivos=0) == 0


def test_vivos_contam_na_memoria_ja_tomada():
    # com 2 vivos e memória exatamente no piso, fica nos 2 (não derruba nem sobe)
    assert P.alvo(disp_gb=P.PISO_GB, cpu_outros=10, ncpu=24, vivos=2) == 2


def test_pausa_so_com_dono_ativo_e_cpu_alta_ou_arquivo():
    assert P.deve_pausar(True, 9999, 0)
    assert P.deve_pausar(False, 10, P.CPU_PAUSA + 1)
    assert not P.deve_pausar(False, 10, P.CPU_PAUSA - 1), "dono ativo com CPU folgada: segue (prioridade IDLE)"
    assert not P.deve_pausar(False, P.OCIOSO_S + 1, 95), "dono ausente: CPU alta é a do próprio JFN, segue"


def test_piso_desce_so_com_o_dono_ausente():
    assert P.piso(P.AUSENTE_S + 1) == P.PISO_AUSENTE_GB < P.PISO_GB
    assert P.piso(60) == P.PISO_GB
    # 5,7 GB disponíveis (medido 19/11 10h28): dono presente → 0; ausente → cabe trabalho
    assert P.alvo(5.7, 16, 24, 0, P.piso(60)) == 0
    assert P.alvo(5.7, 16, 24, 0, P.piso(P.AUSENTE_S + 1)) >= 1
