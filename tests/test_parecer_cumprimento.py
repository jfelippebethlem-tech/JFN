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


# ───────── parecer LONGO: a condicionante mora na CONCLUSÃO (regressão do dado real) ─────────

def test_condicionante_vem_da_conclusao_nao_da_fundamentacao():
    """Medido no acervo (parecer real de 101 mil caracteres): o gatilho casava primeiro dentro da
    FUNDAMENTAÇÃO — numa citação de outro parecer ('seguidas as condições e requisitos exarados do
    Parecer nº 02/2017') — e devolvia como se fosse exigência deste parecer. A condicionante que obriga
    está no fecho ('Isto posto, opino …')."""
    txt = ("PARECER Nº 2848/2024 FS/DIRJUR. RELATÓRIO. Trata-se de processo administrativo. "
           "FUNDAMENTAÇÃO. O ajuste anterior foi celebrado desde que seguidas as condições e requisitos "
           "exarados do Parecer nº 02/2017 GAVI/DIJUR, conforme ali consignado. Prossegue a análise. "
           "ISTO POSTO, opino favoravelmente ao prosseguimento, desde que: "
           "(i) seja juntada a pesquisa de preços atualizada; "
           "(ii) conste a declaração de adequação orçamentária.")
    conds = PC.extrair_condicionantes(txt)
    assert [c["id"] for c in conds] == ["i", "ii"]
    assert not any("02/2017" in c["texto"] for c in conds)


def test_parecer_sem_marcador_de_conclusao_continua_funcionando():
    txt = ("PARECER PGE. Opino favoravelmente desde que: (i) seja juntada a pesquisa de preços; "
           "(ii) conste a dotação orçamentária.")
    assert [c["id"] for c in PC.extrair_condicionantes(txt)] == ["i", "ii"]


def test_citacao_de_outro_parecer_na_fundamentacao_nao_vira_condicionante_deste():
    """O caso REAL que falhou (parecer de 101 mil chars, sem enumeração): o único gatilho de
    condicionalidade estava numa CITAÇÃO dentro da fundamentação — 'seguidas as condições e requisitos
    exarados do Parecer nº 02/2017' — e virava 'a condicionante' deste parecer. O que obriga está no
    fecho ('Isto posto, opino …')."""
    txt = ("PARECER Nº 2848/2024 FS/DIRJUR. RELATÓRIO. Trata-se de processo administrativo de "
           "prorrogação. FUNDAMENTAÇÃO. O ajuste anterior foi celebrado desde que seguidas as condições "
           "e requisitos exarados do Parecer nº 02/2017 GAVI/DIJUR, conforme ali consignado, matéria "
           "que não se repete aqui. ISTO POSTO, opino pelo prosseguimento, condicionado a que seja "
           "juntada aos autos a pesquisa de preços atualizada antes da assinatura do termo.")
    conds = PC.extrair_condicionantes(txt)
    assert len(conds) == 1
    assert "02/2017" not in conds[0]["texto"]
    assert conds[0]["tipo"] == "pesquisa_precos"


def test_anexo_que_apenas_cita_um_parecer_nao_e_parecer():
    """Caso real: 'Anexo 2024PD26194' (programação de desembolso, 38 mil chars) citava 'Parecer nº
    02/2017' lá no meio e era tratado como peça opinativa. Um parecer se ANUNCIA no cabeçalho."""
    anexo = ("Anexo — Programação de Desembolso 2024PD26194. Governo do Estado do Rio de Janeiro. "
             + "Relação de notas e valores. " * 60
             + "O ajuste observou as condições do Parecer nº 02/2017 GAVI/DIJUR, conforme consignado.")
    assert PC.e_parecer("Anexo 2024PD26194", anexo) is False


def test_parecer_de_verdade_se_anuncia_no_cabecalho():
    corpo = ("PARECER Nº 2848/2024 FS/DIRJUR. PROCESSO Nº SEI-080002/020895/2024. "
             + "Trata-se de análise da prorrogação contratual. " * 40
             + "ISTO POSTO, opino pelo prosseguimento, condicionado a que seja juntada a pesquisa de preços.")
    assert PC.e_parecer("Anexo", corpo) is True


def test_explicacao_doutrinaria_nao_e_condicionante():
    """Caso real (Parecer 126, 96 mil chars): o gatilho 'desde que' caiu numa aula sobre resoluções
    ('Resoluções são atos administrativos … desde que complementar à lei'). Condicionante é o que o
    parecerista IMPÕE — anda junto de verbo opinativo ('opino', 'recomendo', 'condiciono')."""
    txt = ("PARECER Nº 126/2024. Resoluções são atos administrativos normativos emanados de autoridades "
           "de elevado escalão, por meio dos quais podem ser tratadas as matérias de sua competência, "
           "desde que complementar à lei ou a outro ato legislativo já existente sobre a temática.")
    assert PC.extrair_condicionantes(txt) == []


def test_transcricao_de_norma_nao_e_condicionante_do_caso():
    """Outro padrão real, repetido em vários processos: o parecer TRANSCREVE o decreto que lista o que
    deve instruir o expediente. Isso é norma citada, não exigência dirigida a este processo."""
    txt = ("PARECER Nº 55/2024. Nos termos do art. 3º do Decreto nº 46.302/2018, o expediente deverá ser "
           "instruído com as seguintes peças: (i) exposição de motivos, justificativa técnica e nota "
           "explicativa; (ii) projeto do ato pretendido; e (iii) parecer conclusivo do órgão de "
           "assessoramento jurídico da respectiva Secretaria de Estado.")
    assert PC.extrair_condicionantes(txt) == []


def test_condicionante_imposta_pelo_parecerista_continua_valendo():
    txt = ("PARECER Nº 77/2024. Após análise, OPINO favoravelmente ao prosseguimento, desde que: "
           "(i) seja juntada a pesquisa de preços; (ii) conste a dotação orçamentária.")
    assert [c["id"] for c in PC.extrair_condicionantes(txt)] == ["i", "ii"]


def test_enumeracao_romana_com_ponto_e_reconhecida():
    """Formato real (Parecer 174): 'desde que observados os apontamentos … notadamente: i. … ii. … iii. …'
    — romano seguido de PONTO, sem parênteses. Antes, a lista inteira virava uma condicionante só."""
    txt = ("PARECER Nº 174/2026. IV. CONCLUSÃO. Ante o exposto, esta Assessoria não vislumbra óbice "
           "jurídico à edição da minuta anexa, desde que observados os apontamentos presentes neste "
           "parecer, notadamente: i. seja corrigida a redação do art. 2º da minuta de resolução; "
           "ii. seja juntada a manifestação do setor técnico competente; "
           "iii. conste a indicação da dotação orçamentária correspondente.")
    conds = PC.extrair_condicionantes(txt)
    assert [c["id"] for c in conds] == ["i", "ii", "iii"]
    assert conds[2]["tipo"] == "dotacao_orcamentaria"


# ───── o gate que descartava o próprio parecer (medido no acervo, 2026-08-02) ─────
# 506 processos do arquivo SEI têm documento de tipo canônico `parecer`; `e_parecer` só reconhecia
# 157. Os 349 restantes eram descartados por dois motivos: (a) o tipo canônico do classificador da
# casa não valia como prova de título, e (b) o veto anti-falso-positivo varria 3.000 caracteres e
# barrava o parecer por citar a peça sobre a qual ele OPINA ("TERMO ADITIVO", "EDITAL DE",
# "CONTRATO Nº"). Resultado: `auditar_parecer_pge` devolvia SEM_PARECER_LOCALIZADO — o entregável
# afirmava que não há parecer jurídico num processo que tem um, de 20 mil caracteres.
# Regra nova: identidade é o que o documento anuncia PRIMEIRO no cabeçalho.

def test_tipo_canonico_parecer_vale_como_titulo():
    """Se o classificador de documentos da casa já disse `parecer`, não se discute o corpo."""
    assert PC.e_parecer("parecer", "Governo do Estado. Trata-se de termo aditivo.") is True
    assert PC.e_parecer("parecer_juridico", "qualquer corpo") is True


def test_parecer_sobre_aditivo_nao_e_vetado_por_falar_do_aditivo():
    """Caso real: Parecer 462/2024/SEDEC/ASSJUR (20 mil chars) era descartado porque 'TERMO
    ADITIVO' aparecia no cabeçalho — inevitável, o parecer OPINA sobre o aditivo."""
    corpo = ("PARECER Nº 462/2024/SEDEC/ASSJUR. Secretaria de Estado de Defesa Civil — "
             "Assessoria Jurídica. PROCESSO Nº SEI-270131/000548/2023. "
             "ASSUNTO: TERMO ADITIVO de prorrogação. " + "Trata-se de análise. " * 30
             + "ISTO POSTO, opino favoravelmente desde que seja juntada a pesquisa de preços.")
    assert PC.e_parecer("outro", corpo) is True
    r = PC.auditar_parecer_pge([{"ref": "1", "tipo": "outro", "texto": corpo}])
    assert r["veredito"] != "SEM_PARECER_LOCALIZADO"


def test_peca_que_se_anuncia_contrato_antes_de_citar_parecer_continua_fora():
    """O veto não some: ele passa a ser POSICIONAL. Quem se anuncia contrato primeiro é contrato."""
    contrato = ("CONTRATO Nº 10/2024 — TERMO DE CONTRATO. " + "Cláusulas gerais. " * 20
                + "O ajuste seguiu o PARECER Nº 02/2017 da PGE, conforme consignado.")
    assert PC.e_parecer("outro", contrato) is False


# ───── G1: grau verde não pode ser dado por falha de leitura (medido 2026-08-02) ─────
# 378 processos recebiam veredito SEM_CONDICIONANTES / grau VERDE / "nada a cobrar quanto a
# condicionantes" — e 160 desses pareceres tinham linguagem de exigência no texto. No dossiê o
# bloco inteiro some (capitulos_dossie.py:386) e a tabela pinta verde: o leitor não distingue
# "não havia exigência" de "não consegui ler a exigência". INDISPONÍVEL ≠ 0.

def test_parecer_com_exigencia_nao_parseada_nao_sai_verde():
    """Há linguagem de exigência e a extração não a alcançou → amarelo, não verde."""
    # 'recomendo' + 'imprescindível' sem estrutura que a extração saiba ler
    corpo = ("PARECER Nº 900/2024 — Procuradoria Geral do Estado. " + "Relatório. " * 40
             + "Isto posto, recomendo cautela ao gestor quanto ao que se apontou acima, "
               "reputando imprescindível o saneamento antes do prosseguimento do feito.")
    r = PC.auditar_parecer_pge([{"ref": "1", "tipo": "parecer", "texto": corpo}])
    assert r["veredito"] == "CONDICIONANTES_NAO_EXTRAIDAS"
    assert r["grau"] == "amarelo"
    assert "INDISPON" in r["leitura"].upper() or "não" in r["leitura"].lower()


def test_parecer_realmente_sem_exigencia_continua_verde():
    """O estado novo não pode engolir o verde legítimo — aprovação lisa segue verde."""
    corpo = ("PARECER Nº 901/2024 — Procuradoria Geral do Estado. " + "Relatório. " * 40
             + "Isto posto, opino favoravelmente à celebração do ajuste, nada mais havendo a "
               "observar quanto aos aspectos jurídicos do feito.")
    r = PC.auditar_parecer_pge([{"ref": "1", "tipo": "parecer", "texto": corpo}])
    assert r["veredito"] == "SEM_CONDICIONANTES"
    assert r["grau"] == "verde"


# ───── G2: formas de exigência colhidas no acervo que o gatilho não reconhecia ─────

def test_sugere_se_a_adaptacao_da_clausula_e_condicionante():
    """Caso real perdido: 'sugere-se a adaptação da redação das cláusulas segunda e quarta'."""
    corpo = ("PARECER Nº 902/2024 da Assessoria Jurídica. Isto posto, opino pelo prosseguimento e, "
             "com o objetivo de aprimorar o texto da minuta encaminhada, sugere-se a adaptação da "
             "redação das cláusulas segunda e quarta aos termos da Lei 14.133/2021.")
    conds = PC.extrair_condicionantes(corpo)
    assert conds, "a exigência de adaptação de cláusula continua invisível"
    assert conds[0]["tipo"] == "minuta_clausula"


def test_mediante_o_atendimento_das_recomendacoes_e_condicionante():
    """Fórmula clássica de ementa da PGE: aprovação condicionada às recomendações."""
    corpo = ("PARECER Nº 903/2024 — Procuradoria Geral do Estado. POSSIBILIDADE, MEDIANTE O "
             "ATENDIMENTO DAS RECOMENDAÇÕES FORMULADAS. " + "Relatório. " * 30
             + "Ante o exposto, opino pela possibilidade jurídica mediante o atendimento das "
               "recomendações formuladas, a saber: i) juntada da pesquisa de preços atualizada; "
               "ii) comprovação da dotação orçamentária.")
    conds = PC.extrair_condicionantes(corpo)
    assert len(conds) >= 2
    assert {c["tipo"] for c in conds} >= {"pesquisa_precos", "dotacao_orcamentaria"}


def test_faz_se_necessario_e_condicionante():
    corpo = ("PARECER Nº 904/2024 da Assessoria Jurídica. Do exposto, opino favoravelmente, mas "
             "faz-se necessária a juntada da certidão negativa de débitos da contratada antes da "
             "assinatura do termo.")
    conds = PC.extrair_condicionantes(corpo)
    assert conds and conds[0]["tipo"] == "regularidade_fiscal"


def test_gatilho_novo_nao_dispara_em_transcricao_de_norma():
    """A porta abre só para a exigência do parecerista — norma citada continua fora."""
    corpo = ("PARECER Nº 905/2024 — PGE. Isto posto, opino favoravelmente. Registre-se que, nos "
             "termos do art. 92 da Lei 14.133/2021, faz-se necessária a indicação do prazo de "
             "vigência em todo contrato administrativo.")
    conds = PC.extrair_condicionantes(corpo)
    assert conds == [], f"transcrição de norma virou exigência: {conds}"


def test_dossie_nao_silencia_o_estado_novo():
    """O bloco de condicionantes some no dossiê para SEM_PARECER/SEM_CONDICIONANTES. O estado
    'não consegui ler' NÃO pode entrar nessa lista de silêncio: é justamente a ressalva que o
    leitor precisa ver — 332 processos no acervo estão nele."""
    from pathlib import Path
    txt = Path(__file__).resolve().parents[1].joinpath(
        "compliance_agent", "reporting", "capitulos_dossie.py").read_text(encoding="utf-8")
    for linha in txt.splitlines():
        if "SEM_CONDICIONANTES" in linha and "not in" in linha:
            assert "CONDICIONANTES_NAO_EXTRAIDAS" not in linha, (
                "o estado de leitura incompleta foi silenciado no dossiê")


# ───── H4: "sem parecer" era três coisas diferentes (medido 2026-08-03) ─────
# 117 processos com documento de tipo canônico `parecer` recebiam SEM_PARECER_LOCALIZADO —
# "nenhum parecer de PGE/PGM/CGE/jurídico entre os documentos LIDOS". Separando as causas:
#   14  o parecer ESTÁ nos autos, com 48-60 chars de texto (só o cabeçalho foi capturado);
#   42  certidão tipada como `parecer_juridico` pelo classificador (o gate acerta ao recusar);
#   61  parecer real de Secretaria cujo corpo não nomeia PGE/CGE/assessoria.
# Só a primeira é afirmação falsa sobre os autos — e é a que ganha estado próprio. A terceira
# ganha uma porta estreita: cabeçalho que ANUNCIA "PARECER Nº" basta, com emissor declarado
# NAO_IDENTIFICADO (recupera 20 pareceres reais e admite 3 certidões, medido no acervo).

def test_parecer_sem_texto_capturado_nao_e_ausencia_de_parecer():
    docs = [{"ref": "Parecer 181 (94130757)", "tipo": "parecer", "texto": "[Parecer 181] (tipo: parecer)"}]
    r = PC.auditar_parecer_pge(docs)
    assert r["veredito"] == "PARECER_SEM_TEXTO_CAPTURADO"
    assert r["grau"] == "amarelo"
    assert "captur" in r["acao"].lower()


def test_processo_realmente_sem_parecer_continua_dizendo_isso():
    docs = [{"ref": "NF 1", "tipo": "nota_fiscal", "texto": "Nota fiscal de serviços prestados."}]
    assert PC.auditar_parecer_pge(docs)["veredito"] == "SEM_PARECER_LOCALIZADO"


def test_parecer_de_secretaria_sem_orgao_nomeado_e_analisado_com_emissor_declarado():
    """Parecer real que não escreve 'PGE' nem 'Assessoria Jurídica' no corpo. Não se inventa o
    emissor: declara-se NAO_IDENTIFICADO."""
    corpo = ("PARECER Nº 111/2025. Governo do Estado do Rio de Janeiro. Secretaria de Estado de "
             "Educação. " + "Trata-se de análise da contratação. " * 20
             + "Isto posto, opino favoravelmente desde que seja juntada a pesquisa de preços.")
    r = PC.auditar_parecer_pge([{"ref": "Parecer 111", "tipo": "parecer", "texto": corpo}])
    assert r["veredito"] not in ("SEM_PARECER_LOCALIZADO", "PARECER_SEM_TEXTO_CAPTURADO")
    assert r["pareceres"][0]["emissor"] == "NAO_IDENTIFICADO"


def test_certidao_tipada_como_parecer_continua_fora():
    """O classificador erra o tipo em 42 processos; o gate não pode herdar o erro."""
    cert = ("Certidão Negativa de Débitos em Dívida Ativa. MINISTÉRIO DA FAZENDA. "
            + "Certificamos que não constam débitos. " * 20)
    r = PC.auditar_parecer_pge([{"ref": "Certidões", "tipo": "parecer", "texto": cert}])
    assert r["veredito"] in ("SEM_PARECER_LOCALIZADO", "PARECER_SEM_TEXTO_CAPTURADO")


# ───── A EMENTA também impõe condicionantes (leitura do original, 2026-08-03) ─────
# Confronto do SEI-270131/000548/2023 lido na íntegra: o Parecer 462/2024/SEDEC/ASSJUR enumera
# QUATRO exigências na EMENTA (o cabeçalho em caixa alta que abre a peça) — pesquisa de mercado,
# decisão da autoridade sobre vantajosidade, reforço da instrução para supressão e juntada da
# habilitação. O extrator lia só o FECHO e devolveu UMA, tipada como minuta_clausula. É a mesma
# causa dos 332 processos em CONDICIONANTES_NAO_EXTRAIDAS: nesta casa a ementa é onde o
# parecerista resume o que exige.

_EMENTA_REAL = (
    "PARECER Nº 462/2024/SEDEC/ASSJUR. Assessoria Jurídica. "
    "1º TERMO ADITIVO AO CONTRATO Nº 16/2023 - PRORROGAÇÃO DE PRAZO DE VIGÊNCIA CONTRATUAL, SEM "
    "APLICAÇÃO DE REAJUSTE - ART. 57, INCISO II, DA LEI Nº 8.666/93 - ENUNCIADOS NºS 09 E 29 DA "
    "PGE - NECESSIDADE DE COMPLEMENTAÇÃO DA INSTRUÇÃO PROCESSUAL: (I) MANIFESTAÇÃO DO SETOR "
    "RESPONSÁVEL PELA PESQUISA DE MERCADO, A RESPEITO DOS NOVOS DOCUMENTOS JUNTADOS; (II) DECISÃO "
    "PELA AUTORIDADE MÁXIMA ACERCA DA VANTAJOSIDADE NA PRORROGAÇÃO; (III) SE ACATADA A SUGESTÃO DE "
    "REDUÇÃO DE 25%, DEVERÁ HAVER O REFORÇO DA INSTRUÇÃO PROCESSUAL PARA A ALTERAÇÃO CONTRATUAL "
    "(SUPRESSÃO); (IV) NECESSIDADE DA JUNTADA DA DOCUMENTAÇÃO DE HABILITAÇÃO - VIABILIDADE DO "
    "PROSSEGUIMENTO DO FEITO CONDICIONADA, DESDE QUE SANADAS AS RESSALVAS APONTADAS. "
    "I. RELATÓRIO. Trata-se de processo administrativo. " + "Fundamentação diversa. " * 40
    + "III. CONCLUSÃO. Diante do exposto, esta ASSJUR manifesta-se pela necessidade de reforço da "
      "instrução processual, conforme apontamentos trazidos no parecer.")


def test_condicionantes_da_ementa_sao_extraidas():
    conds = PC.extrair_condicionantes(_EMENTA_REAL)
    assert len(conds) >= 4, f"a ementa impõe 4 exigências e saíram {len(conds)}: {conds}"


def test_as_quatro_familias_da_ementa_sao_reconhecidas():
    tipos = {c["tipo"] for c in PC.extrair_condicionantes(_EMENTA_REAL)}
    assert "pesquisa_precos" in tipos
    assert "regularidade_fiscal" in tipos, "a juntada da HABILITAÇÃO não foi tipada"


def test_ementa_sem_exigencia_nao_inventa_condicionante():
    """Ementa que só descreve o objeto e aprova não pode virar exigência."""
    limpo = ("PARECER Nº 100/2025. PGE. PRORROGAÇÃO CONTRATUAL - ART. 57, II - VIABILIDADE "
             "JURÍDICA DO PROSSEGUIMENTO DO FEITO. I. RELATÓRIO. " + "Texto. " * 50
             + "III. CONCLUSÃO. Opino favoravelmente, sem ressalvas.")
    assert PC.extrair_condicionantes(limpo) == []


# ───── remissão a recomendações POR NÚMERO (medido 2026-08-03) ─────
# Caso real, obra de R$ 129.595.387,83 (SEI-070002/001289/2022, macrodrenagem do Jacarezinho): a
# Coordenadoria do Sistema Jurídico da PGE conclui que "a instrução processual necessita de
# aperfeiçoamento para possibilitar a continuidade do feito, pelos motivos que passo a expor no
# que tange às recomendações 3, 4, 5, 10, 13, 19, 21" — contradizendo o parecer do INEA, que
# declarara as recomendações cumpridas. São SETE condicionantes remetidas por número, e o
# extrator devolvia zero: a exigência não vem em lista nova, vem por remissão à lista anterior.

_REMISSAO = (
    "Promoção PGE/PG15/COO-CSJ Nº 55. Procuradoria Geral do Estado. PROCESSO Nº "
    "SEI-070002/001289/2022. I. RELATÓRIO. Trata-se de análise de proposta de contratação. "
    + "Relato. " * 30
    + "Vênia devida, me parece que a instrução processual necessita de aperfeiçoamento para "
      "possibilitar a continuidade do feito, pelos motivos que passo a expor no que tange às "
      "recomendações 3, 4, 5, 10, 13, 19, 21.")


def test_recomendacoes_referidas_por_numero_viram_condicionantes():
    conds = PC.extrair_condicionantes(_REMISSAO)
    assert len(conds) == 7, f"esperava as 7 recomendações remetidas, vieram {len(conds)}: {conds}"
    assert {c["id"] for c in conds} == {"3", "4", "5", "10", "13", "19", "21"}


def test_a_remissao_declara_que_o_conteudo_esta_no_parecer_ANTERIOR():
    """Honestidade: aqui só se sabe o NÚMERO. O texto da exigência mora na peça anterior, e o
    veredito não pode fingir que o leu."""
    c = PC.extrair_condicionantes(_REMISSAO)[0]
    assert "anterior" in c["texto"].lower() or "remiss" in c["texto"].lower()


def test_numero_solto_no_texto_nao_vira_condicionante():
    """'nos termos do art. 3, 4 e 5' não é remissão a recomendação."""
    txt = ("PARECER Nº 7. PGE. I. RELATÓRIO. Texto. II. FUNDAMENTAÇÃO. Opino favoravelmente nos "
           "termos dos arts. 3, 4 e 5 da Lei 14.133/2021, sem ressalvas.")
    assert PC.extrair_condicionantes(txt) == []
