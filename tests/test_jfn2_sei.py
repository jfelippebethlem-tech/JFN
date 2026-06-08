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
    assert classificar_doc("Ofício de encaminhamento") == "tramitacao"  # ruído de tramitação
    assert classificar_doc("Documento sem rótulo conhecido xyz") == "outros"
    assert tem_preco("homologacao") and not tem_preco("tr")


def test_classificar_por_conteudo_quando_titulo_numerico():
    """Onda 2: título vem como ID numérico → classifica pelo cabeçalho do conteúdo. Sem falso-positivo
    de keyword curta por substring (ex.: 'tr' em 'administracao' NÃO vira termo_referencia)."""
    from compliance_agent.sei.classificador_doc import classificar_doc
    # título numérico + conteúdo de ARP → detecta ata_rp pelo conteúdo
    assert classificar_doc("132513499", "ATA DE REGISTRO DE PRECOS n 01/2024 itens e valores") == "ata_rp"
    # título numérico + conteúdo de tramitação → tramitacao
    assert classificar_doc("99682088", "Diretoria de Administracao. TERMO DE ENCERRAMENTO de processo.") == "tramitacao"
    # texto administrativo sem tipo de doc → 'outros' (NÃO falso-positivo de 'tr'/'nad')
    assert classificar_doc("123", "Empresa de Obras. Considerando a quitacao integral do faturamento.") == "outros"
    # título informativo ainda prevalece (compatibilidade)
    assert classificar_doc("Termo de Homologacao", "qualquer coisa") == "homologacao"


def test_classificar_rotulos_reais_calibrados():
    """Rótulos REAIS vistos no piloto SRP (UG 270060) — calibração empírica."""
    from compliance_agent.sei.classificador_doc import classificar_doc, tem_preco
    assert classificar_doc("Nota de Empenho Original - NE") == "empenho"
    assert classificar_doc("Nota de Autorização de Despesa - NAD") == "autorizacao_despesa"
    # despacho de mero encaminhamento = ruído (tramitação), não substância
    assert classificar_doc("Despacho de Encaminhamento de Processo") == "tramitacao"
    assert classificar_doc("Recibo") == "tramitacao" and classificar_doc("E-mail") == "tramitacao"
    # novo tipo que CARREGA preço (alvo do varredor)
    assert classificar_doc("Planilha de Preços") == "planilha_preco" and tem_preco("planilha_preco")
    assert classificar_doc("Proposta de Preço da empresa") == "planilha_preco"


def test_parecer_juridico_e_politica_de_storage():
    """Insight do dono: parecer jurídico (PGE/assessoria) aponta as FALHAS → alto valor; ruído não guarda texto."""
    from compliance_agent.sei.classificador_doc import classificar_doc, valor_doc, deve_guardar_texto
    assert classificar_doc("Parecer da Procuradoria Geral do Estado") == "parecer_juridico"
    assert classificar_doc("Análise Jurídica nº 45") == "parecer_juridico"
    assert valor_doc("parecer_juridico") == "alto" and deve_guardar_texto("parecer_juridico") is True
    assert valor_doc("ata_rp") == "alto" and valor_doc("empenho") == "medio"
    # ruído: guarda só título/contagem, não o texto
    assert valor_doc("tramitacao") == "baixo" and deve_guardar_texto("tramitacao") is False
    assert deve_guardar_texto("outros") is False


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


def test_navegador_extrai_processos_relacionados(monkeypatch):
    """A árvore expõe 'Processos Relacionados' (procedimento_visualizar) → cadeia licitação↔contrato↔pagamento."""
    from compliance_agent.sei import navegador

    async def _fake(numero, usar_cache=True):
        return {"numero": numero, "url": "http://sei/x", "texto": "...",
                "documentos": [{"texto": "Nota de Empenho - NE", "url": "http://sei/documento_visualizar?id=1"}],
                "relacionados": [
                    {"texto": "SEI-270060/000123/2022", "titulo": "Pregão Eletrônico SRP", "url": "http://sei/procedimento_visualizar?id=9"},
                    {"texto": "E-12/345/2021", "titulo": "", "url": "http://sei/procedimento_visualizar?id=8"}],
                "conteudo_documentos": []}

    import compliance_agent.collectors.sei_cdp as cdp
    monkeypatch.setattr(cdp, "ler_processo_sei", _fake)
    r = navegador.abrir_processo("E-12/001/2026")
    assert r["ok"] is True and len(r["docs"]) == 1
    rel = r["relacionados"]
    assert len(rel) == 2
    assert rel[0]["numero"].startswith("SEI-270060/000123") and "Pregão" in rel[0]["titulo"]
    assert rel[1]["numero"].startswith("E-12/345/2021")


def test_navegador_diagnostica_zero_docs(monkeypatch):
    """0 docs honesto: acesso restrito (RED FLAG) vs busca não resolvida (falha técnica) vs árvore vazia."""
    from compliance_agent.sei import navegador
    import compliance_agent.collectors.sei_cdp as cdp

    async def _restrito(numero, usar_cache=True):
        return {"numero": numero, "url": "http://sei/proc", "documentos": [], "relacionados": [],
                "texto": "Este processo possui ACESSO RESTRITO conforme nível de acesso definido."}
    monkeypatch.setattr(cdp, "ler_processo_sei", _restrito)
    r = navegador.abrir_processo("E-1/1/2025")
    assert r["acesso_restrito"] is True and r["motivo_zero"] == "acesso_restrito"

    async def _busca(numero, usar_cache=True):
        return {"numero": numero, "url": "https://sei.rj.gov.br/sei/controlador.php?acao=protocolo_pesquisar",
                "documentos": [], "relacionados": [], "texto": "GOVERNO... Iniciar Processo Pesquisa"}
    monkeypatch.setattr(cdp, "ler_processo_sei", _busca)
    r2 = navegador.abrir_processo("E-2/2/2025")
    assert r2["acesso_restrito"] is False and r2["motivo_zero"] == "busca_nao_resolveu"

    # "Nenhum resultado encontrado" (texto real do SEI-RJ) = processo NÃO localizado/acessível
    # pela unidade (nº ruidoso da OB ou fora do escopo ITERJ) — NÃO é falha técnica do reader.
    async def _sem(numero, usar_cache=True):
        return {"numero": numero, "url": "https://sei.rj.gov.br/sei/controlador.php?acao=protocolo_pesquisar",
                "documentos": [], "relacionados": [],
                "texto": "Resultado da Pesquisa ... Nenhum resultado encontrado. Sugestões:"}
    monkeypatch.setattr(cdp, "ler_processo_sei", _sem)
    r3 = navegador.abrir_processo("E-3/3/2025")
    assert r3["acesso_restrito"] is False and r3["motivo_zero"] == "nenhum_resultado"


def test_navegador_cadeado_icone_marca_restrito(monkeypatch):
    """Cadeado (ícone) é sinal mais confiável que texto: acesso_restrito=True mesmo sem marcador textual."""
    from compliance_agent.sei import navegador
    import compliance_agent.collectors.sei_cdp as cdp

    async def _cad(numero, usar_cache=True):
        return {"numero": numero, "url": "http://sei/proc", "texto": "processo normal sem palavra-chave",
                "documentos": [{"texto": "Doc 1", "url": "http://sei/documento_visualizar?id=1", "restrito": True}],
                "relacionados": [], "cadeado": True, "n_docs_restritos": 1}
    monkeypatch.setattr(cdp, "ler_processo_sei", _cad)
    r = navegador.abrir_processo("E-9/9/2025")
    assert r["cadeado"] is True and r["acesso_restrito"] is True and r["n_docs_restritos"] == 1
