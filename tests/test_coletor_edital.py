# -*- coding: utf-8 -*-
"""Teste TARGETED do COLETOR SEI → ctx → pipeline de detectores (spec V2).

Estratégia (leve, VM 2 vCPU/sem swap): MOCK de ``ler`` com um EDITAL de exemplo em texto plausível (datas,
exigências de habilitação, lotes/itens, valor estimado); LLM AUSENTE (usar_llm=False — sem rede/browser).
Verifica: (a) ``montar_ctx_de_sei`` extrai datas/modalidade/exigências/lotes/valor do texto por regex, com
proveniência; (b) ``analisar_processo_sei`` roda os detectores e devolve ResultadoDetector(s) no schema §1.4;
(c) leitura vazia / com erro → INDISPONIVEL honesto.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_coletor_edital.py -q
"""
from __future__ import annotations

import asyncio

from compliance_agent.detectores.base import STATUS_VALIDOS
from compliance_agent.detectores.coletor_edital import (
    analisar_processo_sei,
    analisar_processo_sei_sync,
    montar_ctx_de_sei,
)

# ───────────────────────────── fixture: EDITAL de exemplo (texto plausível) ─────────────────────────────
_EDITAL_TXT = """
PREFEITURA / SECRETARIA — EDITAL DE LICITAÇÃO
Modalidade: PREGÃO ELETRÔNICO Nº 12/2024
Critério de julgamento: MENOR PREÇO por lote.

Data de publicação do edital: 03/06/2024
Data de abertura da sessão pública: 10/06/2024 às 10:00

Valor estimado da contratação: R$ 1.200.000,00

DA HABILITAÇÃO
Atestado de capacidade técnica comprovando o fornecimento de no mínimo 800 unidades do objeto.
Capital social mínimo de R$ 240.000,00 integralizado na data de abertura.
Patrimônio líquido mínimo equivalente a 12% do valor estimado.

DO OBJETO E DOS LOTES
LOTE 1
Item 1 - Notebook corporativo i7 16GB - CATMAT 1234
Item 2 - Cadeira de escritório ergonômica - CATSER 5678
Item 3 - Serviço de manutenção predial - CATMAT 9012
"""


def _leitura_ok(numero: str = "SEI-510001/000876/2024") -> dict:
    """Dict no formato de ``sei_reader.ler`` (sucesso) com o edital de exemplo."""
    # como o reader real: `texto` é o resumo da árvore (curto); a íntegra do edital vem no documento.
    return {
        "numero": numero,
        "texto": "Processo de licitação — Pregão Eletrônico 12/2024. Árvore: Edital, Termo de Referência.",
        "documentos": [{"texto": "Edital 12/2024", "url": "https://sei/doc/1"}],
        "conteudo_documentos": [
            {"doc": "Edital de Pregão 12/2024", "conteudo": _EDITAL_TXT},
        ],
        "relacionados": [],
        "cnpjs": [],
        "valores": ["R$ 1.200.000,00"],
    }


def _ler_mock_ok(numero: str):
    async def _ler(_n):
        return _leitura_ok(numero)
    return _ler


def _ler_mock_vazio(_n=None):
    async def _ler(_n):
        return {"numero": "x", "texto": "", "documentos": [], "conteudo_documentos": []}
    return _ler


def _ler_mock_erro(_n=None):
    async def _ler(_n):
        return {"numero": "x", "erro": "INDISPONÍVEL: SEI_PASS vazio (.env)", "texto": "", "conteudo_documentos": []}
    return _ler


# ───────────────────────────── (a) montar_ctx_de_sei — extração por regex ─────────────────────────────
def test_montar_ctx_extrai_campos_basicos():
    ctx = montar_ctx_de_sei(_leitura_ok(), usar_llm=False)

    assert ctx["processo"] == "SEI-510001/000876/2024"
    assert ctx["modalidade"] == "pregao"
    assert ctx["criterio"] == "menor_preco"
    assert ctx["data_publicacao"].startswith("2024-06-03")
    assert ctx["data_abertura"].startswith("2024-06-10")
    assert ctx["data_abertura_processo"].startswith("2024-06-10")  # rótulo do P5
    assert ctx["valor_estimado"] == 1_200_000.00


def test_montar_ctx_extrai_exigencias_com_provenancia():
    ctx = montar_ctx_de_sei(_leitura_ok(), usar_llm=False)
    exig = ctx["exigencias_habilitacao"]
    tipos = {e["tipo"] for e in exig}
    assert "atestado" in tipos
    assert "capital_social" in tipos
    assert "patrimonio_liquido" in tipos

    # capital social com valor absoluto extraído (R$ 240.000,00)
    cap = next(e for e in exig if e["tipo"] == "capital_social")
    assert cap["valor"] == 240_000.00
    # patrimônio líquido: "12% do valor estimado" → convertido para absoluto com base real
    pl = next(e for e in exig if e["tipo"] == "patrimonio_liquido")
    assert pl["valor"] == round(0.12 * 1_200_000.00, 2)

    # proveniência: cada exigência cita doc/trecho
    for e in exig:
        assert "prov" in e and e["prov"]["doc"] and e["prov"]["trecho"]
    assert ctx["_proveniencia"]["valor_estimado"]["doc"]


def test_montar_ctx_extrai_lotes_e_itens_com_catmat():
    ctx = montar_ctx_de_sei(_leitura_ok(), usar_llm=False)
    lotes = ctx["lotes"]
    assert len(lotes) == 1
    itens = lotes[0]["itens"]
    assert len(itens) == 3
    classes = {it.get("catmat") for it in itens}
    assert {"1234", "5678", "9012"}.issubset(classes)  # ≥3 mercados → E3 candidato


def test_montar_ctx_campo_ausente_fica_fora_do_ctx():
    """Honestidade: texto sem datas/exigências → campos NÃO entram (detector vira nao_avaliavel)."""
    leitura = {"numero": "SEI-1", "texto": "Documento administrativo sem dados de licitação.",
               "documentos": [{"url": "u"}], "conteudo_documentos": []}
    ctx = montar_ctx_de_sei(leitura, usar_llm=False)
    assert "data_publicacao" not in ctx
    assert "exigencias_habilitacao" not in ctx
    assert "lotes" not in ctx


# ───────────────────────────── (b) analisar_processo_sei — roda o pipeline ─────────────────────────────
def test_analisar_roda_detectores_e_retorna_resultados():
    out = asyncio.run(analisar_processo_sei("SEI-510001/000876/2024", ler_fn=_ler_mock_ok("SEI-510001/000876/2024")))

    assert out["status"] == "OK"
    assert out["ctx_resumo"]["modalidade"] == "pregao"
    assert out["ctx_resumo"]["n_lotes"] == 1
    assert out["proveniencia"]  # proveniência propagada

    # detectores de edital + planejamento rodaram (E1/E2/E3 + P1/P2/P5)
    ids = {r["detector"] for r in out["resultados"]}
    assert {"E1", "E2", "E3", "P1", "P2", "P5"}.issubset(ids)

    # schema §1.4 + status válidos
    for r in out["resultados"]:
        assert r["status"] in STATUS_VALIDOS
        assert 0.0 <= r["score"] <= 1.0
        assert set(r) == {"detector", "processo", "score", "valores", "evidencia",
                          "explicacao_inocente", "refutada", "motivo_refutacao", "status"}

    assert isinstance(out["confirmados"], list)
    assert isinstance(out["nao_avaliaveis"], list)


def test_analisar_e2_confirma_prazo_curto_em_dado_real():
    """Pregão pub 03/06 → abertura 10/06 = 5 dias úteis < mínimo art.55 (8) → E2 confirmado pelo dado extraído."""
    out = asyncio.run(analisar_processo_sei("SEI-510001/000876/2024", ler_fn=_ler_mock_ok("SEI-510001/000876/2024")))
    e2 = next(r for r in out["resultados"] if r["detector"] == "E2")
    assert e2["status"] == "confirmado"
    assert e2["valores"]["prazo_util_dias"] < e2["valores"]["minimo_art55_dias"]
    assert e2["evidencia"]


def test_analisar_e1_confirma_capital_acima_do_teto():
    """Capital R$ 240k + PL 12% > 10% do valor estimado → E1 confirmado (teto art. 69 §3º)."""
    out = asyncio.run(analisar_processo_sei("SEI-510001/000876/2024", ler_fn=_ler_mock_ok("SEI-510001/000876/2024")))
    e1 = next(r for r in out["resultados"] if r["detector"] == "E1")
    assert e1["status"] == "confirmado"


def test_sync_wrapper_funciona():
    out = analisar_processo_sei_sync("SEI-1", ler_fn=_ler_mock_ok("SEI-1"))
    assert out["status"] == "OK"
    assert out["numero"] == "SEI-1"


# ───────────────────────────── (c) honestidade: INDISPONIVEL ─────────────────────────────
def test_leitura_vazia_retorna_indisponivel():
    out = asyncio.run(analisar_processo_sei("SEI-vazio", ler_fn=_ler_mock_vazio()))
    assert out["status"] == "INDISPONIVEL"
    assert "documentos" in out["motivo"] or "vazia" in out["motivo"]


def test_leitura_com_erro_retorna_indisponivel():
    out = asyncio.run(analisar_processo_sei("SEI-erro", ler_fn=_ler_mock_erro()))
    assert out["status"] == "INDISPONIVEL"
    assert "SEI_PASS" in out["motivo"]
