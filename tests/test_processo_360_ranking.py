# -*- coding: utf-8 -*-
"""A fila do fiscal é lida de cima para baixo — o motivo impresso tem de ser o achado.

O ranking existe porque o score de convergência satura em processo grande: o que separa o grave
do burocrático é O QUE foi achado. Por isso a coluna "Motivos" é o produto, não enfeite.
"""
from tools.processo_360_ranking import pontuar


def test_rotulo_critico_e_o_ACHADO_e_nao_um_texto_fixo():
    """Medido em 2026-08-04, depois de as famílias X, C e P/E/J passarem a produzir achados
    visíveis: **24 achados no acervo** seriam impressos como "pagamento sem evidência de
    execução" sem ser — um C9 de perfil de fornecedor, um X7 de dupla correção e um I3 de ato sem
    assinatura. O fiscal abriria diligência pelo motivo errado."""
    pts, motivos = pontuar(
        [{"gravidade": "critica", "origem": "fornecedor", "codigo": "C9",
          "diz": "perfil do fornecedor contratado: detector C9 confirmado (intensidade 1.00)"}], {})
    assert pts == 5
    assert "pagamento sem evidência de execução" not in motivos[0]
    assert "C9" in motivos[0] or "fornecedor" in motivos[0]


def test_a_lacuna_de_execucao_mantem_o_rotulo_proprio():
    """Quando o achado É o pagamento sem prova de entrega, o rótulo curto é melhor que o texto
    longo — e é o que o fiscal reconhece de imediato."""
    _, motivos = pontuar(
        [{"gravidade": "critica",
          "diz": "Evidência de execução (medição/atesto/relatório fotográfico) apesar de haver pagamento"}], {})
    assert motivos == ["pagamento sem evidência de execução"]


def test_contrato_antes_do_parecer_pesa_mais_que_achado_burocratico():
    a1, _ = pontuar([{"codigo": "A1_CONTRATO_ANTES_DO_PARECER", "diz": "x"}], {})
    burocratico, _ = pontuar([{"gravidade": "media", "diz": "y"}], {})
    assert a1 > burocratico


def test_processo_sem_achado_nao_pontua():
    assert pontuar([], {}) == (0, [])
