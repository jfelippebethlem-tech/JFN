"""Padrão despesa_estranha_ao_objeto — NF 004 Buzzline (positivo) e negativos (TI, capacitação)."""
from compliance_agent.padroes import despesa_estranha_ao_objeto as D

NF004 = ("Jantar de encerramento de ano e prestação de contas para servidores da Secretaria de turismo do Rio de "
         "Janeiro. Local: Roxy Dinner Show. Período: 18 de Dezembro de 2025")


def test_controle_positivo():
    r = D.avaliar_texto(NF004)
    assert r and r["grau"] == "forte" and "Roxy" in r["trecho"]


def test_dia_do_servidor_e_medio():
    assert D.avaliar_texto("Serviço de buffet no dia do Servidor Público, conforme OS 300")["grau"] == "medio"


def test_negativo_servidor_de_informatica():
    assert D.avaliar_texto("almoço técnico; locação de servidores de rede e storage para o datacenter") is None


def test_capacitacao_rebaixa_para_fraco():
    assert D.avaliar_texto("almoço para servidores participantes do curso de capacitação em licitações")["grau"] == "fraco"


def test_negativo_sem_beneficiario_interno():
    assert D.avaliar_texto("Fornecimento de almoço para os alunos da rede estadual") is None
