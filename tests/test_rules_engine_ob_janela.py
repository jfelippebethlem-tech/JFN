# -*- coding: utf-8 -*-
"""Regras de OB do MotorCompliance: janela recente + candidatos no SQL (10/09/2026).

Antes, quatro regras carregavam 1,18 milhão de OBs pelo ORM (1,7 GB) e faziam uma consulta por OB —
nunca terminavam nos 900 s do cron (rc=124). Aqui: banco em memória, OB velha fora da janela NÃO alerta,
OB recente alerta, e o cruzamento com o D.O. usa `cnpjs_extraidos`."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compliance_agent.database.models import Base, Empresa, OrdemBancaria, PublicacaoDOERJ
from compliance_agent.rules.engine import MotorCompliance

CNPJ = "00801512000157"


@pytest.fixture()
def sessao():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    hoje = date.today()
    s.add(Empresa(cnpj=CNPJ, razao_social="AGILE CORP", data_abertura=hoje - timedelta(days=30)))
    s.add_all([
        OrdemBancaria(numero_ob="2026OB1", data_emissao=hoje - timedelta(days=5), ug_codigo="180100",
                      favorecido_cpf=CNPJ, favorecido_nome="AGILE CORP SERVICOS", valor=100000.0, status="paga"),
        OrdemBancaria(numero_ob="2024OB9", data_emissao=hoje - timedelta(days=400), ug_codigo="180100",
                      favorecido_cpf=CNPJ, favorecido_nome="AGILE CORP SERVICOS", valor=250000.0, status="paga"),
        OrdemBancaria(numero_ob="2026OB2", data_emissao=hoje - timedelta(days=3), ug_codigo="180100",
                      favorecido_cpf="12345678000199", favorecido_nome="OUTRA LTDA", valor=12345.67, status="paga"),
    ])
    s.add(PublicacaoDOERJ(data_publicacao=hoje - timedelta(days=10), tipo_ato="decisão", titulo="x",
                          texto="condenação por improbidade administrativa", cnpjs_extraidos=f'["{CNPJ}"]'))
    s.commit()
    return s


def _titulos(motor):
    return [a.titulo for a in motor._alertas_novos]


def test_regras_de_ob_respeitam_a_janela_e_o_sql(sessao):
    m = MotorCompliance(sessao)
    m._alertas_novos = []
    m._regra_ob_empresa_nova()
    assert [t for t in _titulos(m) if "empresa nova" in t] and "2026OB1" in m._alertas_novos[0].descricao
    m._alertas_novos = []
    m._regra_ob_valor_redondo()
    assert len(m._alertas_novos) == 1 and "2026OB1" in m._alertas_novos[0].descricao, "a OB redonda de 400 dias atrás fica fora da janela"
    m._alertas_novos = []
    m._regra_ob_sem_processo_sei()
    assert sorted("2026OB1" in a.descricao or "2026OB2" in a.descricao for a in m._alertas_novos) == [True, True]
    assert not any("2024OB9" in a.descricao for a in m._alertas_novos)
    m._alertas_novos = []
    m._regra_ob_favorecido_doerj_cruzado()
    assert len(m._alertas_novos) == 1 and "termos suspeitos" in m._alertas_novos[0].descricao
