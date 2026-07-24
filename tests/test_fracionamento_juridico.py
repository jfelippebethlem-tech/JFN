# -*- coding: utf-8 -*-
"""Aplicação JURIDICAMENTE CORRETA da regra do fracionamento (art. 75, Lei 14.133/2021).

Pedido do dono (2026-07-24). O texto legal manda coisas específicas que o detector não aplicava:

  §1º "Para fins de aferição dos valores que atendam aos limites referidos nos incisos I e II do caput,
       deverão ser observados:
       I  - o somatório do que for despendido no EXERCÍCIO FINANCEIRO pela respectiva UNIDADE GESTORA;
       II - o somatório da despesa realizada com objetos de MESMA NATUREZA, entendidos como tais aqueles
            relativos a contratações no MESMO RAMO DE ATIVIDADE."
  §2º "Os valores referidos nos incisos I e II do caput serão DUPLICADOS para compras, obras e serviços
       contratados por CONSÓRCIO PÚBLICO ou por AUTARQUIA ou FUNDAÇÃO qualificadas como AGÊNCIAS
       EXECUTIVAS."

Consequências que estes testes travam:
  • "mesma natureza" é RAMO DE ATIVIDADE — mais amplo que "objeto idêntico" (somar só o idêntico
    SUBESTIMA o fracionamento, que é exatamente a manobra que a lei quer alcançar);
  • o somatório é por UNIDADE GESTORA — misturar unidades no mesmo somatório é ilegal e infla o indício;
  • o limite DOBRA para consórcio público / autarquia-fundação qualificada como agência executiva;
  • só a dispensa POR VALOR (incisos I e II do caput) entra no somatório — emergência, calamidade,
    guerra e demais incisos têm outro fundamento e NÃO somam para o teto de valor.
"""
from __future__ import annotations

from compliance_agent import objeto_similaridade as OS
from compliance_agent.detectores.p4_fracionamento import P4Fracionamento
from compliance_agent.limites_dispensa import limite_dispensa

P4 = P4Fracionamento()


# ───────────────────── §1º, II — mesma natureza = mesmo RAMO DE ATIVIDADE ─────────────────────

def test_ramo_de_atividade_agrupa_objetos_do_mesmo_ramo():
    assert OS.ramo_atividade("Aquisição de material de limpeza") == "limpeza_higiene"
    assert OS.ramo_atividade("Compra de desinfetante e papel higiênico") == "limpeza_higiene"
    assert OS.ramo_atividade("Aquisição de gêneros alimentícios para a merenda") == "alimentacao"
    assert OS.ramo_atividade("Contratação de serviços de vigilância patrimonial") == "vigilancia"
    assert OS.ramo_atividade("Objeto indefinido qualquer") is None


def test_agrupamento_legal_e_por_ramo_nao_por_objeto_identico():
    # sabão em pó e desinfetante NÃO são o mesmo objeto, mas são o mesmo RAMO (§1º, II) — somam
    lote = [{"objeto": "Aquisição de sabão em pó"},
            {"objeto": "Aquisição de desinfetante e água sanitária"},
            {"objeto": "Aquisição de pneus para a frota"}]
    cl = OS.agrupar(lote, por_ramo=True)
    grupo0 = next(g for g in cl if 0 in g)
    assert 1 in grupo0                      # mesmo ramo (limpeza/higiene) → soma
    assert 2 not in grupo0                  # ramo distinto (veículos) → não soma


def test_agrupamento_fino_continua_disponivel_para_o_dossie():
    # o cluster por objeto (TF-IDF) segue existindo — é o DETALHE que o auditor lê; o legal é o ramo
    lote = [{"objeto": "Aquisição de sabão em pó"}, {"objeto": "Aquisição de desinfetante"}]
    assert OS.agrupar(lote, por_ramo=False) == [[0], [1]]
    assert OS.agrupar(lote, por_ramo=True) == [[0, 1]]


def test_preambulo_burocratico_nao_agrupa_por_si():
    # regressão do dado REAL: descrições que começam iguais ("O OBJETIVO DESTE TERMO DE REFERÊNCIA É...")
    # agrupavam por boilerplate, não por objeto
    a = "O objetivo deste Termo de Referência é estabelecer as condições para contratação de empresa especializada em pintura predial"
    b = "O objetivo deste Termo de Referência é estabelecer as condições para contratação de empresa especializada em locação de veículos"
    assert OS.agrupar([{"objeto": a}, {"objeto": b}]) == [[0], [1]]


# ───────────────────── §2º — limites DUPLICADOS ─────────────────────

def test_paragrafo_2_duplica_o_limite():
    normal = limite_dispensa(2025, "compras")
    assert limite_dispensa(2025, "compras", duplicado=True) == normal * 2
    assert limite_dispensa(2025, "obras", duplicado=True) == limite_dispensa(2025, "obras") * 2


def test_consorcio_publico_nao_estoura_com_o_limite_dobrado():
    # soma R$ 100.000 em 2025: estoura o limite simples (62.725,59) mas NÃO o dobrado (125.451,18)
    cs = [{"objeto": "material de limpeza", "valor": 50000.0, "dispensa": True,
           "data": "2025-03-01", "unidade": "UG1"},
          {"objeto": "produtos de limpeza", "valor": 50000.0, "dispensa": True,
           "data": "2025-04-01", "unidade": "UG1"}]
    normal = P4.avaliar({"contratacoes": cs})
    dobrado = P4.avaliar({"contratacoes": cs, "consorcio_publico": True})
    assert normal.valores["limite_dispensa_vigente"] * 2 == dobrado.valores["limite_dispensa_vigente"]
    assert dobrado.valores["limite_duplicado_art75_p2"] is True
    assert any("75" in (r or "") and "§2" in (r or "") for r in [dobrado.valores.get("fundamento_limite", "")])
    assert normal.score > dobrado.score      # com o limite legal correto, o indício some/reduz


def test_agencia_executiva_tambem_duplica():
    cs = [{"objeto": "material de limpeza", "valor": 40000.0, "dispensa": True, "data": "2025-03-01"},
          {"objeto": "produtos de limpeza", "valor": 40000.0, "dispensa": True, "data": "2025-04-01"}]
    r = P4.avaliar({"contratacoes": cs, "agencia_executiva": True})
    assert r.valores["limite_duplicado_art75_p2"] is True


# ───────────────────── §1º, I — somatório por UNIDADE GESTORA ─────────────────────

def test_nao_soma_entre_unidades_gestoras_distintas():
    # mesma natureza, mesmo exercício, MAS unidades gestoras diferentes: o §1º, I manda somar por UG
    cs = [{"objeto": "material de limpeza", "valor": 40000.0, "dispensa": True,
           "data": "2025-03-01", "unidade": "SECRETARIA A"},
          {"objeto": "produtos de limpeza", "valor": 40000.0, "dispensa": True,
           "data": "2025-04-01", "unidade": "SECRETARIA B"}]
    r = P4.avaliar({"contratacoes": cs})
    assert r.status in ("descartado", "nao_avaliavel") or r.score <= 0.3
    assert "unidade" in (r.motivo_refutacao or r.explicacao_inocente or "").lower()


def test_soma_dentro_da_mesma_unidade_gestora():
    cs = [{"objeto": "material de limpeza", "valor": 40000.0, "dispensa": True,
           "data": "2025-03-01", "unidade": "SECRETARIA A"},
          {"objeto": "produtos de limpeza", "valor": 40000.0, "dispensa": True,
           "data": "2025-04-01", "unidade": "SECRETARIA A"}]
    r = P4.avaliar({"contratacoes": cs})
    assert r.score >= 0.6
    assert r.valores["unidade_gestora"] == "SECRETARIA A"


# ───────────────────── só a dispensa POR VALOR soma ─────────────────────

def test_dispensa_de_emergencia_nao_soma_para_o_teto_de_valor():
    # art. 75, VIII (emergência/calamidade) tem outro fundamento — não é dispensa POR VALOR
    cs = [{"objeto": "material de limpeza", "valor": 40000.0, "dispensa": True, "data": "2025-03-01",
           "unidade": "UG1", "enquadramento_legal": "Art. 75, inciso VIII - emergência"},
          {"objeto": "produtos de limpeza", "valor": 40000.0, "dispensa": True, "data": "2025-04-01",
           "unidade": "UG1", "enquadramento_legal": "Art. 75, inciso VIII - emergência"}]
    r = P4.avaliar({"contratacoes": cs})
    assert r.status in ("descartado", "nao_avaliavel") or r.score <= 0.3


def test_dispensa_por_valor_inciso_ii_soma():
    cs = [{"objeto": "material de limpeza", "valor": 40000.0, "dispensa": True, "data": "2025-03-01",
           "unidade": "UG1", "enquadramento_legal": "Art. 75, inciso II - dispensa por valor"},
          {"objeto": "produtos de limpeza", "valor": 40000.0, "dispensa": True, "data": "2025-04-01",
           "unidade": "UG1", "enquadramento_legal": "Art. 75, inciso II"}]
    r = P4.avaliar({"contratacoes": cs})
    assert r.score >= 0.6


def test_fundamento_legal_citado_no_achado():
    cs = [{"objeto": "material de limpeza", "valor": 40000.0, "dispensa": True, "data": "2025-03-01",
           "unidade": "UG1"},
          {"objeto": "produtos de limpeza", "valor": 40000.0, "dispensa": True, "data": "2025-04-01",
           "unidade": "UG1"}]
    r = P4.avaliar({"contratacoes": cs})
    fund = r.valores.get("fundamento_agrupamento", "")
    assert "75" in fund and ("§1" in fund or "ramo" in fund.lower())
