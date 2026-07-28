# -*- coding: utf-8 -*-
"""E-mail não é cargo — nem no banco, nem na tela.

Ao expor `/api/responsaveis` no painel, apareceu isto no processo do INEA:

    Andre Leal de Albuquerque · fiscal_contrato · cargo: andreleal65@gmail.com

O bloco de assinatura tem NOME / cargo / papel, uma linha cada, e o extrator aceita como cargo
a primeira linha curta que não seja identificador. O e-mail da assinatura satisfaz essa
descrição. Medido: **22 dos 392 agentes** (6%) têm e-mail no campo `cargo`.

Dois danos, e o segundo é o que importa: o campo "cargo" deixa de significar cargo — e é por
ele que se responde "quem responde por este processo"; e um endereço pessoal de servidor vira
dado publicável por acidente, num produto de controle externo (LGPD).

A tela já não mostra e-mail. Aqui a correção é na origem: cargo ausente é `None` — lacuna
honesta —, nunca um e-mail no lugar.
"""
from compliance_agent.sei.agentes_publicos import extrair_agentes as extrair

ASSINATURA_COM_EMAIL = """
Documento assinado eletronicamente

Andre Leal de Albuquerque
andreleal65@gmail.com
Fiscal do Contrato
"""

ASSINATURA_COM_CARGO = """
Documento assinado eletronicamente

Maria Veronica Pena de Castro
Chefe de Servico de Engenharia
Fiscal do Contrato
"""


def _um(texto):
    achados = extrair(texto)
    assert achados, "o extrator devia achar o agente"
    return achados[0]


def test_email_nao_vira_cargo():
    a = _um(ASSINATURA_COM_EMAIL)
    assert a.nome == "Andre Leal de Albuquerque"
    assert a.cargo is None or "@" not in a.cargo, f"e-mail entrou como cargo: {a.cargo!r}"


def test_cargo_de_verdade_continua_sendo_capturado():
    """A correção não pode cegar o caso normal.

    OBSERVAÇÃO medida, deliberadamente NÃO corrigida: quando a linha de cargo tem a forma de
    nome próprio ("Engenheira Civil"), a heurística a toma como NOME do agente. No acervo real
    isso ocorre em 1 de 392 registros ("Técnico Administrativo") — reescrever a heurística de
    nome por um caso traria mais risco que ganho. Fica registrado, não escondido.
    """
    a = _um(ASSINATURA_COM_CARGO)
    assert a.cargo == "Chefe de Servico de Engenharia"


def test_o_agente_continua_sendo_extraido_mesmo_sem_cargo():
    """Perder o cargo não pode custar o responsável — lacuna ≠ ausência de agente."""
    a = _um(ASSINATURA_COM_EMAIL)
    assert a.papel == "fiscal_contrato"
