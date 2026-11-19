# -*- coding: utf-8 -*-
"""mrosc_atesto_contra_relatorio — controles com trechos literais (NATA doc 23; Bem Viver docs 102 × 104)."""
from compliance_agent.padroes.mrosc_atesto_contra_relatorio import avaliar_documento, atesto_pleno, quadro_sem_conclusao

NATA_23 = ("visto que a definição das localidades necessita atender às demandas já mapeadas pela Secretaria em "
           "conformidade com as políticas públicas instituídas, contudo, os polos ainda não foram efetivamente "
           "implantados. Neste período ... 3. CONCLUSÃO Do acima exposto, ATESTAMOS a execução INTEGRAL e "
           "SATISFATÓRIA da etapa do Termo de Colaboração referente à competência da segunda parcela")

BEMVIVER_102 = ("A OSC parceira desenvolveu as atividades realizadas atendendo o cumprimento das metas, considerando o "
                "impacto do benefício social obtido")
BEMVIVER_104 = ("FASE ETAPAS STATUS IMPLANTAÇÃO Etapa: Definição dos Polos Iniciada – Em andamento Etapa: Aquisições de "
                "Serviços e Profissionais Iniciada – Em andamento Etapa: Aquisições de Materiais Iniciada – Em andamento "
                "... A etapa de contratação será concluída concomitante a estruturação de todos os Polos.")


def test_positivo_mesmo_documento():
    r = avaliar_documento(NATA_23)
    assert r and "atestamos a execucao integral" in r["atesto"] and "nao foram efetivamente implantad" in r["nega"]


def test_positivo_cruzado_atesto_e_quadro_sem_conclusao():
    assert atesto_pleno(BEMVIVER_102)
    assert quadro_sem_conclusao(BEMVIVER_104)


def test_negativo_atesto_parcial():
    t = NATA_23.replace("ATESTAMOS a execução INTEGRAL e SATISFATÓRIA", "ATESTAMOS parcialmente a execução INTEGRAL e SATISFATÓRIA")
    assert avaliar_documento(t) is None


def test_negativo_atesto_sem_negacao():
    t = "Os polos foram implantados. ATESTAMOS a execução INTEGRAL e SATISFATÓRIA da etapa."
    assert avaliar_documento(t) is None


def test_negativo_quadro_com_etapa_concluida():
    t = "Etapa: Definição dos Polos Concluída Etapa: Capacitação Iniciada – Em andamento Etapa: Divulgação Em andamento"
    assert quadro_sem_conclusao(t) is None
