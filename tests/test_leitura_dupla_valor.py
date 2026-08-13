# -*- coding: utf-8 -*-
"""Dinheiro: aritmética decide, e o `R$` pode estar noutra coluna.

**72 linhas — a maior categoria da fila** — eram brigas no `valor`. Abrindo os casos, o padrão: o
valor da IA estava entre os candidatos da REGRA, só não era o maior. Os dois leram os mesmos números
e discordaram do RANQUE — e "qual é o maior" tem resposta objetiva. Fila é para dúvida, não para
conferir conta.

E um caso não era ranque, era cegueira: em `080002/010108/2024` a IA achava R$ 5.078.755,43 e o
maior da regra era **R$ 4.518,12**. A tabela escreve `R$                            E 5.078.755,43`
— o cifrão numa coluna e o número noutra — e `R\\$\\s?` não atravessa isso. Perder cinco milhões por
layout de tabela é caro demais; o formato brasileiro de milhar identifica dinheiro sozinho.
"""
from __future__ import annotations

from tools.sei_leitura_dupla import comparar, extrair_deterministico


def test_acha_o_valor_quando_o_cifrao_esta_em_outra_coluna():
    d = extrair_deterministico("Item D 846.459,24 R$                            E 5.078.755,43 R$")
    assert d["valores"]["valor"] == "5.078.755,43"


def test_nao_confunde_numero_de_processo_com_dinheiro():
    """A segunda via não pode transformar qualquer número em valor."""
    d = extrair_deterministico("Processo SEI-080001/025757/2025 de 12/08/2025, doc 141775386.")
    assert not d["valores"]["valor"]


def _laudo(ia_valor, candidatos):
    det = {"valores": {"valor": candidatos[0],
                       "alternativas": [{"valor": v} for v in candidatos[1:]]}}
    return comparar(det, {"estado": "ok", "fatos": {"valor": ia_valor}}, {"tem_ob": False})


def test_ia_escolher_o_segundo_maior_NAO_vai_para_a_fila():
    r = _laudo("6.615.200,00", ["6.644.000,00", "6.615.200,00"])
    assert "valor" not in r["discordancia"]
    assert r["ausencia_concorde"]["valor"]["estado"] == "ia_errou_o_maior"


def test_numero_que_a_regra_nao_viu_CONTINUA_na_fila():
    """Fora da lista os dois leram números diferentes — ou a régua é cega, ou o modelo inventou."""
    r = _laudo("2.710.247,50", ["3.710.247,50", "610.222,30"])
    assert r["discordancia"]["valor"]["estado"] == "discordam"
