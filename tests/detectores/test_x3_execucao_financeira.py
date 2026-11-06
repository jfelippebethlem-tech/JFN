

# ═══ tríade sem os três marcos: leitura quebrada, não velocidade (2026-08-04) ═══

def _x3():
    from compliance_agent.detectores.x3_execucao_financeira import X3ExecucaoFinanceira
    return X3ExecucaoFinanceira()


def test_empenho_e_pagamento_na_MESMA_data_nao_e_triade_comprimida():
    """Medido nos processos de maior risco: TODO disparo de "ciclo de 0 dias" tinha
    `data_empenho == data_pagamento`. As etapas são colhidas pela 1ª frase que menciona cada uma
    num monte de documentos concatenados — um documento que cita empenho E ordem bancária dá a
    MESMA data para as duas. Empenho ≠ liquidação ≠ OB: são três eventos, não um lido duas vezes.
    """
    r = _x3().avaliar({"processo": "P-1", "pagamentos": [
        {"data_empenho": "2026-02-01", "data_liquidacao": "2026-05-11",
         "data_pagamento": "2026-02-01", "valor": 10_000.0}]})
    assert r.valores.get("triade_degenerada") is True
    assert r.status != "confirmado" and r.score == 0.0
    assert "não formam tríade" in (r.motivo_refutacao or ""), \
        "o descarte tem de dizer que a LEITURA quebrou, não que o processo é regular"


def test_liquidacao_fora_da_ordem_legal_denuncia_a_leitura_e_nao_o_processo():
    """260006/006916/2025: empenho 27/08, liquidação 16/06 — liquidar antes de empenhar não é
    anomalia do processo, é prova de que os marcos não são o que se supôs."""
    r = _x3().avaliar({"processo": "P-2", "pagamentos": [
        {"data_empenho": "2025-08-27", "data_liquidacao": "2025-06-16",
         "data_pagamento": "2025-08-28", "valor": 10_000.0}]})
    assert r.valores.get("triade_degenerada") is True


def test_triade_ORDENADA_e_curta_continua_sendo_indicio():
    """O corte não pode virar anistia: três marcos distintos, na ordem legal e com ciclo curto,
    continuam pontuando."""
    r = _x3().avaliar({"processo": "P-3", "pagamentos": [
        {"data_empenho": "2025-03-01", "data_liquidacao": "2025-03-01",
         "data_pagamento": "2025-03-02", "valor": 10_000.0}]})
    assert r.valores.get("triade_degenerada") is False
    assert r.status == "confirmado" and r.score > 0
