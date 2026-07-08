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


# ───────────────────────────── (a2) cláusulas restritivas (E7) ─────────────────────────────
_EDITAL_RESTRITIVO = """
EDITAL DE CONCORRÊNCIA Nº 07/2024
Valor estimado da contratação: R$ 2.000.000,00

DA HABILITAÇÃO E QUALIFICAÇÃO
Atestado de capacidade técnica comprovando execução de no mínimo 80% do quantitativo licitado.
Patrimônio líquido mínimo equivalente a 15% do valor estimado.
Garantia de participação na licitação no valor de 3% do valor estimado.
A licitante deverá possuir sede ou filial no Município, para pronta assistência técnica local.
Visita técnica obrigatória, como condição de habilitação, a ser realizada pelo responsável técnico.
Os equipamentos deverão ser da marca ThermoKing modelo TK-500.
"""


def _leitura_restritiva(numero: str = "SEI-330020/000762/2021") -> dict:
    return {
        "numero": numero,
        "texto": "Processo de licitação — Concorrência 07/2024.",
        "documentos": [{"texto": "Edital 07/2024", "url": "https://sei/doc/9"}],
        "conteudo_documentos": [{"doc": "Edital de Concorrência 07/2024", "conteudo": _EDITAL_RESTRITIVO}],
    }


def test_montar_ctx_extrai_clausulas_restritivas_com_categoria():
    ctx = montar_ctx_de_sei(_leitura_restritiva(), usar_llm=False)
    clausulas = ctx["clausulas_edital"]
    tipos = {c["tipo"] for c in clausulas}
    # categorias distintas presentes (técnica, econômica, geográfica, marca)
    assert {"recorte_geografico", "visita_tecnica", "marca_dirigida"}.issubset(tipos)
    assert {"capital_patrimonio", "garantia_proposta"} & tipos
    categorias = {c["categoria"] for c in clausulas}
    assert {"geografico", "marca", "tecnica"}.issubset(categorias)
    # proveniência por cláusula
    for c in clausulas:
        assert c["prov"]["doc"] and c["prov"]["trecho"]


def test_clausula_marca_sem_ou_equivalente_flag():
    ctx = montar_ctx_de_sei(_leitura_restritiva(), usar_llm=False)
    marca = next(c for c in ctx["clausulas_edital"] if c["tipo"] == "marca_dirigida")
    assert marca["tem_ou_equivalente"] is False  # "marca X modelo Y" sem "ou equivalente" → gatilho negativo


def test_clausula_garantia_converte_pct_para_valor():
    ctx = montar_ctx_de_sei(_leitura_restritiva(), usar_llm=False)
    gar = next(c for c in ctx["clausulas_edital"] if c["tipo"] == "garantia_proposta")
    assert gar["pct"] == 0.03
    assert gar["valor"] == round(0.03 * 2_000_000.00, 2)


def test_edital_limpo_sem_clausulas_restritivas():
    """Edital sem gatilhos restritivos → clausulas_edital fica FORA do ctx (campo ausente ≠ 0)."""
    leitura = {"numero": "SEI-2", "texto": "Pregão menor preço, ampla concorrência.",
               "documentos": [{"url": "u"}], "conteudo_documentos": []}
    ctx = montar_ctx_de_sei(leitura, usar_llm=False)
    assert "clausulas_edital" not in ctx


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


def test_end_to_end_edital_mais_ata_destrava_julgamento_e_e7():
    """Edital restritivo + ata de julgamento no MESMO processo: o coletor_ata popula `resultado`/`decisoes` →
    E1 sai de nao_avaliavel (ganha o resultado), E7 confirma cláusula, e o julgamento (J7) PASSA a rodar
    (antes o gate exigia `propostas`) e encontra o par divergente."""
    ata = """
ATA DE SESSÃO DE JULGAMENTO — CONCORRÊNCIA 07/2024
A empresa ALFA LTDA, CNPJ 11.111.111/0001-11, foi INABILITADA por certidão de regularidade fiscal vencida.
A empresa BETA LTDA, CNPJ 22.222.222/0001-22, com a mesma certidão vencida, teve prazo para saneamento
(diligência), sendo HABILITADA e declarada VENCEDORA, proposta R$ 1.900.000,00.
"""
    leitura = {
        "numero": "SEI-330020/000762/2021",
        "texto": "Processo de licitação — Concorrência 07/2024.",
        "documentos": [{"url": "u1"}, {"url": "u2"}],
        "conteudo_documentos": [
            {"doc": "Edital de Concorrência 07/2024", "conteudo": _EDITAL_RESTRITIVO},
            {"doc": "Ata de Sessão de Julgamento 07/2024", "conteudo": ata},
        ],
    }

    async def _ler(_n):
        return leitura

    out = asyncio.run(analisar_processo_sei("SEI-330020/000762/2021", ler_fn=_ler))
    assert out["status"] == "OK"
    por_id = {r["detector"]: r for r in out["resultados"]}

    # E1 ganhou o `resultado` da ata → não fica mais nao_avaliavel (PL 15% > 10% + resultado corrobora)
    assert por_id["E1"]["status"] == "confirmado"
    # E7 confirma cláusula restritiva com fundamentação
    assert por_id["E7"]["status"] == "confirmado"
    assert por_id["E7"]["valores"].get("fundamentacao_juridica")
    # o julgamento PASSOU a rodar (J7 presente) e o pareamento objetivo achou o par divergente
    assert "J7" in por_id
    assert por_id["J7"]["valores"].get("n_pares_divergentes", 0) >= 1
    assert out["ctx_resumo"]["tem_decisoes"] is True


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
