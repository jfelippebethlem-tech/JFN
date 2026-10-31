# -*- coding: utf-8 -*-
"""O E7 dizia "sem justificativa NOS AUTOS" tendo olhado só a LINHA da cláusula.

`justificativa_autos` é calculado pelo `coletor_edital` sobre a mesma linha em que a cláusula
aparece. A Súmula TCU 289 exige que a exigência de índices contábeis seja justificada no
**processo** — e essa justificativa mora no estudo técnico, no termo de referência ou num
despacho, nunca dentro da frase que fixa o índice. Afirmar ausência "nos autos" a partir de uma
linha é afirmar o que não se verificou.

Alargar a janela seria o erro simétrico: medido em 2026-08-05 no SEI-270099/000714/2022, procurar
palavra de justificativa perto de "índice" no edital inteiro devolve VERDADEIRO — e o trecho é uma
*"NOTA 3.1"* sobre **garantia**, onde o que casou foi *"em razão da celebração de Termo Aditivo"*.
Isso inventaria a exculpação. A régua não muda; muda o que ela declara.
"""
from __future__ import annotations

from compliance_agent.detectores.e7_clausula_restritiva import _teste_indices


def test_sem_justificativa_o_texto_diz_o_que_foi_conferido():
    nivel, texto = _teste_indices({"tipo": "indices_contabeis"}, None)
    assert nivel == "medio"
    assert "NA PRÓPRIA CLÁUSULA" in texto
    assert "nos autos" not in texto.lower().replace("no processo", ""), \
        "voltou a afirmar ausência nos autos a partir de uma linha"
    assert "289" in texto and ("estudo técnico" in texto or "termo de referência" in texto), \
        "o achado tem de dizer ONDE conferir"


def test_com_justificativa_na_clausula_o_achado_some():
    nivel, texto = _teste_indices({"tipo": "indices_contabeis", "justificativa_autos": True}, None)
    assert nivel == "ausente" and "própria cláusula" in texto
