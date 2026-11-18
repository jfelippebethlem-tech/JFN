# -*- coding: utf-8 -*-
"""Regra 3 do MotorCompliance (remuneração acima do teto) usa a régua honesta de `acima_do_teto`.

Pente fino 17/11/2026: 403 alertas "Remuneração acima do teto" abertos, TODOS de gravidade ALTA — 53% dos 767
"alta" do card de alertas do Início — e tipo `enriquecimento`, nomeando a pessoa. A regra comparava o LÍQUIDO
com o teto sem a composição do contracheque; a folha da base não traz as verbas, e indenizatórias, férias,
13º e retroativos (RRA) não contam para o teto (CF art. 37 §11). O detector da casa (`acima_do_teto.classificar`)
já dizia: sem composição é VERIFICAR, e ≥2,5× o teto é RRA provável — nunca indício. A regra do motor era a
cópia divergente. Base sintética: nenhum nome real."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compliance_agent.database.models import Base, RegistroFolha
from compliance_agent.rules.engine import TETO_REMUNERATORIO_RJ, MotorCompliance


@pytest.fixture()
def motor():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    t = TETO_REMUNERATORIO_RJ
    s.add_all([
        RegistroFolha(cpf="XX111111XXX", nome="SERVIDOR UM", orgao_nome="ORGAO A", competencia="2026-09",
                      remuneracao_bruta=t * 1.3, remuneracao_liquida=t * 1.1),
        RegistroFolha(cpf="XX222222XXX", nome="SERVIDOR DOIS", orgao_nome="ORGAO A", competencia="2026-09",
                      remuneracao_bruta=t * 4, remuneracao_liquida=t * 3),
        RegistroFolha(cpf="XX333333XXX", nome="SERVIDOR TRES", orgao_nome="ORGAO A", competencia="2026-09",
                      remuneracao_bruta=t * 0.9, remuneracao_liquida=t * 0.7),
    ])
    s.commit()
    m = MotorCompliance(s)
    m._alertas_novos = []
    m._regra_remuneracao_acima_teto("2026-09")
    return m


def test_sem_composicao_nao_e_alta_e_diz_por_que(motor):
    a = {x.titulo.split("— ")[-1]: x for x in motor._alertas_novos}
    assert set(a) == {"SERVIDOR UM", "SERVIDOR DOIS"}
    assert all(x.severidade != "alta" for x in a.values())
    um = a["SERVIDOR UM"]
    assert um.severidade == "média" and "VERIFICAR" in um.descricao and "indenizatória" in um.descricao


def test_muito_acima_do_teto_e_retroativo_provavel_baixa(motor):
    dois = next(x for x in motor._alertas_novos if "DOIS" in x.titulo)
    assert dois.severidade == "baixa" and "RRA" in dois.descricao
