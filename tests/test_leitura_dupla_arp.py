# -*- coding: utf-8 -*-
"""A Ata de Registro de Preços era instrumento INVISÍVEL para os dois leitores.

Achado por um confronto que faltava: ler os processos EU MESMO (Claude) e comparar com a leitura da
LLM gratuita. Ela responde `contrato: NAO_CONSTA` e está tecnicamente CERTA — não há contrato —, só
que o instrumento existe e é uma ARP. Nenhum dos dois leitores era perguntado sobre ela, então o
instrumento sumia do laudo sem que ninguém errasse.

**Medido no acervo: 75 de 362 processos (21%) citam uma Ata de Registro de Preços.**

Importa para a fiscalização porque "consumo de ata" é uma das rotas clássicas de aquisição sem
certame próprio — inclusive carona em ata de outro órgão. Campo que não se pergunta é campo que não
aparece, e o que não aparece não se fiscaliza.
"""
from __future__ import annotations

import pytest

from tools.sei_leitura_dupla import _FATOS, extrair_deterministico

CASOS = [
    ("conforme Ata de Registro de Preços Nº 007/2026, consolidada pela SECRETARIA\n", "007/2026"),
    ("adesão à Ata de Registro de Preços nº 010/2021 do órgão gerenciador\n", "010/2021"),
    ("ATA DE REGISTRO DE PREÇOS N.º 059/2025\n", "059/2025"),
]


@pytest.mark.parametrize("texto,esperado", CASOS)
def test_acha_a_ata_nas_grafias_do_documento(texto, esperado):
    assert extrair_deterministico(texto)["arp"]["valor"] == esperado


def test_a_ata_tambem_e_PERGUNTADA_a_ia():
    """Só extrair pela regra não basta: sem a pergunta, não há confronto — e sem confronto o campo
    volta a ser um número solto em que ninguém reparou."""
    assert "arp" in _FATOS


def test_contrato_de_verdade_nao_vira_ata():
    d = extrair_deterministico("Contrato nº 443/2025 firmado entre as partes.\n")
    assert not d["arp"]["valor"] and d["contrato"]["valor"] == "443/2025"


def test_a_SIGLA_ARP_tambem_e_o_instrumento():
    """`Adesão a ARP nº 025/2024` é como o EXTRATO CONTRATUAL escreve. Exigir a expressão por
    extenso perdia justamente a forma abreviada — que é a usada onde o instrumento APARECE (extrato
    de adesão), não onde ele é explicado."""
    d = extrair_deterministico("INSTRUMENTO: Contrato n° 182/2024. Adesão a ARP nº 025/2024 PE Nº 026/2023\n")
    assert d["arp"]["valor"] == "025/2024"
    assert d["contrato"]["valor"] == "182/2024"


def test_a_sigla_PE_sozinha_e_pregao_eletronico():
    """`PE Nº 026/2023` aparece sem a palavra "Pregão" por perto e o certame escapava."""
    d = extrair_deterministico("Adesão a ARP nº 025/2024 PE Nº 026/2023 - SES do Maranhão\n")
    assert d["pregao"]["valor"] == "026/2023"


def test_PE_sem_o_numero_marcador_NAO_vira_certame():
    """Sem exigir o `nº` colado, a sigla de estado (PE de Pernambuco) viraria pregão."""
    assert not extrair_deterministico("Fornecedor sediado em Recife/PE 2023/2024.\n")["pregao"]["valor"]


def test_ano_implausivel_e_descartado():
    """`arp=36/0045` e `pregao=091/2073` eram o valor TOPO nos processos onde apareciam,
    corrompendo a leitura inteira daquele processo. Nenhum instrumento real tem ano 0045 ou 2073."""
    assert not extrair_deterministico("Ata de Registro de Preços nº 36/0045\n")["arp"]["valor"]
    assert not extrair_deterministico("Pregão Eletrônico nº 091/2073\n")["pregao"]["valor"]


def test_ano_POSTERIOR_ao_processo_continua_valendo():
    """Medido antes de decidir: 22 casos (4%) têm instrumento de ano seguinte, e é LEGÍTIMO — o
    processo ANTECEDE o contrato que ele cria. Filtrar isso trocaria 3 lixos por 22 acertos."""
    d = extrair_deterministico("Contrato nº 02/2023 firmado nos autos.\n", ano_proc=2022)
    assert d["contrato"]["valor"] == "02/2023"
