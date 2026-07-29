# -*- coding: utf-8 -*-
"""Sincronia entre REGISTRO, PESOS_DETECTOR e o catálogo de vícios.

TRÊS DESALINHAMENTOS MEDIDOS EM 2026-07-29, todos silenciosos:

  1. **Sete detectores existiam e o catálogo não os conhecia** — o C8 (servidor no QSA) e os seis de
     aditivo, X7 a X12, construídos na sessão anterior sem o vício correspondente. O efeito é o pior
     possível num catálogo: ele SUBESTIMAVA a própria cobertura, e `lacunas()` mandava construir o
     que já existia. `validar()` só cobrava a direção contrária ("coberto sem detector").
  2. **Quatro detectores não tinham peso**, e `score_processo` cai no default 0,6. `C7` (sancionada
     contratada) e `P6` (contratação direta indevida) são da família `violacao_legal`, peso 1,0:
     o score subestimava os **dois sinais mais graves do sistema**. `C` (empresa-fachada) perdia
     0,8 para 0,6.
  3. Detector alcançável só pelo REGISTRO, fora de qualquer runner por fase — quem chama
     `rodar_*` nunca o executa.

Nada disso aparece em revisão de código: são três listas que precisam concordar, e listas paralelas
divergem. O mesmo mecanismo que produziu nove cópias da constante de teto de dispensa.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detectores_sincronia.py -q
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores import PESOS_DETECTOR, REGISTRO
from compliance_agent.detectores.base import PESOS_FAMILIA
from compliance_agent.knowledge.catalogo_vicios import CATALOGO, validar

# Sub-ids emitidos por `CFachada.avaliar_todos` — não são ids do REGISTRO, mas chegam ao
# `score_processo` como `ResultadoDetector.detector` e portanto precisam de peso próprio.
_SUB_IDS_DA_FAMILIA_C = {"C1", "C2", "C3/C5", "C4"}


def test_todo_detector_do_registro_tem_peso():
    """Peso ausente não dá erro: cai no default 0,6, e o score sai menor sem ninguém ver."""
    faltando = sorted(set(REGISTRO) - set(PESOS_DETECTOR))
    assert not faltando, (
        f"detector sem peso (cai no default 0.6 de `score_processo`): {faltando}"
    )


def test_peso_bate_com_a_familia_do_detector():
    """Divergência entre peso e família é decisão editorial e tem de ser explícita — não pode nascer
    de esquecimento."""
    divergentes = []
    for det_id, det in REGISTRO.items():
        esperado = PESOS_FAMILIA.get(det.familia)
        if esperado is not None and PESOS_DETECTOR[det_id] != esperado:
            divergentes.append(f"{det_id}: {PESOS_DETECTOR[det_id]} != família {det.familia} "
                               f"({esperado})")
    assert not divergentes, (
        "peso divergente da família sem justificativa no código:\n  " + "\n  ".join(divergentes)
    )


def test_peso_dos_dois_sinais_mais_graves():
    """Trava explícita no que a dessincronia estragava: contratar sancionada e contratar sem
    licitação são violação legal, peso 1,0 — não 0,6."""
    assert PESOS_DETECTOR["C7"] == pytest.approx(1.0), "sancionada contratada voltou a pesar menos"
    assert PESOS_DETECTOR["P6"] == pytest.approx(1.0), "direta indevida voltou a pesar menos"
    assert PESOS_DETECTOR["C"] == pytest.approx(0.8), "empresa-fachada voltou a pesar menos"


def test_sub_ids_da_familia_c_tem_peso():
    """`avaliar_todos` emite C1/C2/C3-5/C4 como `detector`; sem peso, o achado de fachada mais
    específico pesaria menos que a família-mãe."""
    faltando = sorted(_SUB_IDS_DA_FAMILIA_C - set(PESOS_DETECTOR))
    assert not faltando, f"sub-id da família C sem peso: {faltando}"


def test_catalogo_conhece_todo_detector():
    """A checagem inversa: detector que existe e nenhum vício aponta. Sem ela, o catálogo
    subestima a cobertura e manda construir o que já está construído."""
    apontados = {d for v in CATALOGO for d in v.detectores}
    orfaos = sorted(set(REGISTRO) - apontados)
    assert not orfaos, (
        "detector no REGISTRO que nenhum vício do catálogo aponta — catalogue o vício:\n  "
        + "\n  ".join(f"{d} — {REGISTRO[d].nome}" for d in orfaos)
    )


def test_catalogo_integro():
    """`validar()` confere todo ponteiro do catálogo contra os acervos reais."""
    assert validar() == []


def test_todo_detector_e_alcancavel_por_algum_runner():
    """Detector fora de todo runner por fase existe e nunca roda para quem chama `rodar_*`.

    Os alcançáveis por FAMÍLIA (e não por id) contam: `rodar_fornecedor` filtra
    `familia == "preco"`, e `CFachada.avaliar_todos` é chamado à parte por ser multi-resultado.
    """
    from pathlib import Path

    fonte = (Path(__file__).resolve().parent.parent
             / "compliance_agent" / "detectores" / "__init__.py").read_text()
    corpo_runners = fonte.split("def rodar_orgao", 1)[-1]

    inalcancaveis = []
    for det_id, det in REGISTRO.items():
        if f'"{det_id}"' in corpo_runners or f"'{det_id}'" in corpo_runners:
            continue
        if f'"{det.familia}"' in corpo_runners:      # alcançado por família
            continue
        if det_id == "C":                            # multi-resultado, chamado à parte
            continue
        inalcancaveis.append(f"{det_id} — {det.nome} (família {det.familia})")
    assert not inalcancaveis, (
        "detector fora de todo runner por fase — existe e nunca roda:\n  "
        + "\n  ".join(inalcancaveis)
    )
