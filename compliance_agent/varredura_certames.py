# -*- coding: utf-8 -*-
"""Varredura por CERTAME — a camada que a varredura por órgão não alcança.

POR QUE ESTE MÓDULO EXISTE. `varredura_orgaos` cobre 3 detectores de 41 por UG, e o motivo é
estrutural, não um defeito dela: a maioria dos detectores é **por certame**. Eles pedem edital,
lista de propostas, matriz de pontuação, ata de julgamento — coisas que não existem no eixo
"unidade gestora × pagamento". Chamá-los ali só produziria `nao_avaliavel` em massa, poluindo a
fila sem informar nada.

O que a base TEM hoje, medido em 2026-07-28:

    pncp_resultado    54.791 linhas   certame, item, fornecedor, valor homologado, classificação
    edital_documento  14.015 linhas   objeto, valor estimado, texto integral, itens
    edital_clausula   11.363 linhas   cláusula por eixo/subtipo, com o trecho-fonte

Isso alimenta, com dado real e sem inventar campo:

    J2  propostas de cobertura      ← ordem_classificacao por item dá a lista de propostas
    J3  desconto anômalo            ← valor_estimado (edital) × valor_homologado (resultado)
    J4  supressão de propostas      ← contagem de licitantes distintos no certame
    E7  cláusula restritiva         ← edital_clausula, o motor já validado (0 falso positivo)
    E1  barreira de entrada         ← exigências de habilitação extraídas das cláusulas
    E3  lote-pacote                 ← itens_json do edital
    P1  especificação dirigida      ← texto do termo de referência
    P3  sobrepreço                  ← série de preços do mesmo item entre certames

HONESTIDADE — o que este módulo NÃO faz, e por quê:

  · Não inventa campo ausente. `data_abertura` não existe em `pncp_resultado`; E2 (prazos) fica
    de fora em vez de receber uma data estimada, porque prazo estimado produz achado falso com
    aparência de achado medido.
  · A COBERTURA é persistida junto com os achados. Certame sem achado pode ser certame limpo ou
    certame sem dado, e as duas coisas são muito diferentes para quem fiscaliza.
  · Achado é indício. `score` é indicação interna, nunca nota pública.

Lê a produção em SÓ-LEITURA e escreve em banco próprio (`data/achados.db`), como a varredura por
órgão — não disputa lock com o servidor nem com o cron, e por isso pode rodar na VM-2.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Callable

from compliance_agent.detectores import REGISTRO
from compliance_agent.detectores.base import ResultadoDetector
from compliance_agent.varredura_certames_ctx import montar_contexto

logger = logging.getLogger(__name__)

DB_LEITURA = os.environ.get("JFN_DB", "data/compliance.db")
DB_ACHADOS = os.environ.get("JFN_DB_ACHADOS", "data/achados.db")

# Detectores por certame que a base atual consegue alimentar. Manter esta lista curta e honesta
# é o ponto: um detector que só receberia campo vazio não entra, porque `nao_avaliavel` em massa
# esconde a cobertura real em vez de revelá-la.
DETECTORES_CERTAME = ("E1", "E3", "E7", "J2", "J3", "J4", "P1", "P3")


def abrir_leitura(caminho: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{caminho or DB_LEITURA}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS achado_certame (
            certame TEXT, detector TEXT, orgao_cnpj TEXT,
            score REAL, status TEXT, motivo TEXT, explicacao_inocente TEXT,
            valores TEXT, evidencia TEXT, gerado_em TEXT,
            PRIMARY KEY (certame, detector)
        );
        CREATE INDEX IF NOT EXISTS ix_ach_cert_score ON achado_certame(score DESC);
        CREATE INDEX IF NOT EXISTS ix_ach_cert_org ON achado_certame(orgao_cnpj, status);
        CREATE TABLE IF NOT EXISTS certame_cobertura (
            certame TEXT PRIMARY KEY, orgao_cnpj TEXT, n_detectores INTEGER,
            n_avaliaveis INTEGER, n_confirmados INTEGER, n_nao_avaliaveis INTEGER,
            tem_edital INTEGER, tem_clausulas INTEGER, n_propostas INTEGER,
            score_max REAL, gerado_em TEXT
        );
    """)
    con.commit()


def abrir_achados(caminho: str | None = None) -> sqlite3.Connection:
    import pathlib
    alvo = pathlib.Path(caminho or DB_ACHADOS)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(alvo, timeout=60)
    init_schema(con)
    return con


def certames_com_resultado(con: sqlite3.Connection, *, ano: int | None = None,
                           orgao: str | None = None, limite: int | None = None) -> list[str]:
    """Certames que têm resultado homologado — só neles há o que julgar.

    Ordena pelo valor homologado do certame: quem fiscaliza começa pelo que pesa, não pela
    ordem alfabética.
    """
    sql = ["SELECT certame, SUM(COALESCE(valor_homologado,0)) v FROM pncp_resultado",
           "WHERE COALESCE(certame,'') <> ''"]
    par: list[Any] = []
    if ano:
        sql.append("AND substr(COALESCE(data_pub,''),1,4) = ?")
        par.append(str(ano))
    if orgao:
        sql.append("AND orgao_cnpj = ?")
        par.append(orgao)
    sql.append("GROUP BY certame ORDER BY v DESC")
    if limite:
        sql.append("LIMIT ?")
        par.append(limite)
    return [r["certame"] for r in con.execute(" ".join(sql), par)]


def _persistir(con: sqlite3.Connection, certame: str, orgao: str,
               resultados: list[ResultadoDetector]) -> None:
    agora = datetime.now().isoformat(timespec="seconds")
    con.executemany(
        "INSERT OR REPLACE INTO achado_certame VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(certame, r.detector, orgao, r.score, r.status,
          (r.motivo_refutacao or "")[:2000], (r.explicacao_inocente or "")[:1200],
          json.dumps(r.valores, ensure_ascii=False, default=str)[:8000],
          json.dumps(r.evidencia, ensure_ascii=False, default=str)[:8000], agora)
         for r in resultados])


def varrer_certame(con: sqlite3.Connection, certame: str, *, gerar: Callable | None = None,
                   con_achados: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Roda os detectores por certame sobre um certame. Devolve achados E cobertura."""
    ctx = montar_contexto(con, certame)
    if gerar is not None:
        ctx["gerar"] = gerar

    resultados: list[ResultadoDetector] = []
    for did in DETECTORES_CERTAME:
        det = REGISTRO.get(did)
        if det is None:
            continue
        try:
            resultados.append(det.avaliar(dict(ctx)))
        except Exception as e:  # noqa: BLE001 — um detector quebrado não derruba a varredura
            logger.warning("certame %s detector %s quebrou: %s", certame, did, str(e)[:120])

    nao_av = [r for r in resultados if r.status == "nao_avaliavel"]
    confirmados = [r for r in resultados if r.status == "confirmado"]
    resumo = {
        "certame": certame,
        "orgao_cnpj": ctx.get("orgao_cnpj") or "",
        "n_detectores": len(resultados),
        "n_avaliaveis": len(resultados) - len(nao_av),
        "n_confirmados": len(confirmados),
        "n_nao_avaliaveis": len(nao_av),
        "tem_edital": bool(ctx.get("tr_texto")),
        "tem_clausulas": bool(ctx.get("clausulas_edital")),
        "n_propostas": len(ctx.get("propostas") or []),
        "score_max": max((r.score for r in resultados), default=0.0),
        "achados": sorted(confirmados, key=lambda r: -r.score),
    }

    if con_achados is not None:
        _persistir(con_achados, certame, resumo["orgao_cnpj"], resultados)
        con_achados.execute(
            "INSERT OR REPLACE INTO certame_cobertura VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (certame, resumo["orgao_cnpj"], resumo["n_detectores"], resumo["n_avaliaveis"],
             resumo["n_confirmados"], resumo["n_nao_avaliaveis"], int(resumo["tem_edital"]),
             int(resumo["tem_clausulas"]), resumo["n_propostas"], resumo["score_max"],
             datetime.now().isoformat(timespec="seconds")))
        con_achados.commit()
    return resumo


def varrer_todos(con: sqlite3.Connection, *, ano: int | None = None, orgao: str | None = None,
                 limite: int | None = None, gerar: Callable | None = None,
                 con_achados: sqlite3.Connection | None = None,
                 log: Callable[[str], None] | None = None) -> dict[str, Any]:
    certames = certames_com_resultado(con, ano=ano, orgao=orgao, limite=limite)
    por_certame, total = [], 0
    for i, c in enumerate(certames, 1):
        r = varrer_certame(con, c, gerar=gerar, con_achados=con_achados)
        por_certame.append(r)
        total += r["n_confirmados"]
        if log and (i % 25 == 0 or r["n_confirmados"]):
            log(f"  [{i}/{len(certames)}] {c[:44]:46} achados={r['n_confirmados']} "
                f"avaliáveis={r['n_avaliaveis']}/{r['n_detectores']}")
    return {"n_certames": len(certames), "total_achados": total, "por_certame": por_certame}
