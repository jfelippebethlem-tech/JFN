# -*- coding: utf-8 -*-
"""Individualização de unidade/medida do item — para não comparar fardo com copinho.

Pedido do dono (2026-07-24): "tem alerta de unidade de água a 140 reais... e se um for
um fardo de garrafas de 1,5L e o outro for copinho de 200ML? temos que saber pra não
errar." Confirmado no dado real: 'AGUA MINERAL (CAIXA COM 48 COPOS DE 200ML)' a R$44,94
caía perto de 'AGUA MINERAL COPO DE 200 ML' a R$0,70 — 64× de falso sobrepreço.
"""
from __future__ import annotations

import pytest

from compliance_agent.medida_item import assinatura_medida, un_canon


# ── volume ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("desc,ml", [
    ("AGUA MINERAL 20 LITROS", 20000),
    ("AGUA MINERAL GARRAFAO 20 L", 20000),
    ("GALAO DE AGUA MINERAL NATURAL - 20LTS", 20000),
    ("agua mineral 500ml", 500),
    ("AGUA MINERAL COM GAS 510ml", 510),
    ("AGUA MINERAL 1,5L FARDO", 1500),
    ("AGUA MINERAL COPO DE 200 ML", 200),
    ("refrigerante 2l", 2000),
])
def test_extrai_volume_em_ml(desc, ml):
    assert assinatura_medida(desc)["ml"] == ml


def test_volume_ausente_e_none():
    assert assinatura_medida("AGUA MINERAL")["ml"] is None
    assert assinatura_medida("CADEIRA DE ESCRITORIO")["ml"] is None


def test_volume_vem_do_campo_unidade_quando_falta_na_descricao():
    """A descrição costuma não ter o tamanho, que vem em unidade_medida ('GARRAFÃO 20L')."""
    assert assinatura_medida("AGUA MINERAL NATURAL", unidade="GARRAFAO 20 L")["ml"] == 20000
    assert assinatura_medida("AGUA MINERAL", unidade="COPO 200ML")["ml"] == 200


def test_descricao_tem_prioridade_sobre_unidade():
    """Se ambos trazem volume, a descrição manda (é mais específica)."""
    assert assinatura_medida("AGUA 500ML", unidade="GARRAFAO 20L")["ml"] == 500


# ── embalagem / contagem ─────────────────────────────────────────────────────

@pytest.mark.parametrize("desc,n", [
    ("AGUA MINERAL (CAIXA COM 48 COPOS DE 200ML)", 48),
    ("AGUA MINERAL FARDO C/ 12", 12),
    ("AGUA COM 6 UNIDADES", 6),
    ("PACOTE COM 100 UNIDADES", 100),
    ("CERVEJA FARDO C/24", 24),
])
def test_extrai_contagem_da_embalagem(desc, n):
    assert assinatura_medida(desc)["n"] == n


def test_sem_embalagem_conta_1():
    assert assinatura_medida("AGUA MINERAL COPO DE 200 ML")["n"] == 1


# ── a assinatura separa produtos diferentes ──────────────────────────────────

def test_caixa_de_48_nao_bate_com_copo_avulso():
    caixa = assinatura_medida("AGUA MINERAL (CAIXA COM 48 COPOS DE 200ML)")
    copo = assinatura_medida("AGUA MINERAL COPO DE 200 ML")
    assert caixa["sig"] != copo["sig"]


def test_fardo_1_5L_nao_bate_com_copo_200ml():
    fardo = assinatura_medida("AGUA MINERAL 1,5L FARDO")
    copo = assinatura_medida("AGUA MINERAL COPO 200ML")
    assert fardo["sig"] != copo["sig"]


def test_mesmo_tamanho_mesma_assinatura():
    a = assinatura_medida("agua mineral 500ml")
    b = assinatura_medida("AGUA MINERAL SEM GAS 500 ML")
    assert a["sig"] == b["sig"] and a["sig"] != ""


def test_sem_medida_assinatura_vazia_nao_atrapalha():
    """Sem tamanho extraível → sig vazia = agrupa como hoje (nunca pior)."""
    assert assinatura_medida("AGUA MINERAL")["sig"] == ""
    assert assinatura_medida("CADEIRA")["sig"] == ""


# ── normalização do vocabulário de unidade ───────────────────────────────────

@pytest.mark.parametrize("bruto,canon", [
    ("Galao", "galao"), ("GALÃO", "galao"), ("GALAO", "galao"),
    ("GL", "galao"), ("GAL", "galao"),
    ("UN", "unidade"), ("UNIDADE", "unidade"), ("Unid", "unidade"),
    ("fardo", "fardo"), ("FARDO", "fardo"),
    ("Caixa", "caixa"), ("CX", "caixa"),
    ("GARRAFA", "garrafa"),
])
def test_unidade_canonica(bruto, canon):
    assert un_canon(bruto) == canon


def test_unidade_desconhecida_preserva_slug():
    assert un_canon("PESSOAS") == "pessoas"
    assert un_canon("") == ""


# ── un_canon com número/medida embutidos: retorna só o TIPO de recipiente ────

@pytest.mark.parametrize("bruto,canon", [
    ("Frasco 100,00 ML", "frasco"),
    ("Pacote 100,00 UN", "pacote"),
    ("Caixa 100,00 UN", "caixa"),
    ("Embalagem 1,00 KG", "embalagem"),
    ("Galão 3,60 L", "galao"),
    ("Ampola 2,00 ML", "ampola"),
    ("Rolo 100,00 M", "rolo"),
    ("Frasco-Ampola", "frasco_ampola"),
    ("UNIDADE 0,00", "unidade"),
])
def test_un_canon_ignora_numero_e_medida_secundaria(bruto, canon):
    assert un_canon(bruto) == canon


def test_un_canon_area_volume_nao_colapsam():
    """m² e m³ são medidas DIFERENTES de metro linear — não podem virar o mesmo grupo."""
    assert un_canon("Metro") == "metro"
    assert un_canon("METRO QUADRADO") == "m2"
    assert un_canon("M2") == "m2"
    assert un_canon("Metro Cúbico") == "m3"
    assert un_canon("M3") == "m3"
    assert len({un_canon("Metro"), un_canon("M2"), un_canon("M3")}) == 3


# ── peso (g/kg/mg) → gramas ──────────────────────────────────────────────────

@pytest.mark.parametrize("desc,un,g", [
    ("SABAO EM PO 1KG", None, 1000),
    ("ACUCAR 5 KG", None, 5000),
    ("cafe 500g", None, 500),
    ("ARROZ", "Embalagem 1,00 KG", 1000),
    ("dipirona 500 mg", None, 0.5),
])
def test_extrai_peso_em_gramas(desc, un, g):
    assert assinatura_medida(desc, un)["g"] == g


# ── contagem embutida no campo unidade ('Pacote 100,00 UN') ──────────────────

@pytest.mark.parametrize("un,n", [
    ("Pacote 100,00 UN", 100),
    ("Caixa 100,00 UN", 100),
    ("Embalagem 100,00 UN", 100),
    ("Pacote 50 UN", 50),
])
def test_contagem_vem_do_campo_unidade(un, n):
    assert assinatura_medida("LUVA DESCARTAVEL", un)["n"] == n


# ── contagens NOMEADAS (cento, milheiro, resma, dúzia) ───────────────────────

@pytest.mark.parametrize("desc,n", [
    ("TIJOLO CERAMICO - CENTO", 100),
    ("BLOCO MILHEIRO", 1000),
    ("PAPEL A4 RESMA", 500),
    ("OVO DUZIA", 12),
    ("PARAFUSO GROSA", 144),
])
def test_contagem_nomeada(desc, n):
    assert assinatura_medida(desc)["n"] == n


# ── a assinatura separa bases de medida diferentes ───────────────────────────

def test_pacote_de_100_nao_bate_com_unidade_avulsa():
    pac = assinatura_medida("LUVA", "Pacote 100,00 UN")
    avu = assinatura_medida("LUVA", "Unidade")
    assert pac["sig"] != avu["sig"] and pac["sig"] != ""


def test_1kg_nao_bate_com_500g():
    a = assinatura_medida("ACUCAR", "Embalagem 1,00 KG")
    b = assinatura_medida("ACUCAR 500 G")
    assert a["sig"] != b["sig"]


def test_resma_nao_bate_com_folha_avulsa():
    resma = assinatura_medida("PAPEL A4 RESMA")
    folha = assinatura_medida("PAPEL A4", "Folha")
    assert resma["sig"] != folha["sig"]


# ── falsos positivos reais achados no dado (regressão) ───────────────────────

def test_por_cento_nao_vira_contagem_cento():
    """'100 por cento poliéster' / 'álcool 70 por cento' ≠ embalagem de 100."""
    assert assinatura_medida("COBERTOR MICROFIBRA 100 por cento POLIESTER", "unidade")["n"] == 1
    assert assinatura_medida("ALCOOL 70 por cento", "Frasco 1,00 L")["n"] == 1


def test_cento_legitimo_ainda_conta():
    assert assinatura_medida("TIJOLO CERAMICO - CENTO")["n"] == 100


def test_carga_e_capacidade_nao_viram_peso():
    """'CARGA TOTAL: 200 KG' (cadeira) e 'SUPORTA 100 KG' são rating, não peso do produto."""
    assert assinatura_medida("CADEIRA CARGA TOTAL: 80 ~ 200 KG", "UN")["g"] is None
    assert assinatura_medida("PRATELEIRA SUPORTA 100 KG", "UN")["g"] is None


def test_peso_real_do_produto_mantido():
    assert assinatura_medida("RACAO", "Saco 20,00 KG")["g"] == 20000
    assert assinatura_medida("ACUCAR CRISTAL 5 KG")["g"] == 5000


# ── separador de MILHAR (bug ALTA-1: '1.500 ML' virava 1,5) ──────────────────

@pytest.mark.parametrize("desc,ml", [
    ("AGUA 1.500 ML", 1500),
    ("SUCO 2.500 ML", 2500),
    ("AGUA 1.5 L", 1500),        # decimal legítimo: 1,5 L = 1500 ml
    ("AGUA 500 ML", 500),
])
def test_milhar_no_volume(desc, ml):
    assert assinatura_medida(desc)["ml"] == ml


@pytest.mark.parametrize("desc,g", [
    ("SACO 1.000 KG", 1_000_000),   # 1000 kg = 1.000.000 g
    ("ACUCAR 5 KG", 5000),
    ("REMEDIO 1.500 MG", 1.5),      # 1500 mg = 1,5 g
])
def test_milhar_no_peso(desc, g):
    assert assinatura_medida(desc)["g"] == g


# ── doses sub-1 mL não podem colapsar (bug ALTA-2: 0,2 e 0,4 viravam ml=0) ────

def test_doses_subml_nao_colapsam():
    d02 = assinatura_medida("ENOXAPARINA", "Seringa 0,20 ML")
    d04 = assinatura_medida("ENOXAPARINA", "Seringa 0,40 ML")
    d06 = assinatura_medida("ENOXAPARINA", "Seringa 0,60 ML")
    assert d02["ml"] == 0.2 and d04["ml"] == 0.4 and d06["ml"] == 0.6
    # cada dose = grupo distinto (dobro de fármaco ≠ mesmo item)
    assert len({d02["sig"], d04["sig"], d06["sig"]}) == 3


def test_volume_zero_nao_vira_sig():
    """ml=0 (arredondamento antigo) não pode ser discriminador que junta itens não-relacionados."""
    assert "ml0" not in assinatura_medida("PARAFUSO 0 ML QUALQUER")["sig"]
