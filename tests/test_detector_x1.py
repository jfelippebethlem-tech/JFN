# -*- coding: utf-8 -*-
"""Teste TARGETED do detector X1 (crescimento aditivo / contrato que engorda) — spec V2 do dono, §X1.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO (dicts), LLM ausente OU rubrica pré-classificada
injetada (sem rede). Cobre: estouro do teto art.125 (crítico), teto 50% de reforma, aditivo de só-prazo que NÃO
conta no teto, confirmação por rubrica 'objeto_novo_disfarcado', exculpatória (acréscimo pequeno + superveniente
documentado) e nao_avaliavel sem dados essenciais.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_x1.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.x1_crescimento_aditivo import X1CrescimentoAditivo


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


# ═══════════════════════════════ (a) ESTOURO do teto art.125 → CRÍTICO ═══════════════════════════════
def test_x1_confirma_critico_estouro_teto():
    """Acréscimos somam > 25% do valor inicial (estouro objetivo do art.125) → crítico."""
    ctx = {
        "processo": "exec-1",
        "valor_inicial": 1_000_000.0,
        "tipo_objeto": "obra",
        "aditivos": [
            {"data": "2025-03-01", "tipo": "valor", "valor": 150_000.0, "justificativa": "acréscimo de quantitativos"},
            {"data": "2025-05-01", "tipo": "valor", "valor": 130_000.0, "justificativa": "novos itens"},
        ],
    }
    r = X1CrescimentoAditivo().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]
    assert r.valores["estouro_teto"] is True
    assert r.valores["pct_acrescimo"] == 0.28
    assert r.evidencia


# ═══════════════════════════════ (b) REFORMA usa teto de 50% ═══════════════════════════════
def test_x1_reforma_teto_50_nao_estoura():
    """Acréscimo de 30% em REFORMA fica sob o teto de 50% (não estoura); a mesma % estouraria em obra (25%)."""
    aditivos = [{"data": "2025-04-01", "tipo": "valor", "valor": 300_000.0}]
    ctx_reforma = {"processo": "exec-2r", "valor_inicial": 1_000_000.0, "tipo_objeto": "reforma de edifício",
                   "aditivos": aditivos}
    r = X1CrescimentoAditivo().avaliar(ctx_reforma)
    _valido(r)
    assert r.valores["teto_art125"] == 0.50
    assert r.valores["estouro_teto"] is False  # 30% < 50%

    # contraste: mesma % em obra (teto 25%) estoura
    ctx_obra = {"processo": "exec-2o", "valor_inicial": 1_000_000.0, "tipo_objeto": "obra", "aditivos": aditivos}
    r2 = X1CrescimentoAditivo().avaliar(ctx_obra)
    _valido(r2)
    assert r2.valores["estouro_teto"] is True
    assert r2.score == ANCORAS["critico"]


# ═══════════════════════════════ (c) aditivo de SÓ-PRAZO não conta no teto ═══════════════════════════════
def test_x1_aditivo_so_prazo_nao_conta_no_teto():
    """Aditivo de prazo sem valor NÃO consome o teto (análise X2). Acréscimo de valor permanece sob controle."""
    ctx = {
        "processo": "exec-3",
        "valor_inicial": 1_000_000.0,
        "tipo_objeto": "obra",
        "aditivos": [
            {"data": "2025-02-01", "tipo": "prazo", "valor": 0.0, "justificativa": "prorrogação de 90 dias"},
            {"data": "2025-06-01", "tipo": "prazo"},  # sem valor
            {"data": "2025-07-01", "tipo": "valor", "valor": 50_000.0},  # 5% só
        ],
    }
    r = X1CrescimentoAditivo().avaliar(ctx)
    _valido(r)
    assert r.valores["n_aditivos_de_valor"] == 1  # só-prazo ignorados
    assert r.valores["pct_acrescimo"] == 0.05
    assert r.valores["estouro_teto"] is False
    assert r.status == "descartado"  # 5% < metade do teto, sem rubrica


# ═══════════════════════════════ (d) confirma por rubrica 'objeto_novo_disfarcado' ═══════════════════════════════
def test_x1_confirma_rubrica_objeto_novo():
    """Acréscimo pequeno, mas rubrica de pertinência injetada 'objeto_novo_disfarcado' → forte autônomo."""
    ctx = {
        "processo": "exec-4",
        "valor_inicial": 1_000_000.0,
        "tipo_objeto": "obra",
        "objeto": "pavimentação asfáltica da via X",
        "aditivos": [
            {"data": "2025-03-01", "tipo": "objeto", "valor": 40_000.0,
             "descricao_objeto": "construção de praça e quadra poliesportiva"},
        ],
        "_rubrica_pertinencia": {"nivel": "objeto_novo_disfarcado",
                                 "trecho": "construção de praça e quadra poliesportiva"},
    }
    r = X1CrescimentoAditivo().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["pertinencia"] == "objeto_novo_disfarcado"


def test_x1_confirma_rubrica_falha_de_projeto_precoce():
    """Aditivo de valor PRECOCE (< 90 dias do início) com rubrica 'falha_de_projeto_admitida' → forte (desenho deliberado)."""
    ctx = {
        "processo": "exec-4b",
        "valor_inicial": 1_000_000.0,
        "tipo_objeto": "obra",
        "data_inicio_execucao": "2025-01-01",
        "aditivos": [
            {"data": "2025-02-15", "tipo": "valor", "valor": 60_000.0,
             "justificativa": "quantitativos subestimados no projeto básico"},
        ],
        "_rubricas_justificativa": [
            {"nivel": "falha_de_projeto_admitida", "trecho": "quantitativos subestimados no projeto básico"},
        ],
    }
    r = X1CrescimentoAditivo().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert "falha_de_projeto_admitida" in r.valores["justificativas"]
    assert r.valores["dias_ate_1o_aditivo_valor"] == 45


# ═══════════════════════════════ (e) exculpatória → descartado ═══════════════════════════════
def test_x1_descartado_superveniente_documentado():
    """Acréscimo pequeno (5%) + rubrica 'fato_superveniente_verificavel' (evento datado/documentado) → descartado."""
    ctx = {
        "processo": "exec-5",
        "valor_inicial": 2_000_000.0,
        "tipo_objeto": "obra",
        "aditivos": [
            {"data": "2025-08-01", "tipo": "valor", "valor": 100_000.0,
             "justificativa": "laudo geotécnico de 2025-07-10 apontou solo instável"},
        ],
        "_rubricas_justificativa": [
            {"nivel": "fato_superveniente_verificavel", "trecho": "laudo geotécnico de 2025-07-10"},
        ],
    }
    r = X1CrescimentoAditivo().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.valores["pct_acrescimo"] == 0.05


# ═══════════════════════════════ (f) nao_avaliavel sem dados essenciais ═══════════════════════════════
def test_x1_nao_avaliavel_sem_valor_inicial():
    """Sem valor_inicial → nao_avaliavel (campo ausente ≠ 0)."""
    r = X1CrescimentoAditivo().avaliar({"processo": "exec-6", "aditivos": [{"tipo": "valor", "valor": 100.0}]})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0
    assert r.valores["tem_valor_inicial"] is False


def test_x1_nao_avaliavel_sem_aditivos():
    """Com valor_inicial mas sem aditivos → nao_avaliavel."""
    r = X1CrescimentoAditivo().avaliar({"processo": "exec-7", "valor_inicial": 1_000_000.0})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0
    assert r.valores["n_aditivos"] == 0


def test_x1_rubricas_nao_avaliaveis_sem_llm():
    """Sem LLM e sem rubrica injetada: parte subjetiva fica nao_avaliavel, cálculo objetivo permanece."""
    ctx = {
        "processo": "exec-8",
        "valor_inicial": 1_000_000.0,
        "tipo_objeto": "obra",
        "aditivos": [{"data": "2025-05-01", "tipo": "valor", "valor": 300_000.0}],  # 30% → estoura 25%
    }
    r = X1CrescimentoAditivo().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]
    assert r.valores["pertinencia"] == "nao_avaliavel"
    assert all(s == "nao_avaliavel" for s in r.valores["justificativas"])


# ═══════════════════════════════ reajuste NÃO consome o teto do art.125 ═══════════════════════════════
def test_x1_reajuste_por_justificativa_nao_conta_no_teto():
    """Aditivo 'valor' cuja justificativa é REAJUSTE (IPCA) é recomposição de preço, não acréscimo —
    excluído do teto: 26% brutos viram 6% reais → descartado (era falso ESTOURO)."""
    ctx = {
        "processo": "exec-9",
        "valor_inicial": 1_000_000.0,
        "aditivos": [
            {"data": "2025-03-01", "tipo": "valor", "valor": 200_000.0,
             "justificativa": "reajuste anual pelo IPCA, cláusula 12ª"},
            {"data": "2025-06-01", "tipo": "valor", "valor": 60_000.0,
             "justificativa": "acréscimo de quantitativos"},
        ],
    }
    r = X1CrescimentoAditivo().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.valores["pct_acrescimo"] == 0.06
    assert r.valores["n_aditivos_reajuste"] == 1
    assert r.valores["n_aditivos_de_valor"] == 1


def test_x1_reajuste_por_tipo_e_repactuacao_nao_contam():
    """`tipo` de reajuste/repactuação também exclui (campo estruturado, sem depender da justificativa)."""
    ctx = {
        "processo": "exec-10",
        "valor_inicial": 1_000_000.0,
        "aditivos": [
            {"data": "2025-03-01", "tipo": "reajuste", "valor": 150_000.0},
            {"data": "2025-05-01", "tipo": "valor", "valor": 140_000.0,
             "justificativa": "repactuação de preços por convenção coletiva"},
        ],
    }
    r = X1CrescimentoAditivo().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.valores["pct_acrescimo"] == 0.0
    assert r.valores["n_aditivos_reajuste"] == 2


# ═══════ base desmentida pelos próprios autos (2026-08-04) ═══════

def test_nao_afirma_estouro_sobre_base_que_os_autos_contradizem():
    """Medido no SEI-070002/001289/2022: a base saiu de uma "Publicação Errata 01"
    (R$ 46.866,00) e o X1 anunciou acréscimo de **10.024%**. O contrato é o 38/2023, de
    R$ 105.988.095,41 — declarado seis vezes nos autos — e o aditivo de R$ 4.697.858,84 é 4,4%,
    dentro do teto. Não havia achado nenhum, e o processo liderava a fila de risco.

    A base sai da 1ª ocorrência do padrão num monte de dezenas de documentos concatenados, sem
    noção de qual deles é o contrato. A refutação não é limiar arbitrário: é o próprio processo
    declarando outro número, sobre o qual o acréscimo cabe no teto.
    """
    r = X1CrescimentoAditivo().avaliar({
        "processo": "SEI-070002/001289/2022", "valor_inicial": 46_866.00, "tipo_objeto": "obra",
        "aditivos": [{"data": "2025-01-01", "tipo": "valor", "valor": 4_697_858.84,
                      "justificativa": "acréscimo de quantitativos"}],
        "_texto_fonte": ("valor do contrato de R$ 46.866,00 ... o Contrato nº 38/2023, no valor "
                         "de R$ 105.988.095,41, recebe acréscimo de R$ 4.697.858,84")})
    assert r.status == "nao_avaliavel" and r.score == 0.0
    assert r.valores.get("base_contraditada_por") == 105_988_095.41
    assert "não fecham" in (r.motivo_refutacao or "")


def test_estouro_real_continua_confirmado_quando_nada_o_contradiz():
    """O corte só vale quando o TEXTO oferece outra base que faz o acréscimo caber no teto — sem
    isso, estouro é estouro. Do contrário a refutação viraria anistia geral."""
    r = X1CrescimentoAditivo().avaliar({
        "processo": "P-1", "valor_inicial": 1_000_000.0, "tipo_objeto": "obra",
        "aditivos": [{"data": "2025-01-01", "tipo": "valor", "valor": 400_000.0,
                      "justificativa": "acréscimo"}],
        "_texto_fonte": "contrato de R$ 1.000.000,00 com aditivo de R$ 400.000,00"})
    assert r.status == "confirmado" and r.score > 0


def test_sem_texto_fonte_o_detector_segue_como_antes():
    """Chamador que não passa `_texto_fonte` (teste, CLI, contexto sintético) não perde o X1."""
    r = X1CrescimentoAditivo().avaliar({
        "processo": "P-2", "valor_inicial": 100_000.0, "tipo_objeto": "obra",
        "aditivos": [{"data": "2025-01-01", "tipo": "valor", "valor": 90_000.0,
                      "justificativa": "acréscimo"}]})
    assert r.status == "confirmado"
