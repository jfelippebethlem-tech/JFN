# -*- coding: utf-8 -*-
"""X7 — reequilíbrio indevido (art. 124). O card que não existia e cuja ausência custou caro.

Antes dele, "reequilíbrio" aparecia UMA vez no código do JFN, e como regex de classificação.
Nenhum detector olhava o art. 124. A régua de `limites_aditivo` tirou a recomposição do teto do
art. 125 — e isso corrigiu 45% de falso positivo no X1 —, mas tirar do teto não é auditar.

O ponto do X7: recomposição é a via SEM teto percentual. Quem quer crescer o contrato além dos
25% do art. 125 tem incentivo direto para chamar o acréscimo de "revisão". Estes testes travam
os cinco sinais objetivos e a linha da honestidade — o que é lacuna de CAPTURA não pode virar
achado, lição das 9.863 red flags do sweep SEI em que 59% eram queixa de captura.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores import REGISTRO

X7 = REGISTRO["X7"]


def _ad(tipo="reajuste", valor=100_000.0, **kw):
    d = {"tipo": tipo, "valor": valor}
    d.update(kw)
    return d


def _ctx(**kw):
    base = {"processo": "P-1", "valor_inicial": 1_000_000.0, "aditivos": []}
    base.update(kw)
    return base


# ───────────────────────────── honestidade: ausência ≠ zero ───────────────────────────────────

def test_sem_aditivos_e_nao_avaliavel():
    r = X7.avaliar(_ctx())
    assert r.status == "nao_avaliavel" and r.score == 0.0


def test_so_acrescimo_e_prazo_nao_aciona_o_card():
    """X7 é sobre RECOMPOSIÇÃO — acréscimo é do X1, prazo é do X2."""
    r = X7.avaliar(_ctx(aditivos=[_ad(tipo="valor"), _ad(tipo="prazo")]))
    assert r.status == "nao_avaliavel"
    assert r.valores["n_recomposicoes"] == 0


def test_recomposicao_isolada_e_regular_e_descartada():
    r = X7.avaliar(_ctx(aditivos=[_ad(valor=30_000.0, data="2024-06-01")]))
    assert r.status == "descartado" and r.score == 0.0


# ───────────────────────────── T1 · dupla correção ────────────────────────────────────────────

def test_duas_recomposicoes_no_mesmo_exercicio_e_critico():
    """Reequilíbrio e reajuste sobre o mesmo período pagam duas vezes a mesma perda de valor."""
    r = X7.avaliar(_ctx(aditivos=[_ad(data="2024-03-01", valor=50_000.0),
                                  _ad(data="2024-09-01", valor=60_000.0)]))
    assert r.status == "confirmado" and r.score == pytest.approx(1.0)
    assert "2024" in r.valores["anos_com_dupla_correcao"]
    assert any("DUPLA CORREÇÃO" in e["trecho"] for e in r.evidencia)


def test_recomposicoes_em_anos_distintos_nao_sao_dupla_correcao():
    r = X7.avaliar(_ctx(aditivos=[_ad(data="2023-03-01", valor=50_000.0),
                                  _ad(data="2024-03-01", valor=50_000.0)]))
    assert "anos_com_dupla_correcao" not in r.valores


# ───────────────────────────── T2 · índice divergente ─────────────────────────────────────────

def test_indice_aplicado_diferente_do_contratado():
    r = X7.avaliar(_ctx(indice_contratado="IPCA",
                        aditivos=[_ad(data="2024-01-01", indice_aplicado="IGP-M")]))
    assert r.status == "confirmado" and r.score == pytest.approx(0.85)
    assert r.valores["indices_divergentes"] == ["igpm"]


def test_variacao_de_grafia_do_indice_nao_gera_falso_positivo():
    """'IPCA-E', 'ipca e' e 'IPCA' são o mesmo índice — comparar cru viraria ruído."""
    r = X7.avaliar(_ctx(indice_contratado="IPCA-E",
                        aditivos=[_ad(data="2024-01-01", indice_aplicado="ipca")]))
    assert "indices_divergentes" not in r.valores


def test_sem_indice_contratado_declara_a_lacuna_em_vez_de_acusar():
    r = X7.avaliar(_ctx(aditivos=[_ad(data="2024-01-01", indice_aplicado="IGP-M")]))
    assert any("indice_contratado" in x for x in r.valores["lacunas"])


# ───────────────────────────── T3 · sem pleito ────────────────────────────────────────────────

def test_revisao_de_oficio_e_forte():
    r = X7.avaliar(_ctx(aditivos=[_ad(data="2024-01-01", houve_pleito=False)]))
    assert r.status == "confirmado" and r.valores["n_sem_pleito"] == 1


def test_ausencia_do_campo_pleito_e_lacuna_nao_achado():
    """INDISPONÍVEL ≠ ausência de pleito. A base não guardar o dado não é vício do gestor."""
    r = X7.avaliar(_ctx(aditivos=[_ad(data="2024-01-01")]))
    assert r.status == "descartado"
    assert any("pleito" in x for x in r.valores["lacunas"])


# ───────────────────────────── T4 · magnitude ─────────────────────────────────────────────────

def test_recomposicao_acima_do_teto_do_art_125_e_forte():
    """Recomposição não tem teto — e é justamente por isso que ela é a via conveniente."""
    r = X7.avaliar(_ctx(valor_inicial=1_000_000.0,
                        aditivos=[_ad(data="2024-01-01", valor=400_000.0)]))
    assert r.status == "confirmado"
    assert r.valores["pct_recomposicao"] == pytest.approx(0.40)
    assert any("MAGNITUDE" in e["trecho"] for e in r.evidencia)


def test_sem_valor_inicial_a_magnitude_nao_e_aferida():
    r = X7.avaliar(_ctx(valor_inicial=None, aditivos=[_ad(data="2024-01-01", valor=400_000.0)]))
    assert any("magnitude" in x for x in r.valores["lacunas"])
    assert "pct_recomposicao" not in r.valores


# ───────────────────────────── T5 · reiteração ────────────────────────────────────────────────

def test_tres_revisoes_por_alea_EXTRAORDINARIA_indicam_desequilibrio_estrutural():
    """REVISTO em 2026-08-04: o teste passava com aditivos sem justificativa nenhuma, e o detector
    contava reajuste anual junto com reequilíbrio. O texto do achado invoca "álea EXTRAORDINÁRIA",
    e reajuste por índice é ORDINÁRIO e previsto — um contrato de cinco anos tem quatro reajustes
    sem nada de errado. A intenção do teste é a mesma; o que mudou é que a recomposição precisa
    trazer a marca da álea extraordinária."""
    r = X7.avaliar(_ctx(aditivos=[
        _ad(data=f"202{i}-01-01", valor=10_000.0,
            justificativa="pedido de reequilíbrio econômico-financeiro por álea extraordinária")
        for i in range(1, 4)]))
    assert r.status == "confirmado"
    assert any("REITERAÇÃO" in e["trecho"] for e in r.evidencia)


def test_reajuste_anual_por_INDICE_nao_conta_como_reiteracao():
    """Medido no acervo: **18 dos 20 disparos** do X7 não tinham NENHUMA recomposição
    extraordinária — e entre as "recomposições" contadas havia endereço e cabeçalho de documento
    ("Francisco Matarazzo, nº 1.350, 17º andar"), porque a extração casa a frase que menciona a
    palavra. Erro jurídico também é falso positivo."""
    r = X7.avaliar(_ctx(aditivos=[
        _ad(data=f"202{i}-01-01", valor=10_000.0,
            justificativa="reajuste anual pelo IPCA, na forma da cláusula décima do contrato")
        for i in range(1, 5)]))
    assert not any("REITERAÇÃO" in e["trecho"] for e in (r.evidencia or []))


def test_o_achado_declara_quantas_eram_ao_todo():
    """O fiscal precisa ver as duas contagens: quantas revisões extraordinárias e quantas
    recomposições havia — senão o número parece menor do que o movimento do contrato."""
    r = X7.avaliar(_ctx(aditivos=[
        _ad(data="2021-01-01", valor=10_000.0, justificativa="reajuste anual pelo IPCA"),
        *[_ad(data=f"202{i}-06-01", valor=10_000.0,
              justificativa="reequilíbrio por álea extraordinária documentada") for i in range(2, 5)],
    ]))
    trecho = " ".join(e["trecho"] for e in (r.evidencia or []))
    assert "3 revisões por álea extraordinária" in trecho and "de 4 recomposições" in trecho


# ───────────────────────────── rubrica de álea (LLM-opcional) ─────────────────────────────────

def test_alea_ordinaria_disfarcada_e_forte_autonomo():
    """Inflação chamada de revisão é reajuste vestido — o vetor mais comum de fuga do teto."""
    texto = "Requer-se a revisão em razão do aumento de custos dos insumos no período."
    r = X7.avaliar(_ctx(aditivos=[_ad(data="2024-01-01", justificativa=texto)],
                        _rubricas_alea=[{"resposta": {"nivel": "ordinaria_disfarcada",
                                                      "trecho": "aumento de custos dos insumos"},
                                         "fonte": texto}]))
    assert r.status == "confirmado" and r.score >= 0.85


def test_alea_extraordinaria_documentada_exculpa():
    texto = ("Requer-se a revisão em razão da Portaria ANP 45/2024, de 12/03/2024, que elevou "
             "em 40% o tributo incidente sobre o insumo, conforme laudo anexo.")
    r = X7.avaliar(_ctx(aditivos=[_ad(data="2024-01-01", justificativa=texto)],
                        _rubricas_alea=[{"resposta": {"nivel": "extraordinaria_documentada",
                                                      "trecho": "Portaria ANP 45/2024"},
                                         "fonte": texto}]))
    assert r.status == "descartado"


def test_rubrica_com_citacao_inventada_e_descartada():
    """Grounding conferido: a citação tem de existir no pleito."""
    texto = "Requer-se a revisão contratual."
    r = X7.avaliar(_ctx(aditivos=[_ad(data="2024-01-01", justificativa=texto)],
                        _rubricas_alea=[{"resposta": {"nivel": "ordinaria_disfarcada",
                                                      "trecho": "o gestor admitiu o conluio"},
                                         "fonte": texto}]))
    assert r.status == "descartado", "citação inventada sustentou achado"


def test_sem_llm_a_parte_objetiva_permanece_e_a_lacuna_e_declarada():
    r = X7.avaliar(_ctx(aditivos=[_ad(data="2024-01-01", houve_pleito=False)]))
    assert r.status == "confirmado"          # o objetivo (T3) sobrevive
    assert any("rubrica de álea" in x for x in r.valores["lacunas"])


def test_llm_que_estoura_nao_derruba_o_card():
    def explode(*_a, **_k):
        raise RuntimeError("provedor fora do ar")

    r = X7.avaliar(_ctx(aditivos=[_ad(data="2024-01-01", justificativa="texto")], gerar=explode))
    assert r.status in {"confirmado", "descartado"}
    assert any("indisponível" in x for x in r.valores["lacunas"])


# ───────────────────────────── contrato de saída ──────────────────────────────────────────────

def test_achado_traz_explicacao_inocente():
    """Presunção de legitimidade: o card entrega a melhor hipótese lícita junto com o indício."""
    r = X7.avaliar(_ctx(aditivos=[_ad(data="2024-03-01", valor=50_000.0),
                                  _ad(data="2024-09-01", valor=60_000.0)]))
    assert "álea extraordinária real" in r.explicacao_inocente


def test_evidencia_tem_hash_e_fonte():
    r = X7.avaliar(_ctx(aditivos=[_ad(data="2024-03-01"), _ad(data="2024-09-01")]))
    for e in r.evidencia:
        assert e["hash"] and e["fonte"] and e["capturado_em"]


def test_esta_no_registro_e_na_fase_de_execucao():
    from compliance_agent.detectores import PESOS_DETECTOR, rodar_execucao

    assert "X7" in PESOS_DETECTOR
    res = rodar_execucao("P-1", contexto=_ctx(aditivos=[_ad(data="2024-01-01")]))
    assert any(x.detector == "X7" for x in res)
