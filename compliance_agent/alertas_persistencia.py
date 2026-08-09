# -*- coding: utf-8 -*-
"""Persistência de alerta de perícia — gravar sem duplicar, podar sem destruir.

POR QUE EXISTE. Havia dois gravadores e só um estava certo. O do PCRJ dedupa por (tipo, título) e
retira o superado; o das emendas fazia `INSERT` cru a cada corrida e **nunca** removia nada.
Medido em 2026-08-09: das 2.322 linhas de alerta de emendas, **434 eram distintas — 81,3% de
duplicação** por reexecução (a mesma ONG sancionada aparecia 60 vezes, uma por rodada). O painel
conta alerta; contagem inflada por reexecução é manchete falsa.

AS TRÊS REGRAS QUE ESTE MÓDULO CARREGA, e que só existiam num dos dois lados:

  1. **Dedup por (tipo, título)** — reexecutar ATUALIZA, não empilha.
  2. **Nunca apagar linha com TRIAGEM.** `status` guarda a decisão de quem fiscaliza
     ('confirmado'/'descartado'); o detector não tem autoridade para desfazê-la. Os 21 alertas
     triados do acervo são todos de UMA família, justamente a que a poda varre.
  3. **INDISPONÍVEL ≠ 0.** Detector que zerou pode ter zerado porque a fonte sumiu — a poda o
     POUPA e declara no relatório. Apagar ali transformaria falha de coleta em "nada a apurar".

O título é a IDENTIDADE do achado: é por ele que se dedupa e se poda. Título que não distingue
órgão/ano/credor funde achados diferentes num só, e aí não há poda correta possível — retirar o
superado leva junto o vivo.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Iterable

logger = logging.getLogger(__name__)


def _tipos_gravados(con, prefixo: str) -> list[str]:
    try:
        return [r[0] for r in con.execute(
            "select distinct tipo from alertas where tipo like ?", (f"{prefixo}_%",))]
    except sqlite3.Error:
        logger.warning("tabela de alertas indisponível — poda não roda nesta corrida")
        return []


def gravar(con, achados: list[dict], cobertura: dict[str, str], *,
           prefixo: str, detectores: Iterable[str], severidade) -> str:
    """Grava os achados deduplicando e retira o que o detector não produz mais.

    `severidade` é a função risco→rótulo de cada perícia (elas divergem por desenho).
    Devolve o aviso da poda, que o chamador põe na cobertura — silêncio aqui é o que
    permitiu 81,3% de duplicação passar despercebido.
    """
    for a in achados:
        tipo = f"{prefixo}_{a['detector']}"
        ev = json.dumps(a["evidencias"], ensure_ascii=False, default=str)
        ex = con.execute("select id from alertas where tipo=? and titulo=?",
                         (tipo, a["titulo"])).fetchone()
        if ex:
            con.execute("update alertas set severidade=?, descricao=?, evidencias=? where id=?",
                        (severidade(a["risco"]), a["descricao"], ev, ex[0]))
        else:
            con.execute(
                "insert into alertas (tipo, severidade, titulo, descricao, evidencias, status) "
                "values (?,?,?,?,?, 'novo')",
                (tipo, severidade(a["risco"]), a["titulo"], a["descricao"], ev))
    aviso = podar(con, achados, cobertura, prefixo=prefixo, detectores=detectores)
    con.commit()
    return aviso


def podar(con, achados: list[dict], cobertura: dict[str, str], *,
          prefixo: str, detectores: Iterable[str]) -> str:
    """Retira alertas que o detector não produz mais — ver as três regras no topo do módulo."""
    vivos: dict[str, set[str]] = {}
    for a in achados:
        vivos.setdefault(f"{prefixo}_{a['detector']}", set()).add(a["titulo"])
    gravados = _tipos_gravados(con, prefixo)
    apagados, poupados, triados = 0, [], []
    for nome in detectores:
        if not str(cobertura.get(nome, "")).startswith("ok"):
            continue                       # erro no detector: não julga o que não mediu
        for tipo in sorted({t for t in list(vivos) + gravados
                            if t.startswith(f"{prefixo}_{nome}_") or t == f"{prefixo}_{nome}"}):
            titulos = vivos.get(tipo)
            if not titulos:
                n = con.execute("select count(*) from alertas where tipo=?", (tipo,)).fetchone()
                if n and n[0]:
                    poupados.append(f"{tipo}({n[0]})")
                continue
            marcas = ",".join("?" * len(titulos))
            cur = con.execute(
                f"delete from alertas where tipo=? and titulo not in ({marcas}) "
                "and coalesce(status,'novo') = 'novo'", (tipo, *sorted(titulos)))
            apagados += cur.rowcount or 0
            n_triado = con.execute(
                f"select count(*) from alertas where tipo=? and titulo not in ({marcas}) "
                "and coalesce(status,'novo') <> 'novo'", (tipo, *sorted(titulos))).fetchone()[0]
            if n_triado:
                triados.append(f"{tipo}({n_triado})")
    aviso = f"{apagados} alerta(s) superado(s) retirado(s)"
    if triados:
        aviso += f"; PRESERVADOS por terem triagem humana: {', '.join(triados)}"
    if poupados:
        aviso += f"; POUPADOS por zerarem nesta corrida (INDISPONÍVEL ≠ 0): {', '.join(poupados)}"
    logger.info("poda de alertas (%s): %s", prefixo, aviso)
    return aviso
