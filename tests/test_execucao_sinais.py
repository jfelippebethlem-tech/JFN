# -*- coding: utf-8 -*-
"""Camada DETERMINÍSTICA de EXECUÇÃO SEM COMPROVAÇÃO (#4, 2026-07-24).

Complementa o `lex_execucao` (que é SÓ LLM) com um sinal offline: pagamento (OB/empenho/liquidação)
presente no processo, mas FALTAM as provas de entrega (medição, nota fiscal, atesto/recebimento). Não fica
cego quando a IA cai. Calibração SENSÍVEL (dono: "rodar sensível e ir filtrando"): dispara na ausência —
mas HONESTO: INDISPONÍVEL ≠ irregular; é FRAGILIDADE a verificar (pode ser captura incompleta), não acusação.
"""
from __future__ import annotations

from compliance_agent import execucao_sinais as ES


def _pgto(extra=""):
    return ("PROCESSO DE PAGAMENTO. Nota de Empenho nº 2024NE000123. Liquidação e Ordem Bancária "
            "para pagamento do valor de R$ 100.000,00 ao fornecedor. " + extra)


def test_pagamento_com_todas_as_provas_verde():
    # verde EXIGE o atesto lastreado por relatório fotográfico (dono: atesto não basta existir)
    txt = _pgto("Boletim de medição anexo. Nota fiscal nº 555. Atesto de recebimento definitivo pelo fiscal. "
                "Relatório fotográfico da execução em anexo.")
    r = ES.analisar_execucao_det(txt)
    assert r["grau"] == "verde"
    assert r["grau"] not in ("indeterminado", "indisponivel")


def test_atesto_sem_relatorio_fotografico_e_fragilidade():
    # medição+NF+atesto presentes, mas SEM relatório fotográfico → atesto "seco" → amarelo
    txt = _pgto("Boletim de medição. Nota fiscal nº 555. Atesto de recebimento definitivo pelo fiscal.")
    r = ES.analisar_execucao_det(txt)
    assert r["grau"] == "amarelo"
    assert r["atesto_sem_foto"] is True
    assert any(s["tipo"] == "atesto_sem_relatorio_fotografico" for s in r["sinais"])
    assert any("sentido" in s["observacao"].lower() for s in r["sinais"])   # marca a coerência p/ o LLM


def test_nota_fiscal_cancelada_vermelho():
    txt = _pgto("Boletim de medição. Atesto pelo fiscal. Relatório fotográfico. "
                "Observação: a nota fiscal foi cancelada após a emissão.")
    r = ES.analisar_execucao_det(txt)
    assert r["grau"] == "vermelho"
    assert any(s["tipo"] == "nota_fiscal_cancelada" for s in r["sinais"])


def test_nota_fiscal_em_contingencia_sinaliza():
    txt = _pgto("Nota fiscal emitida em contingência (EPEC). Boletim de medição. Atesto. Relatório fotográfico.")
    r = ES.analisar_execucao_det(txt)
    assert any(s["tipo"] == "nota_fiscal_contingencia" for s in r["sinais"])
    assert r["grau"] in ("amarelo", "vermelho")
    # a verificação live na SEFAZ (chave de acesso) fica registrada como a_verificar
    assert any("sefaz" in x.lower() for x in r["a_verificar"])


def test_pagamento_faltando_nf_amarelo_com_trecho():
    txt = _pgto("Boletim de medição anexo. Atesto de recebimento pelo fiscal do contrato.")
    r = ES.analisar_execucao_det(txt)
    assert r["grau"] == "amarelo"
    assert "nota_fiscal" in r["faltantes"]
    assert any(s.get("trecho") for s in r["sinais"])          # cada achado tem trecho literal
    assert "medicao" not in r["faltantes"] and "atesto" not in r["faltantes"]


def test_pagamento_sem_nenhuma_prova_vermelho():
    txt = _pgto("Despacho de encaminhamento para pagamento imediato.")
    r = ES.analisar_execucao_det(txt)
    assert r["grau"] == "vermelho"
    assert set(("medicao", "nota_fiscal", "atesto")).issubset(set(r["faltantes"]))
    assert "fragilidade" in r["resumo"].lower() or "verificar" in r["resumo"].lower()  # honesto


def test_sem_contexto_de_pagamento_nao_aplicavel():
    r = ES.analisar_execucao_det("EDITAL DE PREGÃO. Termo de referência. Habilitação e qualificação técnica.")
    assert r["grau"] == "nao_aplicavel"
    assert r["grau"] not in ("indeterminado", "indisponivel")


def test_honesto_ausencia_nao_e_acusacao():
    r = ES.analisar_execucao_det(_pgto())
    # sensível dispara, mas o texto deixa claro que é fragilidade (captura incompleta OU não comprovada)
    assert "≠" in r["ressalva"] or "indispon" in r["ressalva"].lower() or "fragil" in r["resumo"].lower()


# ---------------------------------------------------------------- §2: OB ≠ empenho (calibração 1.4)

def test_empenho_sem_ob_nao_e_pagamento_efetivo():
    # SÓ empenho (compromisso, cancelável) e NENHUMA prova: fragilidade REAL, mas não "pagou sem prova"
    txt = ("Nota de Empenho nº 2024NE000123 emitida em favor do fornecedor no valor de R$ 100.000,00. "
           "Despacho de encaminhamento.")
    r = ES.analisar_execucao_det(txt)
    assert r["tem_empenho"] is True and r["tem_ob"] is False
    assert r["estagio_despesa"] == "empenho"
    assert r["pagamento_efetivo"] is False
    assert r["grau"] == "amarelo"          # teto: sem OB não houve pagamento (§2)
    assert "empenho" in r["resumo"].lower()


def test_ob_sem_nenhuma_prova_vermelho_pagamento_efetivo():
    txt = ("Ordem Bancária emitida para pagamento do valor de R$ 100.000,00. Despacho de encaminhamento.")
    r = ES.analisar_execucao_det(txt)
    assert r["tem_ob"] is True and r["pagamento_efetivo"] is True
    assert r["estagio_despesa"] == "ob"
    assert r["grau"] == "vermelho"


def test_codigo_ob_do_siafe_conta_como_pagamento_efetivo():
    txt = "Documento 2025OB800123 processado. Despacho de encaminhamento ao setor."
    r = ES.analisar_execucao_det(txt)
    assert r["tem_ob"] is True and r["estagio_despesa"] == "ob"


def test_liquidacao_sem_ob_nao_e_pagamento_efetivo():
    txt = "Nota de Liquidação 2025NL000777 da despesa. Sem mais documentos."
    r = ES.analisar_execucao_det(txt)
    assert r["tem_liquidacao"] is True and r["tem_ob"] is False
    assert r["estagio_despesa"] == "liquidacao" and r["pagamento_efetivo"] is False
    assert r["grau"] == "amarelo"


def test_nf_cancelada_e_vermelha_mesmo_sem_ob():
    # vício do documento independe do estágio da despesa (o teto do §2 vale só p/ ausência de prova)
    txt = "Nota de Empenho nº 2024NE000123. A nota fiscal foi cancelada após a emissão."
    r = ES.analisar_execucao_det(txt)
    assert r["grau"] == "vermelho"
    assert any(s["tipo"] == "nota_fiscal_cancelada" for s in r["sinais"])


def test_grau_nunca_indeterminado_nem_indisponivel():
    for txt in ("", "qualquer coisa", _pgto(), _pgto("nota fiscal e medição e atesto")):
        assert ES.analisar_execucao_det(txt)["grau"] not in ("indeterminado", "indisponivel")
