# -*- coding: utf-8 -*-
"""Sem o índice do TCU, o gate calava — e o texto saía com cara de conferido.

Achado ao investigar por que `test_gate_citacoes_canal` falha na VM-2: lá não existe o índice
de jurisprudência, e `sanear_canal` devolve o texto INTACTO, com um `logging.warning` que
ninguém lê no chat. Resultado: "Conforme o Acórdão 9999/2024-Plenário" chega ao destinatário
exatamente igual a uma citação que passou pela conferência.

É o `INDISPONÍVEL ≠ OK` da casa acontecendo dentro do gate que existe justamente para impedir
citação fabricada — e esta casa já encontrou quatro acórdãos impossíveis por aritmética na
própria base curada.

Não dá para suprimir sem o índice: o teto por colegiado e ano vem dele, e inventar teto seria
trocar um erro por outro. O que dá, e é obrigatório, é DECLARAR que não se conferiu.
"""
from compliance_agent.reporting.gate_citacoes import sanear_canal

SEM_INDICE = "/tmp/indice_que_nao_existe.db"
COM_CITACAO = "Conforme o Acórdão 9999/2024-Plenário, o gestor responde."


def test_sem_indice_o_texto_com_citacao_sai_declarando_que_nao_foi_conferido():
    saida = sanear_canal(COM_CITACAO, db=SEM_INDICE, contexto="teste")
    assert COM_CITACAO in saida, "sem índice não se suprime: o teto por colegiado vem dele"
    assert "não conferid" in saida.lower() or "não foram conferidas" in saida.lower(), \
        "silêncio faz a citação parecer aprovada — o aviso é obrigatório"


def test_o_aviso_cabe_em_uma_linha():
    """É canal de chat: nota completa de conferência é ruído, mas alguma nota é dever."""
    extra = sanear_canal(COM_CITACAO, db=SEM_INDICE, contexto="teste").replace(COM_CITACAO, "")
    assert extra.count("\n\n") <= 1 and len(extra.strip().splitlines()) == 1


def test_texto_sem_citacao_nenhuma_nao_ganha_aviso():
    """Avisar sobre conferência num texto que não cita nada é ruído puro."""
    limpo = "O empenho não é pagamento; só a Ordem Bancária quita."
    assert sanear_canal(limpo, db=SEM_INDICE, contexto="teste") == limpo


def test_com_indice_o_comportamento_nao_muda():
    """A correção vale para a máquina SEM índice; onde há índice, suprime como antes."""
    saida = sanear_canal(COM_CITACAO, contexto="teste")
    assert "citação suprimida" in saida
    assert "não foram conferidas" not in saida
