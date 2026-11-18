"""Laudo de execução com proveniência e estado (regra 9) — 18/11/2026: 92% dos 7.919 laudos eram de outro modelo
sem conferência do Claude, e o relatório de fornecedor os mostrava sem dizer; o Opus rebaixou 91% dos 'risco alto'."""
from compliance_agent.correlacao_sei import estado_do_laudo


def test_estado_do_laudo():
    assert estado_do_laudo("claude:claude-sonnet-5-5 (+gemini:x)")[0] == "VERIFICADO"
    assert estado_do_laudo("gemini · conferido claude:claude-opus-5-5")[0] == "VERIFICADO"
    assert estado_do_laudo("regra:sem_doc_execucao")[0] == "REGRA"
    e, txt = estado_do_laudo("gemini:gemini-3-flash-preview")
    assert e == "PENDENTE" and "gemini" in txt and "Opus" in txt
    assert estado_do_laudo(None)[0] == "PENDENTE" and estado_do_laudo("desconhecido")[0] == "PENDENTE"
