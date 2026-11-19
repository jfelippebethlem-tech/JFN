"""Padrão reserva_tecnica_multiplicada — linhas reais do desembolso Cesgranrio (positivo) e material (negativo)."""
from compliance_agent.padroes import reserva_tecnica_multiplicada as R

LINHA = ("5 | Transporte - Distribuição dos instrumentos de avaliação nos polos regionais | locais | 137 | 0.05 | 144 | "
         "1 | 1 | 7407.18 | 1066633.92 |")
COORD = "4 | Coordenador de Polo | hora | 137 | 0.05 | 34560 | 30 | 8 | 30.59 | 1057190.4 | 1057190.4 | 0"


def test_controle_positivo_locais_e_horas():
    ls = R.linhas_reserva(LINHA + "\n" + COORD)
    assert len(ls) == 2
    assert ls[0]["total_pago"] == 144 and ls[0]["excesso_estimado"] == round(7 * 7407.18, 2)
    assert ls[1]["excesso_estimado"] == round(7 * 240 * 30.59, 2)


def test_declaracao_da_contratada():
    t = "A estratégia logística utilizou 137 polos de distribuição distribuídos estrategicamente"
    assert R.declara_quantidade(t, 137) and not R.declara_quantidade(t, 144)


def test_negativo_material_impresso():
    assert R.linhas_reserva("3 | Cadernos de prova impressos | unidade | 1000 | 0.05 | 1050 | 1 | 1 | 2.50 | 2625.0 |") == []


def test_negativo_sem_acrescimo():
    assert R.linhas_reserva("5 | Transporte nos polos | locais | 137 | 0.05 | 137 | 1 | 1 | 7407.18 | 1014783.66 |") == []
