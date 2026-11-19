"""Padrão ob_antes_da_entrega — Angloco (positivo) × Jacinto Marques (falso positivo conhecido: carta de crédito)."""
from datetime import date

from compliance_agent.padroes import ob_antes_da_entrega as O


def test_controle_positivo_sem_recebimento_sem_carta():
    assert O.classificar(date(2025, 9, 23), [], cc=False) == "forte"


def test_angloco_carta_de_credito_sem_recebimento_e_medio():
    assert O.classificar(date(2025, 9, 23), [], cc=True) == "medio"


def test_negativo_jacinto_carta_de_credito_com_recebimento_posterior():
    receb = [{"doc": "doc 80", "data": date(2026, 10, 7)}]
    assert O.classificar(date(2025, 10, 14), receb, cc=True) is None


def test_negativo_recebido_antes_de_pagar():
    receb = [{"doc": "doc 9", "data": date(2025, 3, 1)}]
    assert O.classificar(date(2025, 4, 1), receb, cc=False) is None


def test_recebimento_depois_sem_carta_e_medio():
    receb = [{"doc": "doc 9", "data": date(2025, 6, 1)}]
    assert O.classificar(date(2025, 4, 1), receb, cc=False) == "medio"


def test_texto_de_liquidacao_reconhece_proforma():
    t = "Documento de cobrança: SEI n° (Proforma Invoice 111256454) Valor total a liquidar: R$ 22.000.000,00"
    assert O._RE_PROFORMA.search(t)
    assert O._RE_PROFORMA_NUM.findall("Ceská zbrojovka a.s. PROFORMA INVOICE no 12522397") == ["12522397"]
