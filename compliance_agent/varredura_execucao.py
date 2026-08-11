# -*- coding: utf-8 -*-
"""Varredura da FASE DE EXECUÇÃO — a camada que estava pronta e nunca tinha rodado.

POR QUE ESTE MÓDULO EXISTE. `detectores.rodar_execucao` orquestra X1–X6 desde que a spec V2 foi
implementada: crescimento de aditivo (art. 125), prorrogação perpétua, tríade da despesa, carona
em ata, jogo de planilha e entrega fantasma. Os seis têm teste e passam. E, medido em 2026-07-29,
`achado_detector` tinha **zero** linhas de detector X — porque `rodar_execucao` não era chamado
por nada além dos próprios testes. `varredura_certames` roda E/J/P; `varredura_orgaos` roda
J1/P3/C6/C e declara que execução "exigiria contexto de certame que a varredura por UG não
possui"; `coletor_edital` para no julgamento. A fase de execução simplesmente não existia em
produção.

O QUE A BASE ALIMENTA, medido em 2026-07-29:

    pcrj_contratos     54.624 linhas   valor_inicial, valor_global, vigência, objeto, num_aditivos
    contrato_aditivo    1.728 linhas   valor_acrescido, prazo_aditado_dias, vigencia_fim, objeto

Isso alimenta X1 (teto do art. 125), X2 (prorrogação perpétua) e X7 (reequilíbrio indevido do
art. 124) com dado real. **Só esses três.** O X7 entra porque a classificação de natureza já
separa a recomposição do acréscimo, e três dos seus cinco testes — dupla correção no exercício,
magnitude e reiteração — rodam apenas com data e valor. Os outros dois (índice contratado,
existência de pleito) saem como lacuna DECLARADA, não como ausência de irregularidade.

O QUE FICA DE FORA, e por quê — a mesma regra de `varredura_certames`:

  · X3 (tríade empenho→liquidação→pagamento × atesto) pede os pagamentos DO CONTRATO. A base tem
    1.138.236 OBs, mas a ponte contrato↔OB não existe: `contrato_aditivo.numero_controle_pncp` é
    chave de CONTRATO ("-2-") e `pncp_resultado.certame` é chave de COMPRA ("-1-"), com zero
    casamentos hoje.
  · X4 (carona) pede itens e quantitativos da ata de registro de preços.
  · X5 (jogo de planilha) pede a planilha orçamentária item a item — não há tabela de itens de
    contrato na base.
  · X6 (entrega fantasma) pede atestos e medições.
  · X8 (aditivo retroativo) ENTROU em 2026-08-11. O bloqueio era real quando foi escrito —
    `contrato_aditivo` guardava só `vigencia_fim` e `coletado_em` — e CADUCOU em 2026-08-09, quando
    o coletor do PNCP passou a gravar `dataAssinatura`: hoje 1.684 dos 1.770 termos (95,1%) a têm.
    Ninguém releu o comentário, e o detector seguia fora por um motivo que já não existia. Medido ao
    ligar: **36 contratos de 1.099** têm termo assinado DEPOIS do fim da vigência corrente — entre
    eles um do MPRJ (R$ 3,62 mi) cujo 1º termo, de acréscimo quantitativo, foi assinado quatro dias
    após o contrato expirar. Aditar contrato extinto não é prorrogação.

Rodá-los aqui devolveria `nao_avaliavel` em massa, que não informa nada e ainda faz a cobertura
parecer maior do que é. Quando a ponte contrato↔OB existir (é item do plano), X3 entra aqui.

Lê a produção em SÓ-LEITURA e escreve em banco próprio (`data/achados.db`), como as outras
varreduras — não disputa lock com o servidor nem com o cron.

Uso:
    python -m compliance_agent.varredura_execucao --limite 200
    python -m compliance_agent.varredura_execucao --orgao 00000000000191 --gravar
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
from compliance_agent.varredura_execucao_ctx import montar_contexto

logger = logging.getLogger(__name__)

DB_LEITURA = os.environ.get("JFN_DB", "data/compliance.db")
DB_ACHADOS = os.environ.get("JFN_DB_ACHADOS", "data/achados.db")

# Manter esta lista curta e honesta é o ponto — ver o cabeçalho.
DETECTORES_EXECUCAO = ("X1", "X2", "X7", "X8")


def abrir_leitura(caminho: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{caminho or DB_LEITURA}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS achado_execucao (
            contrato TEXT, detector TEXT, orgao_cnpj TEXT, fornecedor TEXT,
            score REAL, status TEXT, motivo TEXT, explicacao_inocente TEXT,
            valores TEXT, evidencia TEXT, gerado_em TEXT,
            PRIMARY KEY (contrato, detector)
        );
        CREATE INDEX IF NOT EXISTS ix_ach_exec_score ON achado_execucao(score DESC);
        CREATE INDEX IF NOT EXISTS ix_ach_exec_org ON achado_execucao(orgao_cnpj, status);
        CREATE TABLE IF NOT EXISTS execucao_cobertura (
            contrato TEXT PRIMARY KEY, orgao_cnpj TEXT, n_detectores INTEGER,
            n_avaliaveis INTEGER, n_confirmados INTEGER, n_nao_avaliaveis INTEGER,
            tem_valor_inicial INTEGER, n_aditivos INTEGER, n_prorrogacoes INTEGER,
            lacunas TEXT, score_max REAL, gerado_em TEXT
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


def contratos_com_aditivo(con: sqlite3.Connection, *, ano: int | None = None,
                          orgao: str | None = None, limite: int | None = None) -> list[str]:
    """Contratos que têm ao menos um termo aditivo coletado — só neles há o que julgar na X1/X2.

    Ordena pelo valor global: quem fiscaliza começa pelo que pesa.
    """
    sql = ["SELECT c.numero_controle_pncp AS k, COALESCE(c.valor_global, c.valor_inicial, 0) v",
           "FROM pcrj_contratos c",
           "WHERE EXISTS (SELECT 1 FROM contrato_aditivo a",
           "              WHERE a.numero_controle_pncp = c.numero_controle_pncp)"]
    par: list[Any] = []
    if ano:
        sql.append("AND c.ano = ?")
        par.append(int(ano))
    if orgao:
        sql.append("AND c.orgao_cnpj = ?")
        par.append(orgao)
    sql.append("ORDER BY v DESC")
    if limite:
        sql.append("LIMIT ?")
        par.append(int(limite))
    return [r["k"] for r in con.execute(" ".join(sql), par)]


def _persistir(con: sqlite3.Connection, contrato: str, ctx: dict,
               resultados: list[ResultadoDetector]) -> None:
    agora = datetime.now().isoformat(timespec="seconds")
    con.executemany(
        "INSERT OR REPLACE INTO achado_execucao VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(contrato, r.detector, ctx.get("orgao_cnpj") or "",
          ctx.get("fornecedor_documento") or "", r.score, r.status,
          (r.motivo_refutacao or "")[:2000], (r.explicacao_inocente or "")[:1200],
          json.dumps(r.valores, ensure_ascii=False, default=str)[:8000],
          json.dumps(r.evidencia, ensure_ascii=False, default=str)[:8000], agora)
         for r in resultados])


def varrer_contrato(con: sqlite3.Connection, contrato: str, *, gerar: Callable | None = None,
                    con_achados: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Roda os detectores de execução sobre um contrato. Devolve achados E cobertura.

    Cobertura junto com achado é regra da casa: contrato sem achado pode ser contrato regular ou
    contrato sem dado, e para quem fiscaliza são coisas opostas.
    """
    ctx = montar_contexto(con, contrato)
    if gerar is not None:
        ctx["gerar"] = gerar

    resultados: list[ResultadoDetector] = []
    for did in DETECTORES_EXECUCAO:
        det = REGISTRO.get(did)
        if det is None:
            continue
        try:
            resultados.append(det.avaliar(dict(ctx)))
        except Exception as e:  # noqa: BLE001 — um detector quebrado não derruba a varredura
            logger.warning("contrato %s detector %s quebrou: %s", contrato, did, str(e)[:120])

    nao_av = [r for r in resultados if r.status == "nao_avaliavel"]
    confirmados = [r for r in resultados if r.status == "confirmado"]
    resumo = {
        "contrato": contrato,
        "orgao_cnpj": ctx.get("orgao_cnpj") or "",
        "n_detectores": len(resultados),
        "n_avaliaveis": len(resultados) - len(nao_av),
        "n_confirmados": len(confirmados),
        "n_nao_avaliaveis": len(nao_av),
        "tem_valor_inicial": ctx.get("valor_inicial") is not None,
        "n_aditivos": ctx.get("n_aditivos", 0),
        "n_prorrogacoes": len(ctx.get("prorrogacoes") or []),
        "lacunas": list(ctx.get("lacunas") or []),
        "score_max": max((r.score for r in resultados), default=0.0),
        "achados": sorted(confirmados, key=lambda r: -r.score),
        "todos": resultados,
    }

    if con_achados is not None:
        _persistir(con_achados, contrato, ctx, resultados)
        con_achados.execute(
            "INSERT OR REPLACE INTO execucao_cobertura VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (contrato, resumo["orgao_cnpj"], resumo["n_detectores"], resumo["n_avaliaveis"],
             resumo["n_confirmados"], resumo["n_nao_avaliaveis"],
             int(resumo["tem_valor_inicial"]), resumo["n_aditivos"], resumo["n_prorrogacoes"],
             json.dumps(resumo["lacunas"], ensure_ascii=False), resumo["score_max"],
             datetime.now().isoformat(timespec="seconds")))
        con_achados.commit()
    return resumo


def varrer_todos(con: sqlite3.Connection, *, ano: int | None = None, orgao: str | None = None,
                 limite: int | None = None, gerar: Callable | None = None,
                 con_achados: sqlite3.Connection | None = None,
                 log: Callable[[str], None] | None = None) -> dict[str, Any]:
    contratos = contratos_com_aditivo(con, ano=ano, orgao=orgao, limite=limite)
    por_contrato, total = [], 0
    for i, c in enumerate(contratos, 1):
        r = varrer_contrato(con, c, gerar=gerar, con_achados=con_achados)
        por_contrato.append(r)
        total += r["n_confirmados"]
        if log and (i % 25 == 0 or r["n_confirmados"]):
            log(f"  [{i}/{len(contratos)}] {c[:44]:46} achados={r['n_confirmados']} "
                f"avaliáveis={r['n_avaliaveis']}/{r['n_detectores']} aditivos={r['n_aditivos']}")
    sem_valor = sum(1 for r in por_contrato if not r["tem_valor_inicial"])
    return {"n_contratos": len(contratos), "total_achados": total,
            "sem_valor_inicial": sem_valor, "por_contrato": por_contrato}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Varredura da fase de execução contratual (X1, X2)")
    ap.add_argument("--ano", type=int)
    ap.add_argument("--orgao")
    ap.add_argument("--limite", type=int)
    ap.add_argument("--gravar", action="store_true", help="persiste em data/achados.db")
    a = ap.parse_args(argv)

    con = abrir_leitura()
    achados = abrir_achados() if a.gravar else None
    r = varrer_todos(con, ano=a.ano, orgao=a.orgao, limite=a.limite,
                     con_achados=achados, log=print)
    print(f"\ncontratos varridos: {r['n_contratos']} · achados: {r['total_achados']} · "
          f"sem valor_inicial (não aferível pelo art. 125): {r['sem_valor_inicial']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
