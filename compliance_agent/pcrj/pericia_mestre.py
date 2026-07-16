# -*- coding: utf-8 -*-
"""Perícia MESTRE de PPP/concessão municipal — documento definitivo de controle externo.

Produto externo-facing: prosa profissional e minuciosa, impiedosa com qualquer indício
de irregularidade (mantendo indício ≠ acusação; INDISPONÍVEL ≠ 0; nunca inventar número).
Traz: sumário navegável com **hyperlinks clicáveis** (âncoras), análise em prosa por
capítulo, as **cláusulas restritivas** do edital, a lente de concessão cruzada com a
jurisprudência dos Tribunais de Contas, e a **ÍNTEGRA** dos documentos do processo como
anexos navegáveis. Renderiza em PDF via Chromium (preserva os links internos).

Regra dura: **nenhuma menção a sistema/ferramenta interna** no documento — só órgãos e
fontes públicas.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone

from . import db
from . import lente_ppp
from .dossie_ppp import _extrair_resultado, _chaves_projeto
from ..direcionamento_sinais import analisar_direcionamento_det
from ..reporting import render_html as rh

# Rótulos de cláusula restritiva → explicação em prosa (por que restringe / o que aferir).
_ROTULO_CLAUSULA = {
    "atestado_especifico": ("Atestado de capacidade técnica dirigido",
        "exigência de atestado vinculado a objeto idêntico ou a quantitativo específico, que tende "
        "a restringir a competição quando desproporcional à parcela de maior relevância do objeto "
        "(Súmula TCU 263/2011)."),
    "certificacao": ("Exigência de certificação/registro específico",
        "exigência de certificados, registros ou declarações cuja pertinência e proporcionalidade "
        "precisam ser demonstradas nos autos; parte pode ser mera formalidade de autenticação "
        "documental (baixo risco), parte pode barrar licitante idôneo (Súmula TCU 272/2012)."),
    "marca_modelo": ("Indicação de marca/modelo",
        "referência a marca ou modelo sem a cláusula 'ou equivalente' direciona o certame; deve-se "
        "verificar se há justificativa técnica e admissão de similar."),
    "vinculo_previo": ("Exigência de vínculo prévio",
        "exigência de vínculo (profissional/contratual) já existente na data da proposta restringe "
        "novos entrantes; admite-se a comprovação no momento da contratação."),
    "amostra_previa": ("Exigência de amostra/prova prévia",
        "exigência de amostra ou prova de conceito antes da contratação impõe custo e barreira "
        "(Súmula TCU 272/2012 — não exigir para habilitar o que só é necessário após o contrato)."),
    "visita_obrigatoria": ("Visita técnica obrigatória",
        "quando obrigatória e restrita a data/horário exíguos, a visita técnica funciona como "
        "barreira; a jurisprudência admite a visita, mas em regra veda a obrigatoriedade."),
    "capital_garantia_alto": ("Capital/garantia de proposta elevados",
        "exigência de capital social ou de garantia de proposta em patamar elevado filtra "
        "concorrentes por porte, e não por capacidade de execução — aferir proporcionalidade."),
    "prazo_local_quantitativo": ("Restrição de prazo/local/quantitativo",
        "limitações de época, local ou quantitativo dos atestados são, em regra, ilegais por "
        "restringirem a competição sem pertinência com o objeto."),
    "vedacao_somatorio_atestado": ("Vedação ao somatório de atestados",
        "vedar o somatório de atestados quando o atestado único não é imprescindível restringe "
        "indevidamente a competição (jurisprudência consolidada do TCU)."),
}


def _p(*paras: str) -> str:
    return "".join(f"<p>{t}</p>" for t in paras if t)


def _q(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _carregar(slug: str, db_path=None) -> dict:
    db.inicializar(db_path)
    con = db.conectar(db_path)
    try:
        ppp = con.execute("SELECT * FROM pcrj_ppp WHERE slug=?", (slug,)).fetchone()
        ppp = dict(ppp) if ppp else {}
        nome = ppp.get("nome") or slug.replace("-", " ").title()
        chaves = _chaves_projeto(nome)
        if chaves:
            qs = " OR ".join("texto LIKE ?" for _ in chaves)
            acts = [dict(r) for r in con.execute(
                f"SELECT id_materia,data,ano,tipo,processos,texto FROM pcrj_doe_materia "
                f"WHERE {qs} ORDER BY data DESC", [f"%{c}%" for c in chaves]).fetchall()]
        else:
            acts = []
        docs = [dict(r) for r in con.execute(
            "SELECT seq,titulo,texto FROM pcrj_processo_doc WHERE numero_processo=? "
            "AND tipo='edital_ccpar' ORDER BY seq", (slug,)).fetchall()]
    finally:
        con.close()
    return {"slug": slug, "nome": nome, "ppp": ppp, "acts": acts, "docs": docs}


def montar_html(slug: str, db_path=None) -> str:
    dados = _carregar(slug, db_path)
    nome = dados["nome"]
    ppp = dados["ppp"]
    acts = dados["acts"]
    docs = dados["docs"]
    corpus = "\n\n".join(d["texto"] for d in docs if d["texto"])
    resultado = _extrair_resultado(acts)
    datas = json.loads(ppp.get("datas_json") or "[]")
    dirc = analisar_direcionamento_det(corpus) if corpus.strip() else {"clausulas": [], "grau_det": "indeterminado"}
    lente = lente_ppp.analisar_ppp(corpus) if corpus.strip() else {"flags": []}
    data_hoje = datetime.now(timezone.utc).astimezone().strftime("%d de %B de %Y")

    # ── capítulos (id, título, html) ─────────────────────────────────────
    caps: list[tuple[str, str, str]] = []

    caps.append(("cap-sumario", "Sumário Executivo", _p(
        f"O presente trabalho examina, sob a ótica do controle externo, a <b>parceria "
        f"público-privada, na modalidade concessão administrativa, do {_q(nome)}</b>, promovida pela "
        f"Prefeitura do Município do Rio de Janeiro por intermédio da Companhia Carioca de Parcerias e "
        f"Investimentos (CCPAR), e adjudicada à concessionária <b>{_q(resultado['vencedor'] or 'INDISPONÍVEL')}</b>. "
        f"A análise apoiou-se na leitura integral do edital, da minuta de contrato e de seus anexos "
        f"técnicos, bem como nos atos publicados no Diário Oficial do Município e em fontes públicas "
        f"especializadas, cujas íntegras acompanham este documento.",
        "Não se afirma, em nenhum ponto, a existência de irregularidade: prevalece a presunção de "
        "legitimidade dos atos administrativos, e todo apontamento tem natureza de <b>indício sujeito a "
        "apuração</b>. Dentro desse limite, contudo, a análise é minuciosa e não poupa nenhum ponto "
        "sensível.",
        "Os eixos de maior relevância são quatro. Primeiro, e mais grave, a <b>garantia pública de "
        "pagamento lastreada em receitas vinculadas do Fundo Nacional de Saúde</b>: por serem "
        "transferências federais condicionadas, e não receita própria do Município, sua oferta em "
        "garantia a uma concessionária privada, por três décadas, suscita séria dúvida de legalidade. "
        "Segundo, a <b>sustentabilidade fiscal</b> de um contrato cujo valor estimado alcança a casa "
        "dos bilhões ao longo de trinta anos, à luz do teto de 5% da receita corrente líquida. Terceiro, "
        "a <b>modelagem por manifestação de interesse privada</b>, com ressarcimento pelo vencedor, e o "
        "correlato risco de captura. Quarto, o conjunto de <b>exigências de qualificação técnica</b> do "
        "edital, cuja proporcionalidade deve ser demonstrada.",
        "Quanto à governança, registra-se, por dever de exaustividade, que há <b>vínculo de parentesco</b> "
        "entre sócio de instituição financeira de grande porte e o Chefe do Executivo municipal; contudo, "
        "<b>nenhuma fonte pública consultada vincula essa instituição a esta concessão</b> — a questão é "
        "tratada como hipótese a confirmar em fonte primária, jamais como achado.")))

    caps.append(("cap-partes", "Objeto, Partes e Valores", _p(
        f"O objeto contratual é a concessão administrativa para modernização e adequação das instalações "
        f"prediais e a prestação dos serviços não assistenciais do complexo hospitalar, por prazo de "
        f"<b>{_q(ppp.get('prazo_anos') or '30')} anos</b>.")
        + _tabela([
            ("Licitação", "Concorrência Pública SMS CO nº 01/2023 · Processo administrativo "
                          "SMS-PRO-2022/03013"),
            ("Poder concedente", "Município do Rio de Janeiro — Secretaria Municipal de Saúde (SMS), "
                                 "com condução pela Companhia Carioca de Parcerias e Investimentos (CCPAR)"),
            ("Concessionária", "Concessionária Smart Hospital S.A. — CNPJ 52.592.077/0001-00, "
                               "constituída em 19/10/2023, capital social R$ 84.826.000,17"),
            ("Controladores do consórcio", _hl("Lotus Participações (RJ) + Sian Engenharia (BA), "
                               "ligadas a Ivan Mattos Neto — grupo de origem baiana; sócio Qin Zhang "
                               "desde a constituição (a apurar)")),
            ("Contrato", "SMS nº 197/2023 · assinatura em 23/10/2023"),
            ("Contraprestação (anual)", _crit("R$ 191.773.351,61 por ANO")
                + " — e não mensal; ver capítulo de remuneração"),
            ("Teto de referência (receita anual máxima)", "≈ R$ 196,69 milhões/ano · deságio ofertado de 2,5%"),
            ("Valor global do contrato (30 anos)", _hl("R$ 5.753.200.548,30")
                + " (191.773.351,61 × 30) — valor de referência da concedente: R$ 5.806.053.112,77 "
                + _crit("(divergência de ≈ 0,9% a reconciliar)")),
            ("Investimento (CAPEX)", "≈ R$ 848–850 milhões, sendo ≈ R$ 530 milhões nos 3 primeiros anos"),
            ("Prazo", f"{_q(ppp.get('prazo_anos') or '30')} anos"),
            ("Reembolso dos estudos (PMI)", "R$ 3.266.280,90 ao Consórcio Pezco–Kraft–Apparecido, "
                                            "pago pela concessionária"),
            ("Financiamento", _hl("IDB Invest (até R$ 161 mi, empréstimo ainda pendente — status 'Hold', "
                                  "board previsto para 06/10/2026) + Caixa (conta-garantia R$ 9.588.667,58, "
                                  "nov/2024). Nenhuma emissão de dívida em mercado de capitais localizada.")),
            ("Competição no leilão", _crit("PROPONENTE ÚNICO") + " — dos 6 grupos que manifestaram "
                               "interesse na consulta, apenas o Consórcio Smart apresentou proposta e foi "
                               "habilitado (ver capítulo próprio)"),
        ])
        + _p("Os dados acima resultam do cruzamento das íntegras (anexas) com os atos do Diário Oficial "
             "do Município e com fontes públicas especializadas (portal da concedente, base de projetos "
             "de parceria, comunicados da B3 e imprensa), todas relacionadas ao final. Os itens "
             "assinalados em destaque merecem verificação humana; os pontos em vermelho são os de maior "
             "sensibilidade.")))

    caps.append(("cap-crono", "Cronologia do Processo", _cronologia_html(datas)))

    caps.append(("cap-garantia", "Estrutura de Garantia e o Fundo Nacional de Saúde", _p(
        "A cláusula de garantia pública de pagamento destina <b>receitas vinculadas do Fundo Nacional de "
        "Saúde (FNS)</b>, de titularidade do Município, à constituição da garantia da contraprestação "
        "devida à concessionária, por todo o prazo da concessão, mediante contrato de conta garantia.",
        "Aqui reside o ponto de maior densidade jurídica. Os recursos do FNS não constituem receita "
        "própria do Município: são <b>transferências federais, fundo a fundo, condicionadas</b> à "
        "aplicação em ações e serviços públicos de saúde (Lei nº 8.080/1990; Lei Complementar nº "
        "141/2012). A garantia de obrigações pecuniárias do parceiro público, na forma de vinculação de "
        "receitas, é admitida pela Lei nº 11.079/2004 (art. 8º, I), <b>mas a própria norma a condiciona "
        "ao art. 167, IV, da Constituição</b>. Ora, a exceção constitucional que autoriza vincular "
        "receita à saúde existe para <b>custear</b> as ações de saúde, não para servir de penhor, por "
        "trinta anos, em favor de um particular. Comprometer de forma rígida o orçamento afetado ao "
        "piso da saúde tensiona, ainda, o princípio da anualidade orçamentária e a capacidade de o "
        "gestor futuro remanejar recursos essenciais.",
        "Há, ainda, um ponto a reconciliar com rigor documental: " + _hl("a minuta de contrato (cláusula "
        "34.1) refere expressamente 'receitas vinculadas do Fundo Nacional de Saúde' como lastro da "
        "garantia pública; parte das fontes secundárias, porém, descreve a garantia efetiva como o Fundo "
        "Municipal de Saúde somado à conta-garantia na Caixa") + ", tratando o Fundo Nacional como fonte "
        "de custeio (repasses do Sistema Único de Saúde) que ajuda a honrar a contraprestação. A distinção "
        "é juridicamente decisiva — dar em garantia repasse federal condicionado é bem mais grave do que "
        "vincular receita municipal própria. Prevalece, para fins de prova, o <b>documento primário</b> "
        "(a minuta), mas a contradição deve ser dirimida com o decreto e o contrato de conta-garantia.",
        "<b>Encaminhamento:</b> requisitar o decreto municipal que disciplina a garantia (referido na "
        "minuta), o contrato de conta garantia e a demonstração inequívoca de que (i) o lastro é receita "
        "própria — e não repasse condicionado do Fundo Nacional de Saúde —, e (ii) o arranjo não sacrifica "
        "o piso constitucional da saúde.")))

    caps.append(("cap-aporte", "Aporte Público, Conta Garantia e Verificador Independente", _p(
        "A modelagem prevê aporte público de recursos em favor da concessionária, admitido pela Lei nº "
        "11.079/2004 (art. 6º, §2º, e art. 7º) <b>somente após a disponibilização parcial do objeto</b> "
        "e com contabilização própria. Deve-se aferir se o cronograma de aporte está ancorado na entrega "
        "física efetiva, sob pena de transferência indevida de risco ao erário.",
        "A aferição de desempenho que baliza o valor pago cabe a um <b>verificador independente</b>. O "
        "ponto sensível — e recorrentemente cobrado pelos Tribunais de Contas — é a <b>independência</b> "
        "desse verificador: quem o indica e quem o remunera. Verificador indicado ou custeado pela "
        "própria concessionária compromete a segregação de funções e a confiabilidade da medição que "
        "define quanto o poder público desembolsa.")))

    caps.append(("cap-pmi", "Modelagem por Manifestação de Interesse e Risco de Captura", _p(
        "Os estudos que subsidiaram a licitação foram elaborados por grupo privado, no âmbito de "
        "Procedimento de Manifestação de Interesse (PMI), com <b>ressarcimento a cargo do vencedor</b> "
        "da licitação. O arranjo é lícito (Decreto federal nº 8.428/2015), porém sensível: a autorização "
        "para os estudos é concedida sem exclusividade e <b>não gera direito de preferência</b>; e a Lei "
        "nº 14.133/2021 (art. 14, I e §1º) veda a participação, direta ou indireta, do autor do "
        "projeto/estudo — inclusive de empresas do mesmo grupo econômico — na licitação do objeto "
        "correlato.",
        "<b>Encaminhamento:</b> cruzar o quadro societário do consórcio autor dos estudos com o da "
        "concessionária e de seus financiadores, para afastar (ou confirmar) qualquer sobreposição. A "
        "adoção acrítica do modelo apresentado pelo particular, sem análise crítica e independente da "
        "Administração, configuraria captura da modelagem e vício de motivação.")))

    caps.append(("cap-fiscal", "Sustentabilidade Fiscal e o Teto de 5% da Receita Corrente Líquida", _p(
        "A contraprestação por três décadas configura <b>despesa obrigatória de caráter continuado</b> "
        "(Lei de Responsabilidade Fiscal, arts. 16 e 17), a exigir estimativa de impacto orçamentário e "
        "declaração de compatibilidade com a Lei de Diretrizes Orçamentárias — condição de validade da "
        "própria licitação (Lei nº 11.079/2004, art. 10).",
        "Sobretudo, a Lei nº 11.079/2004 (art. 28) fixa que as despesas de PPP de Municípios <b>não "
        "podem exceder 5% da receita corrente líquida</b> do exercício, nem as projetadas para os dez "
        "anos seguintes, sob pena de o ente perder garantias e transferências voluntárias da União. "
        "Trata-se de regra objetiva. <b>Encaminhamento:</b> obter a memória de cálculo do estoque de "
        "parcerias do Município frente à sua receita corrente líquida, projetada por dez anos.")))

    # cap. remuneração ao longo dos 30 anos + coerência econômica
    contrap = resultado["contraprestacao"]
    caps.append(("cap-remuneracao", "Remuneração ao Longo dos 30 Anos e Coerência Econômica", _p(
        "A remuneração da concessionária dá-se por <b>contraprestação pública</b>, definida no contrato "
        "como Valor de Contraprestação Mensal (VCM), devido a partir da ordem de início dos serviços e "
        "<b>reajustado anualmente pelo IPCA/IBGE</b>. O critério de julgamento do leilão foi o de "
        "<b>menor contraprestação</b>, tendo o vencedor ofertado deságio de aproximadamente 2,5%.",
        f"O valor apurado dos atos oficiais — <b>R$ {_q(contrap or 'INDISPONÍVEL')}</b> — precisa ter sua "
        f"unidade lida com rigor, sob pena de erro de ordem de grandeza. O <b>valor estimado do contrato "
        f"é de {_hl('R$ 5.806.053.112,77 para os 30 anos')}</b>, o que equivale a uma média de "
        f"{_hl('≈ R$ 193,5 milhões por ano')}. Confrontando: se aquele valor fosse "
        f"{_crit('mensal')}, o somatório de 30 anos alcançaria cerca de R$ 69 bilhões — <b>doze vezes</b> "
        f"o valor estimado, o que é economicamente incoerente. Lido como {_hl('valor ANUAL de referência')}, "
        f"R$ 191,77 mi × 30 ≈ R$ 5,75 bilhões, praticamente idêntico ao estimado. Conclui-se, portanto, "
        f"que a contraprestação de referência é <b>anual</b> (VCM mensal correspondente ≈ R$ 16 milhões), "
        f"e não mensal. Registra-se a correção porque a leitura equivocada dessa unidade é um erro comum "
        f"e materialmente relevante.",
        "Quanto ao <b>perfil ano a ano</b>, o modelo combina: (i) um <b>desembolso de investimento (CAPEX) "
        "concentrado nos primeiros anos</b> — reportado em cerca de R$ 530 milhões nos três primeiros "
        "anos, ante R$ 850 milhões ao longo de toda a concessão; e (ii) uma <b>contraprestação anual</b> "
        "que se inicia com a entrada em operação e é corrigida por índice. " + _hl("O fluxo detalhado, ano "
        "a ano, da proposta econômica vencedora (plano de negócios) não consta da íntegra publicada do "
        "edital e deve ser requisitado") + " — é peça essencial para aferir se o retorno embutido (a taxa "
        "interna de retorno) e o ramp-up de contraprestação são compatíveis com o risco efetivamente "
        "assumido pela concessionária.",
        "<b>A verificar:</b> o cronograma de contraprestações ano a ano; a taxa interna de retorno do "
        "projeto; a existência de contraprestação em período anterior à plena operação; e a memória de "
        "cálculo do reajuste. " + _hl("Confrontar o CAPEX efetivamente executado com o cronograma, e os "
        "pagamentos já realizados (capítulo próprio), para detectar pagamento em descompasso com a "
        "entrega física."))))

    # cap. competitividade — licitante único (achado central)
    caps.append(("cap-competicao", "Competitividade do Certame — Proponente Único", _p(
        "Este é, ao lado da garantia lastreada em recursos da saúde, o ponto que mais exige do controle "
        "externo. Embora, na fase de sondagem de mercado, " + _hl("seis grupos tenham manifestado "
        "interesse") + " no projeto — segundo a imprensa especializada, um espanhol, um japonês e quatro "
        "brasileiros —, ao leilão realizado em 02/08/2023, na sede da B3, em São Paulo, " + _crit(
        "compareceu e foi habilitado um único proponente") + ": o Consórcio Smart Hospital. Não houve, "
        "portanto, disputa: o deságio de 2,5% sobre o teto foi ofertado em proposta única, e não há mapa "
        "de lances competitivo.",
        "A licitação com proponente único não é, por si, ilegal — mas é um dos <b>indícios mais fortes de "
        "que se deve investigar a competitividade real do edital</b>. A questão central é saber se a "
        "migração de seis interessados para um único proponente decorreu de fatores de mercado legítimos "
        "ou de <b>barreiras erguidas pelo próprio instrumento convocatório</b> — exigências de "
        "qualificação técnica, garantias, prazos ou condições econômicas que, na prática, tenham afastado "
        "concorrentes. É aqui que a análise das cláusulas restritivas (capítulo seguinte) ganha peso: "
        "cada exigência desproporcional, num certame que já terminou com um só licitante, deixa de ser "
        "hipótese abstrata e passa a demandar justificativa concreta nos autos.",
        "Registra-se, ainda, que o edital sofreu " + _hl("duas impugnações, apresentadas pela Dimensional "
        "Engenharia Ltda. em 27/06/2023 e 13/07/2023, ambas julgadas improcedentes") + ", e que o "
        "Tribunal de Contas do Município do Rio de Janeiro, em abril de 2023, determinou que a Secretaria "
        "Municipal de Saúde prestasse esclarecimentos sobre itens do Edital nº 01/2023 — providência de "
        "escopo amplo cujo teor deve ser obtido junto àquela Corte.",
        "<b>Encaminhamento:</b> requisitar a ata da sessão pública e o relatório da comissão de licitação; "
        "obter o inteiro teor das impugnações da Dimensional e das respectivas decisões; e recuperar, no "
        "Tribunal de Contas do Município, o processo do Edital nº 01/2023 — em especial os pontos "
        "objeto de esclarecimento e a análise de competitividade.")))

    # cap. cláusulas restritivas (as flags que faltavam) — em prosa, com o TRECHO COMPLETO do edital
    caps.append(("cap-restritividade", "Cláusulas Restritivas do Edital", _clausulas_restritivas_html(dirc, corpus)))

    # cap. lente × jurisprudência
    caps.append(("cap-lente", "Indícios de Concessão × Jurisprudência dos Tribunais de Contas",
                 _lente_juris_html(lente)))

    # cap. pagamentos já realizados
    caps.append(("cap-pagamentos", "Pagamentos Já Realizados à Concessionária", _p(
        "A execução financeira do contrato é o teste definitivo: importa aferir se o Município já "
        "desembolsou valores em favor da concessionária (CNPJ 52.592.077/0001-00) e, sobretudo, se esses "
        "pagamentos guardam <b>proporção com a entrega física efetiva</b> das obras e serviços — o "
        "descompasso entre pagamento e execução é indício clássico de irregularidade.",
        "Da varredura dos atos do Diário Oficial do Município, localizou-se, até esta data, "
        + _hl("registro de pagamento no valor de R$ 470.148,62, referente a documento fiscal, vinculado "
              "ao processo SMS-PRO-2025/90297 (publicação de 14/01/2026)") + ". Trata-se de valor "
        "modesto diante da contraprestação anual contratada (da ordem de R$ 16 milhões mensais em "
        "referência), o que sugere pagamento de etapa inicial, de serviço específico ou de rubrica "
        "acessória, e não da contraprestação plena — que pressupõe a operação já disponibilizada.",
        _crit("O histórico completo de empenhos, liquidações e ordens bancárias em favor da "
              "concessionária não está integralmente disponível nas fontes abertas consultadas e deve ser "
              "requisitado") + " ao Município (Secretaria Municipal de Fazenda e Secretaria Municipal de "
        "Saúde) e cotejado com os relatórios de execução física e com os termos de verificação emitidos "
        "pelo verificador independente. <b>Encaminhamento:</b> obter o extrato de todos os pagamentos "
        "(empenho → liquidação → ordem bancária) desde a assinatura do contrato, com as respectivas notas "
        "fiscais e os laudos de medição que os lastreiam.")))

    # cap. documentação da sessão e atas
    caps.append(("cap-atas", "Documentação da Sessão de Licitação e Atas", _p(
        "A documentação oficial do certame, reunida a partir do portal da concedente e do Diário Oficial, "
        "compreende o comunicado relevante da comissão especial de licitação (anterior à sessão), o "
        "edital e seus anexos, a minuta de contrato e anexos, o manual de procedimentos da B3 (regras do "
        "leilão) e os avisos de alteração de data. As respectivas íntegras integram os anexos deste "
        "documento; os endereços eletrônicos de origem constam da relação de fontes.",
        _hl("Registra-se que o portal da concedente NÃO expõe, como arquivo autônomo, a 'Ata da Sessão "
            "Pública', o mapa de lances ou a ata de habilitação da sessão de 02/08/2023") + ". Como o "
        "leilão teve proponente único, não há mapa de lances competitivo; ainda assim, a ata da sessão e "
        "o relatório de julgamento/habilitação são peças essenciais e devem ser requisitados via processo "
        "administrativo SMS-PRO-2022/03013, ou localizados na edição do Diário Oficial subsequente ao "
        "leilão. <b>Encaminhamento:</b> requisitar a ata da sessão pública, o relatório da comissão e o "
        "extrato do contrato publicado no Diário Oficial (novembro de 2023).")))

    caps.append(("cap-conflito", "Governança e Conflito de Interesse", _p(
        "Trouxe-se ao exame, por dever de exaustividade, a hipótese aventada de intervenção do banco BTG "
        "Pactual nesta parceria, à luz do <b>vínculo de parentesco</b> — relação de irmandade, reconhecida "
        "publicamente pelo próprio Chefe do Executivo municipal — entre o Prefeito e o Sr. Guilherme Paes, "
        "sócio, diretor estatutário e co-responsável pela área de <i>investment banking</i> daquela "
        "instituição. O parentesco é fato público e verificável.",
        "A hipótese foi investigada de forma sistemática, em cinco frentes: (i) assessoria/estruturação da "
        "modelagem; (ii) financiamento de dívida da concessionária; (iii) coordenação da oferta/leilão; "
        "(iv) participação societária na sociedade de propósito específico; e (v) prestação de garantia. "
        + _crit("Em nenhuma delas se localizou registro público de participação do BTG Pactual nesta "
                "concessão") + ". Ao contrário, as fontes apontam terceiros: a modelagem coube ao Consórcio "
        "Pezco–Kraft–Apparecido; o financiamento de dívida está sendo negociado com o " + _hl("IDB Invest "
        "(até R$ 161 milhões, empréstimo ainda não aprovado — status 'Hold', com decisão de comitê "
        "prevista para 06/10/2026)") + "; a Caixa Econômica Federal figura apenas como banco da "
        "conta-garantia; e a sociedade de propósito específico é controlada por grupo de origem baiana "
        "(Sian Engenharia e Lotus Participações, sob Ivan Mattos Neto). Não se localizou emissão de dívida "
        "da concessionária em mercado de capitais.",
        "A verificação foi levada ao nível do <b>quadro societário oficial (Receita Federal)</b> de toda a "
        "cadeia de controle, sem que o banco apareça em qualquer elo: na concessionária Smart Hospital S.A. "
        "(CNPJ 52.592.077/0001-00) constam apenas os administradores Allan Kardec Machado, André Viana "
        "Portela, Qin Zhang e Rodrigo Galina; na Sian Engenharia Ltda. (CNPJ 03.746.272/0001-23), os "
        "sócios André Portela, Luis Augusto Gomes Siqueira e a Sian Holding; e na Sian Holding Ltda. (CNPJ "
        "36.296.376/0001-32), um quadro amplo de participações de origem baiana — " + _crit("em nenhum "
        "deles figura o BTG Pactual ou fundo por ele gerido") + ". A modelagem coube ao consórcio "
        "Pezco–Kraft–Apparecido e o único financiador de dívida nomeado, no disclosure do próprio "
        "organismo multilateral, é o IDB Invest. Registre-se, por honestidade, a única peça em aberto: o "
        "quadro societário exato da Lotus Participações (a cotista carioca do consórcio) não pôde ser "
        "casado em fonte pública e deve ser obtido no ato de constituição do consórcio — lacuna que, "
        "contudo, " + _hl("não abre qualquer indício de participação do BTG; apenas resta a confirmar em "
        "fonte primária") + ".",
        "Registre-se, por rigor, que a imprensa já associou o BTG a temas da política fluminense em "
        "episódios <b>anteriores e alheios</b> a esta concessão (o imóvel do Sr. Guilherme Paes ocupado "
        "por ex-governador, em 2011; menções em 2013 e 2015). Nada disso guarda nexo documentado com o "
        "Souza Aguiar.",
        "Conclui-se, portanto, que a intervenção do BTG nesta parceria é " + _crit("hipótese NÃO "
        "confirmada — e, pelas fontes abertas, sem sustentação") + ": o parentesco, isoladamente, é "
        "contexto de potencial conflito a monitorar, jamais prova de irregularidade. Afirmá-la sem "
        "elemento probatório violaria a presunção de legitimidade e exporia o próprio controle. "
        "<b>Caso</b> venha a ser demonstrado interesse da instituição em qualquer das partes, o "
        "enquadramento seria o dos princípios da impessoalidade e da moralidade (art. 37 da Constituição), "
        "das vedações da Lei nº 14.133/2021 (arts. 9º e 14) e da Lei nº 12.813/2013 — <b>não</b> a Súmula "
        "Vinculante 13 do Supremo Tribunal Federal, que trata de nomeação para cargo, não de contrato "
        "licitado.",
        "Um ponto societário merece diligência autônoma: a presença, desde a constituição da sociedade de "
        "propósito específico, do sócio " + _hl("Qin Zhang") + ", cuja identidade e cujo papel não estão "
        "esclarecidos nas fontes públicas — possível parceiro/investidor estrangeiro, eventualmente ligado "
        "ao fornecimento de equipamentos (o projeto prevê substituição integral do parque tecnológico). "
        "<b>Encaminhamento:</b> obter, na Junta Comercial, o estatuto e o quadro societário completo da "
        "concessionária (com percentuais e a identificação de Qin Zhang); requisitar os contratos de "
        "financiamento e de garantia; e cruzar os quadros societários da modeladora e da vencedora.")))

    caps.append(("cap-conclusao", "Conclusão e Encaminhamentos", _p(
        "Do exame resulta a existência de <b>indícios relevantes que justificam o aprofundamento da "
        "fiscalização</b>, com destaque para a garantia lastreada em recursos federais da saúde e para a "
        "sustentabilidade fiscal do compromisso trintenário, sem que, até o presente, se possa afirmar "
        "irregularidade ou o alegado conflito de interesse. Preserva-se a presunção de legitimidade; "
        "indício não é acusação.")
        + "<p><b>Recomenda-se:</b></p><ol>"
        "<li>requisitar à concedente e às pastas de saúde e fazenda o decreto e o contrato de conta "
        "garantia, com a demonstração de compatibilidade da garantia com o piso do Sistema Único de "
        "Saúde e com o teto de 5% da receita corrente líquida;</li>"
        "<li>cruzar os quadros societários do autor dos estudos, da concessionária e dos financiadores;</li>"
        "<li>obter a ata da sessão pública de licitação (número de licitantes e motivos de eventuais "
        "inabilitações);</li>"
        "<li>aferir, cláusula a cláusula, a proporcionalidade das exigências de qualificação técnica;</li>"
        "<li>requisitar a relação de assessores/estruturadores e o quadro de credores, para confirmar ou "
        "afastar a hipótese de conflito de interesse;</li>"
        "<li>consultar o Tribunal de Contas do Município e o Ministério Público quanto a eventuais "
        "representações relativas a esta concessão;</li>"
        "<li>confirmados quaisquer dos itens anteriores, avaliar a representação aos órgãos competentes.</li>"
        "</ol>"))

    # ── anexos: ÍNTEGRA dos documentos ───────────────────────────────────
    anexos: list[tuple[str, str, str]] = []
    for i, d in enumerate(docs, 1):
        aid = f"anexo-{i}"
        titulo = d.get("titulo") or f"Documento {i}"
        corpo = (f"<p style='color:#555'>Íntegra reproduzida do documento publicado pela concedente. "
                 f"Extensão: {len(d['texto'] or ''):,} caracteres.</p>".replace(",", ".")
                 + f"<pre class='integra'>{_q(d['texto'])}</pre>")
        anexos.append((aid, f"Anexo {_romano(i)} — {titulo}", corpo))

    return _montar_documento(nome, caps, anexos, data_hoje, dirc, lente, resultado)


# ── helpers de renderização ──────────────────────────────────────────────
def _tabela(linhas) -> str:
    trs = "".join(
        f"<tr><td class='k'>{_q(k)}</td><td>{v}</td></tr>" for k, v in linhas)
    return f"<table class='dados'>{trs}</table>"


def _romano(n: int) -> str:
    vals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out or "I"


def _clausula_completa(corpus_norm: str, trecho: str) -> str:
    """Expande a janela curta do detector até os limites do item numerado do edital (trecho íntegro)."""
    anchor = re.sub(r"\s+", " ", trecho or "").strip()
    if not anchor:
        return ""
    i = corpus_norm.find(anchor[:60])
    if i < 0:
        i = corpus_norm.find(anchor[:30])
    if i < 0:
        return anchor  # não localizou no corpus — devolve o que veio (sem cortar)
    # recua até o início do item numerado (ex.: '25.22.2 '), com teto de 300 p/ trás
    ini = i
    tras = corpus_norm[max(0, i - 300):i]
    marcos = list(re.finditer(r"(?<![\d.])\d{1,2}(?:\.\d{1,3}){1,3}\.?\s", tras))
    if marcos:
        ini = max(0, i - 300) + marcos[-1].start()
    # janela generosa p/ frente (não cortar); só para num item numerado de 3+ grupos
    # (medidas '9.518' e quantidades não têm 3 grupos e não enganam mais), após ≥ 500 chars
    limite = min(len(corpus_norm), ini + 2200)
    janela = corpus_norm[ini + 500:limite]
    m = re.search(r"\s\d{1,2}\.\d{1,3}\.\d{1,3}(?:\.\d{1,3})?\s", janela)
    fim = (ini + 500 + m.start()) if m else limite
    return corpus_norm[ini:fim].strip()


def _clausulas_restritivas_html(dirc: dict, corpus: str = "") -> str:
    clausulas = dirc.get("clausulas", [])
    if not clausulas:
        return _p("A leitura do edital não evidenciou cláusulas restritivas pelos parâmetros aferidos. "
                  "Ausência de indício, contudo, não equivale a atestado de regularidade da fase de "
                  "habilitação, que deve ser confrontada com a ata da sessão pública.")
    from collections import Counter
    corpus_norm = re.sub(r"\s+", " ", corpus or "")  # colapsa TODO whitespace (casa a âncora do detector)
    cont = Counter(c.get("tipo") for c in clausulas)
    intro = _p(
        f"A análise cláusula a cláusula das exigências de habilitação e de qualificação técnica do edital "
        f"identificou <b>{len(clausulas)} ocorrência(s)</b> potencialmente restritivas, assim "
        f"distribuídas: " + "; ".join(f"{_q(t)} ({n})" for t, n in cont.most_common()) + ".",
        "A relação abaixo é <b>exaustiva</b> e deliberadamente crítica; adota-se, porém, triagem honesta: "
        "concessões hospitalares de grande vulto legitimamente exigem qualificação robusta, de modo que o "
        "ponto pericial não é a existência da exigência, e sim a <b>proporcionalidade justificada nos "
        "autos</b>. Cada ocorrência vem acompanhada do <b>trecho íntegro</b> do edital, para conferência "
        "direta.")
    blocos = []
    for n, c in enumerate(clausulas, 1):
        rot, expl = _ROTULO_CLAUSULA.get(c.get("tipo"), (c.get("tipo"), c.get("por_que_restringe") or ""))
        integra = _clausula_completa(corpus_norm, c.get("trecho") or "") if corpus_norm else \
            re.sub(r"\s+", " ", c.get("trecho") or "").strip()
        blocos.append(
            f"<div class='flag'><p class='ft'><b>{n}. {_q(rot)}</b></p>"
            f"<p>{_q(expl)}</p>"
            + (f"<p class='tr'><b>Trecho íntegro do edital:</b></p>"
               f"<blockquote class='clausula'>{_q(integra)}</blockquote>" if integra else "")
            + "</div>")
    return intro + "".join(blocos)


# (data, evento, descrição, crítico?) — linha do tempo do processo
_CRONOLOGIA = [
    ("17/11/2021", "Abertura do Procedimento de Manifestação de Interesse (PMI)",
     "A Secretaria Municipal de Saúde publica o chamamento para que a iniciativa privada apresente "
     "estudos destinados a subsidiar a estruturação da parceria (PMI/SMI nº 01/2021).", False),
    ("2022", "Elaboração dos estudos de modelagem",
     "Os estudos que subsidiaram a licitação são elaborados pelo Consórcio Pezco–Kraft–Apparecido, "
     "com ressarcimento posterior a cargo do vencedor (R$ 3.266.280,90).", False),
    ("05/10 a 04/11/2022", "Consulta pública",
     "Abertura do projeto à sociedade e ao mercado; nessa fase, seis grupos manifestaram interesse "
     "(um espanhol, um japonês e quatro brasileiros).", False),
    ("Abril/2023", "Determinação do Tribunal de Contas do Município (TCM-RJ)",
     "O TCM-RJ determina que a Secretaria Municipal de Saúde preste esclarecimentos sobre itens do "
     "Edital nº 01/2023 — providência de escopo amplo cujo teor deve ser obtido junto à Corte.", True),
    ("03/04/2023", "Publicação do edital",
     "Publicação do Edital de Concorrência Pública SMS CO nº 01/2023 (Processo SMS-PRO-2022/03013).", False),
    ("11/05 a 19/06/2023", "Erratas e versões dos documentos",
     "Sucessivas alterações do edital e dos anexos (erratas de 11/05, 15/06, 16/06 e 19/06/2023), o que "
     "pode sinalizar reabertura de prazos e ajustes relevantes na modelagem — a examinar.", False),
    ("27/06 e 13/07/2023", "Impugnações ao edital",
     "A empresa Dimensional Engenharia Ltda. apresenta duas impugnações, ambas julgadas improcedentes — "
     "cujo inteiro teor e fundamentos devem ser requisitados.", True),
    ("02/08/2023", "Sessão pública / leilão na B3 (São Paulo)",
     "Realiza-se o leilão pelo critério de menor contraprestação. Compareceu e foi habilitado um único "
     "proponente — o Consórcio Smart Hospital —, que ofertou deságio de 2,5% sobre o teto em proposta "
     "única. Não houve disputa nem mapa de lances competitivo.", True),
    ("19/10/2023", "Constituição da concessionária",
     "É constituída a sociedade de propósito específico Concessionária Smart Hospital S.A. "
     "(CNPJ 52.592.077/0001-00), capital social de R$ 84.826.000,17.", False),
    ("23/10/2023", "Assinatura do contrato",
     "Assinatura do contrato de concessão administrativa SMS nº 197/2023, prazo de 30 anos, valor global "
     "de R$ 5.753.200.548,30.", False),
    ("Novembro/2023", "Publicação do extrato do contrato e homologação do ressarcimento",
     "Publicação do extrato do contrato no Diário Oficial do Município e homologação do ressarcimento dos "
     "estudos ao consórcio autor da modelagem.", False),
    ("01/12/2023", "Início da operação pela concessionária",
     "A concessionária assume a responsabilidade pelos serviços, encerrando-se contratos de apoio "
     "operacional anteriores.", False),
    ("26/11/2024", "Contrato de garantia (conta-garantia)",
     "Formaliza-se o contrato de conta-garantia junto à Caixa Econômica Federal (R$ 9.588.667,58).", False),
    ("06/10/2026 (previsto)", "Decisão sobre o financiamento de dívida",
     "Data prevista para a decisão de comitê do IDB Invest sobre o empréstimo (até R$ 161 mi), ainda "
     "pendente de aprovação (status 'Hold') — o funding de longo prazo, portanto, ainda não está fechado.", True),
]


def _cronologia_html(datas_ccpar) -> str:
    linhas = "".join(
        f"<div style='margin:0 0 9px;padding-left:10px;border-left:2px solid "
        f"{'#8a1a1a' if crit else '#ccc'}'>"
        f"<p style='margin:0'><b>{_q(data)} — {_q(ev)}.</b> {desc if not crit else _hl(desc)}</p></div>"
        for data, ev, desc, crit in _CRONOLOGIA)
    intro = _p(
        "A sequência procedimental abaixo foi reconstruída a partir dos atos publicados, do portal da "
        "concedente e das fontes públicas especializadas. Cada marco é descrito, e os pontos de maior "
        "sensibilidade para o controle externo — a determinação do Tribunal de Contas, as impugnações, o "
        "leilão com proponente único e a pendência do financiamento — vêm assinalados.")
    fecho = _p(
        "A leitura integrada da cronologia revela um processo que, entre a consulta pública com seis "
        "interessados e o leilão com um único proponente, <b>perdeu competitividade ao longo do caminho</b> "
        "— fato que, somado às sucessivas erratas, às impugnações e à determinação do Tribunal de Contas, "
        "recomenda exame detido das razões dessa migração.")
    return intro + linhas + fecho


def _lente_juris_html(lente: dict) -> str:
    flags = lente.get("flags", [])
    if not flags:
        return _p("Não foram identificados, no corpus examinado, os indícios típicos de concessão "
                  "aferidos por esta lente.")
    intro = _p(
        "A seguir, cada indício típico de parceria/concessão identificado no edital e na minuta é exposto "
        "e <b>cruzado com a base normativa e o entendimento dos Tribunais de Contas</b>. A competência "
        "para a fiscalização desta parceria municipal é do Tribunal de Contas do Município do Rio de "
        "Janeiro; os precedentes do Tribunal de Contas da União são invocados como jurisprudência "
        "persuasiva sobre as normas gerais federais.")
    blocos = []
    for f in flags:
        cor = {"alta": "#8a1a1a", "media": "#8a5a00"}.get(f.get("gravidade"), "#555")
        blocos.append(
            f"<div class='flag' style='border-left-color:{cor}'>"
            f"<p class='ft'><b>{_q(f['tipo'])}</b> — gravidade {_q(f['gravidade'])}</p>"
            f"<p><b>Base legal.</b> {_q(f['base_legal'])}</p>"
            f"<p><b>Jurisprudência e entendimento dos Tribunais de Contas.</b> {_q(f['jurisprudencia'])}</p>"
            f"<p><b>A verificar.</b> {_q(f['verificar'])}</p></div>")
    return intro + "".join(blocos)


_CSS = """
@page { size: A4; margin: 2.2cm 2cm 2.2cm 2cm;
        @bottom-center { content: counter(page) " / " counter(pages); font: 9px Georgia; color:#888; } }
body { font-family: Georgia,'Times New Roman',serif; color:#1a1a1a; font-size:12.5px; line-height:1.55; }
h1,h2,h3 { font-family: Georgia,serif; color:#111; }
.capa { text-align:center; padding-top:22%; page-break-after:always; }
.capa .cls { letter-spacing:2px; font-size:11px; color:#8a1a1a; text-transform:uppercase; }
.capa h1 { font-size:26px; margin:18px 8%; line-height:1.25; }
.capa .sub { font-size:14px; color:#444; margin:0 10%; }
.capa .meta { margin-top:40px; font-size:12px; color:#555; }
.toc { page-break-after:always; }
.toc h2 { border-bottom:2px solid #111; padding-bottom:4px; }
.toc ol, .toc ul { line-height:2; }
.toc a { text-decoration:none; color:#1a3e6e; }
.toc a:hover { text-decoration:underline; }
.cap { page-break-before:always; }
.cap h2 { border-bottom:1px solid #999; padding-bottom:3px; color:#111; }
.cap p { text-align:justify; }
table.dados { border-collapse:collapse; width:100%; margin:8px 0; }
table.dados td { border:1px solid #ddd; padding:5px 9px; vertical-align:top; }
table.dados td.k { font-weight:bold; width:34%; background:#f6f6f6; }
.flag { border-left:3px solid #8a5a00; padding:6px 12px; margin:10px 0; background:#fafafa; }
.flag .ft { margin:0 0 3px; }
.flag .tr { font-size:11px; color:#444; margin:6px 0 2px; }
blockquote.clausula { white-space:pre-wrap; word-wrap:break-word; font-size:10.5px; line-height:1.4;
    background:#f4f4f4; border-left:2px solid #999; padding:6px 10px; margin:2px 0 0; color:#222; }
.integra { white-space:pre-wrap; word-wrap:break-word; font-family:'DejaVu Sans Mono',monospace;
           font-size:9.5px; line-height:1.35; color:#222; }
.callout { border:1px solid #8a1a1a; background:#fbecec; padding:8px 12px; margin:10px 0; }
.rodape { font-size:10px; color:#777; border-top:1px solid #ccc; margin-top:6px; padding-top:4px; }
.hl { background:#fff3b0; padding:0 2px; }                       /* verificar humanamente (amarelo) */
.crit { color:#8a1a1a; text-decoration:underline; font-weight:bold; }  /* ponto crítico (vermelho sublinhado) */
.legenda { font-size:10.5px; color:#555; margin:6px 0 0; }
"""


def _hl(texto: str) -> str:
    """Destaque amarelo — item a verificar humanamente."""
    return f"<span class='hl'>{texto}</span>"


def _crit(texto: str) -> str:
    """Ponto crítico — vermelho sublinhado."""
    return f"<span class='crit'>{texto}</span>"


def _montar_documento(nome, caps, anexos, data_hoje, dirc, lente, resultado) -> str:
    # capa
    capa = (f"<div class='capa'><p class='cls'>Uso interno · Controle externo · Indício ≠ acusação</p>"
            f"<h1>Perícia de Controle Externo<br>{_q(nome)}</h1>"
            f"<p class='sub'>Parceria público-privada · Concessão administrativa · "
            f"Município do Rio de Janeiro</p>"
            f"<div class='meta'>Assessoria Técnica de Controle Externo<br>{_q(data_hoje)}</div></div>")

    # sumário navegável (hyperlinks)
    itens = "<li><a href='#cap-proveniencia'>Proveniência, Método e Fontes</a></li>" + \
            "".join(f"<li><a href='#{cid}'>{_q(t)}</a></li>" for cid, t, _ in caps)
    itens_anexo = "".join(f"<li><a href='#{aid}'>{_q(t)}</a></li>" for aid, t, _ in anexos)
    toc = (f"<div class='toc'><h2>Sumário</h2><ol>{itens}</ol>"
           + (f"<h3>Anexos — Íntegra do processo</h3><ul>{itens_anexo}</ul>" if itens_anexo else "")
           + "</div>")

    # corpo
    corpo = ""
    for cid, titulo, html_c in caps:
        corpo += f"<div class='cap' id='{cid}'><h2>{_q(titulo)}</h2>{html_c}" \
                 f"<p class='rodape'><a href='#topo' style='color:#777;text-decoration:none'>↑ Sumário</a></p></div>"
    for aid, titulo, html_a in anexos:
        corpo += f"<div class='cap' id='{aid}'><h2>{_q(titulo)}</h2>{html_a}" \
                 f"<p class='rodape'><a href='#topo' style='color:#777;text-decoration:none'>↑ Sumário</a></p></div>"

    fontes_doc = [
        ("Edital de Licitação e Anexos (versão do leilão) — portal da concedente",
         "https://api.mziq.com/mzfilemanager/v2/d/31984144-b5d8-42f6-b944-26345a820727/ef113c39-ac8b-0709-350c-338b1e1e71dc?origin=2"),
        ("Contratos e Anexos (versão vigente) — portal da concedente",
         "https://api.mziq.com/mzfilemanager/v2/d/31984144-b5d8-42f6-b944-26345a820727/c9d24e57-c324-82c9-9e01-f75579e5d595?origin=2"),
        ("Comunicado Relevante da Comissão Especial de Licitação (01/08/2023)",
         "https://api.mziq.com/mzfilemanager/v2/d/31984144-b5d8-42f6-b944-26345a820727/92eb3bca-7ac1-9bf7-11b3-f30bc36363ad?origin=2"),
        ("Manual de Procedimentos B3 (regras do leilão)",
         "https://api.mziq.com/mzfilemanager/v2/d/31984144-b5d8-42f6-b944-26345a820727/526e3803-a2b4-eac3-e35c-32ab877d6825?origin=2"),
        ("Página do projeto — índice de documentos (concedente)",
         "https://www.ccpar.rio/mapa/complexo-hospitalar-souza-aguiar/"),
        ("Transparência / Licitações da concedente",
         "https://www.ccpar.rio/institucional/transparencia/licitacoes/"),
    ]
    fontes_pesq = [
        ("Resumo do contrato de PPP (base de projetos de parceria) — modeladora, ressarcimento, "
         "impugnações, conta-garantia Caixa, valor global",
         "https://radarppp.com/resumo-de-contratos-de-ppps/unidades-da-coordenadoria-geral-de-emergencia-da-area-de-planejamento-1-0-municipio-do-rio-de-janeiro/"),
        ("Resultado do leilão e proponente único — Prefeitura do Rio",
         "https://prefeitura.rio/noticias/prefeitura-do-rio-faz-leilao-e-anuncia-consorcio-vencedor-da-ppp-do-complexo-hospitalar-souza-aguiar/"),
        ("Comunicado do leilão — B3",
         "https://www.b3.com.br/pt_br/noticias/prefeitura-do-rio-de-janeiro-realiza-leilao-para-ppp-do-complexo-hospitalar-souza-aguiar.htm"),
        ("Modelo econômico, teto anual e interessados na consulta — Brazil Journal",
         "https://braziljournal.com/a-ppp-que-vai-mudar-a-cara-do-souza-aguiar-a-maior-emergencia-da-america-latina/"),
        ("Financiamento de dívida (status 'Hold', board 06/10/2026) — IDB Invest",
         "https://www.idbinvest.org/en/projects/smart-hospital-ppp-renovation-rio-de-janeiros-public-hospital"),
        ("Cadastro da sociedade de propósito específico (CNPJ 52.592.077/0001-00) — Econodata / CNPJá",
         "https://www.econodata.com.br/consulta-empresa/52592077000100-smarthospital-sa"),
        ("Controle baiano do consórcio (Sian/Lotus, Ivan Mattos Neto) — imprensa",
         "https://www.bnews.com.br/noticias/economia-e-mercado/exclusivo-consorcio-com-empresa-baiana-ganha-concessao-milionaria-de-grande-hospital-do-rio-de-janeiro.html"),
        ("Parentesco e histórico BTG × política do Rio — Diário do Rio",
         "https://diariodorio.com/qual-relacao-de-eduardo-paes-com-o-btg-pactual/"),
    ]
    lista_d = "".join(f"<li>{_q(t)}<br><a href='{_q(u)}' style='font-size:10px'>{_q(u)}</a></li>" for t, u in fontes_doc)
    lista_p = "".join(f"<li>{_q(t)}<br><a href='{_q(u)}' style='font-size:10px'>{_q(u)}</a></li>" for t, u in fontes_pesq)
    proveniencia = (
        "<div class='cap' id='cap-proveniencia'><h2>Proveniência, Método e Fontes</h2>"
        + _p("Este documento foi elaborado exclusivamente a partir de fontes públicas, abaixo relacionadas "
             "com seus endereços eletrônicos de origem. A íntegra do edital, da minuta de contrato e dos "
             "anexos técnicos, reproduzida ao final, foi obtida diretamente no portal da concedente. Todo "
             "apontamento tem natureza de indício sujeito a apuração; nenhum número foi presumido ou "
             "arbitrado; a ausência de informação é registrada como indisponível, jamais como zero. Os "
             "trechos em destaque amarelo assinalam pontos a verificar humanamente; os grifos em vermelho, "
             "os de maior sensibilidade.")
        + "<h3>Documentos oficiais do processo</h3><ol>" + lista_d + "</ol>"
        + "<h3>Fontes de pesquisa consultadas</h3><ol>" + lista_p + "</ol>"
        + "<p class='legenda'>Observação: a ata da sessão pública, o índice de reajuste da contraprestação, "
          "o perfil ano a ano do fluxo e o histórico completo de pagamentos não constam das fontes abertas "
          "e devem ser requisitados às autoridades competentes (Secretaria Municipal de Saúde, Secretaria "
          "Municipal de Fazenda, Companhia Carioca de Parcerias e Tribunal de Contas do Município).</p>"
        + "</div>")

    return (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            f"<title>Perícia — {_q(nome)}</title><style>{_CSS}</style></head>"
            f"<body><a id='topo'></a>{capa}{toc}{proveniencia}{corpo}</body></html>")


async def gerar_pdf(slug: str, db_path=None, destino: str = "") -> str:
    html_str = montar_html(slug, db_path)
    destino = destino or f"reports/pericia_mestre_{slug}_{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d')}.pdf"
    import os
    os.makedirs("reports", exist_ok=True)
    return await rh.html_to_pdf(html_str, destino)
