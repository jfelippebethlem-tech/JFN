# -*- coding: utf-8 -*-
"""execucao_acima_do_valor_antes_do_aditivo — FAETEC × Scalle (SEI-260005/007167/2024, docs 12, 15, 18)."""
from compliance_agent.padroes.execucao_acima_do_valor_antes_do_aditivo import avaliar, serie_consolidada

PLANILHA = ("MEDIÇÃO Nº:\n10ª MEDIÇÃO\n11ª MEDIÇÃO\n12ª MEDIÇÃO\nPeríodo de Referência:\nnov/23\ndez/23\njan/24\n"
            "Total desta Med. (COM \nBDI)\n1,00\nR$\nTotal do Acum. (COM BDI)\n44.185.076,94\nR$ \n53.772.203,62\nR$ \n"
            "60.495.456,62\nR$ \nAcumulado 1X\n")
TA = [{"data": "2024-01-24", "total": None, "incremento": 69368160.14, "doc": 15}]


def test_serie_da_planilha_consolidada():
    assert serie_consolidada(PLANILHA) == [("2023-11", 44185076.94), ("2023-12", 53772203.62), ("2024-01", 60495456.62)]


def test_positivo_scalle_acima_antes_do_1o_ta():
    r = avaliar(45872202.68, TA, serie_consolidada(PLANILHA))
    assert r["grau"] == "forte" and r["mes"] == "2023-12" and r["acumulado"] == 53772203.62


def test_negativo_dentro_do_valor_ate_o_aditivo():
    s = [("2023-11", 40000000.0), ("2023-12", 45000000.0), ("2024-02", 60000000.0)]
    assert avaliar(45872202.68, TA, s) is None


def test_negativo_sem_aditivo_datado_nao_avalia():
    assert avaliar(45872202.68, [], serie_consolidada(PLANILHA)) is None


def test_serie_que_decresce_e_leitura_errada():
    ruim = PLANILHA.replace("60.495.456,62", "6.495.456,62")
    assert serie_consolidada(ruim) == []
