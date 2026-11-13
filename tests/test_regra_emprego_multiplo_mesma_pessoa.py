"""Regra 9 (emprego múltiplo): CPF da folha é mascarado — só agrupa a MESMA pessoa (CPF parcial + nome).

Revisão de 13/11/2026: agrupar só pelo CPF mascarado juntava pessoas diferentes (99,57% dos grupos) e o alerta
publicava o nome de uma somado à remuneração de outras. Dados sintéticos.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compliance_agent.database.models import Base, RegistroFolha
from compliance_agent.rules.engine import MotorCompliance


def _sessao():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _folha(s, cpf, nome, orgao):
    s.add(RegistroFolha(cpf=cpf, nome=nome, orgao_nome=orgao, competencia="2026-10", remuneracao_bruta=1000.0))


def test_mesmo_cpf_mascarado_nomes_diferentes_nao_vira_alerta():
    s = _sessao()
    _folha(s, "***123456**", "FULANA DE TAL", "SEEDUC")
    _folha(s, "***123456**", "BELTRANO SILVA", "SES")
    s.commit()
    m = MotorCompliance(s)
    m._regra_emprego_multiplo_orgaos("2026-10")
    assert [a for a in m._alertas_novos if a.tipo == "acumulacao"] == []


def test_mesma_pessoa_em_dois_orgaos_vira_alerta_media_a_verificar():
    s = _sessao()
    _folha(s, "***123456**", "FULANA DE TAL", "SEEDUC")
    _folha(s, "***123456**", "Fulana de Tal ", "SES")
    s.commit()
    m = MotorCompliance(s)
    m._regra_emprego_multiplo_orgaos("2026-10")
    (a,) = [a for a in m._alertas_novos if a.tipo == "acumulacao"]
    assert a.severidade == "média" and "a verificar" in a.titulo and "art. 37, XVI" in a.descricao
