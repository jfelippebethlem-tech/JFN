# -*- coding: utf-8 -*-
"""Duas máquinas capturando o SEI não podem pegar o MESMO processo.

O `sweep_sei.sh` já protege contra dois sweeps na mesma máquina (`pgrep` com o truque do
colchete). Entre máquinas não há nada: VM-1 e VM-2 puxam a fila do mesmo banco, veem a mesma
ordem e começariam pelo mesmo processo — dobrando o custo de browser e de sessão SEI para
entregar metade do resultado.

A divisão é determinística e sem coordenação: cada máquina fica com uma FATIA do hash do
número do processo. Sem lock distribuído, sem heartbeat, sem quem-fala-com-quem — duas
máquinas offline uma para a outra continuam sem colidir.

Medido em 2026-07-28: 45.939 processos no universo SIAFE, 2.007 com texto capturado, vazão de
102 processos/dia. Nessa vazão, uma máquina sozinha levaria ~430 dias.
"""
import pytest

from tools.sei_sweep import fatia_desta_maquina, na_minha_fatia


def test_processo_cai_sempre_na_mesma_fatia():
    """Determinístico: sem isso, um processo pularia de máquina a cada execução."""
    p = "SEI-070002/006145/2024"
    assert na_minha_fatia(p, 0, 2) == na_minha_fatia(p, 0, 2)


def test_as_fatias_sao_disjuntas_e_cobrem_tudo():
    procs = [f"SEI-0700{i:02d}/00{i:04d}/2025" for i in range(200)]
    f0 = [p for p in procs if na_minha_fatia(p, 0, 2)]
    f1 = [p for p in procs if na_minha_fatia(p, 1, 2)]
    assert not set(f0) & set(f1), "nenhum processo pode estar nas duas fatias"
    assert len(f0) + len(f1) == len(procs), "nenhum processo pode ficar de fora"


def test_a_divisao_e_equilibrada():
    """Fatia torta desperdiça a máquina ociosa — 40/60 já seria ruim em 43 mil processos."""
    procs = [f"SEI-0700{i:02d}/00{i:04d}/2025" for i in range(1000)]
    f0 = sum(1 for p in procs if na_minha_fatia(p, 0, 2))
    assert 400 <= f0 <= 600, f"desequilíbrio: {f0} de 1000 numa fatia de 1/2"


def test_uma_maquina_so_pega_tudo():
    """O padrão (1 fatia) não pode mudar o comportamento de quem nunca dividiu nada."""
    assert na_minha_fatia("SEI-070002/006145/2024", 0, 1)


@pytest.mark.parametrize("total,indice", [(2, 2), (2, -1), (0, 0)])
def test_configuracao_invalida_falha_alto(total, indice):
    """Errar a fatia em silêncio faria uma máquina varrer o vazio por dias."""
    with pytest.raises(ValueError):
        na_minha_fatia("SEI-070002/006145/2024", indice, total)


def test_fatia_vem_do_ambiente_e_o_padrao_e_maquina_unica(monkeypatch):
    monkeypatch.delenv("JFN_SWEEP_FATIA", raising=False)
    assert fatia_desta_maquina() == (0, 1)
    monkeypatch.setenv("JFN_SWEEP_FATIA", "1/2")
    assert fatia_desta_maquina() == (1, 2)


def test_fatia_malformada_no_ambiente_nao_vira_maquina_unica_silenciosa(monkeypatch):
    """Cair no padrão sob variável errada faria as duas máquinas varrerem tudo, duplicando."""
    monkeypatch.setenv("JFN_SWEEP_FATIA", "banana")
    with pytest.raises(ValueError):
        fatia_desta_maquina()
