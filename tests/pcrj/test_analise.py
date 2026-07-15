# -*- coding: utf-8 -*-
"""Testa a INTEGRAÇÃO da captação municipal aos motores existentes (``pcrj/analise.py``).

Determinístico (``usar_llm=False``) — sem rede, sem API. Verifica que os 4 motores
estão de fato plugados e que a consolidação sobe o risco num edital com direcionamento.
"""
from compliance_agent.pcrj.analise import analisar_edital, montar_leitura

EDITAL_DIRIGIDO = (
    "EDITAL DE PREGÃO ELETRÔNICO Nº 078/2025 - Processo nº 09/002.991/2022. "
    "Exige-se atestado comprovando fornecimento da marca Philips modelo IntelliVue MX750, "
    "não se admitindo o somatório de atestados. Visita técnica prévia obrigatória, "
    "sob pena de inabilitação. Capital social mínimo de 30% do valor estimado."
)
ATA = ("3 licitantes. Empresa A inabilitada por não realizar visita técnica. "
       "Empresa B inabilitada por não realizar visita técnica. Empresa C VENCEDORA.")

EDITAL_LIMPO = "EDITAL DE PREGÃO Nº 1/2025. Aquisição de material de escritório. Menor preço por item."


def test_montar_leitura_formato():
    leit = montar_leitura("texto do edital", "09/002.991/2022", valor=1000.0)
    assert leit["conteudo_documentos"][0]["conteudo"] == "texto do edital"
    assert leit["valores"] == ["R$ 1000.00"]


def test_quatro_motores_presentes():
    r = analisar_edital(EDITAL_DIRIGIDO, numero="09/002.991/2022", ata=ATA)
    for chave in ("detectores", "direcionamento", "lex", "fraude", "resumo"):
        assert chave in r


def test_edital_dirigido_sobe_risco():
    r = analisar_edital(EDITAL_DIRIGIDO, numero="09/002.991/2022",
                        orgao="SMS", modalidade="Pregão Eletrônico", ata=ATA)
    assert r["direcionamento"]["grau_det"] == "vermelho"
    assert r["resumo"]["score"] >= 0.7
    assert "🔴" in r["resumo"]["faixa"]
    # cascata de inabilitações deve ser sinalizada
    assert r["direcionamento"]["cascata"] is True


def test_edital_limpo_nao_alarma():
    r = analisar_edital(EDITAL_LIMPO, numero="1/2025", modalidade="Pregão")
    assert r["resumo"]["score"] < 0.7
    assert r["direcionamento"]["grau_det"] in ("verde", "amarelo", "indeterminado")


def test_motor_isola_falha():
    """Texto vazio não pode derrubar a análise — cada motor tolera dado faltante."""
    r = analisar_edital("", numero="")
    assert "resumo" in r  # não levantou
