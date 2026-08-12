# -*- coding: utf-8 -*-
"""Card que não chegou porque a rota ainda estava VOANDO não é card quebrado.

O `painel_fila_check` espera até 120 s e depois declara "faltando". Em 2026-08-11 ele bloqueou um
commit dizendo que três cards não chegaram à tela — e cinco minutos depois, com o mesmo código,
os dez chegaram. A diferença era cache frio (servidor recém-reiniciado) somado a `load 11`: a API
é single-process, as rotas pesadas serializam, e as três últimas ainda estavam em voo quando o
orçamento acabou.

Um gate que confunde "ainda não chegou" com "não existe" treina quem trabalha a usar `--no-verify`
— e essa é a porta pela qual já entrou painel quebrado na casa. É a mesma disciplina que a casa
aplica em toda parte: **INDISPONÍVEL não é 0**, e o `pre_push_gate` acima de load 6 DECLARA que não
mediu em vez de aprovar em silêncio.

O veredito, portanto, é de três valores, e não de dois:

    faltando + requisição de API ainda pendente  →  NÃO MEDI (declara, não bloqueia)
    faltando + nada pendente                     →  FALHOU  (bloqueia: o card não vem mesmo)
    nada faltando                                →  OK
"""
from __future__ import annotations

from tools.painel_fila_check import veredito


def test_tudo_presente_e_ok():
    v = veredito(faltando=[], pageerror=[], em_voo=[])
    assert v["estado"] == "ok" and v["bloqueia"] is False


def test_faltando_com_requisicao_em_voo_declara_que_NAO_MEDIU():
    v = veredito(faltando=["voltaram vazios"], pageerror=[],
                 em_voo=["/api/fiscal/zeros_sem_causa?limite=12"])
    assert v["estado"] == "nao_medido"
    assert v["bloqueia"] is False
    assert "voo" in v["motivo"].lower() or "pendente" in v["motivo"].lower()


def test_faltando_SEM_nada_em_voo_bloqueia():
    """Aqui o card não vem mesmo: a rota respondeu (ou nem foi pedida) e a seção não existe."""
    v = veredito(faltando=["voltaram vazios"], pageerror=[], em_voo=[])
    assert v["estado"] == "falhou" and v["bloqueia"] is True


def test_pageerror_bloqueia_mesmo_com_requisicao_em_voo():
    """`pageerror` é defeito de código, não lentidão — não há orçamento que o justifique."""
    v = veredito(faltando=[], pageerror=["X is not defined"], em_voo=["/api/x"])
    assert v["estado"] == "falhou" and v["bloqueia"] is True


def test_o_laudo_diz_QUAIS_estao_em_voo_nao_quantos():
    """Onde a casa corta lista, perguntar QUAIS N, nunca só quantos — sem isso ninguém sabe se a
    lentidão é da rota que interessa ou de outra."""
    v = veredito(faltando=["a", "b"], pageerror=[], em_voo=["/api/fiscal/consorcio"])
    assert v["em_voo"] == ["/api/fiscal/consorcio"]
    assert v["faltando"] == ["a", "b"]
