"""Padrão despesa_estranha_ao_objeto — NF 004 Buzzline (positivo) e negativos (TI, capacitação)."""
from compliance_agent.padroes import despesa_estranha_ao_objeto as D

NF004 = ("Jantar de encerramento de ano e prestação de contas para servidores da Secretaria de turismo do Rio de "
         "Janeiro. Local: Roxy Dinner Show. Período: 18 de Dezembro de 2025")


def test_controle_positivo():
    r = D.avaliar_texto(NF004)
    assert r and r["grau"] == "forte" and "Roxy" in r["trecho"]


def test_dia_do_servidor_e_medio():
    assert D.avaliar_texto("Material gráfico referente ao dia do Servidor Público, conforme OS 300")["grau"] == "medio"


def test_negativo_servidor_de_informatica():
    assert D.avaliar_texto("almoço técnico; locação de servidores de rede e storage para o datacenter") is None


def test_capacitacao_rebaixa_para_fraco():
    assert D.avaliar_texto("confraternização dos servidores no encerramento do curso de capacitação")["grau"] == "fraco"


def test_negativo_sem_beneficiario_interno():
    assert D.avaliar_texto("Fornecimento de almoço para os alunos da rede estadual") is None


def test_negativo_contrato_de_alimentacao_de_presidio():
    t = "Desjejum - Presos 52.906 Un 2 Desjejum - Funcionarios 600 Un 4 Almoco - Funcionarios 980 Un Jantar-Funcionarios"
    assert D.avaliar_texto(t) is None


def test_negativo_refeicao_de_servidor_sem_evento():
    assert D.avaliar_texto("JANTAR SERVIDOR 21069090 UN 1.550,000 ALMOÇO SERVIDORES LANCHE SERVIDORES") is None


def test_jantar_de_secretarios_e_dia_do_servidor_com_evento():
    assert D.avaliar_texto("ITENS PARA ATENDER O JANTAR DE SECRETÁRIOS DE ESTADO. Local: Masi")["grau"] == "forte"
    assert D.avaliar_texto("SS 273 EVENTO: 1º Evento em comemoração ao Dia do Servidor Local: Palácio")["grau"] == "forte"


def test_negativo_servidor_de_video():
    assert D.avaliar_texto("confraternização; Serviços de Painéis de LED, Servidores de Vídeo, Acessórios") is None


def test_negativo_presente_atestado_nao_e_brinde():
    assert D.avaliar_texto("ACEITOS PELO PRESENTE ATESTADO OS SERVIÇOS; servidor responsável") is None
    assert D.avaliar_texto("COFFE BREAK PGERJ PARA 500 PAX 30/10 Dia do Servidor")["grau"] == "forte"
