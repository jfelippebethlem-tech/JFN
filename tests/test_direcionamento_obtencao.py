# -*- coding: utf-8 -*-
"""Ponte de OBTENÇÃO do edital+ata — "se vira pra conseguir" (diretriz do dono 2026-07-24).

Direcionamento EXIGE o edital e a ata. Um processo de execução/pagamento não os traz — mas cita o
certame-lastro (Pregão/ARP). Em vez de fingir veredito "resolvido" sobre a peça errada (desonesto), o
sistema VAI BUSCAR o edital+ata do certame e reavalia sobre os documentos reais. Só quando a obtenção
genuinamente falha é que se reporta a lacuna — dizendo o que foi tentado (honesto), nunca fabricando.

Tudo sem rede: `buscar_docs` é injetável (async(refs, contexto) -> [{titulo,tipo,texto}]).
"""
from __future__ import annotations

import json

from compliance_agent import direcionamento_cerebro as DC

# Um processo de EXECUÇÃO (não é edital/ata) que CITA o pregão-lastro.
_EXECUCAO = ("PROCESSO DE PAGAMENTO. Nota de Empenho e liquidação referentes à Ata de Registro de Preços "
             "nº 012/2024, oriunda do Pregão Eletrônico nº 045/2024. Execução do contrato. " * 20)

# Documentos REAIS do certame que a busca retorna: um edital com cláusula FORTE e uma ata com cascata.
_DOC_EDITAL = {"titulo": "Edital de Pregão Eletrônico nº 045/2024", "tipo": "Edital",
               "texto": ("EDITAL DE PREGAO ELETRONICO. Termo de Referencia e habilitacao. Qualificacao "
                         "tecnica. Proposta. É vedado o somatorio de atestados de capacidade tecnica. " * 12)}
_DOC_ATA = {"titulo": "Ata da Sessão Pública / Mapa de Lances", "tipo": "Ata",
            "texto": ("ATA DA SESSAO. A empresa ALFA foi inabilitada por nao apresentar atestado de "
                      "capacidade tecnica. A empresa BETA foi inabilitada por nao apresentar atestado de "
                      "capacidade tecnica. A empresa GAMA foi inabilitada por nao apresentar atestado de "
                      "capacidade tecnica. Declarada vencedora a empresa OMEGA. " * 6)}


def _fake_llm(grau_json):
    async def _g(_):
        return json.dumps(grau_json)
    return _g


async def _busca_ok(refs, contexto):
    """Fake do fetcher — devolve o edital e a ata do certame referenciado."""
    return [_DOC_EDITAL, _DOC_ATA]


async def _busca_vazia(refs, contexto):
    return []


# ── obter_edital_ata: separa edital de ata a partir dos docs baixados ──────────
def test_obter_separa_edital_e_ata():
    import asyncio
    obt = asyncio.run(DC.obter_edital_ata(_EXECUCAO, buscar_docs=_busca_ok))
    assert obt["obtido"] is True
    assert "vedado o somatorio" in obt["edital_txt"].lower()
    assert "inabilitada" in obt["ata_txt"].lower()
    assert obt["refs"]["n_refs"] >= 1                 # extraiu o Pregão/ARP do texto
    assert obt["n_docs"] == 2


def test_obter_honesto_quando_busca_vazia():
    import asyncio
    obt = asyncio.run(DC.obter_edital_ata(_EXECUCAO, buscar_docs=_busca_vazia))
    assert obt["obtido"] is False and obt["edital_txt"] == "" and obt["ata_txt"] == ""


# ── avaliar_direcionamento_resolvido: vai buscar e reavalia sobre os docs reais ─
def test_vai_buscar_edital_ata_e_da_veredito_real():
    """Texto de execução (não é edital) → o sistema BUSCA o edital+ata e conclui vermelho pelos documentos
    reais (FORTE+cascata). Prova que não fingiu 'resolvido' sobre a peça errada."""
    import asyncio
    res = asyncio.run(DC.avaliar_direcionamento_resolvido(
        _EXECUCAO, gerar=_fake_llm({"grau": "verde", "dados_suficientes": True}), buscar_docs=_busca_ok))
    assert res["grau"] == "vermelho"                  # veredito pelos documentos obtidos
    assert res["obtencao"]["n_docs"] == 2             # proveniência do que foi buscado
    assert res["grau"] not in ("nao_aplicavel", "indeterminado", "indisponivel")


def test_falha_de_obtencao_e_honesta_nao_fake():
    """Busca não retorna nada → NÃO finge 'resolvido': reporta a lacuna dizendo o que tentou."""
    import asyncio
    res = asyncio.run(DC.avaliar_direcionamento_resolvido(
        _EXECUCAO, gerar=_fake_llm({"grau": "verde"}), buscar_docs=_busca_vazia))
    assert res["grau"] == "edital_ata_nao_obtido"
    assert "obten" in res["resumo"].lower() or "obt" in res["resumo"].lower()
    assert res["obtencao"]["refs"]["n_refs"] >= 1     # mostra que tentou pelo certame referenciado
    assert res["grau"] != "nao_aplicavel"             # não maquia a lacuna como resolução


def test_texto_ja_edital_nao_busca():
    """Se o texto JÁ é edital/ata, não sai buscando (economia) — dá o veredito direto."""
    import asyncio
    chamou = {"n": 0}
    async def _busca_espia(refs, ctx):
        chamou["n"] += 1
        return []
    edital = ("EDITAL DE PREGAO ELETRONICO. Termo de referencia habilitacao qualificacao tecnica proposta. " * 30
              + "É vedado o somatorio de atestados. ")
    res = asyncio.run(DC.avaliar_direcionamento_resolvido(
        edital, gerar=_fake_llm({"grau": "amarelo", "dados_suficientes": True}), buscar_docs=_busca_espia))
    assert chamou["n"] == 0                            # não precisou buscar
    assert res["grau"] in ("amarelo", "vermelho")     # veredito direto do edital
