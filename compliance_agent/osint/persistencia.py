# -*- coding: utf-8 -*-
"""Persiste o `GrafoVinculos` nas tabelas que a casa já tinha desenhado — e nunca preencheu.

`pessoas` (0 linhas) e `relacionamentos` (0 linhas) estão no schema desde sempre, com exatamente as
colunas que um grafo de vínculos precisa: `tipo`, `fonte`, `data_inicio`, `data_fim`. Faltava quem
escrevesse nelas. Sem persistência, cada consulta remonta o grafo do zero e nada do que se descobre
sobrevive à execução — o que impede a pergunta mais útil de todas: *o que mudou desde a última vez?*

DUAS RECUSAS QUE FAZEM ESTE MÓDULO SER CONFIÁVEL:

  · **Aresta sem fonte não entra.** É a mesma regra do `GrafoVinculos.ligar`, repetida aqui porque
    a tabela é lida por outros caminhos que não passam pelo motor.
  · **`data_fim` fica NULA, e isso é uma afirmação, não um esquecimento.** A base de sócios da
    Receita é um snapshot único com data de ENTRADA e nenhuma data de saída. Preencher `data_fim`
    com a data do snapshot seria inventar um desligamento que ninguém observou. Nulo aqui significa
    "vínculo visto no snapshot; término INDISPONÍVEL" — e é assim que o produto tem de ler.

Vocabulário de `tipo`: os ids de `TIPOS_ARESTA`, sem tradução. O rótulo FollowTheMoney
(`Ownership`, `Directorship`, `Family`, `UnknownLink`) é derivado na EXPORTAÇÃO, não gravado — para
que a mudança de ontologia externa não obrigue a reescrever a base.
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

from compliance_agent.osint.vinculos import TIPOS_ARESTA, Aresta, GrafoVinculos

__all__ = ["salvar_grafo", "arestas_persistidas", "para_ftm", "FTM_POR_TIPO"]

# Ponte com a ontologia FollowTheMoney (OCCRP/Aleph) — usada só na exportação.
FTM_POR_TIPO: dict[str, str] = {
    "socio_de": "Ownership",
    "mesmo_socio": "UnknownLink",
    "parente_de": "Family",
    "servidor_de": "Directorship",
    "sucessora_de": "Succession",
    "doou_para": "Payment",
    "nomeado_por": "Directorship",
    "subcontratou": "Contract",
}
_FTM_PADRAO = "UnknownLink"

# ARESTA SEM SENTIDO NÃO PODE ENTRAR DUAS VEZES. "A tem o mesmo telefone que B" e "B tem o mesmo
# telefone que A" são UM fato; o grafo, porém, é montado por alvo, e quando A e B são os dois
# credores do universo cada um produz a sua metade. Gravadas as duas, a base diria o dobro dos
# vínculos que existem — e quem contasse arestas por empresa acharia concentração onde há espelho.
# `socio_de`, `doou_para`, `nomeado_por`, `sucessora_de` e `subcontratou` NÃO entram aqui: nesses a
# direção é a informação (quem é sócio de quem, quem doou para quem).
_SIMETRICOS = frozenset({
    "mesmo_socio", "mesmo_socio_doc_parcial", "mesma_sala", "mesmo_predio", "mesmo_ip",
    "mesmo_telefone", "mesmo_email", "mesmo_contador", "mesmo_advogado", "mesmo_registrante",
    "parente_de", "nome_igual_sem_documento",
})


def _pessoa_id(con: sqlite3.Connection, chave: str, rotulo: str) -> int:
    """Id em `pessoas` para um nó do grafo, criando se preciso.

    A tabela guarda pessoas E empresas (a coluna `tipo` distingue) porque o grafo liga as duas, e
    `relacionamentos` tem chave estrangeira só para `pessoas`. `cpf` fica NULO quando o documento
    veio mascarado da Receita — gravar seis dígitos num campo chamado `cpf` seria mentir ao
    próximo leitor.
    """
    prefixo, _, resto = chave.partition(":")
    tipo = {"pj": "empresa", "pj_nome": "empresa", "pf": "pessoa", "pf_nome": "pessoa"}.get(
        prefixo, prefixo)
    doc = resto if prefixo in ("pj", "pf") else None
    nome = (rotulo or chave).strip()[:200]

    # O DOCUMENTO É A IDENTIDADE, e a base já dizia isso: `pessoas` tem UNIQUE em `cpf`. Procurar
    # por (nome, tipo, doc) fazia a MESMA empresa, vinda com dois rótulos diferentes (razão social
    # de um lado, chave crua do outro), ser inserida duas vezes — e a segunda estourava a UNIQUE,
    # derrubando a passada inteira. Sem documento não há o que casar senão o nome.
    if doc:
        r = con.execute("SELECT id FROM pessoas WHERE cpf=?", (doc,)).fetchone()
    else:
        r = con.execute("SELECT id FROM pessoas WHERE nome=? AND COALESCE(tipo,'')=? AND cpf IS NULL",
                        (nome, tipo)).fetchone()
    if r:
        return int(r[0])
    cur = con.execute(
        "INSERT INTO pessoas (cpf, nome, tipo, ativo, created_at) "
        "VALUES (?,?,?,1,datetime('now'))", (doc, nome, tipo))
    return int(cur.lastrowid)


def salvar_grafo(con: sqlite3.Connection, grafo: GrafoVinculos) -> dict:
    """Grava nós e arestas. Idempotente: rodar duas vezes não duplica.

    Devolve `{pessoas_novas, arestas_novas, arestas_repetidas, recusadas}`. `recusadas` é o que foi
    descartado por falta de fonte ou por tipo fora do vocabulário — número que interessa, porque
    aresta silenciosamente descartada é como um grafo fica menor do que a realidade sem ninguém ver.
    """
    n_pessoas_antes = con.execute("SELECT COUNT(*) FROM pessoas").fetchone()[0]
    novas = repetidas = recusadas = 0
    for a in grafo.arestas:
        if not a.fonte or a.tipo not in TIPOS_ARESTA:
            recusadas += 1
            continue
        a_id = _pessoa_id(con, a.origem, grafo.rotulos.get(a.origem, ""))
        b_id = _pessoa_id(con, a.destino, grafo.rotulos.get(a.destino, ""))
        if a.tipo in _SIMETRICOS and a_id > b_id:
            a_id, b_id = b_id, a_id      # direção canônica: o espelho não vira segunda aresta
        ja = con.execute(
            "SELECT 1 FROM relacionamentos WHERE pessoa_a_id=? AND pessoa_b_id=? AND tipo=? "
            "AND COALESCE(fonte,'')=? AND COALESCE(data_inicio,'')=?",
            (a_id, b_id, a.tipo, a.fonte, a.data or "")).fetchone()
        if ja:
            repetidas += 1
            continue
        con.execute(
            "INSERT INTO relacionamentos (pessoa_a_id, pessoa_b_id, tipo, descricao, fonte, "
            "data_inicio, data_fim, created_at) VALUES (?,?,?,?,?,?,NULL,datetime('now'))",
            (a_id, b_id, a.tipo, a.detalhe or TIPOS_ARESTA[a.tipo].descricao, a.fonte,
             a.data or None))
        novas += 1
    con.commit()
    n_pessoas_depois = con.execute("SELECT COUNT(*) FROM pessoas").fetchone()[0]
    return {
        "pessoas_novas": n_pessoas_depois - n_pessoas_antes,
        "arestas_novas": novas,
        "arestas_repetidas": repetidas,
        "recusadas": recusadas,
        "nota_data_fim": ("`data_fim` gravada NULA de propósito: a fonte não observa saída de "
                          "sócio. Nulo = término INDISPONÍVEL, não = vínculo vigente."),
    }


def arestas_persistidas(con: sqlite3.Connection, nome: str = "") -> list[dict]:
    """Arestas já gravadas, opcionalmente filtradas por nome de uma das pontas."""
    sql = ("SELECT r.tipo, r.descricao, r.fonte, r.data_inicio, r.data_fim, "
           "a.nome AS de, a.tipo AS de_tipo, b.nome AS para, b.tipo AS para_tipo "
           "FROM relacionamentos r JOIN pessoas a ON a.id=r.pessoa_a_id "
           "JOIN pessoas b ON b.id=r.pessoa_b_id")
    args: tuple = ()
    if nome:
        sql += " WHERE a.nome LIKE ? OR b.nome LIKE ?"
        args = (f"%{nome}%", f"%{nome}%")
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def para_ftm(arestas: Iterable[Aresta | dict]) -> list[dict]:
    """Exporta no vocabulário FollowTheMoney, para interoperar com Aleph/Gephi.

    Adotar uma ontologia pronta em vez de inventar a nossa é decisão deliberada: `Ownership`,
    `Directorship` e `Family` já significam algo fora de casa, e o painel já expõe `/api/grafo/ftm`.
    """
    out = []
    for a in arestas:
        d = a if isinstance(a, dict) else {
            "tipo": a.tipo, "de": a.origem, "para": a.destino, "fonte": a.fonte,
            "data_inicio": a.data, "descricao": a.detalhe,
        }
        out.append({
            "schema": FTM_POR_TIPO.get(d.get("tipo", ""), _FTM_PADRAO),
            "properties": {
                "role": [d.get("tipo", "")],
                "startDate": [d.get("data_inicio")] if d.get("data_inicio") else [],
                "endDate": [],  # a fonte não observa término — ver `nota_data_fim`
                "sourceUrl": [d.get("fonte", "")],
                "summary": [d.get("descricao", "")],
            },
            "de": d.get("de"), "para": d.get("para"),
        })
    return out
