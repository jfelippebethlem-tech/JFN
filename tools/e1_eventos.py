# -*- coding: utf-8 -*-
"""E1 → estágios nativos: os eventos `coleta/*` que a coleta LEGADA não emite (O9.0, 25/11/2026).

Achado da preparação da religação: as rotas nativas do config/fluxo.yaml (`nativos.rotas`) começam em
`coleta/ob_nova` (→ E2 árvore), `coleta/fonte_mudou` (→ E9 elegibilidade e E15 siafe_stats) e `coleta/conferidos`
(→ E13), mas em produção só o ensaio O8.5 (`tools/ensaio_o85.py`, replay) os emitia — os coletores do E1 são legados
e a ponte da propagação entrega `siafe_ob/mudou` sem processo. Com as portas legadas do SEI desligadas na religação
(sweep_sei e cia. `substituida_por: E2`), sem este passo o E2 nativo não teria entrada. Este é o E1 → nativo:

  · `coleta/ob_nova` (chave = processo SEI-RJ canônico): OB EMITIDA nova no SIAFE. "Nova" = número da OB acima do
    maior já visto na mesma (UG emitente, exercício) — a recoleta diária regrava `coletado_em` de todas as OB
    (medido 25/11: 39.482 processos "coletados" em 5 dias contra 3.847 com OB emitida na semana), então a data de
    coleta NÃO serve. Primeira rodada sem marca: com `desde` (job da religação, `JFN_DESDE`) = OB com
    `data_emissao` (texto DD/MM/AAAA) ≥ desde; sem `desde` = só grava a marca (o histórico não vira rajada);
  · `coleta/fonte_mudou` (chave = unidade do E9): a assinatura (linhas, maior carimbo de coleta) da tabela mudou;
  · `coleta/conferidos` (chave `alertas_triagem`): a triagem/Opus gravou veredito novo.

Só LÊ o compliance.db (mode=ro). Grava os eventos no `fluxo.eventos` numa transação e SÓ DEPOIS a marca
(`data/e1_eventos_marca.json`): queda no meio reemite — o evento repetido cai no mesmo job (chave do dependente).

    python -m tools.e1_eventos [--desde AAAA-MM-DD] [--ensaio]      # --ensaio: conta e imprime, não grava nada
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DB = RAIZ / "data" / "compliance.db"
MARCA = RAIZ / "data" / "e1_eventos_marca.json"
ENV_DESDE = "JFN_DESDE"                     # o mesmo do estágio legado (aplicacao/estagios/legado.py)
OB = "ob_orcamentaria_siafe"
# tabela → (expressão do carimbo de coleta, unidade do E9). Carimbo normalizado: 'T' e ' ' misturados nas tabelas
# (memória timestamp-iso-com-T-quebra-comparacao) — compara-se a assinatura, nunca o texto cru entre tabelas.
TABELAS = {OB: ("coletado_em", "ob_siafe"),
           "ordens_bancarias": ("coalesce(coletado_em, updated_at, created_at)", "ob_tfe"),
           "contratos_tcerj": ("ingerido_em", "contrato_tcerj"),
           "compras_diretas_tcerj": ("ingerido_em", "compra_direta_tcerj"),
           "siga_contratos": ("visto_em", "contrato_siga")}
CONFERIDOS = ("alertas_triagem", "em")
# o que este passo emite (tools/religar_o90.py confere que toda rota nativa de entrada tem produtor)
EMITE = ("coleta/ob_nova", "coleta/fonte_mudou", "coleta/conferidos")
_NUM = "CAST(substr(numero_ob, 7, 5) AS INTEGER)"          # '2026OB00553' → 553 ('…P' de complemento: mesmo nº)


def _norm(expr: str) -> str:
    return f"substr(replace({expr}, 'T', ' '), 1, 19)"


def _tem(con: sqlite3.Connection, t: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is not None


def assinatura(con: sqlite3.Connection, t: str, expr: str) -> list:
    n, mx = con.execute(f'SELECT count(*), max({_norm(expr)}) FROM "{t}"').fetchone()
    return [n, mx]


def maiores_ob(con: sqlite3.Connection) -> dict[str, int]:
    """(UG emitente|exercício) → maior número de OB visto."""
    return {f"{ug}|{ex}": int(n or 0) for ug, ex, n in con.execute(
        f"SELECT ug_emitente, exercicio, max({_NUM}) FROM {OB} WHERE numero_ob LIKE '____OB%' "
        "GROUP BY ug_emitente, exercicio")}


def _iso_desde(desde: str) -> str:
    d = desde.strip()[:10]
    if len(d) != 10 or d[4] != "-" or d[7] != "-":
        raise ValueError(f"desde tem de ser AAAA-MM-DD: {desde!r}")
    return d.replace("-", "")


def ob_novas(con: sqlite3.Connection, marca: dict | None, desde: str | None) -> set[str]:
    """Processos SEI-RJ (chave canônica) com OB emitida nova desde a marca (ou desde `desde`, sem marca)."""
    from compliance_agent.dominio import processo_id as PI
    if marca and marca.get("ob_maiores") is not None:
        vistos = marca["ob_maiores"]
        linhas = ((ug, ex, n, p) for ug, ex, n, p in con.execute(
            f"SELECT ug_emitente, exercicio, {_NUM}, processo FROM {OB} WHERE numero_ob LIKE '____OB%'")
                  if int(n or 0) > int(vistos.get(f"{ug}|{ex}", 0)))
        brutos = {p for *_r, p in linhas}
    elif desde:
        brutos = {p for (p,) in con.execute(
            f"SELECT DISTINCT processo FROM {OB} WHERE substr(data_emissao, 7, 4) || substr(data_emissao, 4, 2) || "
            "substr(data_emissao, 1, 2) >= ?", (_iso_desde(desde),))}
    else:
        return set()
    return {k for k in (PI.chave_processo(p or "") for p in brutos) if k}


def calcular(con: sqlite3.Connection, marca: dict | None, desde: str | None) -> tuple[list[tuple], dict]:
    """(eventos [(fonte, tipo, chave)], marca nova). Pura sobre a conexão só-leitura."""
    eventos: list[tuple] = [("coleta", "ob_nova", p) for p in sorted(ob_novas(con, marca, desde))] if _tem(con, OB) \
        else []
    nova = {"ob_maiores": maiores_ob(con) if _tem(con, OB) else {}, "assinaturas": {}}
    antes = (marca or {}).get("assinaturas") or {}
    for t, (expr, unidade) in TABELAS.items():
        if not _tem(con, t):
            continue
        a = assinatura(con, t, expr)
        nova["assinaturas"][t] = a
        if (marca is not None and antes.get(t) != a) or (marca is None and desde):
            eventos.append(("coleta", "fonte_mudou", unidade))
    t, col = CONFERIDOS
    if _tem(con, t):
        a = assinatura(con, t, col)
        nova["assinaturas"][t] = a
        if (marca is not None and antes.get(t) != a) or (marca is None and desde):
            eventos.append(("coleta", "conferidos", t))
    return eventos, nova


def ler_marca(caminho: Path = MARCA) -> dict | None:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def rodar(db: Path = DB, marca_arq: Path = MARCA, desde: str | None = None, ensaio: bool = False,
          con_fluxo=None) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        marca = ler_marca(marca_arq)
        eventos, nova = calcular(con, marca, desde)
    finally:
        con.close()
    contagem: dict[str, int] = {}
    for f, t, _k in eventos:
        contagem[f"{f}/{t}"] = contagem.get(f"{f}/{t}", 0) + 1
    if ensaio:
        return {"ensaio": True, "primeira": marca is None, "eventos": contagem}
    if eventos:
        from compliance_agent.fluxo import fila
        proprio = con_fluxo is None
        c = con_fluxo or fila.conectar()
        try:
            with c.transaction():
                for f, t, k in eventos:
                    fila.emitir(c, f, t, k, {"origem": "e1_eventos", **({"desde": desde} if desde else {})})
        finally:
            if proprio:
                c.close()
    tmp = marca_arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(nova, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(marca_arq)                       # só depois do PG: queda no meio reemite (mesma chave de job)
    return {"primeira": marca is None, "eventos": contagem}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.e1_eventos")
    ap.add_argument("--desde", default=os.environ.get(ENV_DESDE) or None)
    ap.add_argument("--ensaio", action="store_true")
    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args(argv)
    r = rodar(Path(a.db), desde=a.desde, ensaio=a.ensaio)
    n = sum(r["eventos"].values())
    print(f"e1_eventos: {'emitidos ' + str(n) if n else 'sem novidade'} {json.dumps(r, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
