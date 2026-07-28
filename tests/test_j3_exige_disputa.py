# -*- coding: utf-8 -*-
""""Desconto irrisório" pressupõe DISPUTA — sem ela, o fenômeno é outro.

O J3 diz, na própria razão do achado: *"vencedor fechou rente ao teto"*. Isso descreve
competição. Medido na varredura de 1.331 certames com cláusula extraída (2026-07-28):

    achados J3 "desconto irrisório" .................. 395
      em certame com UM fornecedor (sem disputa) ..... 395   (100%)
      em certame com 2+ fornecedores ................. 0

(A primeira contagem desta sessão disse 88%, e estava errada: um `grep -B 3` associava o
achado ao certame do bloco anterior do log. O parse sequencial — cada "[i/N] certame" define
o dono das linhas seguintes — deu 100%. O erro de medição foi meu, não do detector.)

E o dado geral confirma o mecanismo: dos 1.190 certames em que o homologado bate com o
estimado AO CENTAVO, **1.152 (97%) têm um único fornecedor**. Fechar no valor de referência
quando não houve quem cobrisse é o resultado esperado de dispensa, inexigibilidade ou
licitação fracassada — não indício de cartel.

Contar isso como achado de julgamento infla a fila com 475 casos e, pior, ensina o leitor a
ignorar o J3 — que continua valendo onde há disputa de verdade.

O QUE NÃO MUDA: homologar ACIMA do estimado (art. 59, III) segue sendo achado com ou sem
disputa. Pagar mais que a própria estimativa não precisa de concorrência para ser irregular.
"""
from compliance_agent.detectores.j3_desconto_anomalo import J3DescontoAnomalo


def _ctx(**kw):
    base = {"certame": "X-1/2025", "valor_estimado": 100_000.0, "valor_homologado": 100_000.0,
            "propostas": [{"cnpj": "1", "valor": 100_000.0, "classificacao": 1}]}
    base.update(kw)
    return base


def test_desconto_zero_com_um_fornecedor_nao_e_achado_de_disputa():
    r = J3DescontoAnomalo().avaliar(_ctx())
    texto = f"{r.motivo_refutacao or ''}"
    assert not (r.status == "confirmado" and "irrisório" in texto), \
        "sem disputa não se afirma 'vencedor fechou rente ao teto'"


def test_o_motivo_explica_a_ausencia_de_disputa():
    r = J3DescontoAnomalo().avaliar(_ctx())
    texto = (r.motivo_refutacao or "").lower()
    assert "disputa" in texto or "fornecedor" in texto, \
        "o leitor precisa saber POR QUE não foi avaliado — lacuna declarada, não silêncio"


def test_desconto_irrisorio_com_disputa_real_continua_sendo_achado():
    """A correção não pode cegar o caso legítimo, mesmo que ele não apareça neste corpus."""
    r = J3DescontoAnomalo().avaliar(_ctx(propostas=[
        {"cnpj": "1", "valor": 100_000.0, "classificacao": 1},
        {"cnpj": "2", "valor": 101_000.0, "classificacao": 2},
        {"cnpj": "3", "valor": 102_000.0, "classificacao": 3},
    ]))
    assert r.score > 0, "com disputa e desconto ~0, o indício permanece"


def test_homologado_ACIMA_do_estimado_vale_mesmo_sem_disputa():
    """Art. 59, III: pagar acima da própria estimativa não precisa de concorrência."""
    r = J3DescontoAnomalo().avaliar(_ctx(valor_homologado=120_000.0))
    assert r.score > 0, "homologar 20% acima do estimado é achado com ou sem disputa"
