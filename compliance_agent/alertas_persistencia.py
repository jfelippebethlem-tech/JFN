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
  4. **Todo alerta carrega DUAS datas.** `created_at` = quando o achado apareceu pela primeira vez;
     `visto_em` = a última corrida em que o detector ainda o produziu. Sem elas a fila do fiscal é
     atemporal: medido em 2026-08-10, os **3.082 alertas do acervo tinham `created_at` NULO** — a
     coluna existia e ninguém a preenchia. Isso importa porque régua muda: no mesmo dia o corte do
     art. 125 passou de `>=` para `>`, e sem `visto_em` não há como distinguir o alerta reconfirmado
     sob a régua nova daquele que sobreviveu à poda por ter triagem humana e não é mais produzido.

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


def _garantir_visto_em(con) -> bool:
    """Cria a coluna `visto_em` se faltar. Idempotente; base antiga segue funcionando sem ela."""
    try:
        cols = {r[1] for r in con.execute("pragma table_info(alertas)")}
        if "visto_em" not in cols:
            con.execute("alter table alertas add column visto_em text")
        return True
    except sqlite3.Error as exc:
        logger.warning("não consegui garantir a coluna visto_em: %s", exc)
        return False


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
    tem_visto = _garantir_visto_em(con)
    for a in achados:
        tipo = f"{prefixo}_{a['detector']}"
        ev = json.dumps(a["evidencias"], ensure_ascii=False, default=str)
        # Ordena preferindo quem tem TRIAGEM: se houver cópias, a que fica é a decidida pelo
        # fiscal. As demais são colapsadas — dedup que só ATUALIZA a primeira deixa as cópias
        # antigas vivas para sempre (medido: 73 pares (tipo, título) com até 7 cópias cada,
        # sobreviventes de gravações anteriores ao dedup).
        ids = [r[0] for r in con.execute(
            "select id from alertas where tipo=? and titulo=? "
            "order by case when coalesce(status,'novo') <> 'novo' then 0 else 1 end, id",
            (tipo, a["titulo"]))]
        if ids:
            con.execute(
                "update alertas set severidade=?, descricao=?, evidencias=?"
                + (", visto_em=datetime('now')" if tem_visto else "") + " where id=?",
                (severidade(a["risco"]), a["descricao"], ev, ids[0]))
            # Cópias sem triagem saem. Cópias TRIADAS só saem se a decisão for a MESMA da que
            # fica — aí colapsar é sem perda. Decisões DIVERGENTES para o mesmo achado ficam todas:
            # o conflito é informação, e resolvê-lo é de quem fiscaliza, não do gravador.
            # Medido: os 21 alertas "triados" do acervo eram 7 decisões triplicadas.
            mantido = con.execute("select coalesce(status,'novo') from alertas where id=?",
                                  (ids[0],)).fetchone()[0]
            for extra in ids[1:]:
                con.execute("delete from alertas where id=? and coalesce(status,'novo') in "
                            "('novo', ?)", (extra, mantido))
        else:
            campos = "tipo, severidade, titulo, descricao, evidencias, status, created_at"
            valores = "?,?,?,?,?, 'novo', datetime('now')"
            if tem_visto:
                campos += ", visto_em"; valores += ", datetime('now')"
            con.execute(f"insert into alertas ({campos}) values ({valores})",
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
                # ZEROU NESTA CORRIDA. Poupa — mas a razão NÃO é a mesma nos dois casos, e dizer
                # "INDISPONÍVEL ≠ 0" quando a cobertura veio `ok` é mentir sobre o próprio motivo:
                # ali o detector mediu e não achou, e os alertas antigos estão SUPERADOS. Continuam
                # gravados por precaução (apagar em massa a partir de uma corrida é irreversível),
                # e é o `visto_em` que os denuncia: alerta não reconfirmado hoje tem data velha.
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
        aviso += ("; POUPADOS por zerarem nesta corrida — o detector pode ter zerado por falha de "
                  "fonte (INDISPONÍVEL ≠ 0) ou por medir e não achar; nos dois casos o alerta fica "
                  f"e o `visto_em` diz se ele foi reconfirmado: {', '.join(poupados)}")
    logger.info("poda de alertas (%s): %s", prefixo, aviso)
    return aviso
