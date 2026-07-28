# -*- coding: utf-8 -*-
"""O medidor tinha um ponto cego: não penalizava monólogo.

Medido em 2026-07-28. `nvidia/nemotron-3-super-120b-a12b:free` tirou 100,0 no banco de provas
e, ao consolidar um dossiê real, devolveu o próprio raciocínio em inglês — 13 marcadores de
monólogo, truncado no meio de uma frase, sem nenhuma das sete seções pedidas. O conteúdo
extraído era bom; o formato era inutilizável.

Por que passou: a pontuação casa SUBSTRING. Um monólogo que menciona o nome certo pontua igual
a uma resposta limpa. Como `escolher("documento")` passou a confiar na nota medida, o ponto cego
do medidor virou escolha de modelo errada para a tarefa mais caras que temos.
"""
from __future__ import annotations

from tools.bench_modelos import penalidade_formato, PROVAS


_MONOLOGO = """Let me go through the provided documents to extract the requested information.
I need to find the fiscal. We must be careful not to over-assign. The user says they want
only the names, so I should list: TAYANE CORDEIRO PALMA DE HOLANDA, ID 4398712-6."""

_LIMPO = "Fiscal do Contrato: TAYANE CORDEIRO PALMA DE HOLANDA, ID funcional 4398712-6."


def test_monologo_e_penalizado():
    assert penalidade_formato(_MONOLOGO) > 0


def test_resposta_limpa_nao_e_penalizada():
    assert penalidade_formato(_LIMPO) == 0


def test_penalidade_cresce_com_a_quantidade_de_monologo():
    pouco = "Let me check. Fiscal: TAYANE CORDEIRO PALMA DE HOLANDA."
    assert penalidade_formato(_MONOLOGO) > penalidade_formato(pouco)


def test_penalidade_tem_teto_para_nao_virar_nota_negativa():
    assert penalidade_formato(_MONOLOGO * 20) <= 100


def test_portugues_normal_nao_dispara_falso_positivo():
    """'devemos' e 'preciso' aparecem em texto legítimo; o gatilho é o padrão de deliberação
    em primeira pessoa sobre a PRÓPRIA tarefa, não qualquer verbo modal."""
    texto = ("O gestor deve atestar a execução. É preciso juntar a nota fiscal. "
             "Consta que o fiscal designado é TAYANE CORDEIRO PALMA DE HOLANDA.")
    assert penalidade_formato(texto) == 0


def test_todas_as_provas_aplicam_a_penalidade():
    """Sem isto, corrigir uma prova e esquecer as outras reabre o mesmo ponto cego."""
    for nome, _sistema, _prompt, pontuar in PROVAS:
        limpa = pontuar(_LIMPO)
        suja = pontuar(_LIMPO + "\n\n" + _MONOLOGO)
        assert suja <= limpa, f"prova {nome} não penaliza monólogo"
