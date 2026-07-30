# -*- coding: utf-8 -*-
"""Ponte TCE-RJ → contexto de detector de julgamento. O que destrava o J4 (item E.0.1).

O PROBLEMA QUE ISTO RESOLVE. Os detectores de julgamento da casa — J2 (propostas de cobertura),
J4 (supressão de propostas / licitante único), J7 (inabilitação seletiva) — dependem da LISTA DE
PROPONENTES, e a base tinha **77 linhas** em `proposta_item`. Ficavam `nao_avaliavel` em massa, e não
por defeito deles: o registro típico do PNCP traz só o vencedor, e "1 fornecedor distinto no
resultado" nunca provou licitante único — pode ser adjudicação múltipla, pode ser falta de captura.

A API de dados abertos do TCE-RJ publica a lista, certame a certame, e publica o campo que resolve a
ambiguidade: **`QuantidadeParticipante`**. Com ele, "licitante único" deixa de ser inferido da
ausência de registro e passa a ser **declarado pela fonte** — a diferença entre um achado e um
artefato de captura.

Medido em 2026-07-29, na primeira execução real do coletor (que existia, era testado com `buscar`
injetado e **nunca havia rodado contra a API**): 13.021 certames municipais, 34.659 perdedores
nominados, e **3.782 certames (29,0%) com um único participante declarado**.

O LIMITE, declarado. A API traz o participante por **NOME**, sem CNPJ. Então esta ponte serve o J4
(que conta inscritos × classificados) e **não** serve o E.3.2 (cruzamento de QSA entre vencedor e
perdedoras), que precisa de documento para chegar ao quadro societário. Resolver nome → CNPJ é
resolução de entidade, e é o que falta — não algo que se possa fingir aqui.
"""
from __future__ import annotations

import sqlite3
from typing import Any

__all__ = ["certames_disponiveis", "contexto_j4", "cobertura_tcerj", "LIMITE_SEM_CNPJ"]

LIMITE_SEM_CNPJ = (
    "A API do TCE-RJ identifica o licitante por NOME, sem CNPJ. Serve para contar inscritos e "
    "classificados (J4/J7); NÃO serve para cruzar quadro societário (E.3.2), que exige documento. "
    "Resolver nome → CNPJ é resolução de entidade e segue pendente."
)

# Palavras que, no campo de resultado, indicam que o licitante NÃO seguiu ao julgamento.
_NAO_CLASSIFICADO = ("PERDEDOR", "INABILITAD", "DESCLASSIFICAD", "DESIST")


def _chave(ente: str, ano: Any, processo: str) -> str:
    return f"{ente}|{ano}|{processo}"


def certames_disponiveis(con: sqlite3.Connection, *, ano: int | None = None,
                         min_participantes: int | None = None,
                         limite: int = 500) -> list[dict]:
    """Certames municipais com lista de licitantes, do mais disputado ao menos.

    `min_participantes=1` isola o universo de licitante único — que é o que o J4 quer olhar
    primeiro e o que a casa nunca pôde apurar.
    """
    cond, args = ["1=1"], []
    if ano:
        cond.append("ano = ?")
        args.append(ano)
    if min_participantes is not None:
        cond.append("CAST(COALESCE(qtd_participantes,0) AS INTEGER) >= ?")
        args.append(min_participantes)
    try:
        linhas = con.execute(
            f"SELECT ente, ano, processo, MAX(modalidade) modalidade, MAX(objeto) objeto, "
            f"MAX(CAST(COALESCE(qtd_participantes,0) AS INTEGER)) inscritos, "
            f"SUM(CASE WHEN UPPER(COALESCE(resultado,'')) LIKE 'VENCEDOR%' THEN 1 ELSE 0 END) venc, "
            f"COUNT(*) linhas, MAX(data_homologacao) data "
            f"FROM tcerj_licitante WHERE {' AND '.join(cond)} "
            f"GROUP BY ente, ano, processo ORDER BY inscritos DESC LIMIT ?",
            (*args, int(limite))).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"chave": _chave(r[0], r[1], r[2]), "ente": r[0], "ano": r[1], "processo": r[2],
             "modalidade": r[3], "objeto": r[4], "inscritos": r[5], "vencedores": r[6],
             "linhas": r[7], "data_homologacao": r[8]} for r in linhas]


def contexto_j4(con: sqlite3.Connection, ente: str, ano: int, processo: str) -> dict[str, Any]:
    """Contexto do J4 para um certame municipal, a partir da lista real de licitantes.

    `licitantes_inscritos` vem de `QuantidadeParticipante` — **declarado pela fonte**, não contado
    por nós; contar as linhas daria o número de licitantes que o TCE registrou, que pode ser menor.
    A diferença entre os dois vira `cobertura`, para o leitor saber o quanto da lista foi observado.
    """
    con.row_factory = sqlite3.Row
    try:
        linhas = [dict(r) for r in con.execute(
            "SELECT participante, resultado, tipo_participacao, qtd_participantes, modalidade, "
            "objeto, valor_homologacao, valor_estimado, data_homologacao "
            "FROM tcerj_licitante WHERE ente=? AND ano=? AND processo=?",
            (ente, ano, processo))]
    except sqlite3.OperationalError:
        linhas = []
    if not linhas:
        return {"processo": _chave(ente, ano, processo), "motivo": "certame sem licitante na base",
                "fonte": "TCE-RJ dados abertos", "limite": LIMITE_SEM_CNPJ}

    inscritos_declarados = max(
        (int(x["qtd_participantes"] or 0) for x in linhas), default=0)
    nominados = {(x["participante"] or "").strip().upper() for x in linhas if x["participante"]}
    # mantido para diagnóstico e para a cobertura; NÃO alimenta o funil do J4 (ver nota abaixo)
    classificados = sorted({(x["participante"] or "").strip().upper() for x in linhas
                            if not any(m in (x["resultado"] or "").upper()
                                       for m in _NAO_CLASSIFICADO)})
    nao_nominados = max(0, inscritos_declarados - len(nominados))

    ctx = {
        "processo": _chave(ente, ano, processo),
        "orgao": ente,
        "modalidade": linhas[0]["modalidade"],
        "objeto": linhas[0]["objeto"],
        "data_homologacao": linhas[0]["data_homologacao"],
        "licitantes_inscritos": inscritos_declarados or len(nominados),
        "valor_homologado": linhas[0]["valor_homologacao"],
        "valor_estimado": linhas[0]["valor_estimado"],
        "cobertura": {
            "inscritos_declarados_pela_fonte": inscritos_declarados,
            "licitantes_nominados": len(nominados),
            "nao_nominados": nao_nominados,
            "funil_observavel": nao_nominados == 0,
            "nominados_sem_derrota_declarada": len(classificados),
            "nota": ("`QuantidadeParticipante` é declarada pelo TCE-RJ; os nomes vêm das listas de "
                     "vencedor e perdedor, que podem cobrir menos que o total. Diferença = licitante "
                     "que participou e não foi nominado — lacuna de captura, não ausência."),
        },
        "fonte": "TCE-RJ dados abertos (licitante_vencedor/perdedor_municipio)",
        "limite": LIMITE_SEM_CNPJ,
    }

    # AQUI ESTAVA O ERRO QUE O DADO REAL PEGOU, e ele vale ficar escrito — foram DOIS,
    # ambos pegos por conferir o dado real em vez de confiar no formato.
    #
    # PRIMEIRO. A versão inicial entregava `licitantes_classificados` sempre, e o J4 confirmava
    # "forte" em Teresópolis 2244/2025 lendo "129 inscritos, 0 inabilitados ⇒ 1 classificado". Só que
    # os nominados eram UM: o vencedor. Os outros 128 não foram desclassificados — não foram
    # NOMINADOS. Afunilamento de 129 para 1 era lacuna de captura vestida como a assinatura mais
    # forte do detector.
    #
    # SEGUNDO, e mais sutil. Mesmo com todos nominados, a API **não distingue** o licitante
    # INABILITADO do que simplesmente perdeu no preço: os dois vêm como `PERDEDOR`. E o J4 não é
    # sobre perder um leilão — é sobre SELETIVIDADE NA HABILITAÇÃO. Mapear `PERDEDOR` para
    # `licitantes_inabilitados` faria o detector descrever toda licitação competitiva normal (71
    # licitantes, 1 vencedor) como afunilamento. Por isso o funil NÃO é alimentado a partir desta
    # fonte, em nenhum caso.
    #
    # O que a fonte sustenta de verdade é `licitantes_inscritos` — declarado, não inferido — e com
    # ele o LICITANTE ÚNICO, que era exatamente o que a casa não podia apurar: "1 fornecedor
    # distinto no resultado do PNCP" nunca provou licitante único.
    ctx["licitante_unico_declarado"] = ctx["licitantes_inscritos"] == 1
    ctx["funil_nao_alimentado"] = (
        "A fonte não distingue INABILITAÇÃO de derrota no preço — ambos vêm como PERDEDOR. O J4 mede "
        "seletividade na habilitação, não resultado de disputa; alimentar o funil daqui faria toda "
        "licitação competitiva normal parecer afunilamento. Para o funil, a fonte é a ata de sessão."
    )
    if nao_nominados:
        ctx["motivo_funil_nao_observavel"] = (
            f"{inscritos_declarados} participante(s) declarado(s) e apenas {len(nominados)} "
            f"nominado(s) na base: {nao_nominados} não têm nome publicado."
        )
    return ctx


def cobertura_tcerj(con: sqlite3.Connection) -> dict[str, Any]:
    """O denominador do eixo de julgamento municipal — e o antes/depois desta coleta."""
    try:
        total = con.execute(
            "SELECT COUNT(DISTINCT ente||'|'||ano||'|'||processo) FROM tcerj_licitante").fetchone()[0]
        perdedores = con.execute(
            "SELECT COUNT(*) FROM tcerj_licitante WHERE UPPER(resultado)='PERDEDOR'").fetchone()[0]
        unico = con.execute(
            "SELECT COUNT(DISTINCT ente||'|'||ano||'|'||processo) FROM tcerj_licitante "
            "WHERE CAST(COALESCE(qtd_participantes,0) AS INTEGER)=1").fetchone()[0]
        nomes = con.execute(
            "SELECT COUNT(DISTINCT participante) FROM tcerj_licitante").fetchone()[0]
        anos = dict(con.execute("SELECT ano, COUNT(*) FROM tcerj_licitante GROUP BY 1"))
    except sqlite3.OperationalError as e:
        return {"ok": False, "erro": f"tabela ausente: {e}"}
    return {
        "ok": True, "certames": total, "perdedores_nominados": perdedores,
        "licitante_unico_apuravel": unico,
        "pct_licitante_unico": round(100.0 * unico / total, 1) if total else 0.0,
        "nomes_distintos": nomes, "por_ano": anos,
        "antes": ("114 certames com classificado além do 1º lugar (0,66% de 17.242) em "
                  "`pncp_resultado`, e 77 linhas em `proposta_item`"),
        "limite": LIMITE_SEM_CNPJ,
    }
