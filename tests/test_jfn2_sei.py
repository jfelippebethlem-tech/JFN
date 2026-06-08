# -*- coding: utf-8 -*-
"""Onda 5 (SEI funcional) — scaffolding: classificador_doc, extrator_precos (camadas), navegador (wrap itkava)."""
from __future__ import annotations


def test_classificar_doc_por_titulo():
    from compliance_agent.sei.classificador_doc import classificar_doc, tem_preco
    assert classificar_doc("Termo de Homologação") == "homologacao"
    assert classificar_doc("Ata de Registro de Preços nº 12/2025") == "ata_rp"
    assert classificar_doc("Termo de Contrato 050/2024") == "contrato"
    assert classificar_doc("Mapa de Lances") == "mapa_lances"
    assert classificar_doc("Termo de Referência") == "tr"
    assert classificar_doc("Ofício de encaminhamento") == "outros"
    assert tem_preco("homologacao") and not tem_preco("tr")


def test_classificar_rotulos_reais_calibrados():
    """Rótulos REAIS vistos no piloto SRP (UG 270060) — calibração empírica."""
    from compliance_agent.sei.classificador_doc import classificar_doc, tem_preco
    assert classificar_doc("Nota de Empenho Original - NE") == "empenho"
    assert classificar_doc("Nota de Autorização de Despesa - NAD") == "autorizacao_despesa"
    assert classificar_doc("Despacho de Encaminhamento de Processo") == "parecer"
    assert classificar_doc("Recibo") == "outros" and classificar_doc("E-mail") == "outros"
    # novo tipo que CARREGA preço (alvo do varredor)
    assert classificar_doc("Planilha de Preços") == "planilha_preco" and tem_preco("planilha_preco")
    assert classificar_doc("Proposta de Preço da empresa") == "planilha_preco"


def test_num_br():
    from compliance_agent.sei.extrator_precos import _num_br
    assert _num_br("1.234,56") == 1234.56
    assert _num_br("R$ 2.000,00") == 2000.0
    assert _num_br("") is None and _num_br(None) is None


def test_extrair_itens_llm_texto():
    from compliance_agent.sei import extrator_precos as E
    texto = "Item 1 ... tabela de preços ..."
    def _gerar(prompt):
        return '[{"item":"1","descricao":"Notebook i7","unidade":"un","quantidade":"10","valor_unitario":"4.500,00","valor_total":"45.000,00"}]'
    itens, metodo, conf = E.extrair_itens(texto, gerar=_gerar)
    assert metodo == "llm_texto" and conf == 0.8
    assert itens[0]["valor_unitario"] == 4500.0 and itens[0]["quantidade"] == 10.0


def test_extrair_itens_falha_honesta():
    from compliance_agent.sei import extrator_precos as E
    # sem texto plausível e sem gerar → falha (nunca chuta)
    itens, metodo, conf = E.extrair_itens("", gerar=None)
    assert itens == [] and metodo == "falha" and conf == 0.0
    # gerar devolve lista vazia (sem tabela de preços) → falha honesta
    itens2, metodo2, _ = E.extrair_itens("texto qualquer", gerar=lambda p: "[]")
    assert itens2 == [] and metodo2 == "falha"


def test_navegador_abrir_processo_mapeia_arvore(monkeypatch):
    from compliance_agent.sei import navegador

    async def _fake_ler(numero, usar_cache=True):
        return {"numero": numero, "url": "http://sei/x", "texto": "...",
                "documentos": [{"texto": "Termo de Homologação", "url": "http://sei/doc1.pdf"},
                               {"texto": "Ofício 123", "url": "http://sei/doc2"}],
                "conteudo_documentos": [{"doc": "Termo de Homologação", "conteudo": "tabela de itens..."}],
                "cnpjs": ["11222333000144"], "valores": ["R$ 45.000,00"]}

    import compliance_agent.collectors.sei_cdp as cdp
    monkeypatch.setattr(cdp, "ler_processo_sei", _fake_ler)
    r = navegador.abrir_processo("E-12/001/2026")
    assert r["ok"] is True and len(r["docs"]) == 2
    d0 = r["docs"][0]
    assert d0.titulo == "Termo de Homologação" and d0.formato == "pdf" and "tabela" in d0.conteudo
    assert navegador.baixar(d0) == "tabela de itens..."


def test_navegador_erro_honesto(monkeypatch):
    from compliance_agent.sei import navegador

    async def _waf(numero, usar_cache=True):
        return {"erro": "WAF bloqueou a página"}

    import compliance_agent.collectors.sei_cdp as cdp
    monkeypatch.setattr(cdp, "ler_processo_sei", _waf)
    r = navegador.abrir_processo("E-12/001/2026")
    assert r["ok"] is False and "WAF" in r["erro"] and r["docs"] == []
