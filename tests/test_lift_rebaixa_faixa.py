# -*- coding: utf-8 -*-
"""Detector que NÃO prediz não pode carregar faixa de risco no produto.

O painel de lift (G.8) mediu e publicou, contra a taxa-base de 7,01% do acervo:

  escalada_preco ........ lift 2,17   aponta bem acima da base
  sobrepreco ............ lift 1,49   contribui para ordenar
  corrida_dezembro ...... lift 0,59   aponta para empresas MENOS sancionadas
  fornecedor_dependente . lift 0,48   idem
  radar_risco ........... lift 12,98  CIRCULAR (usa sanção como insumo)

Medir e publicar não muda comportamento sozinho. Os dois anti-preditivos continuavam registrados com
faixa **MÉDIO** em `intel_relatorio._detectores()` — ou seja, o PDF entregue afirmava nível de risco
médio a partir de um sinal que, medido, aponta para o lado contrário. Não é que corrida de dezembro
seja lícita: é que, **como preditor de sanção**, o sinal não serve, e usá-lo para ordenar a fila gasta
a atenção do fiscal.

A decisão tomada em 2026-07-29 foi **rebaixar a INFORMATIVO**, não aposentar: o padrão fático (rush
de fim de exercício, fornecedor dependente de um só órgão) é juridicamente relevante e continua
valendo como leitura. O que sai é a pretensão de graduar risco com ele — e o lift medido passa a
aparecer no próprio documento.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_lift_rebaixa_faixa.py -q
"""
from __future__ import annotations

import pytest

from compliance_agent.intel_relatorio import (
    LIFT_MEDIDO,
    _detectores,
    faixa_ajustada_por_lift,
)


def test_os_dois_anti_preditivos_estao_declarados_com_o_numero():
    """O número tem de estar no código, não na memória de quem leu o painel uma vez."""
    for det in ("corrida_dezembro", "fornecedor_dependente"):
        assert det in LIFT_MEDIDO, f"{det} sem lift declarado"
        assert LIFT_MEDIDO[det] < 1.0, (
            f"{det} tem lift {LIFT_MEDIDO[det]} — se subiu acima de 1, remedir e reavaliar o rebaixamento"
        )
    assert LIFT_MEDIDO["escalada_preco"] > 2.0, "o contraexemplo forte tem de estar junto"


def test_lift_abaixo_de_um_rebaixa_a_informativo():
    assert faixa_ajustada_por_lift("corrida_dezembro", "MÉDIO") == "INFORMATIVO"
    assert faixa_ajustada_por_lift("fornecedor_dependente", "MÉDIO") == "INFORMATIVO"


def test_lift_bom_nao_e_promovido_nem_rebaixado():
    """Lift alto produz achado mais VALIOSO, não achado mais provado — o teto da régua de evidência
    continua valendo. Rebaixar é medida de honestidade; promover seria o mesmo erro ao contrário."""
    assert faixa_ajustada_por_lift("escalada_preco", "ALTO") == "ALTO"
    assert faixa_ajustada_por_lift("sobrepreco", "ALTO") == "ALTO"


def test_detector_sem_lift_medido_mantem_a_faixa():
    """Ausência de medição não é evidência de nada — não rebaixa nem promove."""
    assert faixa_ajustada_por_lift("detector_que_nao_existe", "ALTO") == "ALTO"


def test_circular_nao_promove():
    """`radar_risco` tem lift 12,98 porque usa sanção como insumo. Lift circular não é mérito."""
    assert LIFT_MEDIDO.get("radar_risco") is None or "radar_risco" in LIFT_MEDIDO
    assert faixa_ajustada_por_lift("radar_risco", "ALTO") == "ALTO", (
        "detector circular não pode ser promovido pelo lift que a própria circularidade produz"
    )


def test_o_registro_de_detectores_aplica_o_rebaixamento():
    reg = _detectores()
    for det in ("corrida_dezembro", "fornecedor_dependente"):
        assert det in reg, f"{det} saiu do registro — se foi aposentado, remova daqui também"
        assert reg[det][2] == "INFORMATIVO", (
            f"{det} voltou a carregar faixa de risco ({reg[det][2]}) contra o lift medido"
        )
    assert reg["escalada"][2] == "ALTO"
    assert reg["socio_servidor"][2] == "EXTREMO"


@pytest.mark.parametrize("det", ["corrida_dezembro", "fornecedor_dependente"])
def test_o_documento_declara_o_lift(det: str):
    """O leitor do PDF tem de ver o número, não só o rótulo rebaixado."""
    from compliance_agent.intel_relatorio import nota_de_lift

    nota = nota_de_lift(det)
    assert nota, f"{det} sem nota de lift para o documento"
    assert str(LIFT_MEDIDO[det]) in nota
    assert "7,01" in nota or "7.01" in nota, "a taxa-base tem de vir junto, senão o lift não se lê"
    assert "não" in nota.lower()
