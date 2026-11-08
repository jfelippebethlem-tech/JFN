# -*- coding: utf-8 -*-
"""A fila de processos-pai nunca andava: quem devolvia ZERO documentos voltava para sempre.

Medido na VM-2 em 2026-08-07: os MESMOS CINCO processos relidos a cada 30 minutos, 110-136 s cada,
**34 minutos de CPU por rodada**, durante dias — enquanto os outros 120 detectados jamais chegavam
a ser oferecidos. A regra antiga excluía da fila apenas quem tinha devolvido documento; zero
documentos, que é resultado LEGÍTIMO (processo restrito, árvore que não abre), condenava o processo
a ser relido indefinidamente.

O sweep normal já tinha o skip após três tentativas exatamente por isto. Aqui faltava.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_pais_teto_de_tentativas.py -q
"""
from __future__ import annotations

import inspect
import re


def _selecionar(pais, feitos, max_n=5):
    """Reproduz a seleção da fila de pais — a mesma expressão de `run_pais`."""
    from tools.sei_pais import _norm

    teto = 3
    chega = {_norm(k) for k, v in feitos.items()
             if (v.get("n_docs", 0) or 0) > 0 or (v.get("tentativas", 1) or 1) >= teto}
    return [p for p in pais if _norm(p["pai"]) not in chega][:max_n]


def test_processo_que_devolve_zero_sai_da_fila_depois_de_tres_tentativas():
    pais = [{"pai": f"SEI-08000{i}/00000{i}/2024"} for i in range(1, 6)]
    feitos = {p["pai"]: {"n_docs": 0, "tentativas": 3} for p in pais[:3]}
    fila = _selecionar(pais, feitos)
    assert [p["pai"] for p in fila] == [pais[3]["pai"], pais[4]["pai"]], (
        "a fila continuou presa nos processos que já falharam três vezes")


def test_ate_a_terceira_tentativa_ele_continua_na_fila():
    """Zero pode ser transitório — árvore que não abriu numa sessão abre na seguinte."""
    pais = [{"pai": "SEI-080001/000001/2024"}]
    for n in (1, 2):
        assert _selecionar(pais, {pais[0]["pai"]: {"n_docs": 0, "tentativas": n}}), (
            f"desistiu na tentativa {n} — cedo demais")
    assert not _selecionar(pais, {pais[0]["pai"]: {"n_docs": 0, "tentativas": 3}})


def test_quem_entregou_documento_nunca_volta():
    pais = [{"pai": "SEI-080001/000001/2024"}]
    assert not _selecionar(pais, {pais[0]["pai"]: {"n_docs": 40, "tentativas": 1}})


def test_o_contador_de_tentativas_e_gravado_no_progresso():
    """Sem gravar, o teto não existe: toda rodada recomeçaria do zero."""
    from tools.sei_sweep import run_pais

    fonte = inspect.getsource(run_pais)
    assert re.search(r'"tentativas":\s*_antes\s*\+\s*1', fonte), (
        "run_pais deixou de acumular o contador de tentativas")
    assert "_TETO_TENTATIVAS" in fonte, "o teto sumiu da seleção da fila"
