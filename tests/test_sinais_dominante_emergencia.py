# -*- coding: utf-8 -*-
"""Quem é a empresa que concentra a emergência — e o que NÃO sabemos dela.

Cruzando os fornecedores dominantes dos 28 grupos de emergência (R$ 2,08 bi) com o cadastro:

    BRASVIP SEGURANÇA .... aberta 2020-10-28 · 92% de R$ 60,9 mi no DER-RJ em 2025
    UP MED ............... aberta 2020-10-19 · 45% de R$ 120,1 mi no HU/UERJ em 2024
    AGILE CORP ........... NÃO consta no cadastro local · 100% de R$ 159,7 mi na SEEDUC
    SAVVY SERVIÇOS ....... NÃO consta no cadastro local ·  98% de R$ 32,9 mi na UERJ

Dois sinais distintos, e confundi-los seria erro:

· **empresa recente** concentrando emergência é indício a apurar — não prova de nada, porque
  empresa nova pode ser idônea e o mercado tem entrantes legítimos;
· **ausência no cadastro** NÃO é sinal sobre a empresa: é lacuna NOSSA, de enriquecimento. Tratar
  como suspeita seria transformar buraco de dado em acusação, que é o erro que esta casa
  persegue desde sempre (INDISPONÍVEL ≠ irregular).
"""
from compliance_agent.fracionamento_emergencia import sinais_do_dominante

GRUPO = {"unidade": "DER-RJ", "exercicio": 2025, "n": 7, "total": 60_884_229.86,
         "fornecedor_dominante": "BRASVIP SEGURANCA PRIVADA LTDA",
         "concentracao_dominante": 0.92}


def test_empresa_recente_concentrando_vira_indicio():
    s = sinais_do_dominante(GRUPO, cadastro={"situacao": "ATIVA", "data_abertura": "2020-10-28"})
    assert any("recente" in x.lower() or "aberta" in x.lower() for x in s["sinais"])


def test_empresa_antiga_nao_vira_indicio_por_idade():
    s = sinais_do_dominante(GRUPO, cadastro={"situacao": "ATIVA", "data_abertura": "1972-01-12"})
    assert not any("recente" in x.lower() for x in s["sinais"])


def test_ausencia_no_cadastro_e_LACUNA_nossa_nao_sinal_contra_a_empresa():
    s = sinais_do_dominante(GRUPO, cadastro=None)
    # a concentração continua sendo sinal — ela é sobre o PADRÃO de contratação, não sobre a
    # empresa. O que não pode virar sinal é a ausência de dado.
    assert not any("cadastro" in x.lower() or "não consta" in x.lower() for x in s["sinais"]), \
        "buraco de dado não vira indício contra a empresa"
    assert s["lacunas"], "mas a lacuna precisa aparecer, para ser preenchida"
    assert "cadastro" in s["lacunas"][0].lower()


def test_situacao_cadastral_irregular_e_sinal_forte():
    s = sinais_do_dominante(GRUPO, cadastro={"situacao": "BAIXADA", "data_abertura": "2010-01-01"})
    assert any("baixada" in x.lower() or "irregular" in x.lower() for x in s["sinais"])


def test_concentracao_baixa_nao_gera_sinal_de_dominancia():
    g = {**GRUPO, "concentracao_dominante": 0.11}
    s = sinais_do_dominante(g, cadastro={"situacao": "ATIVA", "data_abertura": "2020-10-28"})
    assert not any("concentr" in x.lower() for x in s["sinais"])


def test_concentracao_total_e_o_sinal_mais_forte():
    g = {**GRUPO, "concentracao_dominante": 1.0}
    s = sinais_do_dominante(g, cadastro={"situacao": "ATIVA", "data_abertura": "1990-01-01"})
    assert any("100%" in x or "integral" in x.lower() for x in s["sinais"])


def test_data_de_abertura_ilegivel_vira_lacuna_e_nao_sinal():
    s = sinais_do_dominante(GRUPO, cadastro={"situacao": "ATIVA", "data_abertura": "sem data"})
    assert not any("recente" in x.lower() for x in s["sinais"])
    assert any("abertura" in x.lower() for x in s["lacunas"])
