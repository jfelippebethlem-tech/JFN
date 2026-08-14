# -*- coding: utf-8 -*-
"""Em metade do acervo a pergunta "qual é o contrato" NÃO TEM resposta única.

Medido em 467 leituras, com a conferência por documento inteiro: **49% dos processos citam mais de
um contrato distinto**, 29% mais de um pregão, 16% mais de uma ata. Um processo real
(`080001/021161/2025`) traz QUATRO atas, QUATRO pregões, contratos de gestão e um TAC — é compêndio
de extratos, não um instrumento só.

Quando os dois leitores escolhem do MESMO conjunto, eles não discordam sobre o documento: respondem
uma pergunta mal posta. Mandar isso para a fila humana é pedir que alguém decida qual dos quatro
contratos "é" o contrato — decisão que o próprio processo não tomou.

É o mesmo tratamento dado ao favorecido de um processo com 1.199 recebedores: quando a pergunta
pressupõe unicidade que o documento não tem, o honesto é DECLARAR a pluralidade.
"""
from __future__ import annotations

from tools.sei_leitura_dupla import comparar


def _det(valor, *outros):
    return {"contrato": {"valor": valor,
                         "alternativas": [{"valor": o} for o in outros]}}


def test_escolhas_diferentes_do_MESMO_conjunto_saem_da_fila():
    r = comparar(_det("36/2023", "04/2020", "09/2021", "10/2022"),
                 {"estado": "ok", "fatos": {"contrato": "10/2022"}}, {"tem_ob": False})
    assert "contrato" not in r["discordancia"]
    assert r["ausencia_concorde"]["contrato"]["estado"] == "varios_instrumentos"


def test_instrumento_UNICO_continua_sendo_comparado_de_verdade():
    """A guarda não pode esvaziar o campo: com um só candidato, divergência é divergência."""
    r = comparar(_det("443/2025"), {"estado": "ok", "fatos": {"contrato": "417/2023"}},
                 {"tem_ob": False})
    assert r["discordancia"]["contrato"]["estado"] == "discordam"


def test_valor_FORA_do_conjunto_continua_na_fila():
    """Se a IA responde número que a régua não colheu, ou ela leu o que a régua perdeu, ou inventou
    — e as duas hipóteses merecem o olho humano."""
    r = comparar(_det("36/2023", "04/2020"),
                 {"estado": "ok", "fatos": {"contrato": "99/1999"}}, {"tem_ob": False})
    assert r["discordancia"]["contrato"]["estado"] == "discordam"
