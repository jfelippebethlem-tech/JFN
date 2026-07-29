# -*- coding: utf-8 -*-
"""Economicidade: sobrepreço ≠ superfaturamento, e o preço só compara entre iguais.

DUAS CONFUSÕES QUE CUSTAM CARO, e este módulo existe para impedir as duas.

**A primeira é jurídica.** *Sobrepreço* é o preço contratado acima da referência de mercado — é
vício do ORÇAMENTO, aferível sem que nada tenha sido executado. *Superfaturamento* é o DANO
efetivo, e exige execução medida e pagamento comprovado. O vocabulário se mistura nos relatórios,
e a consequência não é estética: `knowledge/tipicidade` mostra que o art. 10 da Lei 8.429 exige
perda patrimonial "efetiva e comprovadamente" demonstrada. Chamar sobrepreço de superfaturamento
é afirmar dano que não se provou — e é a forma mais rápida de perder a peça. Aqui, dano só existe
com **Ordem Bancária**; empenho não é pagamento (regra absoluta da casa).

**A segunda é estatística.** Comparar preços de coisas diferentes produz "economia potencial"
inventada. Medido na casa: 60% de uma manchete de economia comparava produtos distintos —
"peça de veículo" tem dispersão de 1292× entre itens que o catálogo trata como o mesmo. A
manchete caiu de R$ 15,6 mi para R$ 6,2 mi quando só o homogêneo entrou. Por isso a comparação
tem um PORTÃO: grupo com dispersão acima do limiar não vira achado de preço — vira achado de
PLANEJAMENTO (a especificação genérica é que impede a aferição, art. 40 da Lei 14.133).

**A hierarquia da referência** segue a prática consagrada: tabela oficial do objeto primeiro
(SINAPI/SICRO para obras federais, EMOP no Estado do RJ), depois painel de preços públicos,
depois contratações similares do próprio ente, e por último pesquisa direta com fornecedores.
Cada referência carrega fonte e data — referência sem procedência não sustenta glosa.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Sequence

# `moeda()` é o formatador da casa: 1.234,56. Montar o valor com o separador padrão do Python
# produziria 1,234.56 — o formato AMERICANO dentro de um texto em português. A catraca
# `tests/test_moeda_padrao_brasileiro` existe exatamente para isso, e pegou este módulo na
# primeira passada (inclusive dentro de um comentário, o que é o comportamento certo: um exemplo
# copiado de comentário vira código).
from compliance_agent.reporting.intel_base import moeda

# ── vocabulário ───────────────────────────────────────────────────────────────────────────────
SOBREPRECO = "sobrepreco"
SUPERFATURAMENTO = "superfaturamento"

DEFINICOES: dict[str, dict[str, str]] = {
    SOBREPRECO: {
        "nome": "Sobrepreço",
        "definicao": "preço contratado ou orçado acima da referência de mercado",
        "exige_execucao": "não",
        "prova": "orçamento/contrato + referência de preço com fonte e data",
        "consequencia": "vício do orçamento — determinação de adequação, glosa preventiva",
    },
    SUPERFATURAMENTO: {
        "nome": "Superfaturamento",
        "definicao": "dano efetivo decorrente de pagamento acima do preço de referência",
        "exige_execucao": "sim — medição e pagamento comprovados",
        "prova": "sobrepreço + quantidade EXECUTADA + Ordem Bancária (empenho não é pagamento)",
        "consequencia": "ressarcimento ao erário, com memória de cálculo",
    },
}

# ── hierarquia da referência de preço ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Referencia:
    id: str
    nome: str
    prioridade: int          # 1 = melhor
    aplicavel_a: str
    observacao: str = ""


HIERARQUIA_REFERENCIA: tuple[Referencia, ...] = (
    Referencia("sinapi", "SINAPI", 1, "obras e serviços de engenharia",
               "atenção à versão desonerada × não desonerada — confundi-las inverte a conclusão"),
    Referencia("sicro", "SICRO", 1, "obras rodoviárias"),
    Referencia("emop", "EMOP", 1, "obras do Estado do Rio de Janeiro",
               "tabela estadual; prevalece sobre a federal no âmbito do Estado"),
    Referencia("painel_precos", "Painel de Preços / Compras Dados Abertos", 2,
               "bens e serviços comuns"),
    Referencia("contratacoes_similares", "contratações similares do próprio ente", 3, "qualquer"),
    Referencia("pesquisa_fornecedores", "pesquisa direta com fornecedores", 4, "qualquer",
               "a mais frágil: sujeita a cotação de fachada (ver detector P2)"),
)

# Dispersão acima da qual o grupo NÃO é comparável. Calibrado no acervo: "peça de veículo" chega
# a 1292× entre itens que o catálogo trata como o mesmo. Coeficiente de variação de 1,0 já
# significa desvio-padrão do tamanho da própria média — não há "preço do item" a comparar.
CV_MAXIMO_COMPARAVEL = 1.0
N_MINIMO_REFERENCIA = 5      # mediana com menos que isto não é referência, é anedota


def melhor_referencia(disponiveis: Sequence[str], *, tipo_objeto: str = "") -> Referencia | None:
    """A referência de MAIOR prioridade entre as disponíveis, respeitando o tipo de objeto."""
    obj = str(tipo_objeto or "").lower()
    candidatas = [r for r in HIERARQUIA_REFERENCIA if r.id in set(disponiveis or ())]
    if obj:
        preferidas = [r for r in candidatas
                      if r.aplicavel_a == "qualquer" or any(p in obj for p in
                                                            r.aplicavel_a.split()[:2])]
        candidatas = preferidas or candidatas
    return min(candidatas, key=lambda r: r.prioridade) if candidatas else None


def homogeneidade(precos: Sequence[float]) -> dict[str, Any]:
    """O grupo é comparável? `{comparavel, cv, n, razao_max_min, motivo}`.

    O coeficiente de variação é a medida certa aqui porque é adimensional: compara dispersão de
    parafuso e de retroescavadeira na mesma régua.
    """
    valores = [float(p) for p in (precos or []) if p not in (None, "") and float(p) > 0]
    n = len(valores)
    if n < 2:
        return {"comparavel": False, "cv": None, "n": n, "razao_max_min": None,
                "motivo": "amostra insuficiente para medir dispersão"}
    media = statistics.fmean(valores)
    dp = statistics.pstdev(valores)
    cv = dp / media if media else 0.0
    razao = max(valores) / min(valores)
    comparavel = cv <= CV_MAXIMO_COMPARAVEL and n >= N_MINIMO_REFERENCIA
    if not comparavel:
        motivo = (f"dispersão alta demais (CV {cv:.2f} > {CV_MAXIMO_COMPARAVEL:.2f}; "
                  f"razão máx/mín {razao:.0f}×) — o grupo reúne itens DIFERENTES sob a mesma "
                  f"descrição" if cv > CV_MAXIMO_COMPARAVEL else
                  f"amostra pequena (n={n} < {N_MINIMO_REFERENCIA}) — mediana ainda não é referência")
    else:
        motivo = f"grupo homogêneo (CV {cv:.2f}, n={n})"
    return {"comparavel": comparavel, "cv": round(cv, 4), "n": n,
            "razao_max_min": round(razao, 2), "motivo": motivo}


def avaliar(preco_contratado: float | None, precos_referencia: Sequence[float], *,
            fonte_referencia: str = "", data_referencia: str = "",
            quantidade_executada: float | None = None,
            pago_ob: float | None = None) -> dict[str, Any]:
    """Classifica em sobrepreço × superfaturamento, com a prova que cada um exige.

    `pago_ob` é o valor efetivamente PAGO, apurado em Ordem Bancária. Sem ele não há
    superfaturamento — no máximo sobrepreço. Empenho não entra aqui por decisão de projeto: a
    casa trata empenho como valor bruto cancelável, e chamá-lo de pagamento já custou uma
    correção de R$ 2,11 bi.
    """
    base = {"classificacao": None, "sobrepreco_pct": None, "dano": None,
            "fonte_referencia": fonte_referencia, "data_referencia": data_referencia,
            "definicoes": DEFINICOES}
    try:
        preco = float(preco_contratado) if preco_contratado is not None else None
    except (TypeError, ValueError):
        preco = None
    if not preco or preco <= 0:
        return {**base, "aferivel": False,
                "motivo": "preço contratado ausente — nada a comparar (ausente ≠ zero)"}

    hom = homogeneidade(precos_referencia)
    if not hom["comparavel"]:
        return {**base, "aferivel": False, "homogeneidade": hom,
                "achado_alternativo": {
                    "familia": "planejamento",
                    "descricao": ("A comparação de preço fica prejudicada porque a descrição do "
                                  "item agrupa produtos diferentes. Isso é, em si, achado de "
                                  "PLANEJAMENTO: a especificação deve permitir a aferição do "
                                  "preço (Lei 14.133/2021, art. 40)."),
                },
                "motivo": f"grupo não comparável — {hom['motivo']}"}
    if not fonte_referencia:
        return {**base, "aferivel": False, "homogeneidade": hom,
                "motivo": "referência sem fonte declarada — não sustenta glosa"}

    valores = [float(p) for p in precos_referencia if p and float(p) > 0]
    # Mediana como padrão (IN SEGES 65/2021); média exigiria justificativa, e justificativa não
    # se inventa em código.
    mediana = statistics.median(valores)
    pct = (preco - mediana) / mediana if mediana else 0.0
    r = {**base, "aferivel": True, "homogeneidade": hom, "mediana_referencia": round(mediana, 2),
         "estatistica": "mediana (IN SEGES 65/2021 — média exigiria justificativa nos autos)",
         "sobrepreco_pct": round(pct, 4)}

    if pct <= 0:
        return {**r, "classificacao": None,
                "motivo": "preço contratado igual ou abaixo da referência"}

    r["classificacao"] = SOBREPRECO
    r["motivo"] = (f"preço {pct:.1%} acima da mediana de referência "
                   f"({fonte_referencia}{', ' + data_referencia if data_referencia else ''})")

    if pago_ob and float(pago_ob) > 0:
        qtd = float(quantidade_executada) if quantidade_executada else None
        dano = (preco - mediana) * qtd if qtd else None
        r["classificacao"] = SUPERFATURAMENTO
        r["dano"] = round(dano, 2) if dano is not None else None
        r["memoria_de_calculo"] = (
            f"(preço contratado R$ {moeda(preco)} − mediana de referência R$ {moeda(mediana)}) "
            f"× quantidade executada {qtd:g} = R$ {moeda(dano)}" if dano is not None else
            "quantidade executada não informada — o dano não foi quantificado")
        r["motivo"] += "; com pagamento comprovado em Ordem Bancária, o sobrepreço configura DANO"
        if dano is None:
            r["lacuna"] = ("pagamento comprovado, mas sem quantidade executada: o dano existe e "
                           "não está quantificado — pedir a medição")
    else:
        r["lacuna"] = ("sem Ordem Bancária que comprove pagamento: é SOBREPREÇO, não "
                       "superfaturamento. Empenho não é pagamento.")
    return r


def intervalo_economia(economias_homogeneas: Sequence[float],
                       economias_brutas: Sequence[float]) -> dict[str, Any]:
    """Manchete de economia como INTERVALO, nunca como número único.

    Regra derivada das quatro manchetes superestimadas que a casa já corrigiu: o número bruto
    (todos os grupos) e o número homogêneo (só grupos comparáveis) são os dois extremos honestos,
    e publicar só o primeiro é o que produziu R$ 15,6 mi onde havia R$ 6,2 mi.
    """
    hom = sum(float(x) for x in (economias_homogeneas or []) if x)
    bruta = sum(float(x) for x in (economias_brutas or []) if x)
    return {
        "minimo": round(hom, 2),
        "maximo": round(max(hom, bruta), 2),
        "n_homogeneos": len(list(economias_homogeneas or [])),
        "n_total": len(list(economias_brutas or [])),
        "texto": (f"entre R$ {moeda(hom)} (somente grupos comparáveis, "
                  f"n={len(list(economias_homogeneas or []))}) e "
                  f"R$ {moeda(max(hom, bruta))} (todos os grupos, "
                  f"n={len(list(economias_brutas or []))})"),
        "ressalva": ("O limite superior inclui grupos cuja descrição agrupa produtos diferentes; "
                     "só o limite inferior é comparação entre iguais."),
    }
