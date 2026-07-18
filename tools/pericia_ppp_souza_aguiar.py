# -*- coding: utf-8 -*-
"""Perícia de controle externo — PPP do Complexo Hospitalar Souza Aguiar.

Monta o dossiê pericial (padrão Kroll, via reporting/render_html) a partir das
íntegras já captadas (edital + minuta de contrato + anexos, ingeridos em pcrj.db /
extraídos do ZIP da CCPAR) e da análise dos motores + verificação externa.

HONESTIDADE (regra da casa): indício ≠ acusação; INDISPONÍVEL ≠ 0; nada de número
inventado; presunção de legitimidade. O vínculo Guilherme Paes (BTG) × Prefeito é
tratado como HIPÓTESE a confirmar em fonte primária — as fontes públicas NÃO
colocam o BTG nesta PPP.

Uso: python -m tools.pericia_ppp_souza_aguiar [--pdf]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
from datetime import datetime, timezone

from compliance_agent.reporting import render_html as rh
from compliance_agent.pcrj import lente_ppp
from compliance_agent.pcrj import db as _pcrj_db

_SLUG = "complexo-hospitalar-souza-aguiar"


def _corpus_ccpar() -> str:
    """Texto integral do edital+minuta+anexos ingeridos (pcrj.db), p/ rodar a lente."""
    try:
        con = _pcrj_db.conectar("data/pcrj.db")
        rows = con.execute(
            "SELECT texto FROM pcrj_processo_doc WHERE numero_processo=? AND tipo='edital_ccpar' ORDER BY seq",
            (_SLUG,)).fetchall()
        con.close()
        return "\n\n".join(r["texto"] for r in rows if r["texto"])
    except sqlite3.Error:
        return ""


def _secao_cruzamento_lente() -> str:
    """Cruza cada flag da lente PPP (rodada no corpus real) com a jurisprudência/TC."""
    corpus = _corpus_ccpar()
    lente = lente_ppp.analisar_ppp(corpus) if corpus.strip() else {"flags": [], "grau": "sem_dados"}
    if not lente["flags"]:
        return ("<p>Lente PPP sem corpus ingerido — rode a ingestão do edital CCPAR "
                "(<code>ppp_ccpar.ingerir_edital</code>) para o cruzamento por flag.</p>")
    blocos = []
    for f in lente["flags"]:
        blocos.append(
            f"<div style='margin:0 0 12px;padding:8px 12px;border-left:3px solid "
            f"{'#b00' if f['gravidade']=='alta' else '#c80' if f['gravidade']=='media' else '#888'}'>"
            f"<p style='margin:0 0 3px'><b>{_q(f['tipo'])}</b> · gravidade {_q(f['gravidade'])}</p>"
            f"<p style='margin:0 0 3px;font-size:12px'><b>Base legal:</b> {_q(f['base_legal'])}</p>"
            f"<p style='margin:0 0 3px;font-size:12px'><b>Jurisprudência / Tribunais de Contas:</b> "
            f"{_q(f['jurisprudencia'])}</p>"
            f"<p style='margin:0 0 3px;font-size:12px'><b>A verificar:</b> {_q(f['verificar'])}</p>"
            f"<p style='margin:0;font-size:11px;color:#666'><b>Trecho:</b> …{_q(f['trecho'])}…</p></div>")
    cab = (f"<p>Lente PPP aplicada ao edital+minuta+anexos (íntegra): <b>{_q(lente['grau'])}</b>, "
           f"{lente['n_flags']} indício(s), {lente['n_altas']} de gravidade alta. "
           f"Cada indício é cruzado com sua base normativa e o entendimento dos Tribunais de Contas.</p>")
    return cab + "".join(blocos)

TXT = "/tmp/claude-1001/-home-ubuntu/75ab75be-dc47-4cd9-900a-a179d0f75684/scratchpad/sa_edital/_txt"


def _q(s: str) -> str:
    return html.escape(s or "")


def _tab(linhas, larg=("38%", "62%")):
    trs = "".join(
        f"<tr><td style='padding:5px 10px;font-weight:600;vertical-align:top;width:{larg[0]}'>{k}</td>"
        f"<td style='padding:5px 10px;vertical-align:top'>{v}</td></tr>" for k, v in linhas
    )
    return f"<table style='border-collapse:collapse;width:100%;border:1px solid #ddd'>{trs}</table>"


def _verbatim(titulo, texto):
    return (f"<p style='font-weight:600;margin:10px 0 4px'>{_q(titulo)}</p>"
            f"<blockquote style='margin:0;padding:8px 12px;border-left:3px solid #888;"
            f"background:#f7f7f7;font-size:12.5px;white-space:pre-wrap'>{_q(texto)}</blockquote>")


def _dispositivos_tc():
    """Quadro de fundamentos normativos e jurisprudência dos TCs.

    Preenchido com fundamentos SÓLIDOS e citáveis (Constituição/leis/súmulas).
    Acórdãos específicos são enriquecidos pela pesquisa jurídica quando disponível.
    """
    linhas = [
        ("Garantia com recursos do FNS/SUS (transferência federal condicionada)",
         "<b>Solidez alta.</b> Recursos do Fundo Nacional de Saúde são <b>transferências federais "
         "fundo-a-fundo condicionadas</b> (LC 141/2012; Lei 8.080/90) — <b>não são receita própria do "
         "Município</b>, e garantia só recai sobre receita própria do ente. A vinculação de receita como "
         "garantia (Lei 11.079, art. 8º, I) é <b>expressamente condicionada ao art. 167, IV da CF</b>. "
         "Comprometer 30 anos de orçamento afetado à saúde ainda tensiona a anualidade (art. 167, III)."),
        ("Limite fiscal de PPP (5% da RCL) + DOCC/LRF",
         "<b>Solidez alta.</b> Lei 11.079, <b>art. 28</b>: despesas de PPP de Estados/DF/Municípios não "
         "podem exceder <b>5% da RCL</b> (sob pena de perda de garantias/transferências da União). "
         "Contraprestação de 30 anos é despesa obrigatória de caráter continuado (LRF arts. 16/17) e "
         "exige declaração de adequação (Lei 11.079, art. 10). <b>Exigir memória de cálculo.</b>"),
        ("Impedimento do autor da modelagem (captura via PMI)",
         "<b>Solidez alta.</b> Lei 14.133/2021, <b>art. 14, I e §1º</b>: o autor de projeto/estudo (PF ou "
         "PJ) — e empresas do <b>mesmo grupo econômico</b> — não participa, direta ou indiretamente, da "
         "licitação do objeto correlato. Decreto 8.428/2015, art. 6º: autor de estudo do PMI <b>não</b> "
         "tem preferência. <b>Cruzar QSA</b> Pezco/Kraft/Apparecido × Smart/Sian/Lotus × financiadores."),
        ("Restritividade em qualificação técnica (CAT)",
         "<b>Solidez alta.</b> Súmula TCU <b>263/2011</b> (quantitativo mínimo só nas parcelas de maior "
         "relevância e <b>na proporção</b> da complexidade) e <b>272/2012</b> (vedado exigir, para "
         "habilitar, o que só é necessário após o contrato); jurisprudência: quantitativo &gt;~50% do "
         "contratado é, em regra, irregular sem justificativa. <b>Aferir</b> o item 25.22.2 (≥3 obras, "
         "cada ≥ 9.518 m²) contra a parcela de maior relevância real (operação hospitalar)."),
        ("Impessoalidade / conflito de interesses (NÃO é Súmula 13)",
         "<b>Solidez média — exige nexo concreto.</b> Fundamentar por <b>CF art. 37</b> "
         "(impessoalidade/moralidade) + <b>Lei 14.133 arts. 9º e 14</b> + <b>Lei 12.813/2013</b> "
         "(parâmetro). <b>Cautela técnica:</b> a Súmula Vinculante 13/STF trata de <b>nomeação para "
         "cargo/função</b>, <b>não</b> de contratação por licitação — não estendê-la ao contrato. "
         "Improbidade (Lei 8.429, art. 11, pós-Lei 14.230/2021) exige <b>dolo específico</b> e rol "
         "taxativo — não afirmar sem prova do elemento subjetivo."),
    ]
    return (_tab([(f"<b>{_q(k)}</b>", v) for k, v in linhas], larg=("30%", "70%"))
            + "<p style='font-size:11px;color:#666'>Competência: PPP municipal do Rio é fiscalizada pelo "
              "<b>TCM-RJ</b>; precedentes do TCU são persuasivos/analógicos sobre as normas gerais "
              "federais. Súmulas TCU 263/272 e dispositivos legais/constitucionais conferidos em fonte "
              "primária; acórdãos do TCU sobre garantia de PPP a conferir no inteiro teor antes de citar nº.</p>")


def montar_ctx() -> dict:
    # Íntegras (trechos verbatim já extraídos)
    cl_34 = ("34.1. Nos termos do art. 8º, I, da LEI FEDERAL DE PPPs, do art. 28, II, da LEI MUNICIPAL "
             "DE PPPs, as receitas vinculadas do FUNDO NACIONAL DE SAÚDE, de titularidade do MUNICÍPIO "
             "DO RIO DE JANEIRO, serão destinadas à constituição da GARANTIA PÚBLICA, conforme "
             "sistemática prevista no Decreto Municipal n.º [●], no presente CONTRATO e no CONTRATO DE "
             "CONTA GARANTIA.")
    cl_cat = ("25.22.2. A comprovação da capacidade técnica da empresa contratada será atestada por "
              "intermédio de Certificado de Atestação Técnica – CAT – nos quais se indiquem, no mínimo: "
              "a. Execução de ao menos 3 (três) projetos envolvendo obras civis de edificações similares "
              "ao objeto previsto neste EDITAL, tendo cada um dos projetos área maior ou igual a "
              "9.518 mil m² de intervenção, equivalente a 25% (vinte e cinco por cento) da área "
              "construída atual do CHMSA; e b. Serviços de manutenção predial hospitalar em edifício(s) "
              "com área de, no mínimo, 9.518 m².")
    cl_pmi = ("[Ressarcimento] custos incorridos pelo consórcio Pezco-Kraft-Apparecido, grupo privado "
              "autorizado no âmbito de Procedimento de Manifestação de Interesse (PMI), cujos estudos "
              "que subsidiaram este processo licitatório foram aprovados pela Comissão de Avaliação do PMI.")
    cl_b3 = ("“B3” B3 S.A. – Brasil, Bolsa, Balcão […] assessora técnica da COMISSÃO ESPECIAL DE "
             "LICITAÇÃO; […] devidos à B3 pela assessoria ao procedimento licitatório […] emitido via "
             "boleto bancário após a publicação do ato de adjudicação.")

    secoes = []

    # Sumário executivo
    secoes.append({"titulo": "Sumário Executivo", "html":
        "<p>Perícia de controle externo sobre a <b>Parceria Público-Privada (concessão administrativa) "
        "do Complexo Hospitalar Municipal Souza Aguiar – CHMSA</b> (Prefeitura do Rio de Janeiro), "
        "conduzida pela CCPAR, vencida pela Concessionária <b>Smart Hospital S.A</b>. Analisou-se o "
        "<b>edital (53 pág.), a minuta de contrato (64 pág.) e os anexos técnicos</b> (íntegras "
        "captadas do portal da CCPAR e do Diário Oficial do Rio), com apoio dos motores de análise do "
        "JFN (E1–E7, direcionamento, Lex, hipóteses de fraude) e verificação em fontes externas.</p>"
        "<p><b>Eixos de risco documentados</b> (indício ≠ acusação): (i) garantia pública lastreada em "
        "<b>receitas vinculadas do Fundo Nacional de Saúde</b>; (ii) <b>modelagem por PMI privado</b> "
        "com ressarcimento; (iii) <b>sustentabilidade fiscal</b> de R$ 5,806 bi por 30 anos; "
        "(iv) exigências de <b>qualificação técnica</b> a justificar. "
        "<b>Governança/conflito de interesse:</b> confirma-se que <b>Guilherme Paes</b>, sócio e head de "
        "Investment Banking do <b>BTG Pactual</b>, é <b>irmão do Prefeito Eduardo Paes</b>; contudo "
        "<b>nenhuma fonte pública coloca o BTG nesta PPP</b> — tratado como hipótese a confirmar em "
        "fonte primária, não como achado.</p>"})

    # I. Identificação
    secoes.append({"titulo": "I. Identificação e Partes", "html": _tab([
        ("Objeto", "Concessão administrativa (PPP) para modernização/adequação predial e serviços não "
                   "assistenciais do CHMSA + Maternidade Maria Amélia Buarque de Hollanda + CER Centro"),
        ("Poder concedente", "Município do Rio de Janeiro · condução <b>CCPAR</b> (Companhia Carioca de "
                             "Parcerias e Investimentos, órgão SIGA 006600)"),
        ("Concessionária (SPE)", "<b>Smart Hospital S.A</b> — consórcio reportado com Sian Engenharia (BA) "
                                 "e Lotus Participações (RJ) <i>(a confirmar no contrato/QSA)</i>"),
        ("Modelagem (estudos)", "Consórcio <b>Pezco–Kraft–Apparecido</b> via PMI (ressarcimento "
                                "R$ 3.266.280,90) — <i>fonte: Radar PPP</i>"),
        ("Financiamento", "IDB Invest (até R$ 161 mi) + Caixa (contrato de garantia, 26/11/2024) — "
                          "<i>fonte: IDB Invest / Radar PPP</i>. <b>BTG não localizado.</b>"),
        ("Contraprestação mensal (VCM)", "R$ 191.773.351,61 <i>(deságio ~2,5%)</i>"),
        ("Investimento previsto", "R$ 850.000.000,00 · <b>Valor estimado do contrato: R$ 5,806 bi</b> (30 anos)"),
        ("Prazo", "30 anos"),
        ("Processos administrativos", "09/002.991/2022 e 09/61/000.285/2023 (SIGA, órgão 09 = Saúde)"),
        ("Marcos", "PMI 17/11/2021 · Consulta pública 05/10–04/11/2022 · Edital (Concorrência 01/2023) "
                   "03/04/2023 · Leilão B3 02/08/2023 · Assinatura 19/10 a 06/11/2023 · opex desde 01/12/2023"),
        ("Fontes", "Portal CCPAR; Diário Oficial do Rio (Elasticsearch aberto); edital+anexos (ZIP "
                   "CCPAR); Radar PPP; B3; IDB Invest; imprensa"),
    ])})

    # II. Cadeia documental / íntegras
    secoes.append({"titulo": "II. Cadeia Documental (íntegras — trechos verbatim)", "page_break": True, "html":
        "<p>Documentos captados e lidos na íntegra (11 PDFs, ~2,1 mil páginas): Edital; Minuta de "
        "Contrato; Cadernos de Encargos, Arquitetura, Engenharia, Sustentabilidade; Indicadores de "
        "Desempenho; Plano de TIC; Modelos de Declaração; Proposta Econômica; Errata. Trechos "
        "probatórios centrais:</p>"
        + _verbatim("Garantia pública lastreada no Fundo Nacional de Saúde (Cláusula 34.1 do Contrato)", cl_34)
        + _verbatim("Qualificação técnica – CAT (item 25.22.2 do Edital)", cl_cat)
        + _verbatim("Modelagem via PMI privado e ressarcimento (Edital)", cl_pmi)
        + _verbatim("B3 como assessora técnica da Comissão de Licitação, paga pelo vencedor (Edital)", cl_b3)})

    # III. Restritividade (triada honestamente)
    secoes.append({"titulo": "III. Restritividade do Edital — triagem honesta", "html":
        "<p>Os motores sinalizaram <b>12 cláusulas restritivas</b> (E7 confirmado; Lex R5/R7). "
        "<b>Triagem crítica</b> (para não inflar achado):</p>"
        + _tab([
            ("<b>Indícios substantivos</b> (merecem justificativa nos autos)",
             "• <b>CAT 25.22.2</b>: ≥3 obras similares, cada ≥ 9.518 m² — quantitativo elevado, aferir "
             "proporcionalidade (Súmula TCU 263).<br>• <b>Garantia de proposta</b> com validade de 180 "
             "dias e regras de aporte — verificar efeito sobre a competição."),
            ("<b>Falsos positivos</b> (transparência)",
             "• “Visita técnica” — o edital diz que <b>NÃO é obrigatória</b> (item 11.1.1).<br>"
             "• “Marca/modelo” — é cláusula de <b>madeira de procedência legal</b> (sustentabilidade), "
             "não direcionamento de marca."),
            ("<b>A verificar</b>",
             "Nº de licitantes que efetivamente disputaram o leilão (deságio de apenas 2,5% pode indicar "
             "baixa competição) — dado não disponível nas fontes; requer a ata da sessão pública."),
        ], larg=("28%", "72%"))
        + "<p style='font-size:11px;color:#666'>Concessões hospitalares de 30 anos legitimamente exigem "
          "qualificação técnica robusta; o ponto pericial é a <b>proporcionalidade justificada</b> "
          "(Súmulas TCU 263/2011 e 272/2012; jurisprudência do teto de ~50% do quantitativo), não a "
          "existência da exigência em si.</p>"
        + "<p style='margin-top:10px'><b>Sobre a B3 (assessora do leilão):</b> o uso da B3 como assessora "
          "técnica da comissão e praça do leilão é <b>legal e prática consolidada</b> (Lei 8.987/95; "
          "Lei 11.079/04) — <b>não</b> é irregularidade. Pontos de atenção apenas: preservação da "
          "competência decisória da autoridade (a B3 assessora, não julga), transparência da remuneração "
          "(paga pelo vencedor) e segregação frente ao modelador/assessor financeiro.</p>"})

    # IV. Garantia FNS (o achado forte)
    secoes.append({"titulo": "IV. Garantia Pública lastreada no Fundo Nacional de Saúde", "html":
        "<p>A Cláusula 34.1 destina <b>receitas vinculadas do Fundo Nacional de Saúde (FNS)</b>, de "
        "titularidade do Município, à constituição da <b>garantia pública</b> de pagamento da "
        "contraprestação, por todo o prazo da concessão.</p>"
        "<p><b>Questão jurídica (o achado mais forte):</b> os recursos do <b>FNS são transferências "
        "federais fundo-a-fundo condicionadas</b> (LC 141/2012; Lei 8.080/90) — <b>não são receita "
        "própria do Município</b>. Garantia de PPP só pode recair sobre <b>receita própria</b> do ente; "
        "oferecer em penhor repasses federais afetados ao SUS é juridicamente frágil, e a própria "
        "Lei 11.079 (art. 8º, I) condiciona a vinculação ao <b>art. 167, IV da CF</b>. Ainda que a "
        "contraprestação de um hospital público tenda a qualificar-se como ação/serviço de saúde (o que "
        "legitima pagá-la com verba da saúde), <b>empenhar 30 anos</b> desse orçamento como garantia "
        "rígida tensiona a anualidade orçamentária (art. 167, III) e a flexibilidade do piso do SUS.</p>"
        "<p><b>Encaminhamento:</b> requisitar o Decreto Municipal referido (constava “[●]” na minuta), o "
        "Contrato de Conta Garantia, e a demonstração de que (a) o lastro é receita própria — não repasse "
        "condicionado do FNS —, (b) há compatibilidade com o piso do SUS e (c) o estoque de PPPs respeita "
        "o limite de 5% da RCL (Lei 11.079, art. 28).</p>"})

    # V. Modelagem PMI
    secoes.append({"titulo": "V. Modelagem por PMI privado e risco de captura", "html":
        "<p>Os estudos que subsidiaram a licitação foram elaborados por grupo privado (<b>consórcio "
        "Pezco–Kraft–Apparecido</b>), autorizado em PMI, com <b>ressarcimento de R$ 3.266.280,90</b> "
        "pelo adjudicatário. É estrutura legalmente prevista (Decreto 8.428/2015), porém sensível: o "
        "autor dos estudos <b>não</b> pode ter preferência, e há vedação de participação, direta ou "
        "indireta, de quem elaborou o projeto (Lei 14.133, art. 14).</p>"
        "<p><b>Indício a verificar (não comprovado):</b> eventual sobreposição societária/econômica entre "
        "o consórcio autor dos estudos e a Concessionária Smart Hospital (Sian/Lotus). Pelas fontes, os "
        "grupos são distintos — mas só o cruzamento de QSA fecha. <b>Encaminhamento:</b> cruzar QSA de "
        "Pezco, Kraft, Apparecido × Smart Hospital/Sian/Lotus e financiadores.</p>"})

    # VI. Sustentabilidade fiscal
    secoes.append({"titulo": "VI. Sustentabilidade fiscal (R$ 5,806 bi / 30 anos)", "html":
        "<p>O <b>valor estimado do contrato</b> é de <b>R$ 5,806 bilhões</b> ao longo de 30 anos. "
        "Despesas continuadas de PPP submetem-se ao teto de <b>5% da Receita Corrente Líquida</b> "
        "(Lei 11.079, arts. 22 e 28; LRF). <b>Encaminhamento:</b> obter da SMF/Município a memória de "
        "cálculo do estoque de PPPs frente à RCL e a declaração de adequação orçamentário-financeira "
        "(art. 10, I, ‘b’ e art. 16 da LRF).</p>"})

    # VII. Conflito de interesse — tratamento honesto
    secoes.append({"titulo": "VII. Governança e conflito de interesse — vínculo BTG/Guilherme Paes",
        "page_break": True, "html":
        "<p><b>Fatos confirmados:</b> <b>Guilherme (da Costa) Paes</b> é <b>sócio, diretor estatutário e "
        "head/co-responsável de Investment Banking do BTG Pactual</b> (Bloomberg; BTG institucional) e é "
        "<b>irmão do Prefeito Eduardo (da Costa) Paes</b> (declaração do próprio Prefeito; imprensa).</p>"
        "<p><b>O que NÃO se confirmou (honestidade):</b> nenhuma fonte pública — CCPAR, Diário Oficial, "
        "Radar PPP, IDB Invest, imprensa especializada — coloca o <b>BTG Pactual</b> nesta PPP, seja na "
        "modelagem (Pezco/Kraft/Apparecido), na condução (CCPAR/B3), no financiamento (IDB Invest/Caixa) "
        "ou na composição da SPE (Sian/Lotus). Os atos do próprio Diário Oficial do contrato <b>não "
        "mencionam o BTG</b>.</p>"
        "<p><b>Enquadramento pericial:</b> trata-se de <b>hipótese de conflito de interesse a confirmar em "
        "fonte primária</b>, e <b>não</b> de achado. Afirmar conflito sem prova violaria a presunção de "
        "legitimidade e exporia o controle externo. <b>Se</b> vier a ser comprovado interesse do BTG "
        "(assessoria a qualquer das partes, dívida, participação na SPE ou nos financiadores), o "
        "enquadramento correto é <b>CF art. 37</b> (impessoalidade/moralidade) + <b>Lei 14.133 arts. 9º e "
        "14</b> (impedimentos, inclusive vínculo indireto/grupo econômico) + <b>Lei 12.813/2013</b>. "
        "<b>Cautela técnica:</b> <u>não</u> invocar a Súmula Vinculante 13 (é sobre nomeação para cargo, "
        "não sobre contrato licitado); improbidade (Lei 8.429, art. 11) só com <b>dolo específico</b> "
        "provado (Lei 14.230/2021). "
        "<b>Encaminhamento:</b> requisitar (i) todos os assessores/estruturadores contratados pela CCPAR e "
        "pela SPE; (ii) o quadro de credores/financiadores da concessionária (além de IDB/Caixa); "
        "(iii) o cap table final da Smart Hospital S.A — para confirmar ou <b>afastar</b> o vínculo.</p>"})

    # VIII. Quadro de dispositivos
    secoes.append({"titulo": "VIII. Dispositivos e boas práticas dos Tribunais de Contas", "html":
        _dispositivos_tc()})

    # IX. Cruzamento das flags da lente PPP × jurisprudência (rodada no corpus real)
    secoes.append({"titulo": "IX. Cruzamento das flags (lente PPP) × jurisprudência dos TCs",
        "page_break": True, "html": _secao_cruzamento_lente()})

    # X. Conclusão
    secoes.append({"titulo": "X. Conclusão e Encaminhamentos", "html":
        "<p><b>Veredito de triagem:</b> há <b>indícios que justificam aprofundamento</b> — com destaque "
        "para a <b>garantia via Fundo Nacional de Saúde</b> e a <b>sustentabilidade fiscal</b> — sem que, "
        "até aqui, se confirme irregularidade ou o alegado conflito via BTG. Presunção de legitimidade "
        "mantida; <b>indício ≠ acusação</b>.</p><p><b>Encaminhamentos:</b></p><ol>"
        "<li>Requisitar à CCPAR/SMS/SMF: Decreto Municipal da garantia, Contrato de Conta Garantia, "
        "demonstração de compatibilidade com o piso do SUS e com o limite de 5% da RCL.</li>"
        "<li>Cruzar QSA: autores do PMI (Pezco/Kraft/Apparecido) × SPE (Smart/Sian/Lotus) × financiadores.</li>"
        "<li>Obter a ata da sessão pública (nº de licitantes; motivos de eventuais inabilitações).</li>"
        "<li>Requisitar a lista de assessores/estruturadores e o quadro de credores da concessionária, "
        "para confirmar ou afastar interesse do BTG (§VII).</li>"
        "<li>Consultar TCM-RJ e MPRJ sobre representações/procedimentos relativos a esta PPP (não "
        "localizados em busca aberta — INDISPONÍVEL ≠ inexistência).</li>"
        "<li>Se confirmado qualquer dos itens 1–4, avaliar representação ao TCM-RJ e ao MPRJ.</li></ol>"})

    score = 0.6  # triagem: risco médio-alto documentado, sem irregularidade fechada
    return {
        "titulo": "Perícia de Controle Externo — PPP do Complexo Hospitalar Souza Aguiar",
        "subtitulo": "Concessão Administrativa · Prefeitura do Rio de Janeiro · Concessionária Smart Hospital S.A",
        "classificacao": "USO INTERNO — CONTROLE EXTERNO · INDÍCIO ≠ ACUSAÇÃO",
        "metodologia": "Leitura integral das íntegras (edital+minuta+anexos, ~2,1 mil pág.) + motores JFN "
                       "(E1–E7, direcionamento, Lex, fraudes) + verificação em fontes externas com URL.",
        "analista": "Núcleo de Fiscalização JFN",
        "score": score, "rotulo_score": "Índice de risco (triagem)", "faixa": "🟡 médio-alto",
        "top_flags": ["Garantia via Fundo Nacional de Saúde", "R$ 5,806 bi / 30 anos",
                      "Modelagem por PMI privado", "CAT a justificar", "Conflito BTG: hipótese não comprovada"],
        "secoes": secoes,
        "proveniencia": "CCPAR (ccpar.rio) · Diário Oficial do Rio (doweb) · edital+anexos (ZIP CCPAR) · "
                        "Radar PPP · B3 · IDB Invest · Bloomberg · imprensa. Motores: compliance_agent/*.",
        "ressalva": "Documento de TRIAGEM por indícios. Indício ≠ acusação; INDISPONÍVEL ≠ 0; presunção de "
                    "legitimidade. Nº de processo/valores conferidos em fonte; o vínculo BTG/Paes é "
                    "hipótese a confirmar em fonte primária (não comprovado nesta PPP). Empenho ≠ pagamento (OB).",
        "data": datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y"),
        "_dados": {"caso": "ppp-souza-aguiar", "valor_estimado_contrato": 5_806_000_000},
    }


def gerar(pdf: bool = False) -> dict:
    ctx = montar_ctx()
    out = {"titulo": ctx["titulo"], "n_secoes": len(ctx["secoes"])}
    if pdf:
        import asyncio
        out["pdf"] = asyncio.run(rh.gerar_pdf(ctx, "pericia_ppp_souza_aguiar"))
    else:
        os.makedirs("output", exist_ok=True)
        p = "output/pericia_ppp_souza_aguiar.html"
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(rh.render_html(ctx))
        out["html"] = p
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="store_true")
    a = ap.parse_args()
    print(json.dumps(gerar(pdf=a.pdf), ensure_ascii=False, indent=2))
