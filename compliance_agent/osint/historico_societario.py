# -*- coding: utf-8 -*-
"""Histórico societário — quem ENTROU, quem SAIU, e em que janela. O eixo do tempo que faltava.

O BURACO QUE ESTE MÓDULO FECHA. A base de sócios era um snapshot único (`socios_receita.fonte_mes`
com um só valor) trazendo `data_entrada` e **nenhuma** data de saída. Consequência prática: toda
afirmação de "vínculo à época do certame" era inverificável, e a pergunta que fecha os casos mais
caros da casa — *o sócio comum já era sócio no dia da licitação, ou entrou depois?* — não tinha
como ser respondida. Pior: a ausência era silenciosa, e silêncio se lê como "não há vínculo".

O CAMINHO, e por que este e não outro. O layout `Socios*.zip` da Receita não tem campo de
desligamento — conferido na fonte, não de memória. Ex-sócio com data só sai de **diferença entre
snapshots**: presente no mês M, ausente em M+1 ⇒ saiu na janela. A precisão máxima é de um mês, e o
módulo diz isso em toda saída, em vez de fingir uma data exata.

A opção pelo BigQuery/Base dos Dados foi descartada por decisão do dono (nada com billing). O que
a substitui é melhor: o espelho público `dados-abertos-rf-cnpj.casadosdados.com.br` mantém **41
snapshots mensais, de 2023-03 a 2026-07**, sem chave e sem cobrança. A série histórica não precisa
"começar agora" — ela já existe, e é retroativa em mais de três anos.

O QUE O MÓDULO SE RECUSA A DIZER:

  · **Não converte lacuna em saída.** Sócio ausente num snapshot que a casa nunca ingeriu não
    "saiu": o mês não foi observado. Por isso `diff` só compara meses **consecutivos entre os
    ingeridos** e marca `janela_confiavel=False` quando há buraco entre eles.
  · **Não afirma vínculo fora da janela coberta.** Perguntado por uma data anterior ao primeiro
    snapshot, `vinculo_na_data` devolve `INDISPONIVEL`, com o pedido de diligência à JUCERJA — que
    é a fonte que dá a data exata da alteração contratual.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Iterable

__all__ = [
    "SCHEMA", "criar_schema", "registrar_snapshot", "snapshots_ingeridos",
    "diff_snapshots", "vinculo_na_data", "historico_do_socio", "trocas_perto_de",
]

_RE_DIG = re.compile(r"\D")

SCHEMA = """
CREATE TABLE IF NOT EXISTS socio_snapshot (
  fonte_mes   TEXT NOT NULL,          -- 'AAAA-MM' do snapshot da Receita
  cnpj_basico TEXT NOT NULL,
  doc_socio   TEXT NOT NULL,          -- CNPJ íntegro (sócio PJ) ou máscara ***NNNNNN**
  nome_norm   TEXT NOT NULL,
  ident       TEXT,                   -- 1=PJ, 2=PF, 3=estrangeiro
  qualificacao TEXT,
  data_entrada TEXT,
  PRIMARY KEY (fonte_mes, cnpj_basico, doc_socio, nome_norm)
);
CREATE INDEX IF NOT EXISTS ix_socio_snapshot_raiz ON socio_snapshot (cnpj_basico, fonte_mes);
CREATE INDEX IF NOT EXISTS ix_socio_snapshot_doc  ON socio_snapshot (doc_socio, fonte_mes);

CREATE TABLE IF NOT EXISTS socio_historico (
  cnpj_basico  TEXT NOT NULL,
  doc_socio    TEXT NOT NULL,
  nome_norm    TEXT NOT NULL,
  qualificacao TEXT,
  data_entrada TEXT,                  -- declarada pela Receita (entrada na sociedade)
  visto_de     TEXT NOT NULL,         -- primeiro snapshot em que aparece
  visto_ate    TEXT NOT NULL,         -- último snapshot em que aparece
  saiu_entre   TEXT,                  -- 'AAAA-MM..AAAA-MM' quando some entre dois meses observados
  status       TEXT NOT NULL,         -- 'ativo' | 'saiu' | 'indeterminado'
  janela_confiavel INTEGER NOT NULL DEFAULT 1,   -- 0 quando há mês não observado no meio
  PRIMARY KEY (cnpj_basico, doc_socio, nome_norm)
);
CREATE INDEX IF NOT EXISTS ix_socio_hist_doc ON socio_historico (doc_socio);

CREATE TABLE IF NOT EXISTS socio_snapshot_meta (
  fonte_mes TEXT PRIMARY KEY,
  origem    TEXT NOT NULL,
  ingerido_em TEXT NOT NULL,
  n_linhas  INTEGER NOT NULL,
  n_raizes  INTEGER NOT NULL,
  escopo    TEXT NOT NULL             -- 'raizes-alvo' | 'completo'
);
"""


def criar_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.commit()


def _norm_nome(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().upper()


def registrar_snapshot(con: sqlite3.Connection, fonte_mes: str, linhas: Iterable[dict], *,
                       origem: str, escopo: str = "raizes-alvo") -> dict:
    """Grava um snapshot mensal. Idempotente por (mês, raiz, doc, nome).

    `linhas` traz dicts com `cnpj_basico`, `doc_socio`, `nome_socio`, `ident`, `qualificacao_txt`,
    `data_entrada`. Não recalcula o histórico — isso é `diff_snapshots`, que precisa da série
    inteira para não confundir lacuna com saída.
    """
    criar_schema(con)
    n = 0
    raizes: set[str] = set()
    for ln in linhas:
        raiz = str(ln.get("cnpj_basico") or "").strip()
        doc = str(ln.get("doc_socio") or "").strip()
        nome = _norm_nome(ln.get("nome_socio") or ln.get("nome_norm"))
        if not raiz or not (doc or nome):
            continue
        raizes.add(raiz)
        con.execute(
            "INSERT OR REPLACE INTO socio_snapshot "
            "(fonte_mes, cnpj_basico, doc_socio, nome_norm, ident, qualificacao, data_entrada) "
            "VALUES (?,?,?,?,?,?,?)",
            (fonte_mes, raiz, doc, nome, str(ln.get("ident") or ""),
             str(ln.get("qualificacao_txt") or ln.get("qualificacao") or ""),
             str(ln.get("data_entrada") or "")))
        n += 1
    con.execute(
        "INSERT OR REPLACE INTO socio_snapshot_meta "
        "(fonte_mes, origem, ingerido_em, n_linhas, n_raizes, escopo) "
        "VALUES (?,?,datetime('now'),?,?,?)", (fonte_mes, origem, n, len(raizes), escopo))
    con.commit()
    return {"fonte_mes": fonte_mes, "n_linhas": n, "n_raizes": len(raizes), "escopo": escopo}


def snapshots_ingeridos(con: sqlite3.Connection) -> list[str]:
    try:
        return [r[0] for r in con.execute(
            "SELECT fonte_mes FROM socio_snapshot_meta ORDER BY fonte_mes").fetchall()]
    except sqlite3.Error:
        return []


def _meses_entre(a: str, b: str) -> int:
    """Distância em meses entre 'AAAA-MM' — para saber se a janela tem buraco."""
    try:
        ay, am = (int(x) for x in a.split("-")[:2])
        by, bm = (int(x) for x in b.split("-")[:2])
    except (ValueError, IndexError):
        return 0
    return (by - ay) * 12 + (bm - am)


def diff_snapshots(con: sqlite3.Connection) -> dict:
    """Recalcula `socio_historico` a partir de TODOS os snapshots ingeridos.

    A regra é conservadora de propósito: um sócio só recebe `status='saiu'` quando some entre dois
    meses **efetivamente ingeridos**. Se entre eles há mês não observado, a saída continua valendo,
    mas `janela_confiavel=0` — o produto tem de dizer "saiu em algum ponto de um intervalo de N
    meses", e não fingir precisão mensal que a série não tem.
    """
    criar_schema(con)
    meses = snapshots_ingeridos(con)
    if not meses:
        return {"ok": False, "motivo": "nenhum snapshot ingerido", "meses": []}

    ultimo = meses[-1]
    con.execute("DELETE FROM socio_historico")
    linhas = con.execute(
        "SELECT cnpj_basico, doc_socio, nome_norm, "
        "       MIN(fonte_mes) visto_de, MAX(fonte_mes) visto_ate, "
        "       MAX(qualificacao) qualificacao, MAX(data_entrada) data_entrada "
        "FROM socio_snapshot GROUP BY cnpj_basico, doc_socio, nome_norm").fetchall()

    n_saiu = n_ativo = 0
    for raiz, doc, nome, visto_de, visto_ate, qualif, dt_ent in linhas:
        if visto_ate == ultimo:
            status, saiu_entre, confiavel = "ativo", None, 1
        else:
            posteriores = [m for m in meses if m > visto_ate]
            prox = posteriores[0] if posteriores else None
            if prox is None:
                status, saiu_entre, confiavel = "indeterminado", None, 1
            else:
                status = "saiu"
                saiu_entre = f"{visto_ate}..{prox}"
                confiavel = 1 if _meses_entre(visto_ate, prox) <= 1 else 0
        n_saiu += status == "saiu"
        n_ativo += status == "ativo"
        con.execute(
            "INSERT OR REPLACE INTO socio_historico (cnpj_basico, doc_socio, nome_norm, "
            "qualificacao, data_entrada, visto_de, visto_ate, saiu_entre, status, janela_confiavel) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (raiz, doc, nome, qualif, dt_ent, visto_de, visto_ate, saiu_entre, status, confiavel))
    con.commit()
    return {
        "ok": True, "meses": meses, "n_meses": len(meses),
        "n_vinculos": len(linhas), "n_ativos": n_ativo, "n_sairam": n_saiu,
        "cobertura": f"{meses[0]} a {ultimo}",
        "nota": ("Saída inferida por DIFERENÇA entre snapshots: precisão máxima de um mês. "
                 "Sócio ausente em mês NÃO ingerido não saiu — o mês não foi observado."),
    }


def vinculo_na_data(con: sqlite3.Connection, cnpj_basico: str, data: str, *,
                    doc_socio: str = "", nome: str = "") -> dict:
    """*Fulano era sócio desta empresa NESTA data?* — a pergunta que fecha caso de direcionamento.

    Três respostas possíveis, e a terceira é a que mais importa: `INDISPONIVEL`. Perguntar por uma
    data fora da janela coberta pela série não pode devolver "não era sócio".
    """
    meses = snapshots_ingeridos(con)
    alvo = (str(data or "")[:7]).strip()
    base = {"cnpj_basico": cnpj_basico, "data": data, "mes_alvo": alvo,
            "serie": {"de": meses[0] if meses else None, "ate": meses[-1] if meses else None,
                      "n_meses": len(meses)}}
    if not meses or not re.match(r"^\d{4}-\d{2}$", alvo):
        return {**base, "resposta": "INDISPONIVEL",
                "motivo": "série de snapshots vazia ou data ilegível",
                "diligencia": _DILIGENCIA_JUCERJA}
    if alvo < meses[0] or alvo > meses[-1]:
        return {**base, "resposta": "INDISPONIVEL",
                "motivo": (f"a data pedida está fora da série observada ({meses[0]} a {meses[-1]}). "
                           "Ausência de observação não é ausência de vínculo."),
                "diligencia": _DILIGENCIA_JUCERJA}

    # o snapshot ingerido mais próximo por baixo é o que descreve o estado naquele momento
    anteriores = [m for m in meses if m <= alvo]
    mes_ref = anteriores[-1]
    cond, args = ["cnpj_basico=?", "fonte_mes=?"], [cnpj_basico, mes_ref]
    if doc_socio:
        cond.append("doc_socio=?"); args.append(doc_socio)
    if nome:
        cond.append("nome_norm=?"); args.append(_norm_nome(nome))
    achou = con.execute(
        f"SELECT doc_socio, nome_norm, qualificacao, data_entrada FROM socio_snapshot "
        f"WHERE {' AND '.join(cond)}", args).fetchall()
    defasagem = _meses_entre(mes_ref, alvo)
    return {
        **base, "mes_observado": mes_ref, "defasagem_meses": defasagem,
        "resposta": "SIM" if achou else "NAO",
        "socios": [{"doc": d, "nome": n, "qualificacao": q, "data_entrada": e}
                   for d, n, q, e in achou],
        "ressalva": (f"Estado observado em {mes_ref}, {defasagem} mês(es) antes da data pedida. "
                     "A Receita publica mensalmente; alteração contratual dentro da janela não "
                     "aparece. Para data exata, a fonte é a ficha cadastral da junta comercial."),
        "diligencia": None if achou else _DILIGENCIA_JUCERJA,
    }


_DILIGENCIA_JUCERJA = {
    "orgao": "JUCERJA — Junta Comercial do Estado do Rio de Janeiro",
    "documento": "Ficha Cadastral Completa (FCN) com histórico de alterações contratuais",
    "por_que": ("A base aberta da Receita publica snapshots mensais e não registra data de saída "
                "de sócio; só o registro na junta dá a data exata da alteração."),
    "como": ("Consulta pública do portal entrega apenas situação/NIRE; a ficha com histórico exige "
             "login e recolhimento de DARJ — via natural é o ofício institucional."),
}


def historico_do_socio(con: sqlite3.Connection, *, doc_socio: str = "", nome: str = "") -> list[dict]:
    """Todas as sociedades de uma pessoa ao longo da série, com entrada e saída observadas."""
    cond, args = [], []
    if doc_socio:
        cond.append("doc_socio=?"); args.append(doc_socio)
    if nome:
        cond.append("nome_norm=?"); args.append(_norm_nome(nome))
    if not cond:
        return []
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        f"SELECT * FROM socio_historico WHERE {' AND '.join(cond)} "
        f"ORDER BY visto_de", args).fetchall()]


def trocas_perto_de(con: sqlite3.Connection, cnpj_basico: str, data: str, *,
                    meses_janela: int = 6) -> dict:
    """Troca de quadro societário na vizinhança de uma data — o padrão que interessa.

    Sócio que ENTRA logo depois da homologação, ou que SAI logo depois do pagamento, é o sinal que
    a linha do tempo (`osint/timeline`) sempre quis ler e nunca teve fonte para ler.
    """
    alvo = (str(data or "")[:7]).strip()
    if not re.match(r"^\d{4}-\d{2}$", alvo):
        return {"ok": False, "motivo": "data ilegível"}
    con.row_factory = sqlite3.Row
    linhas = [dict(r) for r in con.execute(
        "SELECT * FROM socio_historico WHERE cnpj_basico=?", (cnpj_basico,)).fetchall()]
    entradas, saidas = [], []
    for r in linhas:
        if abs(_meses_entre(r["visto_de"], alvo)) <= meses_janela and r["visto_de"] != r["visto_ate"]:
            entradas.append(r)
        if r["saiu_entre"]:
            fim = r["saiu_entre"].split("..")[0]
            if abs(_meses_entre(fim, alvo)) <= meses_janela:
                saidas.append(r)
    return {
        "ok": True, "cnpj_basico": cnpj_basico, "data": data, "janela_meses": meses_janela,
        "entradas": entradas, "saidas": saidas,
        "n_entradas": len(entradas), "n_saidas": len(saidas),
        "leitura": ("Troca de quadro societário próxima da data é INDÍCIO de reorganização "
                    "oportunista — e é igualmente compatível com sucessão familiar, saída de sócio "
                    "minoritário ou reestruturação ordinária. Confirmar na alteração contratual."),
    }
