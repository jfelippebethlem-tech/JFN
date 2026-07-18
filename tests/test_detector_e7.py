# -*- coding: utf-8 -*-
"""Teste do detector E7 — cláusula-a-cláusula finalística + efeito combinado.

Sem rede/LLM: contextos mínimos por categoria, rubrica de pertinência pré-injetada quando preciso. Verifica os
limiares no código, o efeito combinado (≥3 categorias), o cruzamento com o resultado da ata, a fundamentação
jurídica anexada, e a honestidade (sem cláusulas → nao_avaliavel; edital limpo → descartado).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_e7.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.e7_clausula_restritiva import E7ClausulaRestritiva


def _av(ctx: dict):
    ctx.setdefault("processo", "SEI-TESTE/000001/2024")
    return E7ClausulaRestritiva().avaliar(ctx)


def test_sem_clausulas_nao_avaliavel():
    res = _av({})
    assert res.status == "nao_avaliavel"
    assert res.valores["n_clausulas"] == 0


def test_capital_acima_de_10pct_forte():
    res = _av({"valor_estimado": 1_000_000.0,
               "clausulas_edital": [{"tipo": "capital_patrimonio", "categoria": "economica",
                                     "texto": "Patrimônio líquido mínimo de 15% do valor estimado", "pct": 0.15}]})
    assert res.status == "confirmado"
    assert res.score >= 0.85
    assert "capital_patrimonio" in res.valores["fundamentacao_juridica"]


def test_marca_sem_ou_equivalente_forte():
    res = _av({"clausulas_edital": [{"tipo": "marca_dirigida", "categoria": "marca",
                                     "texto": "Equipamento marca ThermoKing modelo TK-500", "tem_ou_equivalente": False}]})
    assert res.status == "confirmado"
    assert res.score >= 0.85
    fund = res.valores["fundamentacao_juridica"]["marca_dirigida"]
    assert any("270" in s for s in fund["sumulas"])


def test_marca_com_ou_equivalente_descartado():
    res = _av({"clausulas_edital": [{"tipo": "marca_dirigida", "categoria": "marca",
                                     "texto": "marca X ou equivalente", "tem_ou_equivalente": True}]})
    assert res.status == "descartado"


def test_visita_sem_declaracao_forte():
    res = _av({"clausulas_edital": [{"tipo": "visita_tecnica", "categoria": "tecnica",
                                     "texto": "Visita técnica obrigatória, condição de habilitação",
                                     "tem_declaracao_substitutiva": False}]})
    assert res.status == "confirmado"
    assert res.score >= 0.85
    # visita carrega o aviso de verificação (âncora TCU só secundária)
    assert "visita_tecnica" in res.valores.get("verificar_antes_de_citar", [])


def test_efeito_combinado_tres_categorias_forte():
    """3 categorias distintas (econômica + geográfica + marca), cada uma isolada poderia ser branda → forte."""
    res = _av({"valor_estimado": 1_000_000.0, "clausulas_edital": [
        {"tipo": "indices_contabeis", "categoria": "economica", "texto": "índice de liquidez ≥ 2,0",
         "justificativa_autos": False},
        {"tipo": "recorte_geografico", "categoria": "geografico", "texto": "sede no Município"},
        {"tipo": "marca_dirigida", "categoria": "marca", "texto": "marca ABC", "tem_ou_equivalente": False},
    ]})
    assert res.status == "confirmado"
    assert res.score >= 0.85
    assert len(res.valores["categorias_marcadas"]) >= 3
    assert "direcionamento_conjunto" in res.valores["fundamentacao_juridica"]


def test_cumulacao_capital_e_garantia_forte():
    res = _av({"valor_estimado": 1_000_000.0, "clausulas_edital": [
        {"tipo": "capital_patrimonio", "categoria": "economica", "texto": "capital social mínimo 5%", "pct": 0.05},
        {"tipo": "garantia_proposta", "categoria": "economica", "texto": "garantia de participação 0,5%", "pct": 0.005},
    ]})
    assert res.status == "confirmado"
    assert res.score >= 0.85  # cumulação Súmula 275 mesmo com cada um dentro do teto isolado


def test_cumulacao_exige_teste_finalistico_nao_presenca_crua():
    """'Garantia' citada SEM valor/percentual literal (teste finalístico nao_avaliavel) não cumula com o
    capital por mera presença crua — era falso positivo de Súmula 275."""
    res = _av({"valor_estimado": 1_000_000.0, "clausulas_edital": [
        {"tipo": "capital_patrimonio", "categoria": "economica", "texto": "capital social mínimo 5%", "pct": 0.05},
        {"tipo": "garantia_proposta", "categoria": "economica",
         "texto": "garantia de participação conforme o edital"},   # sem pct/valor → nao_avaliavel
    ]})
    assert res.status == "descartado"
    assert res.score == 0.0


def test_cruza_resultado_explica_cascata():
    res = _av({"clausulas_edital": [{"tipo": "recorte_geografico", "categoria": "geografico",
                                     "texto": "sede no Município"}],
               "resultado": {"licitantes": 1, "inabilitados": 2}})
    assert res.status == "confirmado"
    assert any("cascata" in e["trecho"].lower() or "corrobora" in res.motivo_refutacao.lower()
               for e in res.evidencia) or "corrobora" in res.motivo_refutacao


def test_pertinencia_rebaixa_clausula():
    """Rubrica de pertinência 'proporcional_ao_risco' rebaixa a cláusula → não pontua (descartado)."""
    res = _av({"clausulas_edital": [{"tipo": "amostra_poc", "categoria": "amostra",
                                     "texto": "amostra de todos os licitantes antes do julgamento",
                                     "_rubrica_pertinencia": {"nivel": "proporcional_ao_risco",
                                                              "trecho": "amostra de todos os licitantes"}}]})
    assert res.status == "descartado"


def test_objeto_critico_rebaixa():
    res = _av({"objeto_critico": True,
               "clausulas_edital": [{"tipo": "vinculo_profissional", "categoria": "tecnica",
                                     "texto": "vínculo empregatício do responsável técnico"}]})
    assert res.status == "confirmado"
    assert res.score <= 0.6  # objeto crítico rebaixa forte → medio
