# -*- coding: utf-8 -*-
"""Régua única de credor institucional (20/11/2026).

O alerta `direcionamento` "favorecido em N UGs distintas" acusava concessionária de energia/água, Correios
(empresa pública) e plano de previdência dos servidores — 107 dos 230 vereditos dessa regra voltaram
`provavel_falso_positivo` da triagem do Opus. Credor institucional recebe de várias UGs por natureza: o alerta
continua existindo (rastro), mas declara "NÃO é acusação", e a triagem o pula. Empresa privada comum continua
acusando; Receita indisponível NÃO absolve (INDISPONÍVEL ≠ 0)."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compliance_agent import credor_institucional as ci
from compliance_agent.database.models import Base, OrdemBancaria
from compliance_agent.rules.engine import MotorCompliance

LIGHT = "60444437000146"      # S.A. aberta (2046), CNAE 3514000 distribuição de energia
CORREIOS = "34028316000294"   # empresa pública (2011), CNAE 5310501
AGUAS = "42644220000106"      # S.A. fechada (2054), CNAE 3600601 — concessionária só pelo CNAE
RJPREV = "48307566000197"     # 3328 plano de benefícios de previdência complementar fechada
PRIVADA = "05969071000110"    # LTDA (2062), CNAE 7830200 — fornecedor comum


@pytest.fixture()
def receita(tmp_path, monkeypatch):
    db = tmp_path / "receita_estab.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE empresas (cnpj_basico TEXT PRIMARY KEY, natureza_cod TEXT)")
    con.execute("CREATE TABLE estabelecimentos (cnpj TEXT PRIMARY KEY, cnae_principal TEXT)")
    for cnpj, nat, cnae in [(LIGHT, "2046", "3514000"), (CORREIOS, "2011", "5310501"), (AGUAS, "2054", "3600601"),
                            (RJPREV, "3328", "6541300"), (PRIVADA, "2062", "7830200")]:
        con.execute("INSERT INTO empresas VALUES (?,?)", (cnpj[:8], nat))
        con.execute("INSERT INTO estabelecimentos VALUES (?,?)", (cnpj, cnae))
    con.commit()
    con.close()
    monkeypatch.setattr(ci, "_DB_RECEITA", db)
    return db


@pytest.mark.parametrize("cnpj, trecho", [
    (LIGHT, "S.A. aberta"), (CORREIOS, "empresa pública"), (AGUAS, "concessionária"),
    (RJPREV, "previdência complementar"),
])
def test_institucional_reconhece_estatal_aberta_concessionaria_e_previdencia(receita, cnpj, trecho):
    r = ci.institucional(cnpj)
    assert r["institucional"] is True and trecho in r["motivo"]


def test_privada_comum_nao_e_institucional(receita):
    assert ci.institucional(PRIVADA)["institucional"] is False


def test_cnae_informado_prevalece_e_aceita_descricao(receita):
    assert ci.institucional(PRIVADA, cnae="Distribuição de energia elétrica")["institucional"] is True
    assert ci.institucional("99999999000199", cnae="6120501")["institucional"] is True   # telefonia móvel


def test_indisponivel_nao_absolve(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "_DB_RECEITA", tmp_path / "nao_existe.db")
    r = ci.institucional(CORREIOS)
    assert r["institucional"] is False and "INDISPONÍVEL" in r["motivo"]
    assert ci.institucional("12345678901")["institucional"] is False          # CPF: nunca institucional


def test_natureza_fora_importa_da_regua_unica():
    from tools import desmascarar_cpf_externo as d
    assert d.natureza_fora is ci.natureza_fora


def _sessao(cnpj, nome):
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    hoje = date.today() - timedelta(days=2)
    s.add_all([OrdemBancaria(numero_ob=f"2026OB{i}", data_emissao=hoje, ug_codigo=ug, favorecido_cpf=cnpj,
                             favorecido_nome=nome, valor=1000.0 * (i + 1), status="paga")
               for i, ug in enumerate(("180100", "290100", "300100"))])
    s.commit()
    return s


@pytest.mark.parametrize("cnpj, nome", [(LIGHT, "LIGHT SERVICOS DE ELETRICIDADE S/A"),
                                        (CORREIOS, "EMPRESA BRASILEIRA DE CORREIOS E TELEGRAFOS")])
def test_regra_multiplas_ugs_nao_acusa_credor_institucional(receita, cnpj, nome):
    m = MotorCompliance(_sessao(cnpj, nome))
    m._alertas_novos = []
    m._regra_ob_favorecido_multiplas_ugs()
    assert len(m._alertas_novos) == 1
    a = m._alertas_novos[0]
    assert a.descricao.startswith("NÃO é acusação — credor institucional:")
    assert "carimbado" not in a.descricao


def test_regra_multiplas_ugs_continua_acusando_privada(receita):
    m = MotorCompliance(_sessao(PRIVADA, "APPA SERVICOS TEMPORARIOS E EFETIVOS LTDA"))
    m._alertas_novos = []
    m._regra_ob_favorecido_multiplas_ugs()
    assert len(m._alertas_novos) == 1
    assert not m._alertas_novos[0].descricao.startswith("NÃO é acusação")
    assert "carimbado" in m._alertas_novos[0].descricao


def test_emissora_de_vale_beneficio_e_institucional_so_pelo_cnae():
    from compliance_agent.credor_institucional import institucional
    r = institucional("69034668000156", cnae="8299702")      # Pluxee
    assert r["institucional"] and "vale" in r["motivo"]
    assert not institucional("11111111000191", cnae="8299799")["institucional"]   # outra 8299 não entra


# ── Segundo sinal (21/11/2026) ────────────────────────────────────────────────────────────────────────────────
# Fornecedor privado de porte também recebe de várias UGs por natureza: 233 triados desta regra, 129 provável falso
# positivo e 0 'aprofundar' depois da conferência do Opus. A hipótese do nome (laranja "carimbado") só se sustenta
# com porte incompatível. Os casos abaixo são os do acervo real (nomes trocados, números preservados).
from types import SimpleNamespace

from compliance_agent.rules.engine import _segundo_sinal_dispersao


def _emp(porte, cap, nome="ALFA LTDA", natureza=None):
    return SimpleNamespace(porte=porte, capital_social=cap, razao_social=nome, natureza_jur=natureza)


def test_fornecedor_de_porte_sem_segundo_sinal_nao_acusa():
    # controle negativo real: EXTREME DIGITAL — DEMAIS, capital R$ 4.250.001, R$ 18,18 mi num mês (Opus: monitorar)
    assert _segundo_sinal_dispersao("14139773000168", _emp("DEMAIS", 4_250_001.0), 18_182_021.0)["estado"] == "ausente"


def test_associacao_com_capital_zero_nao_e_capital_incompativel():
    # controle negativo real: CIEE — Associação Privada, capital R$ 0,00 (2 triados, ambos sem indício)
    s = _segundo_sinal_dispersao("33661745000150", _emp("DEMAIS", 0.0, "CENTRO DE INTEGRACAO EMPRESA ESCOLA",
                                                         "Associação Privada"), 4_332_271.98)
    assert s["estado"] == "ausente"


@pytest.mark.parametrize("doc, emp, total, trecho", [
    ("***123456**", None, 900_000.0, "pessoa física"),                       # CPF mascarado
    ("11111111000191", _emp("MICRO EMPRESA", 10_000.0), 2_000_000.0, "MICRO EMPRESA"),
    ("11111111000191", _emp("DEMAIS", 1_000.0), 2_000_000.0, "incompatível"),  # 2.000× o capital
])
def test_segundo_sinal_presente_acusa(doc, emp, total, trecho):
    s = _segundo_sinal_dispersao(doc, emp, total)
    assert s["estado"] == "presente" and trecho in s["motivo"]


def test_cadastro_indisponivel_nao_absolve():
    assert _segundo_sinal_dispersao("11111111000191", None, 1.0)["estado"] == "indisponivel"
    assert _segundo_sinal_dispersao("11111111000191", _emp(None, None), 1.0)["estado"] == "indisponivel"


def test_regra_multiplas_ugs_grande_sem_segundo_sinal_vira_rastro(receita):
    from compliance_agent.database.models import Empresa
    s = _sessao(PRIVADA, "APPA SERVICOS TEMPORARIOS E EFETIVOS LTDA")
    s.add(Empresa(cnpj=PRIVADA, razao_social="APPA SERVICOS TEMPORARIOS E EFETIVOS LTDA", porte="DEMAIS",
                  capital_social=5_000_000.0))
    s.commit()
    m = MotorCompliance(s)
    m._alertas_novos = []
    m._regra_ob_favorecido_multiplas_ugs()
    a = m._alertas_novos[0]
    assert a.descricao.startswith("NÃO é acusação — dispersão por UG sem segundo sinal")
