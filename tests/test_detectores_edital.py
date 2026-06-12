# -*- coding: utf-8 -*-
"""Teste TARGETED dos detectores da FASE DE EDITAL: E1 (barreira), E2 (prazos), E3 (lote-pacote) — spec V2.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO DE EDITAL (dicts), LLM ausente OU rubrica
pré-classificada injetada (sem rede). Para cada detector: (a) caso que CONFIRMA, (b) caso exculpatório/descartado,
(c) ctx sem campo essencial → nao_avaliavel. As partes OBJETIVAS são determinísticas (limiar no código).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detectores_edital.py -q
"""
from __future__ import annotations

from compliance_agent.detectores import (
    ANCORAS,
    REGISTRO,
    E1Barreira,
    E2Prazos,
    E3LotePacote,
    ResultadoDetector,
    rodar_edital,
    score_processo,
)
from compliance_agent.detectores.base import STATUS_VALIDOS
from compliance_agent.detectores.e2_prazos import dias_uteis, minimo_art55


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


# ═══════════════════════════════ E1 — barreira de entrada ═══════════════════════════════
def test_e1_confirma_atestado_acima_de_100pct():
    """Atestado exige quantitativo > 100% do licitado → crítico (violação objetiva)."""
    ctx = {
        "processo": "edital-1",
        "exigencias_habilitacao": [
            {"tipo": "atestado", "texto": "atestado de fornecimento", "quantitativo_exigido": 1200},
        ],
        "quantitativos": 1000,
        "resultado": {"licitantes": 1, "inabilitados": 2},
    }
    r = E1Barreira().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]            # >100% do quantitativo = crítico
    assert r.evidencia


def test_e1_confirma_capital_acima_do_teto_10pct():
    """Capital social exigido > 10% do valor estimado (art. 69 §3º) → forte."""
    ctx = {
        "processo": "edital-2",
        "exigencias_habilitacao": [
            {"tipo": "capital_social", "texto": "capital social mínimo", "valor": 300_000.0},
        ],
        "valor_estimado": 1_000_000.0,   # 30% → acima do teto de 10%
    }
    r = E1Barreira().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["valor_estimado"] == 1_000_000.0


def test_e1_sob_medida_vs_analogos():
    """Exigência ausente em ≥metade dos análogos → candidata a sob medida (médio)."""
    ctx = {
        "processo": "edital-3",
        "exigencias_habilitacao": [{"tipo": "certificacao_rara_xyz", "texto": "certificação XYZ proprietária"}],
        "editais_analogos": [
            {"exigencias": [{"tipo": "atestado"}]},
            {"exigencias": [{"tipo": "atestado"}, {"tipo": "balanco"}]},
        ],
    }
    r = E1Barreira().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["medio"]
    assert "certificacao_rara_xyz" in r.valores["exigencias_sob_medida"]


def test_e1_exculpatorio_objeto_critico_rebaixa():
    """Objeto crítico (UTI/segurança) justifica exigência alta → score rebaixado para no máx 'medio'."""
    ctx = {
        "processo": "edital-4",
        "exigencias_habilitacao": [
            {"tipo": "atestado", "texto": "atestado", "quantitativo_exigido": 1200},
        ],
        "quantitativos": 1000,
        "objeto_critico": True,
    }
    r = E1Barreira().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score <= ANCORAS["medio"]              # crítico rebaixado por objeto crítico
    assert r.valores["objeto_critico"] is True


def test_e1_exculpatorio_rubrica_proporcional():
    """Rubrica LLM diz 'proporcional ao risco' (injetada, sem rede) → exculpatória, score ≤ fraco."""
    ctx = {
        "processo": "edital-5",
        "exigencias_habilitacao": [
            {"tipo": "atestado", "texto": "atestado", "quantitativo_exigido": 1200,
             "_rubrica_pertinencia": {"nivel": "proporcional_ao_risco", "trecho": "exige metade do contrato"}},
        ],
        "quantitativos": 1000,
    }
    r = E1Barreira().avaliar(ctx)
    _valido(r)
    assert r.score <= ANCORAS["fraco"]
    assert r.valores["pertinencia"] == "proporcional_ao_risco"


def test_e1_descartado_dentro_dos_limites():
    """Atestado < 50% e sem análogos divergentes → descartado."""
    ctx = {
        "processo": "edital-6",
        "exigencias_habilitacao": [{"tipo": "atestado", "texto": "atestado", "quantitativo_exigido": 300}],
        "quantitativos": 1000,
    }
    r = E1Barreira().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_e1_nao_avaliavel_sem_exigencias():
    r = E1Barreira().avaliar({"processo": "edital-7"})
    _valido(r)
    assert r.status == "nao_avaliavel"


def test_e1_nao_avaliavel_sem_base_numerica():
    """Tem exigências mas sem valor estimado, sem quantitativo, sem análogos → nao_avaliavel honesto."""
    ctx = {"processo": "edital-8", "exigencias_habilitacao": [{"tipo": "atestado", "texto": "x"}]}
    r = E1Barreira().avaliar(ctx)
    _valido(r)
    assert r.status == "nao_avaliavel"


# ═══════════════════════════════ E2 — prazos minimizados ═══════════════════════════════
def test_e2_tabela_art55_e_dias_uteis():
    """Sanidade das funções objetivas determinísticas."""
    assert minimo_art55("pregao", "menor_preco") == 8
    assert minimo_art55("concorrencia", "tecnica_e_preco") == 15
    assert minimo_art55("modalidade_inexistente") is None
    from datetime import date
    # seg 2024-01-01 (feriado) a seg 2024-01-15: descontando 1º jan e fins de semana
    n = dias_uteis(date(2024, 1, 1), date(2024, 1, 15), {date(2024, 1, 1)})
    assert n == 10


def test_e2_confirma_prazo_abaixo_do_minimo():
    """Pregão com prazo útil < 8 dias úteis → forte (violação art. 55)."""
    ctx = {
        "processo": "cert-1",
        "modalidade": "pregao", "criterio": "menor_preco",
        "data_publicacao": "2024-03-04",   # segunda
        "data_abertura": "2024-03-11",      # segunda seguinte = 5 dias úteis (< 8)
    }
    r = E2Prazos().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["prazo_util_dias"] < r.valores["minimo_art55_dias"]


def test_e2_no_piso_so_fraco():
    """Prazo exatamente no mínimo legal → 'fraco' (lícito; agravante, não sustenta sozinho)."""
    ctx = {
        "processo": "cert-2",
        "modalidade": "pregao", "criterio": "menor_preco",
        "data_publicacao": "2024-03-01",   # sexta
        "data_abertura": "2024-03-13",      # qua seguinte → 8 dias úteis exatos
    }
    r = E2Prazos().avaliar(ctx)
    _valido(r)
    assert r.valores["prazo_util_dias"] == r.valores["minimo_art55_dias"] == 8
    assert r.score == ANCORAS["fraco"]


def test_e2_ausencia_pncp_forte():
    ctx = {
        "processo": "cert-3", "modalidade": "pregao", "criterio": "menor_preco",
        "data_publicacao": "2024-03-01", "data_abertura": "2024-04-01", "no_pncp": False,
    }
    r = E2Prazos().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["no_pncp"] is False


def test_e2_retificacao_impacta_sem_reabertura():
    """Retificação que afeta substância (rubrica injetada) sem reabrir prazo → forte."""
    ctx = {
        "processo": "cert-4", "modalidade": "pregao", "criterio": "menor_preco",
        "data_publicacao": "2024-03-01", "data_abertura": "2024-04-01",  # prazo folgado
        "versoes": [{
            "secao": "especificacao", "antes": "modelo A", "depois": "modelo B exclusivo",
            "reabriu_prazo": False,
            "_rubrica_impacto": {"nivel": "afeta_substancialmente", "trecho": "modelo B exclusivo"},
        }],
    }
    r = E2Prazos().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]


def test_e2_descartado_prazo_folgado():
    ctx = {
        "processo": "cert-5", "modalidade": "pregao", "criterio": "menor_preco",
        "data_publicacao": "2024-03-01", "data_abertura": "2024-05-01",  # prazo amplo, sem flags
    }
    r = E2Prazos().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_e2_nao_avaliavel_sem_datas():
    r = E2Prazos().avaliar({"processo": "cert-6", "modalidade": "pregao"})
    _valido(r)
    assert r.status == "nao_avaliavel"


def test_e2_nao_avaliavel_modalidade_desconhecida():
    ctx = {"processo": "cert-7", "modalidade": "modalidade_xyz",
           "data_publicacao": "2024-03-01", "data_abertura": "2024-03-11"}
    r = E2Prazos().avaliar(ctx)
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert "desconhecida" in r.motivo_refutacao


# ═══════════════════════════════ E3 — lote-pacote ═══════════════════════════════
def _lote_heterogeneo():
    """Lote com 5 mercados distintos (classes CATMAT por prefixo)."""
    return [{"id": "L1", "itens": [
        {"descricao": "computador", "catmat": "70010001"},
        {"descricao": "cadeira", "catmat": "71050002"},
        {"descricao": "papel", "catmat": "75090003"},
        {"descricao": "café", "catmat": "78600004"},
        {"descricao": "serviço de limpeza", "catser": "26010005"},
    ]}]


def test_e3_confirma_lote_heterogeneo_sem_justificativa():
    """5 mercados distintos + justificativa ausente → forte."""
    ctx = {"processo": "lote-1", "lotes": _lote_heterogeneo()}  # sem justificativa
    r = E3LotePacote().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["n_mercados_no_lote"] == 5
    assert r.valores["justificativa_status"] == "ausente"


def test_e3_justificativa_generica_medio():
    """Lote heterogêneo com justificativa genérica (rubrica injetada) — agregação confirmada."""
    ctx = {
        "processo": "lote-2",
        "lotes": [{"id": "L1", "itens": [
            {"descricao": "a", "catmat": "70010001"},
            {"descricao": "b", "catmat": "71050002"},
            {"descricao": "c", "catmat": "75090003"},
        ]}],
        "justificativa_nao_parcelamento": "por eficiência administrativa",
        "_rubrica_justificativa": {"nivel": "generica", "trecho": "eficiência administrativa"},
    }
    r = E3LotePacote().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["medio"]
    assert r.valores["justificativa_status"] == "generica"


def test_e3_exculpatorio_integracao_real():
    """Rubrica de interdependência = integração necessária (sistema único) → exculpatória, score ≤ fraco."""
    ctx = {
        "processo": "lote-3",
        "lotes": _lote_heterogeneo(),
        "_rubrica_interdep": {"nivel": "integracao_necessaria", "trecho": "hardware + software do mesmo sistema"},
    }
    r = E3LotePacote().avaliar(ctx)
    _valido(r)
    assert r.score <= ANCORAS["fraco"]
    assert r.valores["interdependencia"] == "integracao_necessaria"


def test_e3_descartado_lote_homogeneo():
    """Lote com itens do MESMO mercado (≤2 classes) → descartado."""
    ctx = {"processo": "lote-4", "lotes": [{"id": "L1", "itens": [
        {"descricao": "toner a", "catmat": "70010001"},
        {"descricao": "toner b", "catmat": "70010002"},   # mesmo prefixo 7001
    ]}]}
    r = E3LotePacote().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_e3_nao_avaliavel_sem_lotes():
    r = E3LotePacote().avaliar({"processo": "lote-5"})
    _valido(r)
    assert r.status == "nao_avaliavel"


def test_e3_nao_avaliavel_sem_classe_catmat():
    """Lotes existem mas nenhum item tem classe → não dá para contar mercados → nao_avaliavel."""
    ctx = {"processo": "lote-6", "lotes": [{"id": "L1", "itens": [
        {"descricao": "item sem código"}, {"descricao": "outro sem código"}]}]}
    r = E3LotePacote().avaliar(ctx)
    _valido(r)
    assert r.status == "nao_avaliavel"


# ═══════════════════════════════ orquestrador + registro ═══════════════════════════════
def test_registro_tem_os_novos_edital():
    assert {"E1", "E2", "E3"} <= set(REGISTRO)
    # não quebrou os existentes
    assert {"P4", "J1", "P3", "C"} <= set(REGISTRO)


def test_rodar_edital_combina_e1_e2_e3():
    ctx = {
        # E1
        "exigencias_habilitacao": [{"tipo": "atestado", "texto": "atestado", "quantitativo_exigido": 1200}],
        "quantitativos": 1000,
        # E2
        "modalidade": "pregao", "criterio": "menor_preco",
        "data_publicacao": "2024-03-04", "data_abertura": "2024-03-11",
        # E3
        "lotes": _lote_heterogeneo(),
    }
    res = rodar_edital("certame-x", contexto=ctx)
    ids = {r.detector for r in res}
    assert {"E1", "E2", "E3"} <= ids
    for r in res:
        _valido(r)
    from compliance_agent.detectores import PESOS_DETECTOR
    s = score_processo(res, PESOS_DETECTOR)
    assert 0.0 <= s <= 1.0


def test_rodar_edital_exculpatoria_degrada_sem_llm():
    """exculpatoria=True com gerar que SIMULA LLM offline → não refuta, não quebra (honesto)."""
    def _gerar_offline(prompt, sistema):
        raise RuntimeError("LLM offline")

    ctx = {"lotes": _lote_heterogeneo()}  # E3 confirma; E1/E2 nao_avaliavel
    res = rodar_edital("certame-y", contexto=ctx, exculpatoria=True, gerar=_gerar_offline)
    for r in res:
        _valido(r)
        if r.status == "confirmado":
            assert r.refutada is False
