"""Padrão atesto_antes_do_periodo — controle positivo (Buzzline/SETUR) e negativos, sem varrer o acervo."""
from datetime import date

from compliance_agent.padroes import atesto_antes_do_periodo as A

ATESTO = ("ATESTADO DE REALIZAÇÃO DOS SERVIÇOS Ref.: NF 77(145642059) Atestamos que os serviços relativos a nota "
          "fiscal nº 77(145642059) foram executados de acordo com as especificações contratuais. "
          "Rio de Janeiro, 04 de novembro de 2026")
NF77 = "montagem de STAND NA FEIRA FESTURIS 2026 . Local: Gramado - Serra Park Gramado; Período 06 a 11 de novembro de 2026"


def test_controle_positivo_periodo_na_nf_citada():
    r = A.avaliar_atesto(ATESTO, {"145642059": NF77})
    assert r and r["fim"] == date(2026, 11, 11) and r["folga"] == 7 and r["antes_do_inicio"]
    g, pagas = A.classificar(r, [{"numero_ob": "2026OB01391", "data_emissao": "09/11/2026", "valor": 1555515.05}])
    assert g == "forte" and pagas


def test_lista_de_dias_e_mes_de_referencia():
    assert A.periodos("PERÍODO: 15, 16, 22, 23 E 28/02 À 09/03 DE 2025.")[0][:2] == (date(2025, 2, 15), date(2025, 3, 9))
    p = A.periodos("Atestamos que o repasse dos meses de Novembro e Dezembro 2025 referentes à prestação")
    assert p and p[0][1] == date(2025, 12, 31)


def test_negativo_vigencia_nao_e_periodo_de_servico():
    assert A.periodos("vigência pelo período de 01/01/2025 a 31/12/2025") == []


def test_negativo_atesto_depois_do_periodo():
    t = ATESTO.replace("04 de novembro de 2026", "12 de novembro de 2026")
    assert A.avaliar_atesto(t, {"145642059": NF77}) is None


def test_negativo_concessionaria():
    assert A.avaliar_atesto("Fatura de energia elétrica Light. " + ATESTO, {"145642059": NF77}) is None


def test_atesto_antecipado_sem_ob_e_medio():
    r = A.avaliar_atesto(ATESTO.replace("04 de novembro", "07 de novembro"), {"145642059": NF77})
    assert A.classificar(r, [])[0] == "medio"


def test_negativo_periodo_contratual_e_vigencia():
    assert A.periodos("Período contratual: 02/06/2025 a 01/06/2026") == []


def test_negativo_cartao_beneficio_credito_no_inicio_do_mes():
    t = "Atestamos os serviços do mês de maio/2026 — fornecimento de vale-refeição. Rio de Janeiro, 06 de maio de 2026"
    assert A.avaliar_atesto(t, {}) is None
