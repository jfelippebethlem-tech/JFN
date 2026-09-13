# -*- coding: utf-8 -*-
"""Certidão negativa não é parecer jurídico — nem quando a PGFN assina.

Medido em 2026-08-03 no arquivo SEI: 42 processos tinham Certidão Negativa de Débitos tipada
como `parecer_juridico`. Duas causas somadas:

  1. `procuradoria` é keyword de `parecer_juridico`, e TODA CND traz "Procuradoria-Geral da
     Fazenda Nacional" no corpo — a classificação por conteúdo casa e devolve parecer;
  2. `certidao` só existe como keyword de `tramitacao` e não casa o plural "Certidões", que é
     como o SEI-RJ costuma nomear o documento — então nem o título salva.

O efeito não é cosmético: o tipo `parecer_juridico` é `valor_doc == 'alto'` (guarda o texto
inteiro), entra na rubrica de juízo por documento e é o que `auditar_parecer_pge` procura para
responder sobre o art. 53 da Lei 14.133. Certidão entrando nesse caminho contamina os três.
"""
import pytest

from compliance_agent.sei.classificador_doc import classificar_doc

CND = ("CERTIDÃO NEGATIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS FEDERAIS E À DÍVIDA ATIVA DA UNIÃO. "
       "MINISTÉRIO DA FAZENDA. Secretaria da Receita Federal do Brasil. "
       "Procuradoria-Geral da Fazenda Nacional. Ressalvado o direito de a Fazenda Nacional cobrar.")


@pytest.mark.parametrize("titulo", [
    "Certidões Negativa de Débitos em Dívida Ativa",
    "Certidão Negativa de Débitos",
    "87550058",                       # título como ID numérico: sobra só o conteúdo
    "Documentos fiscais - Certidões",
])
def test_certidao_negativa_nao_vira_parecer(titulo):
    assert classificar_doc(titulo, CND) != "parecer_juridico"


def test_certificado_de_regularidade_do_fgts_tambem_nao():
    crf = ("Certificado de Regularidade do FGTS - CRF. A Caixa Econômica Federal certifica que "
           "a empresa encontra-se em situação regular perante o Fundo de Garantia.")
    assert classificar_doc("132792061", crf) != "parecer_juridico"


def test_parecer_de_verdade_continua_sendo_parecer():
    """A trava não pode custar o que ela protege."""
    corpo = ("PARECER Nº 462/2024. Procuradoria Geral do Estado do Rio de Janeiro. "
             "Trata-se de análise jurídica da minuta. Opino favoravelmente.")
    assert classificar_doc("Parecer 462 (74886257)", corpo) == "parecer_juridico"
    assert classificar_doc("74886257", corpo) == "parecer_juridico"


def test_parecer_que_menciona_certidao_no_corpo_continua_parecer():
    """Parecer que EXIGE certidão fala de certidão — não pode virar tramitação por isso."""
    corpo = ("PARECER Nº 500/2025 da Assessoria Jurídica. Opino favoravelmente desde que seja "
             "juntada a certidão negativa de débitos da contratada antes da assinatura.")
    assert classificar_doc("Parecer 500", corpo) == "parecer_juridico"
