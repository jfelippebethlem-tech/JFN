# -*- coding: utf-8 -*-
"""Lane da varredura SEI não dispara Python quando não há alvo.

Laudo dos motores (13/11/2026): 4 fatias × 144 disparos = ~576 processos Python por dia, e 168
das últimas 400 linhas do log eram `resumo: {}` — a fatia acordava, montava a fila (varre o
acervo inteiro) e saía sem nada para ler. A fila depende do ritmo da captura, que é lento.

Conserto: quando a fila INTEIRA (antes de fatiar) está vazia, o leitor deixa uma marca; o lane
não dispara enquanto a marca for recente. Havendo alvo, a marca sai. Critério do laudo: menos de
50 disparos Python por dia ociosos, sem perder `lido_em` por dia.
"""
import os
import time
from pathlib import Path

from tools import sei_leitura_dupla as V

LANE = Path(__file__).resolve().parents[1] / "tools" / "varredura_sei_lane.sh"


def test_fila_vazia_deixa_marca(tmp_path):
    marca = tmp_path / ".varredura_sei.sem_alvo"
    V._marcar_sem_alvo(True, marca)
    assert marca.exists()


def test_fila_com_alvo_tira_a_marca(tmp_path):
    marca = tmp_path / ".varredura_sei.sem_alvo"
    marca.touch()
    V._marcar_sem_alvo(False, marca)
    assert not marca.exists()


def test_tirar_marca_inexistente_nao_quebra(tmp_path):
    V._marcar_sem_alvo(False, tmp_path / "nada")


def test_lane_consulta_a_marca_antes_de_disparar():
    src = LANE.read_text(encoding="utf-8")
    i_marca = src.find("find data/.varredura_sei.sem_alvo -mmin")
    i_python = src.find("python -u -m tools.sei_leitura_dupla")
    assert 0 < i_marca < i_python, "o lane tem de olhar a marca ANTES de lançar as fatias"


def test_marca_e_a_mesma_dos_dois_lados():
    assert V._MARCA_SEM_ALVO.name in LANE.read_text(encoding="utf-8")
