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


def test_o_cifrao_nao_pode_impedir_o_encontro():
    """`_norm` preserva letras, então `R$ 4.100.955,10` virava `R410095510` e nunca casava com o
    `410095510` da regra — mesmo com o valor ESTANDO na lista. Dinheiro se compara por dígito: o
    cifrão, o ponto de milhar e a vírgula decimal são grafia, não conteúdo.

    O leitor do volume devolve ora `R$ 4.100.955,10`, ora `233014.52` (padrão americano): as duas
    grafias têm de encontrar o mesmo número.
    """
    r = _laudo("R$ 4.100.955,10", ["414.507.934,94", "4.100.955,10"])
    assert r["ausencia_concorde"]["valor"]["estado"] == "ia_errou_o_maior"


def test_grafia_americana_tambem_encontra():
    r = _laudo("4100955.10", ["414.507.934,94", "4.100.955,10"])
    assert "valor" not in r["discordancia"]


def test_a_lista_de_valores_guarda_mais_que_quatro_candidatos():
    """Um processo de despesa traz dezenas de cifras, e a que a IA elege costuma ser real — só não
    está entre as quatro maiores. Cortar em 4 mandava para a fila humana o que a aritmética resolve.
    """
    from tools.sei_leitura_dupla import extrair_deterministico
    texto = "".join(f"R$ {n}.000.000,00\n" for n in range(1, 15))
    assert len(extrair_deterministico(texto)["valores"]["alternativas"]) > 4


def test_a_ordem_bancaria_arbitra_quando_a_regua_pega_TOTAL_DE_ORCAMENTO():
    """A régua responde "o maior número do documento", e processo de despesa carrega QUADRO
    ORÇAMENTÁRIO inteiro. No `080002/020895/2024` ela devolvia R$ 174.084.499,56 — o `TOTAL` de uma
    tabela de orçamento — enquanto a IA dizia R$ 6.615.200,00 e a OB do processo somava
    R$ 6.535.472,00.

    Medido nas 116 discordâncias de valor: nas 81 arbitráveis, a OB corrobora **a IA em 76 e a régua
    em 2**. Com árbitro canônico (regra nº 2 da casa: OB é a verdade sobre o que se pagou) não há o
    que um humano decida.
    """
    from tools.sei_leitura_dupla import comparar
    det = {"valores": {"valor": "174.084.499,56", "alternativas": []}}
    ia = {"estado": "ok", "fatos": {"valor": "6.615.200,00"}}
    r = comparar(det, ia, {"tem_ob": True, "total": 6_535_472.00, "favorecidos": set()})
    assert "valor" not in r["discordancia"]
    assert r["ausencia_concorde"]["valor"]["estado"] == "ia_corroborada_pela_ob"


def test_sem_margem_LARGA_a_OB_nao_arbitra():
    """Exigir o dobro de proximidade evita arbitrar empate: quando os dois estão perto do pago, a
    divergência é real e merece o olho humano."""
    from tools.sei_leitura_dupla import comparar
    det = {"valores": {"valor": "6.500.000,00", "alternativas": []}}
    ia = {"estado": "ok", "fatos": {"valor": "6.600.000,00"}}
    r = comparar(det, ia, {"tem_ob": True, "total": 6_535_472.00, "favorecidos": set()})
    assert r["discordancia"]["valor"]["estado"] == "discordam"


def test_sem_OB_nao_ha_arbitro():
    from tools.sei_leitura_dupla import comparar
    det = {"valores": {"valor": "174.084.499,56", "alternativas": []}}
    ia = {"estado": "ok", "fatos": {"valor": "6.615.200,00"}}
    r = comparar(det, ia, {"tem_ob": False})
    assert r["discordancia"]["valor"]["estado"] == "discordam"
