# -*- coding: utf-8 -*-
"""Converte lacuna probatória em PEDIDO: quesitos de perícia e rol de diligências (H.7).

O PRODUTO QUE FALTAVA. `knowledge/tipicidade.o_que_falta` já responde, por regime, o que ainda
precisa ser provado — e a resposta morria no dossiê como texto. Quem lê um dossiê de controle
externo não quer saber apenas que falta prova: quer o **documento que se pede** e a **pergunta
que se faz ao perito**. É a diferença entre "não consigo provar" e uma ação concreta.

A REGRA QUE GOVERNA O TEXTO. Quesito e diligência são PEDIDOS, não acusações — mesma disciplina
de `reporting/requisicao`: vigora a presunção de legitimidade, e nenhuma palavra de juízo entra.
Um quesito que já afirma o vício ("comprove o superfaturamento de R$ X") contamina a resposta e
é atacável; o quesito correto pergunta o fato ("qual o preço de referência do item na data, e
qual o contratado?"). Há teste travando o vocabulário.

O QUE NÃO SE PEDE. Fonte sob sigilo que o JFN não acessa — RIF/COAF, quebra bancária, eSocial
completo — não vira quesito de perícia: vira **requisição a quem tem competência**, e sai
declarada como tal. Pedir ao perito o que só o juízo pode requisitar produz peça inócua.

ORDEM DE UTILIDADE, e ela não é alfabética: primeiro o que falta para o regime MAIS PRÓXIMO de
fechar. Um controlador persegue a imputação que está a uma prova de distância, não a que está a
quatro — e `o_que_falta` já ordena assim.
"""
from __future__ import annotations

from typing import Any

from compliance_agent.knowledge.tipicidade import PROVAS, o_que_falta

# Vocabulário vedado NO QUESITO e no rol de documentos — o mesmo espírito de
# `reporting/requisicao.PALAVRAS_VEDADAS`. Quesito que afirma o vício contamina a resposta do
# perito e é atacável na origem.
#
# ONDE ESTAS PALAVRAS PODEM APARECER, e a distinção não é formalidade: o NOME do regime sob
# hipótese ("improbidade_principios", "crime_licitatorio") precisa ser dito, senão o leitor não
# sabe o que está em jogo nem qual standard se aplica. A regra da casa (B.4.4) resolve assim:
# palavra de tipicidade só sai DENTRO de seção declarada como qualificação HIPOTÉTICA, com a
# ressalva junto. É o que o render faz — e há teste travando que ela não escape da seção.
PALAVRAS_VEDADAS = ("irregular", "ilegal", "fraude", "improbidade", "desvio", "superfatur",
                    "sobrepreç", "dolo", "má-fé", "crime", "culpado", "responsabiliza",
                    "direcionamento", "conluio", "cartel")

# Cada elemento a provar vira (a) um quesito ao perito e (b) o documento que se requisita.
# O quesito PERGUNTA o fato; nunca pede confirmação de conclusão.
_ROTEIRO: dict[str, dict[str, Any]] = {
    "dano": {
        "quesito": ("Qual era o preço de referência de mercado de cada item, na data da "
                    "contratação, segundo a tabela oficial aplicável ao objeto? Qual o preço "
                    "unitário contratado? Qual a quantidade efetivamente medida e paga?"),
        "documentos": ("planilha orçamentária do contrato com memória de cálculo",
                       "boletins de medição assinados",
                       "ordens bancárias emitidas, com data e valor",
                       "pesquisa de preços que instruiu a contratação"),
        "onde": "autos do processo administrativo e SIAFE",
    },
    "beneficiario": {
        "quesito": ("Qual a composição do quadro societário do contratado nas datas da "
                    "publicação do edital, da homologação e do pagamento? Houve alteração "
                    "nesse intervalo?"),
        "documentos": ("ficha cadastral completa na Junta Comercial, com o histórico de "
                       "alterações contratuais",
                       "quadro de sócios e administradores (QSA) da Receita Federal"),
        "onde": "JUCERJA e Receita Federal",
    },
    "dolo": {
        "quesito": ("Qual a sequência cronológica dos atos, com data e autoria de cada um? "
                    "Houve manifestação técnica ou jurídica contrária, e qual foi o "
                    "encaminhamento dado a ela?"),
        "documentos": ("íntegra do processo administrativo, com todos os despachos",
                       "pareceres técnicos e jurídicos, inclusive os não acolhidos",
                       "comunicações internas sobre o objeto no período"),
        "onde": "autos do processo administrativo",
        "nota": ("Elemento subjetivo não se presume (Lei 8.429/1992, art. 17-C, I). A diligência "
                 "busca o registro do que foi decidido e por quem, não a intenção declarada."),
    },
    "conduta": {
        "quesito": ("Quais atos foram praticados, em que datas, e qual agente subscreveu cada "
                    "um deles?"),
        "documentos": ("íntegra do processo com a identificação do ordenador de despesa, do "
                       "gestor e do fiscal do contrato",
                       "portarias de designação vigentes à época"),
        "onde": "autos do processo administrativo",
    },
    "nexo": {
        "quesito": ("Qual a linha do tempo entre o ato apontado e o pagamento? Que atos "
                    "intermediários ocorreram entre um e outro?"),
        "documentos": ("empenhos, liquidações e ordens bancárias com datas",
                       "termos de recebimento provisório e definitivo"),
        "onde": "SIAFE e autos do processo",
    },
    "vantagem": {
        "quesito": ("Há bens ou direitos registrados em nome dos agentes envolvidos, ou de "
                    "terceiros a eles vinculados, adquiridos no período?"),
        "documentos": ("declaração de bens apresentada ao órgão",
                       "certidões de registro de imóveis, RENAVAM, RAB e Tribunal Marítimo"),
        "onde": "órgão de origem e cartórios/registros públicos",
        "requisicao_externa": ("Movimentação financeira e declaração de rendimentos dependem de "
                               "afastamento de sigilo — competência do juízo ou do órgão "
                               "legitimado, não do controle administrativo."),
    },
    "ato_lesivo": {
        "quesito": ("A pessoa jurídica praticou, no interesse ou benefício próprio, algum dos "
                    "atos descritos no art. 5º da Lei 12.846/2013? Quais e quando?"),
        "documentos": ("íntegra do procedimento licitatório",
                       "comunicações entre a empresa e a Administração",
                       "programa de integridade da empresa, se houver"),
        "onde": "autos do processo e a própria pessoa jurídica",
    },
    "norma": {
        "quesito": ("Qual o valor aferido do requisito questionado e qual o limite previsto na "
                    "norma aplicável ao caso?"),
        "documentos": ("edital e anexos na íntegra", "justificativa técnica da exigência"),
        "onde": "autos do certame",
    },
    "impacto_fiscal": {
        "quesito": ("Consta dos autos a estimativa de impacto orçamentário-financeiro e a "
                    "declaração de adequação orçamentária? Em que documento?"),
        "documentos": ("estimativa de impacto (LRF art. 16)",
                       "declaração do ordenador de adequação orçamentária e financeira"),
        "onde": "autos do processo administrativo",
    },
}


def _sem_juizo(texto: str) -> bool:
    t = (texto or "").lower()
    return not any(p in t for p in PALAVRAS_VEDADAS)


def montar(vicio: str, provas_disponiveis: set[str] | list[str] | None = None) -> dict[str, Any]:
    """Quesitos e diligências para o que ainda falta provar, por regime.

    Devolve também `nao_mapeado` quando o vício não está em `knowledge/tipicidade` — lacuna
    declarada, e não lista vazia que pareceria "nada a pedir".
    """
    falta = o_que_falta(vicio, provas_disponiveis)
    if not falta.get("mapeado"):
        return {"vicio": vicio, "mapeado": False, "quesitos": [], "diligencias": [],
                "nota": falta.get("nota", ""),
                "ressalva": _RESSALVA}

    vistos: set[str] = set()
    quesitos, diligencias, requisicoes = [], [], []
    for regime in falta["regimes"]:
        for prova in regime["provas_faltantes"]:
            if prova in vistos:
                continue
            vistos.add(prova)
            roteiro = _ROTEIRO.get(prova)
            if not roteiro:
                # Elemento sem roteiro é lacuna do MAPA, não ausência de pedido a fazer.
                diligencias.append({"elemento": prova, "descricao": PROVAS.get(prova, prova),
                                    "documentos": [], "onde": "",
                                    "nota": "elemento ainda sem roteiro de diligência mapeado"})
                continue
            quesitos.append({
                "elemento": prova, "para_o_regime": regime["regime"],
                "standard": regime["standard"],
                "quesito": roteiro["quesito"],
                "nota": roteiro.get("nota", ""),
            })
            diligencias.append({
                "elemento": prova, "descricao": PROVAS.get(prova, prova),
                "documentos": list(roteiro["documentos"]), "onde": roteiro["onde"],
            })
            if roteiro.get("requisicao_externa"):
                requisicoes.append({"elemento": prova, "motivo": roteiro["requisicao_externa"]})

    return {
        "vicio": vicio, "mapeado": True,
        "regime_mais_proximo": falta["regimes"][0]["regime"] if falta["regimes"] else None,
        "algum_fecha": falta.get("algum_fecha", False),
        "quesitos": quesitos, "diligencias": diligencias,
        "requisicoes_a_orgao_competente": requisicoes,
        "ressalva": _RESSALVA,
    }


def render_texto(pacote: dict[str, Any]) -> str:
    """Texto pronto para a peça. Montado pelo CÓDIGO a partir da estrutura, nunca por prosa de IA."""
    if not pacote.get("mapeado"):
        return (f"Vício '{pacote.get('vicio')}' ainda não mapeado em knowledge/tipicidade — "
                "lacuna declarada; sem quesitos a formular.")
    linhas = [f"QUESITOS E DILIGÊNCIAS — {pacote['vicio']}", ""]
    if pacote.get("algum_fecha"):
        linhas.append("Há regime cujos elementos já estão reunidos; os quesitos abaixo dizem "
                      "respeito aos demais.")
        linhas.append("")
    if pacote["quesitos"]:
        linhas.append("I. QUESITOS")
        for i, q in enumerate(pacote["quesitos"], 1):
            linhas.append(f"  {i}. {q['quesito']}")
            if q.get("nota"):
                linhas.append(f"     Obs.: {q['nota']}")
        linhas.append("")
    if pacote["diligencias"]:
        linhas.append("II. DOCUMENTOS A REQUISITAR")
        for i, d in enumerate(pacote["diligencias"], 1):
            linhas.append(f"  {i}. {d['descricao']}")
            for doc in d["documentos"]:
                linhas.append(f"     - {doc}")
            if d.get("onde"):
                linhas.append(f"     Onde: {d['onde']}")
            if d.get("nota"):
                linhas.append(f"     Obs.: {d['nota']}")
        linhas.append("")
    linhas.append(SECAO_HIPOTETICA)
    for q in pacote["quesitos"]:
        linhas.append(f"  - {q['elemento']}: instrui a hipótese de {q['para_o_regime']} "
                      f"(standard exigido: {q['standard']})")
    linhas.append("")
    if pacote["requisicoes_a_orgao_competente"]:
        linhas.append("IV. FORA DO ALCANCE DO CONTROLE ADMINISTRATIVO")
        for r in pacote["requisicoes_a_orgao_competente"]:
            linhas.append(f"  - {r['elemento']}: {r['motivo']}")
        linhas.append("")
    linhas.append(pacote["ressalva"])
    return "\n".join(linhas)


# A seção onde o nome do regime pode aparecer — e só ela.
SECAO_HIPOTETICA = (
    "III. A QUE HIPÓTESE CADA ELEMENTO SERVE (qualificação HIPOTÉTICA, não imputação — a "
    "tipificação compete ao órgão próprio e os elementos não se presumem)")

_RESSALVA = (
    "Quesitos e diligências são PEDIDOS de instrução, não imputação. Vigora a presunção de "
    "legitimidade dos atos administrativos; os elementos do tipo não podem ser presumidos "
    "(Lei 8.429/1992, art. 17-C, I), e a qualificação jurídica compete ao órgão competente."
)


def validar() -> list[str]:
    """Todo quesito está livre de palavra de juízo? Roda no teste."""
    fora = []
    for elemento, roteiro in _ROTEIRO.items():
        if not _sem_juizo(roteiro["quesito"]):
            fora.append(f"{elemento}: quesito contém palavra de juízo")
        if not roteiro.get("documentos"):
            fora.append(f"{elemento}: sem documento a requisitar")
    return fora
