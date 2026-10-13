# -*- coding: utf-8 -*-
"""Quem está a POUCOS documentos de um veredito alto lê primeiro.

Medido em 2026-08-09: **33 processos** estão marcados `NAO_AVALIAVEL` apenas porque a captura é
incompleta, mas o motor já lhes atribui **score ≥ 60** com o pouco que leu — 070002/001289/2022
chega a 90,2. Ler mais alguns documentos deles não muda a fila: muda o VEREDITO. Ainda assim a
fila de recaptura os tratava como qualquer outro: um a **1 documento** do fim estava na posição
314 de 3.625, e a maioria entre 1.575 e 2.729. A ~5 processos por ciclo por máquina, isso é
esperar meses por uma leitura quase pronta.

A ordem antiga (menor buraco primeiro) foi MEDIDA e continua valendo dentro de cada faixa — o
gigante de 900 documentos não cabe num slot e trava a passada. Por isso a promoção é
conservadora: só entra na frente quem tem buraco pequeno o bastante para caber num slot
(`_TETO_SLOT`), com score alto e sem veredito. Sem a tabela de avaliação, nada muda.
"""
from __future__ import annotations

import tools.sweep_recaptura_integral as SRI


def test_quase_veredito_vem_antes_do_buraco_menor(monkeypatch):
    monkeypatch.setattr(SRI, "_quase_veredito", lambda: {"1234567890122034": 90.2})
    bruta = [
        {"numero": "SEI-000001/000001/2024", "arvore": 10, "lido": 9, "faltam": 1},
        {"numero": "SEI-123456/789012/2034", "arvore": 50, "lido": 42, "faltam": 8},
        {"numero": "SEI-000002/000002/2024", "arvore": 10, "lido": 8, "faltam": 2},
    ]
    ordenada = SRI.ordenar(bruta)
    assert ordenada[0]["numero"] == "SEI-123456/789012/2034", (
        "processo a 8 docs de um veredito 90 continua atrás de quem não muda veredito nenhum")
    # dentro da faixa comum, o menor buraco segue primeiro (a regra medida)
    assert [x["faltam"] for x in ordenada[1:]] == [1, 2]


def test_gigante_quase_veredito_nao_fura_a_fila(monkeypatch):
    """Buraco que não cabe no slot não entra na frente — foi o que travou a passada em 07/08."""
    monkeypatch.setattr(SRI, "_quase_veredito", lambda: {"9999999999999999": 95.0})
    bruta = [
        {"numero": "SEI-000001/000001/2024", "arvore": 10, "lido": 9, "faltam": 1},
        {"numero": "SEI-999999/999999/9999", "arvore": 956, "lido": 40, "faltam": 916},
    ]
    assert SRI.ordenar(bruta)[0]["faltam"] == 1


def test_sem_tabela_de_avaliacao_a_ordem_e_a_antiga(monkeypatch):
    monkeypatch.setattr(SRI, "_quase_veredito", dict)
    bruta = [
        {"numero": "SEI-000002/000002/2024", "arvore": 10, "lido": 8, "faltam": 2},
        {"numero": "SEI-000001/000001/2024", "arvore": 10, "lido": 9, "faltam": 1},
        {"numero": "SEI-000003/000003/2024", "arvore": 99, "lido": 0, "faltam": 0,
         "faltam_desconhecido": True},
    ]
    assert [x["faltam"] for x in SRI.ordenar(bruta)] == [1, 2, 0]


def test_desconhecido_continua_por_ultimo(monkeypatch):
    """Tamanho desconhecido não é 'quase pronto' — é ignorância, e vai para o fim."""
    monkeypatch.setattr(SRI, "_quase_veredito", lambda: {"3333333333333333": 88.0})
    bruta = [
        {"numero": "SEI-333333/333333/3333", "arvore": 0, "lido": 0, "faltam": 0,
         "faltam_desconhecido": True},
        {"numero": "SEI-000001/000001/2024", "arvore": 10, "lido": 9, "faltam": 1},
    ]
    assert SRI.ordenar(bruta)[0]["numero"] == "SEI-000001/000001/2024"
