# -*- coding: utf-8 -*-
"""Atesto não tem data no FUTURO — ele certifica o que já foi entregue.

Data posterior a hoje é, por definição, outra coisa: validade de certidão, fim de vigência,
cronograma. Medido em 2026-08-05 nos **3 achados X3 do acervo**, todos "pago ANTES do atesto":

    pago 2024-12-27 → "atesto" 2026-09-30   (21 meses depois, e no FUTURO)
    pago 2024-07-10 → "atesto" 2025-09-30   (14 meses depois)
    pago 2024-07-10 → "atesto" 2026-03-31   (20 meses depois)

Todas em fim de trimestre — a assinatura de validade de CND, não de atesto de execução.

A janela de 160 caracteres (`_JANELA_MARCO`, 2026-08-04) reduziu esse erro mas não o eliminou:
dentro da janela ainda cabe a data errada. Esta guarda é de outra natureza e não depende de
distância no texto — **é o calendário que decide**.

⚠️ Empenho ≠ liquidação ≠ OB: a data de pagamento aqui só existe com o código da Ordem Bancária,
regra que a casa já aplicava desde 2026-08-04.
"""
from __future__ import annotations

from datetime import date, timedelta

from compliance_agent.execucao_fatos import contexto_x3

_BASE = ("Nota de empenho 2024NE00123 emitida em 10/01/2024. "
         "Ordem bancária 2024OB000789 paga em 10/07/2024. ")


def test_atesto_com_data_futura_e_descartado():
    futuro = (date.today() + timedelta(days=400)).strftime("%d/%m/%Y")
    r = contexto_x3(_BASE + f"Atesto conforme certidão válida até {futuro}.")
    assert r["pagamento_anterior_ao_atesto"] is False
    assert r["pagamentos"][0]["data_atesto"] is None


def test_atesto_passado_continua_valendo():
    """A correção não pode desarmar o achado verdadeiro: pagamento antes de um atesto REAL."""
    r = contexto_x3(_BASE + "Atesto de execução firmado em 20/08/2024.")
    assert r["pagamentos"][0]["data_atesto"] == "2024-08-20"
    assert r["pagamento_anterior_ao_atesto"] is True


def test_sem_ordem_bancaria_nao_ha_pagamento():
    """Só a OB é pagamento — empenho e liquidação não são (regra §2 da casa)."""
    r = contexto_x3("Nota de empenho 2024NE00123 em 10/01/2024. "
                    "Atesto de execução firmado em 20/08/2024.")
    assert r["pagamentos"][0]["data_pagamento"] is None
    assert r["pagamento_anterior_ao_atesto"] is False


# ── as fórmulas que a Administração usa de verdade (2026-08-06) ───────────────

def test_carimbo_do_almoxarifado_conta_como_atestacao():
    """O atesto de compra de material é o carimbo na própria nota. Medido lendo os autos dos 118
    disparos de `X_PAGAMENTO_SEM_ATESTACAO`: a primeira versão do vocabulário perdia
    *"Recebi, a contento, o(s) material(is) constante(s) desta Nota Fiscal. Assinatura e Carimbo"*
    e o canhoto do DANFE *"Recebemos de <fornecedor> os produtos/serviços constantes da Nota
    Fiscal"*. Acusar de "pagou sem atestar" quem tem canhoto assinado é acusar o normal."""
    ob = "Ordem bancária 2024OB000789 paga em 10/07/2024. "
    for texto in ("Recebi, a contento, o(s) material(is) constante(s) desta Nota Fiscal. "
                  "Assinatura e Carimbo",
                  "Recebemos de Medical Suture Comércio de Material Hospitalar Ltda os "
                  "produtos/serviços constantes da Nota Fiscal indicada ao lado"):
        assert contexto_x3(ob + texto)["atestacao_ausente"] is False, texto[:50]


def test_rodape_de_assinatura_do_sei_nao_e_atestacao():
    """*"A autenticidade deste documento pode ser CONFERIDA no site sei.rj.gov.br"* aparece em TODO
    documento assinado eletronicamente — é prova da assinatura, não do recebimento. Se entrasse no
    vocabulário, o detector jamais acusaria coisa alguma."""
    ob = "Ordem bancária 2024OB000789 paga em 10/07/2024. "
    rodape = ("A autenticidade deste documento pode ser conferida no site "
              "http://sei.rj.gov.br/sei/controlador_externo.php informando o código verificador.")
    assert contexto_x3(ob + rodape)["atestacao_ausente"] is True
