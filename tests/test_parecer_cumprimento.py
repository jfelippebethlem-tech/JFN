# -*- coding: utf-8 -*-
"""Cumprimento das CONDICIONANTES do parecer da PGE (pedido do dono 2026-07-24).

Doutrina: "acolho o parecer" NÃO prova cumprimento. O parecer aprova SOB CONDIÇÃO (i, ii, iii) e cada
condicionante tem de ser verificada nos documentos POSTERIORES do processo, item a item. Honesto:
ausência de doc posterior = NÃO VERIFICÁVEL (cobertura), nunca "descumprida".
"""
from __future__ import annotations

import asyncio

from compliance_agent import parecer_cumprimento as PC

_PARECER = (
    "PARECER Nº 145/2024 — PROCURADORIA GERAL DO ESTADO (PGE-RJ). Analisada a minuta do edital, opino "
    "favoravelmente ao prosseguimento, DESDE QUE observadas as seguintes condicionantes: "
    "(i) seja juntada aos autos a pesquisa de preços com no mínimo três cotações, nos termos do art. 23; "
    "(ii) conste a declaração de adequação orçamentária e financeira com a indicação da dotação; "
    "(iii) seja corrigida a cláusula 7.2 da minuta contratual, que prevê pagamento antecipado, vedado pelo "
    "art. 145 da Lei 14.133/2021. Sem o atendimento das ressalvas, o feito não deve prosseguir."
)


def _docs(*posteriores):
    docs = [{"ref": "1", "tipo": "Despacho", "texto": "Encaminho para análise jurídica."},
            {"ref": "2", "tipo": "Parecer PGE", "texto": _PARECER}]
    for i, t in enumerate(posteriores, start=3):
        docs.append({"ref": str(i), "tipo": t[0], "texto": t[1]})
    return docs


# ───────────────────────────── extração das condicionantes ─────────────────────────────

def test_extrai_cada_condicionante_do_parecer():
    conds = PC.extrair_condicionantes(_PARECER)
    assert len(conds) == 3
    assert [c["id"] for c in conds] == ["i", "ii", "iii"]
    assert all(c["trecho"] for c in conds)                      # trecho literal em cada item
    tipos = {c["tipo"] for c in conds}
    assert {"pesquisa_precos", "dotacao_orcamentaria", "minuta_clausula"} <= tipos


def test_condicionante_sem_enumeracao_tambem_e_extraida():
    txt = ("PARECER PGE. Aprovo a minuta, condicionado a que seja juntada a certidão negativa de débitos "
           "do fornecedor antes da assinatura.")
    conds = PC.extrair_condicionantes(txt)
    assert len(conds) == 1
    assert conds[0]["tipo"] == "regularidade_fiscal"


def test_parecer_sem_condicionante_nao_inventa():
    txt = "PARECER PGE. Opino favoravelmente à contratação. Nada a ressalvar."
    assert PC.extrair_condicionantes(txt) == []


def test_boilerplate_de_checklist_nao_vira_condicionante():
    txt = ("PARECER PGE. Recomenda-se a leitura do checklist correspondente e a verificação de sua "
           "autenticidade no portal. Opino favoravelmente.")
    assert PC.extrair_condicionantes(txt) == []


# ───────────────── anti-falso-positivo (trechos REAIS do arquivo SEI, 2026-07-24) ─────────────────

def test_contrato_que_cita_a_procuradoria_nao_e_parecer():
    # trecho real: minuta de contrato mencionando a PGE — citar a procuradoria não faz do doc um parecer
    contrato = ("CONTRATO Nº 10/2024. CLÁUSULA DÉCIMA: o presente ajuste foi previamente examinado pela "
                "Procuradoria Geral do Estado. PARÁGRAFO ÚNICO – A CONTRATADA indica seu preposto, "
                "Engenheiro Lisandro do Nascimento, que fica autorizado a representar a CONTRATADA em suas "
                "relações com o CONTRATANTE, desde que a) mantenha as condições de habilitação.")
    assert PC.extrair_condicionantes(contrato) == [] or PC.e_parecer("Contrato", contrato) is False
    r = PC.auditar_parecer_pge([{"ref": "1", "tipo": "Contrato", "texto": contrato}])
    assert r["veredito"] == "SEM_PARECER_LOCALIZADO"


def test_marcador_solto_no_meio_do_texto_nao_vira_condicionante():
    # regressão real: "(a) Engenheiro" e "(15) SEI/pg. 1" viravam condicionantes de uma linha
    txt = ("PARECER PGE nº 12/2024. Opino favoravelmente desde que sejam observadas as normas. "
           "a) Engenheiro. (15) SEI-030029/002513/2023 / pg. 1 KIT MATERIAL ESCOLAR 18043 164.731")
    conds = PC.extrair_condicionantes(txt)
    assert all(len(c["texto"]) >= PC._MIN_COND for c in conds)
    assert not any(c["texto"].strip() in ("Engenheiro", "Engenheiro.") for c in conds)


def test_itens_fora_de_sequencia_sao_ignorados():
    # só conta enumeração REAL (i, ii, iii…): rótulos avulsos espalhados não formam lista
    txt = ("PARECER PGE. Opino favoravelmente desde que: (i) seja juntada a pesquisa de preços com três "
           "cotações; (ii) conste a dotação orçamentária do exercício corrente. Consta ainda que o item "
           "(x) do anexo trata de outro assunto e a alínea (b) do contrato não se aplica aqui.")
    ids = [c["id"] for c in PC.extrair_condicionantes(txt)]
    assert ids == ["i", "ii"]


def test_tipo_sem_verificador_deterministico_nunca_vira_descumprida():
    # regressão real: itens genéricos ('projeto do ato pretendido') não têm marcador de cumprimento —
    # sem verificador, o honesto é NAO_VERIFICAVEL (a camada LLM julga), nunca NAO_CUMPRIDA
    txt = ("PARECER PGE nº 9/2024. Opino favoravelmente desde que os autos sejam instruídos com: "
           "(i) o projeto do ato pretendido pela autoridade competente; "
           "(ii) a declaração de adequação orçamentária e financeira com indicação da dotação.")
    docs = [{"ref": "1", "tipo": "Parecer PGE", "texto": txt},
            {"ref": "2", "tipo": "Homologação", "texto": "Homologo o resultado do certame."}]
    r = PC.auditar_parecer_pge(docs)
    generico = next(c for c in r["condicionantes"] if c["tipo"] == "outra")
    assert generico["status"] == "NAO_VERIFICAVEL"
    assert "verificador" in generico["observacao"].lower() or "leitura" in generico["observacao"].lower()
    # o item COM verificador (dotação) segue apontável como não cumprido
    assert next(c for c in r["condicionantes"]
                if c["tipo"] == "dotacao_orcamentaria")["status"] == "NAO_CUMPRIDA"


def test_classificacao_olha_o_nucleo_da_exigencia():
    # regressão real: 'publicação' no FIM de um item longo o classificava como 'publicidade'
    item = ("seja juntada aos autos a pesquisa de preços com três cotações, nos termos do art. 23 da Lei "
            "14.133/2021, observando-se ainda as regras aplicáveis à publicação dos atos no Diário Oficial")
    assert PC.classificar_condicionante(item) == "pesquisa_precos"


# ───────────────────────────── verificação do cumprimento ─────────────────────────────

def test_condicionante_cumprida_em_doc_posterior():
    docs = _docs(("Mapa de preços", "Em atendimento ao parecer da PGE, juntada a pesquisa de preços com "
                                    "três cotações: empresa A, B e C."))
    r = PC.auditar_parecer_pge(docs)
    item = next(c for c in r["condicionantes"] if c["tipo"] == "pesquisa_precos")
    assert item["status"] == "CUMPRIDA"
    assert item["evidencia"] and item["doc_ref"] == "3"


def test_cumprimento_so_conta_documento_POSTERIOR_ao_parecer():
    # a pesquisa de preços aparece ANTES do parecer: não serve para cumprir uma condicionante posterior
    docs = [{"ref": "1", "tipo": "Mapa de preços", "texto": "Pesquisa de preços com três cotações juntada."},
            {"ref": "2", "tipo": "Parecer PGE", "texto": _PARECER}]
    r = PC.auditar_parecer_pge(docs)
    item = next(c for c in r["condicionantes"] if c["tipo"] == "pesquisa_precos")
    assert item["status"] == "NAO_VERIFICAVEL"
    assert r["veredito"] == "COBERTURA_INSUFICIENTE"


def test_sem_documento_posterior_e_nao_verificavel_nunca_descumprida():
    r = PC.auditar_parecer_pge(_docs())
    assert {c["status"] for c in r["condicionantes"]} == {"NAO_VERIFICAVEL"}
    assert r["veredito"] == "COBERTURA_INSUFICIENTE"
    assert r["grau"] == "amarelo"                       # fragilidade de captura, não acusação
    assert "captur" in r["acao"].lower() or "coletar" in r["acao"].lower()


def test_descumprimento_quando_processo_avanca_sem_atender():
    # homologou e contratou SEM nenhuma das condicionantes atendidas → indício forte
    docs = _docs(("Termo de Homologação", "Homologo o resultado do certame e adjudico o objeto à vencedora."),
                 ("Contrato", "Contrato nº 10/2024 firmado com a empresa vencedora. Cláusula 7.2 mantida."))
    r = PC.auditar_parecer_pge(docs)
    assert r["veredito"] == "DESCUMPRIDO_INDICIO"
    assert r["grau"] == "vermelho"
    assert any(c["status"] == "NAO_CUMPRIDA" for c in r["condicionantes"])
    assert "indício" in r["leitura"].lower()            # honesto: indício, não acusação


def test_cumprimento_parcial():
    docs = _docs(("Mapa de preços", "Em cumprimento à recomendação da PGE, juntada a pesquisa de preços."),
                 ("Termo de Homologação", "Homologo o resultado do certame e adjudico o objeto."))
    r = PC.auditar_parecer_pge(docs)
    assert r["veredito"] == "CUMPRIDO_PARCIAL"
    assert r["grau"] == "vermelho"                       # avançou sem cumprir tudo
    assert r["n_cumpridas"] == 1 and r["n_nao_cumpridas"] >= 1


def test_cumprimento_integral_fecha_verde():
    docs = _docs(("Mapa de preços", "Em atendimento ao parecer, juntada a pesquisa de preços (três cotações)."),
                 ("Declaração orçamentária", "Declaração de adequação orçamentária e financeira; dotação "
                                             "programa de trabalho 10.302.0025."),
                 ("Minuta retificada", "Retificada a cláusula 7.2 da minuta contratual, suprimido o "
                                       "pagamento antecipado, em atendimento ao parecer da PGE."),
                 ("Termo de Homologação", "Homologo o resultado do certame."))
    r = PC.auditar_parecer_pge(docs)
    assert r["veredito"] == "CUMPRIDO_INTEGRAL"
    assert r["grau"] == "verde"
    assert r["n_nao_cumpridas"] == 0


def test_sem_parecer_e_resolvido_e_honesto():
    r = PC.auditar_parecer_pge([{"ref": "1", "tipo": "Despacho", "texto": "Encaminho para pagamento."}])
    assert r["veredito"] == "SEM_PARECER_LOCALIZADO"
    assert r["grau"] not in ("indeterminado", "indisponivel")
    assert "≠" in r["ressalva"] or "indispon" in r["ressalva"].lower()


def test_veredito_sempre_resolvido():
    for docs in ([], [{"ref": "1", "tipo": "x", "texto": ""}], _docs(), _docs(("Despacho", "Segue."))):
        r = PC.auditar_parecer_pge(docs)
        assert r["veredito"] and r["grau"] not in ("indeterminado", "indisponivel", "")


# ───────────────────────────── camada LLM (subjetiva) + fusão ─────────────────────────────

def test_llm_confirma_descumprimento_material_e_funde():
    # determinístico acha a palavra de cumprimento, mas o LLM vê que é formal/vazio → fusão não silencia
    docs = _docs(("Despacho", "Em atendimento ao parecer da PGE, informo que a pesquisa de preços será "
                              "providenciada oportunamente."),
                 ("Termo de Homologação", "Homologo o resultado."))

    async def gerar_fake(messages):
        assert "condicionante" in messages[-1]["content"].lower()
        return ('{"grau":"vermelho","cumpridas":[],"nao_cumpridas":["i","ii","iii"],'
                '"resumo":"promessa de providenciar não é cumprimento","dados_suficientes":true}')

    r = asyncio.run(PC.avaliar_parecer_cumprimento(docs, gerar=gerar_fake))
    assert r["grau"] == "vermelho"
    assert r["grau_llm"] == "vermelho" and r["grau_det"]
    assert r["fonte_grau"] in ("subjetivo", "objetivo", "subjetivo+objetivo")


def test_llm_indisponivel_mantem_veredito_deterministico():
    docs = _docs(("Termo de Homologação", "Homologo o resultado do certame."))

    async def gerar_ruim(messages):
        raise RuntimeError("sem chave")

    r = asyncio.run(PC.avaliar_parecer_cumprimento(docs, gerar=gerar_ruim))
    assert r["grau"] == "vermelho"                     # o determinístico sustenta o veredito
    assert r["grau_llm"] is None
    assert r["grau"] not in ("indeterminado", "indisponivel")


def test_snapshot_tem_hash_da_versao():
    r = asyncio.run(PC.avaliar_parecer_cumprimento(_docs(), gerar=None))
    assert r["_versao_hash"] and len(r["_versao_hash"]) == 16
