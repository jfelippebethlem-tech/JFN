# -*- coding: utf-8 -*-
"""diario_de_obra_copiado — Hydra (SEI-070002/026015/2024, docs 381 × 397)."""
from compliance_agent.padroes.diario_de_obra_copiado import contencao, datas_canonicas, local, preparar

ATIV = ("Escavação manual de vala na margem esquerda trecho {i} com remoção de entulho e lançamento em caçamba "
        "estacionada na rua Euclydes de Oliveira próximo ao número {i}; equipe de {i} ajudantes e um encarregado.")


def _rdo(datas, fmt):
    return "\n".join(f"RELATORIO DIÁRIO DE OBRA (RDO)\nData\n{fmt(d)}\n" + ATIV.format(i=d) for d in datas)


def test_positivo_mesmo_rdo_em_formatos_de_data_diferentes():
    a = preparar(_rdo(range(1, 31), lambda d: f"{d}/11/25"))
    b = preparar(_rdo(range(1, 31), lambda d: f"{d:02d}/11/2025"))
    assert a and b and contencao(a["sh"], b["sh"]) >= 0.95 and a["datas"] == b["datas"]


def test_negativo_diarios_com_atividades_diferentes():
    a = preparar(_rdo(range(1, 31), lambda d: f"{d:02d}/11/2025"))
    outro = "\n".join(f"Data {d:02d}/12/2025 concretagem do muro de contenção bloco {d * 7} com {d + 3} m3 lançados "
                      f"pela betoneira, armação de {d * 11} kg de aço CA-50 e forma de madeira reaproveitada"
                      for d in range(1, 16))
    b = preparar(outro)
    assert b and contencao(a["sh"], b["sh"]) < 0.85


def test_local_ignora_numero_da_medicao():
    assert local("Diário de Obras - 16ª Medição (PETROPOLIS) (121666308)") == \
        local("Diário de Obras - 17ª Medição (PETROPOLIS) (121667861)") == "petropolis"
    assert datas_canonicas("1/11/25") == "01/11/2025"
