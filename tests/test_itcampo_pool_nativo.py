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
    # 80% dos 24 núcleos ocupados por outros → sobram ~4,8 núcleos → 1 trabalhador de 4 threads
    assert P.alvo(disp_gb=P.PISO_GB + 20, cpu_outros=80, ncpu=24, vivos=0) == 1


def test_vivos_contam_na_memoria_ja_tomada():
    # com 2 vivos e memória exatamente no piso, fica nos 2 (não derruba nem sobe)
    assert P.alvo(disp_gb=P.PISO_GB, cpu_outros=10, ncpu=24, vivos=2) == 2


def test_pausa_so_com_dono_ativo_e_cpu_alta_ou_arquivo():
    assert P.deve_pausar(True, 9999, 0)
    assert P.deve_pausar(False, 10, P.CPU_PAUSA + 1)
    assert not P.deve_pausar(False, 10, P.CPU_PAUSA - 1), "dono ativo com CPU folgada: segue (prioridade IDLE)"
    assert not P.deve_pausar(False, P.OCIOSO_S + 1, 95), "dono ausente: CPU alta é a do próprio JFN, segue"
