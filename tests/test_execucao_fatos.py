# -*- coding: utf-8 -*-
"""Ponte TEXTO → FATOS que os detectores X1 (aditivo) e X3 (execução financeira) já sabem julgar.

Descoberta ao executar o plano #4 (itens 2.1/2.2): a regra jurídica NÃO precisa ser reescrita — X1 já
calcula o teto do art. 125 (25%/50%, reajuste fora, prazo fora) e X3 já pega pagamento antes do atesto.
O que faltava era alguém EXTRAIR esses fatos do texto do processo SEI; sem isso os detectores ficavam
`nao_avaliavel` para sempre. Este módulo é essa ponte — e só ela (nenhum limiar legal vive aqui).
"""
from __future__ import annotations

from compliance_agent import execucao_fatos as EF

_TEXTO = (
    "CONTRATO Nº 45/2023, valor inicial de R$ 2.000.000,00 para reforma da cobertura. "
    "PRIMEIRO TERMO ADITIVO, de 10/03/2024: acréscimo de R$ 300.000,00 (15%) ao valor contratual, "
    "em razão de quantitativos subestimados no projeto básico. "
    "SEGUNDO TERMO ADITIVO, de 05/06/2024: prorrogação do prazo de vigência por 12 meses, sem "
    "acréscimo de valor. "
    "TERCEIRO TERMO ADITIVO, de 20/09/2024: reajuste contratual pelo IPCA no valor de R$ 120.000,00. "
    "QUARTO TERMO ADITIVO, de 01/11/2024: acréscimo de R$ 250.000,00 por ampliação dos serviços."
)


def test_valor_brasileiro():
    assert EF.valor_br("R$ 1.234.567,89") == 1234567.89
    assert EF.valor_br("R$ 300.000,00") == 300000.0
    assert EF.valor_br("sem valor") is None


def test_extrai_valor_inicial_do_contrato():
    assert EF.extrair_valor_inicial(_TEXTO) == 2000000.0


def test_extrai_aditivos_classificando_o_tipo():
    ads = EF.extrair_aditivos(_TEXTO)
    assert len(ads) == 4
    tipos = [a["tipo"] for a in ads]
    assert tipos == ["valor", "prazo", "reajuste", "valor"]
    assert ads[0]["valor"] == 300000.0 and ads[0]["data"] == "2024-03-10"
    assert ads[1]["valor"] in (None, 0, 0.0)          # prorrogação não carrega acréscimo
    assert ads[3]["valor"] == 250000.0
    assert all(a["trecho"] for a in ads)              # cada fato com o trecho literal que o sustenta


def test_reajuste_nao_conta_no_teto_do_art125():
    # a regra é do X1 — aqui só se garante que a PONTE entrega o tipo que o X1 sabe excluir
    from compliance_agent.detectores.x1_crescimento_aditivo import _conta_no_teto
    ads = EF.extrair_aditivos(_TEXTO)
    assert [_conta_no_teto(a) for a in ads] == [True, False, False, True]


def test_contexto_x1_pronto_para_o_detector():
    ctx = EF.contexto_x1(_TEXTO)
    assert ctx["valor_inicial"] == 2000000.0
    assert ctx["tipo_objeto"] == "reforma"            # teto de 50% (art. 125) — quem aplica é o X1
    assert len(ctx["aditivos"]) == 4


def test_sem_dado_nao_inventa():
    ctx = EF.contexto_x1("Despacho de encaminhamento ao setor competente.")
    assert ctx["valor_inicial"] is None and ctx["aditivos"] == []


# ───────────────────────────── X3: datas da despesa × atesto ─────────────────────────────

_PGTO = (
    "Nota de Empenho 2024NE000123 emitida em 02/04/2024, no valor de R$ 150.000,00. "
    "Nota de Liquidação 2024NL000456 em 03/04/2024. "
    "Ordem Bancária 2024OB000789 paga em 04/04/2024. "
    "Atesto do fiscal do contrato em 20/04/2024, após o boletim de medição de 18/04/2024."
)


def test_extrai_a_triade_e_o_atesto():
    p = EF.extrair_pagamentos(_PGTO)
    assert len(p) == 1
    assert p[0]["data_empenho"] == "2024-04-02"
    assert p[0]["data_liquidacao"] == "2024-04-03"
    assert p[0]["data_pagamento"] == "2024-04-04"
    assert p[0]["data_atesto"] == "2024-04-20"
    assert p[0]["valor"] == 150000.0


def test_contexto_x3_flagra_pagamento_antes_do_atesto():
    # o julgamento é do X3 (art. 63 Lei 4.320 / atesto prévio); aqui só se garante o insumo correto
    ctx = EF.contexto_x3(_PGTO)
    pg = ctx["pagamentos"][0]
    assert pg["data_pagamento"] < pg["data_atesto"]    # pagou 04/04, atestou 20/04
    assert ctx["pagamento_anterior_ao_atesto"] is True


def test_atesto_anterior_ao_pagamento_nao_acusa():
    txt = ("Atesto do fiscal em 10/05/2024. Nota de Empenho 2024NE000999 em 12/05/2024. "
           "Ordem Bancária 2024OB000999 paga em 20/05/2024 no valor de R$ 80.000,00.")
    ctx = EF.contexto_x3(txt)
    assert ctx["pagamento_anterior_ao_atesto"] is False


def test_sem_ob_nao_afirma_pagamento(monkeypatch=None):
    # §2: empenho não é pagamento — sem OB, não há data_pagamento (nunca se presume)
    ctx = EF.contexto_x3("Nota de Empenho 2024NE000123 em 02/04/2024. Atesto em 01/04/2024.")
    assert ctx["pagamentos"][0]["data_pagamento"] is None
    assert ctx["pagamento_anterior_ao_atesto"] is False   # não se acusa antecipação sem pagamento


# ═══ só a ORDEM BANCÁRIA é pagamento — e o que a identifica é o código (2026-08-04) ═══

def test_pagamento_exige_o_CODIGO_da_ob_nao_a_palavra():
    """Medido nos 80 processos de maior risco: 3 tinham código de OB e **9 tinham só as palavras
    "ordem bancária"** perdidas num bloco de OCR — inclusive numa página de "Detalhamento de
    Empenho". Era dessa data que o X3 dizia "pago ANTES do atesto", chamando de pagamento o que
    era EMPENHO. Regra-mãe da casa: empenho ≠ liquidação ≠ OB."""
    from compliance_agent.execucao_fatos import extrair_pagamentos
    so_termo = ("Nota de empenho emitida em 01/03/2025. O setor informa que a ordem bancária "
                "será processada conforme a rotina.")
    p = extrair_pagamentos(so_termo)
    assert p and p[0].get("data_pagamento") is None, "palavra solta não prova pagamento"

    com_codigo = ("Nota de empenho emitida em 01/03/2025. Ordem bancária 2025OB000789 paga em "
                  "10/03/2025.")
    p2 = extrair_pagamentos(com_codigo)
    assert p2 and p2[0].get("data_pagamento") == "2025-03-10"


def test_empenho_e_liquidacao_seguem_reconhecidos_pelo_termo():
    """O aperto é só do PAGAMENTO: empenho e liquidação continuam identificáveis pelo termo, ou
    a tríade inteira sumiria."""
    from compliance_agent.execucao_fatos import extrair_pagamentos
    p = extrair_pagamentos("Nota de empenho de 01/03/2025. Liquidação em 05/03/2025.")
    assert p and p[0]["data_empenho"] == "2025-03-01" and p[0]["data_liquidacao"] == "2025-03-05"


def test_data_longe_do_termo_nao_qualifica_o_marco():
    """`_sentencas` corta em ponto-e-vírgula e num PDF de nota fiscal devolve blocos de página
    inteira: medido em 2026-08-04, as "frases" do atesto tinham 780 e 506 caracteres e a data
    saía de outro canto do bloco — o X3 anunciava "pago ANTES do atesto" com atesto 20 meses no
    futuro. O dado que qualifica um termo mora ao lado dele."""
    from compliance_agent.execucao_fatos import extrair_pagamentos
    longe = ("atesto de recebimento do material" + " x" * 200 + " 30/09/2026 "
             "Ordem bancária 2025OB000001 paga em 10/03/2025.")
    p = extrair_pagamentos(longe)
    assert p and p[0].get("data_atesto") is None, "data a 400 chars do termo não é do atesto"


def test_data_ao_lado_do_termo_continua_valendo():
    from compliance_agent.execucao_fatos import extrair_pagamentos
    perto = "Atesto do recebimento em 30/09/2025. Ordem bancária 2025OB000001 paga em 10/10/2025."
    p = extrair_pagamentos(perto)
    assert p and p[0]["data_atesto"] == "2025-09-30" and p[0]["data_pagamento"] == "2025-10-10"


# ═══ de onde sai o VALOR INICIAL: força da declaração, não posição (2026-08-04) ═══

def test_clausula_do_contrato_vence_valor_solto_de_errata():
    """Medido no SEI-070002/001289/2022: o padrão antigo pegava a PRIMEIRA ocorrência num monte
    de dezenas de documentos e colheu "VALOR DO CONTRATO: R$ 46.866,00" de uma *Publicação
    Errata 01*; o X1 anunciou acréscimo de 10.024%. O contrato é de R$ 105.988.095,41, declarado
    dezesseis vezes com fórmulas que o padrão não alcançava."""
    from compliance_agent.execucao_fatos import extrair_valor_inicial
    texto = ("Publicação Errata 01 ... VALOR DO CONTRATO: R$ 46.866,00 ... "
             "CLÁUSULA SEGUNDA: DO VALOR DO CONTRATO. O valor total do presente Contrato é de "
             "R$ 105.988.095,41 ... com valor inicial contratual de R$ 105.988.095,41")
    assert extrair_valor_inicial(texto) == 105_988_095.41


def test_dentro_da_mesma_forca_vence_o_mais_repetido():
    """Comparar declarações do MESMO tipo é legítimo — a lição do G2 foi não adivinhar entre
    coisas diferentes, e aqui todas são a mesma fórmula."""
    from compliance_agent.execucao_fatos import extrair_valor_inicial
    texto = ("valor inicial contratual de R$ 1.000.000,00. valor inicial contratual de "
             "R$ 9.999.999,99. valor inicial contratual de R$ 1.000.000,00")
    assert extrair_valor_inicial(texto) == 1_000_000.00


def test_sem_nenhuma_declaracao_devolve_None():
    from compliance_agent.execucao_fatos import extrair_valor_inicial
    assert extrair_valor_inicial("processo sem valor declarado") is None
