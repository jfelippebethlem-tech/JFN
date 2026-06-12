# -*- coding: utf-8 -*-
"""Teste da seção 8-B (Lei de Benford) do relatório de fornecedor. Sem rede: ctx com pagamentos sintéticos."""
from compliance_agent.reporting import inteligencia as ig


def _ctx(valores):
    return {"pagamentos": {"tem_dados": True, "anos": [2024],
                           "por_ano": {2024: {"linhas": [{"valor": v} for v in valores]}}}}


def test_benford_conforme():
    # distribuição Benford-like (muitos 1, menos 9) → conforme
    valores = [1]*301 + [2]*176 + [3]*125 + [4]*97 + [5]*79 + [6]*67 + [7]*58 + [8]*51 + [9]*46
    valores = [v * 100 + 50 for v in valores]  # garante 1º dígito = v
    md = ig._render_benford(_ctx(valores))
    assert "## 8-B." in md and "Benford" in md
    assert "Esperado" in md and "Observado" in md  # tabela dígito x esperado x observado


def test_benford_sem_dados_indisponivel():
    md = ig._render_benford({"pagamentos": {"tem_dados": False}})
    assert "8-B" in md and "INDISPONÍVEL" in md


def test_benford_amostra_pequena_avisa():
    md = ig._render_benford(_ctx([123, 234, 345, 456, 567]))  # n=5 < 50
    assert "pouco confiável" in md.lower()


def test_benford_tabela_tem_9_digitos():
    valores = [v * 100 + 50 for v in ([1]*60 + [7]*60)]  # desbalanceado mas n>=50
    md = ig._render_benford(_ctx(valores))
    # 9 linhas de dígito na tabela (1..9)
    assert all(f"| {d} |" in md for d in range(1, 10))
