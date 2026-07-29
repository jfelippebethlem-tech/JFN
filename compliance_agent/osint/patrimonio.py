# -*- coding: utf-8 -*-
"""Incompatibilidade entre o que a pessoa DECLARA e o que passa pelas mãos dela.

POR QUE ISTO É DELICADO, E POR QUE MESMO ASSIM VALE. "Patrimônio a descoberto" é a espinha dorsal
de investigação financeira, e também a acusação mais fácil de errar: renda não é só salário, bem
declarado tem valor de aquisição e não de mercado, empresa movimenta dinheiro que não é do sócio.
Um módulo que ignore isso produz manchete e não produz prova.

Aqui a régua é deliberadamente conservadora, e cada escolha tem uma razão:

  · **O que se compara é RECEBIMENTO PÚBLICO da empresa contra CAPACIDADE declarada**, não
    "patrimônio" em abstrato. O dado existe e é aberto: o quanto o ente pagou à empresa (OB), o
    capital social registrado, a remuneração do sócio na folha pública, os bens que ele declarou
    ao TSE se foi candidato.
  · **Capital social ínfimo diante de contrato grande é indício de FACHADA, não de
    enriquecimento** — são coisas diferentes e o módulo as separa, porque tratá-las como a mesma
    coisa é o erro que transforma micro-empresa legítima em suspeito.
  · **Faixa, nunca ponto.** A razão entre o recebido e a capacidade sai como faixa com o `n` de
    fontes consideradas; um número único sugere precisão que este dado não tem.
  · **Ausência de renda conhecida NÃO é renda zero.** Quem não está na folha pública pode ter
    renda privada inteira — e é o caso da maioria. Sem fonte de renda conhecida, o resultado é
    `nao_aferivel`, jamais "renda incompatível".

O QUE NÃO ESTÁ AQUI, e é o que fecharia o caso: movimentação bancária, declaração de imposto de
renda e RIF do COAF. São dados sob sigilo, fora do alcance de fonte aberta. Onde a conclusão
dependeria deles, o resultado diz qual diligência pedir — que é o produto útil a quem tem
prerrogativa de requisitar.
"""
from __future__ import annotations

from typing import Any

# Múltiplos a partir dos quais a desproporção deixa de ser explicável por variação normal.
# Conservadores de propósito: o custo do falso positivo aqui é acusar alguém de enriquecimento.
RAZAO_ATENCAO = 10.0     # recebido = 10× a capacidade conhecida
RAZAO_FORTE = 50.0
RAZAO_CRITICA = 200.0

# Capital social abaixo desta fração do contrato sugere FACHADA (art. 69 da Lei 14.133 admite
# exigir qualificação econômico-financeira justamente por isso). É sinal de outra família.
FRACAO_CAPITAL_MINIMA = 0.01


def _f(v) -> float | None:
    try:
        x = float(v)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def avaliar_pessoa(*, nome: str = "", recebido_via_empresas: Any = None,
                   remuneracao_publica_anual: Any = None,
                   bens_declarados: Any = None,
                   outras_rendas_conhecidas: Any = None,
                   anos: int = 1) -> dict[str, Any]:
    """Compara o que passou pelas empresas da pessoa com a capacidade que se conhece dela.

    Todas as entradas são de fonte aberta. `anos` normaliza o recebido para base anual — comparar
    quatro anos de contrato com um ano de salário é o erro aritmético que infla o resultado.
    """
    recebido = _f(recebido_via_empresas)
    fontes: list[tuple[str, float]] = []
    for rotulo, valor in (("remuneração pública (folha)", remuneracao_publica_anual),
                          ("bens declarados ao TSE", bens_declarados),
                          ("outras rendas conhecidas", outras_rendas_conhecidas)):
        v = _f(valor)
        if v is not None:
            fontes.append((rotulo, v))

    base = {"nome": nome, "recebido_via_empresas": recebido, "fontes_de_capacidade": fontes,
            "n_fontes": len(fontes), "anos": max(1, int(anos or 1))}

    if recebido is None:
        return {**base, "aferivel": False, "nivel": None,
                "motivo": "sem valor recebido apurado — nada a comparar (ausente ≠ zero)"}
    if not fontes:
        return {**base, "aferivel": False, "nivel": None,
                "motivo": ("nenhuma fonte de renda conhecida — quem não está na folha pública "
                           "pode ter renda privada inteira. INDISPONÍVEL, não 'renda zero'"),
                "diligencia_sugerida": ("requisitar declaração de bens e rendimentos e, havendo "
                                        "prerrogativa, RIF ao COAF — dados sob sigilo, fora do "
                                        "alcance de fonte aberta")}

    capacidade = sum(v for _, v in fontes) * base["anos"]
    razao = recebido / capacidade if capacidade else None
    nivel = (None if razao is None or razao < RAZAO_ATENCAO else
             "critico" if razao >= RAZAO_CRITICA else
             "forte" if razao >= RAZAO_FORTE else "medio")

    r = {**base, "aferivel": True, "capacidade_no_periodo": round(capacidade, 2),
         "razao": round(razao, 2) if razao else None, "nivel": nivel}
    if nivel is None:
        r["motivo"] = (f"recebido {razao:.1f}× a capacidade conhecida — abaixo do limiar de "
                       f"atenção ({RAZAO_ATENCAO:.0f}×)")
        return r
    r["motivo"] = (f"recebido pelas empresas é {razao:.0f}× a capacidade conhecida da pessoa "
                   f"no período ({base['n_fontes']} fonte(s) somada(s))")
    r["explicacao_inocente"] = (
        "o faturamento da empresa NÃO é renda do sócio: cobre custo, folha, tributo e capital de "
        "giro. A desproporção só vira indício de enriquecimento se o padrão de vida ou o "
        "patrimônio acompanharem — e isso não se apura em fonte aberta")
    r["diligencia_sugerida"] = (
        "requisitar declaração de bens e rendimentos do agente, e cruzar com registros de imóveis "
        "e veículos; havendo prerrogativa, RIF ao COAF")
    r["ressalva"] = ("Razão apurada sobre fontes ABERTAS e parciais. Não é prova de "
                     "enriquecimento; é critério de priorização de diligência.")
    return r


def avaliar_empresa(*, razao_social: str = "", capital_social: Any = None,
                    valor_contratado: Any = None, valor_pago_ob: Any = None) -> dict[str, Any]:
    """Capital social × porte do contrato — sinal de FACHADA, não de enriquecimento.

    A distinção importa: capital ínfimo diante de contrato grande diz que a empresa provavelmente
    não tem estrutura para executar, o que é questão de qualificação econômico-financeira
    (art. 69). Tratar isso como enriquecimento ilícito confunde duas famílias e produz acusação
    errada contra micro-empresa legítima.
    """
    capital = _f(capital_social)
    contrato = _f(valor_contratado) or _f(valor_pago_ob)
    base = {"razao_social": razao_social, "capital_social": capital,
            "valor_referencia": contrato}
    if capital is None or contrato is None:
        return {**base, "aferivel": False, "nivel": None,
                "motivo": "capital social ou valor do contrato ausente — ausente ≠ zero"}
    fracao = capital / contrato
    nivel = ("forte" if fracao < FRACAO_CAPITAL_MINIMA / 10 else
             "medio" if fracao < FRACAO_CAPITAL_MINIMA else None)
    r = {**base, "aferivel": True, "fracao_capital": round(fracao, 6), "nivel": nivel,
         "familia": "perfil_contratado"}
    if nivel is None:
        r["motivo"] = f"capital social equivale a {fracao:.1%} do contrato — dentro do usual"
        return r
    r["motivo"] = (f"capital social de {fracao:.2%} do valor contratado — abaixo do piso usual de "
                   f"{FRACAO_CAPITAL_MINIMA:.0%}, indício de estrutura incompatível com o objeto")
    r["explicacao_inocente"] = (
        "capital social é registro contábil e pode estar desatualizado há anos; empresas de "
        "serviço com baixa imobilização operam legitimamente com capital pequeno")
    r["nota"] = ("Isto é sinal de FACHADA (qualificação econômico-financeira, art. 69 da Lei "
                 "14.133), NÃO de enriquecimento ilícito — são famílias diferentes.")
    return r
