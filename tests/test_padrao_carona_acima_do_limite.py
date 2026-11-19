# -*- coding: utf-8 -*-
"""carona_acima_do_limite — STEM × SEGOV (SEI-420001/006323/2025): ARP IFMT 90048/2024 homologou R$ 3,3 mi; pago
R$ 25.662.000,00 (2025OB06215). Globaltec (SEI-260005/010324/2025): contrato de 06/05/2025 com fundamento na 8.666."""
from compliance_agent.padroes._carona_comum import Doc
from compliance_agent.padroes.carona_acima_do_limite import ata_citada, lei_revogada, limite_aderente

ATA_IFMT = {"controle_ata": "10784782000150-1-000466/2024-000001", "orgao": "IFMT", "total_homologado": 3300000.0,
            "itens": [{"item": 1, "descricao": "Livro Didático", "resultados": [{"qtd": 5000000.0, "unit": 0.66}]}]}


def test_positivo_stem_estoura_50pct():
    s = limite_aderente(25662000.0, ATA_IFMT)
    assert s["grau"] == "forte" and s["razao_pago_sobre_homologado"] == 7.78


def test_negativo_adesao_dentro_do_limite():
    assert limite_aderente(1_000_000.0, ATA_IFMT) is None          # 30% do homologado
    assert limite_aderente(1_650_000.0, ATA_IFMT) is None          # exatamente 50%: limite inclusivo
    assert limite_aderente(2_000_000.0, ATA_IFMT)["grau"] == "medio"


def test_numero_da_ata_dos_autos():
    d = Doc("arquivo", "0", "Despacho", "conforme Termo de Referência e Ata de Registro de Preços nº 90048/2024 (doc. SEI)")
    assert ata_citada([d])[:2] == ("90048", "2024")


ADESAO = Doc("arquivo", "20", "Nota de Empenho", "Mod. Licitação 10 - Adesão ao Registro de Preços Interno - Pregão")
EXTRATO = Doc("arquivo", "8", "Anexo Extrato instrumento contratual",
              "PARTES: FAETEC e GLOBALTEC TECNOLOGIAS EDUCACIONAIS LT-\nDA.\nDATA DA A S S I N AT U R A : 06/05/2025.\n"
              "VALOR: R$ 21.352.000,00\nFUNDAMENTO: Lei nº 8.666, de 21 de junho de 1.993 e alterações")


def test_positivo_globaltec_lei_revogada():
    s = lei_revogada([ADESAO, EXTRATO], "GLOBALTEC TECNOLOGIAS EDUCACIONAIS LTDA")
    assert s and s["data_assinatura"] == "06/05/2025"


def test_negativo_extrato_vizinho_de_outro_credor_e_2023():
    assert lei_revogada([ADESAO, EXTRATO], "OUTRA EMPRESA QUALQUER SA") is None
    velho = Doc("arquivo", "8", "Extrato", "GLOBALTEC DATA DA ASSINATURA: 06/05/2023. FUNDAMENTO: Lei nº 8.666")
    assert lei_revogada([ADESAO, velho], "GLOBALTEC TECNOLOGIAS") is None
