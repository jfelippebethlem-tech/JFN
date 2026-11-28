# -*- coding: utf-8 -*-
"""Semeador do backlog do E2 (O9.0, 25/11/2026): processos SEI-RJ com OB paga e SEM árvore viram jobs
`arvore:<processo>` do estágio nativo, na PRIORIDADE ÚNICA, com teto por ciclo.

Por que existe: o `sweep_sei` (desligado na religação, `substituida_por: E2`) varria o backlog da fila antiga; o E2
nativo só nasce de evento (`coleta/ob_nova` do e1_eventos, citado, reabertura). Sem este passo, processo com OB paga
que nunca teve árvore ficaria sem entrada.

Ordem: a de `aplicacao/estagios/arvore.fila` = `fluxo/prioridade.ordenar` (plano §3.7 + §16.3): urgente do dono,
os degraus do sei_sweep (legível/à mão/direta grande/lacuna/OSINT/folha por último), o ESCALAR de valor da OB paga do
SIAFE (`ob_paga_sql`, nunca empenho) + bônus de lente, desempate por valor, risco e idade; a cota Couto de 50% é
RESERVA intercalada (`foco.intercalar`), nunca peso. Nunca a posição na árvore nem a ordem/score do arquivo antigo:
as filas antigas (`data/sei_fila_*.json`, `data/bombeiros_sei_fila.json`) só entram como fonte do nº do processo.

Universo semeável = processo com OB paga > 0 OU presente numa fila antiga; fora: quem já tem leitura de árvore
(`arvore_leitura`) ou árvore legada carregada no PG (`arvores`, O3.1) e quem já tem job `arvore:` em qualquer estado (idempotência pela chave; `fila.enfileirar` também
não duplica). Teto por ciclo (`--teto`). Cada job leva `payload.prioridade` = os componentes (`prioridade.explicar`)
e a posição na ordem.

Só LÊ o compliance.db (mode=ro, sem immutable: o banco é vivo) e o PG.

    python -m tools.e2_semear [--teto 40] [--ensaio] [--mostrar 20]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DB = RAIZ / "data" / "compliance.db"
FILAS_ANTIGAS = ("sei_fila_dinheiro.json", "sei_fila_vinculo_ob.json", "bombeiros_sei_fila.json",
                 "sei_fila_licitacao.json")   # 27/11: processo da licitação citado (tools/e2_licitacao_relacionada)
TETO = 40
CORRELACAO = "e2_semear"


def filas_antigas(pasta: Path = RAIZ / "data") -> dict[str, set[str]]:
    """Nº de processo das filas antigas (fonte do nº; a ordem delas não vale). Ausente = fonte vazia declarada."""
    out = {}
    for nome in FILAS_ANTIGAS:
        p = pasta / nome
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            out[f"fila_antiga:{nome}"] = set()
            continue
        out[f"fila_antiga:{nome}"] = {str(x.get("sei") or "") for x in d if isinstance(x, dict) and x.get("sei")}
    return out


DIAS_RECONFERIR_RESTRITO = 90        # a mesma janela do sei_sweep (_DIAS_RECONFERIR_RESTRITO): a marca expira


def restritos_confirmados(pasta: Path = None, agora: datetime | None = None) -> set[str]:
    """Processos com RESTRITO **confirmado** (duas leituras 0-doc de processo que existe) visto há menos de 90 dias, no
    registro do sei_sweep (data/sei_restritos.json) — regra portada (26/11/2026: na religação 14 de ~30 árvores
    semeadas eram restritas). `RESTRITO?` (uma leitura só) volta à fila; registro ilegível = nenhum excluído."""
    from compliance_agent.dominio import processo_id as PI
    agora = agora or datetime.now()
    try:
        reg = json.loads(((pasta or RAIZ / "data") / "sei_restritos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    out = set()
    for e in reg.values() if isinstance(reg, dict) else []:
        if not isinstance(e, dict) or e.get("status") != "RESTRITO":
            continue
        try:
            visto = datetime.fromisoformat(str(e.get("ultima") or "").replace(" ", "T"))
        except ValueError:
            continue
        k = PI.chave_processo(str(e.get("numero") or ""))
        if k and (agora - visto).days < DIAS_RECONFERIR_RESTRITO:
            out.add(k)
    return out


def ja_tem(con_pg) -> set[str]:
    """Processos com leitura de árvore OU com job `arvore:` (qualquer estado). Tabela ausente = vazio declarado."""
    out: set[str] = set()
    if con_pg is None:
        return out
    for t in ("public.arvore_leitura", "public.arvores"):     # leitura do E2 nativo e árvore legada (carga O3.1)
        if con_pg.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0]:
            out |= {r[0] for r in con_pg.execute(f"SELECT DISTINCT processo FROM {t}")}
    if con_pg.execute("SELECT to_regclass('fluxo.jobs')").fetchone()[0]:
        out |= {r[0].split(":", 1)[1] for r in con_pg.execute("SELECT chave FROM fluxo.jobs WHERE tipo = 'arvore'")}
    return out


def selecionar(fonte: sqlite3.Connection, excluir: set[str], teto: int, extras: dict[str, set[str]],
               lentes_res: dict | None = None, fila=None) -> list[tuple]:
    """[(item, explicar, posição)] — os `teto` primeiros semeáveis na ordem única."""
    from compliance_agent.aplicacao.estagios import arvore as A
    if lentes_res is None:
        from compliance_agent.fluxo import lentes as L
        lentes_res, _ = L.resolver(L.carregar(), fonte)
    antigas = set().union(*(v for k, v in extras.items() if k.startswith("fila_antiga:"))) if extras else set()
    from compliance_agent.dominio import processo_id as PI
    antigas = {PI.chave_processo(p) for p in antigas} - {None, ""}
    out = []
    for pos, (it, e) in enumerate((fila or A.fila)(fonte, lentes_res, None, extras=extras), start=1):
        if it.processo in excluir or not (it.ob_paga > 0 or it.processo in antigas):
            continue
        out.append((it, e, pos))
        if len(out) >= teto:
            break
    return out


def semear(con_fluxo, g, escolhidos: list[tuple]) -> dict:
    """Enfileira `arvore:<processo>` com o contrato do estágio nativo E2. Idempotente pela chave."""
    from compliance_agent.fluxo import fila
    c = g.contrato_do_estagio("E2")
    base = g.payload_do_estagio("E2")
    novos = 0
    for it, e, pos in escolhidos:
        p = {**base, "processo": it.processo, "prioridade": {**e, "posicao": pos}, "origem": CORRELACAO}
        if fila.enfileirar(con_fluxo, "arvore", f"arvore:{it.processo}", p, prioridade=c["prioridade"],
                           recursos=c["recursos"], volta=c["volta"], no_preferido=c["no_preferido"],
                           correlation_id=CORRELACAO) is not None:
            novos += 1
    return {"escolhidos": len(escolhidos), "novos": novos}


def _motivo(e: dict) -> str:
    s = e.get("sinais") or {}
    partes = [f"OB paga R$ {s.get('ob_paga', 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")]
    partes += [n for n in ("manual", "legivel", "lacuna_provada", "osint", "couto") if s.get(n)]
    if e.get("direta_grande"):
        partes.append("direta_grande")
    if s.get("folha"):
        partes.append("folha(rebaixada)")
    if s.get("lente"):
        partes.append(f"lente {s['lente']} (+{e.get('bonus_lente', 0)})")
    return "; ".join(partes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.e2_semear")
    ap.add_argument("--teto", type=int, default=TETO)
    ap.add_argument("--ensaio", action="store_true", help="só mostra os escolhidos com o motivo; não grava")
    ap.add_argument("--mostrar", type=int, default=20)
    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args(argv)
    from compliance_agent.aplicacao.estagios import arvore as A
    from compliance_agent.evidencias import dsn_vigente
    from compliance_agent.fluxo import grafo as G
    fonte = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    pg = None
    try:
        if dsn_vigente():
            from compliance_agent.fluxo import schema
            pg = schema.conectar_leitura(dsn_vigente())
        extras = {**A.extras_locais(None), **filas_antigas()}
        if pg is not None and pg.execute("SELECT to_regclass('public.processos')").fetchone()[0]:
            extras["identidade_pg"] = {r[0] for r in pg.execute("SELECT processo FROM public.processos")}
        restritos = restritos_confirmados()
        excluir = ja_tem(pg) | restritos
        escolhidos = selecionar(fonte, excluir, a.teto, extras)
    finally:
        fonte.close()
        if pg is not None:
            pg.close()
    for it, e, pos in escolhidos[: a.mostrar]:
        print(f"  #{pos:>6}  {it.processo:<28} {_motivo(e)}")
    if a.ensaio:
        print(f"e2_semear: ENSAIO — {len(escolhidos)} escolhido(s) (teto {a.teto}), {len(excluir)} já com árvore/job; "
              "nada gravado")
        return 0
    from compliance_agent.fluxo import fila
    con = fila.conectar()
    try:
        r = semear(con, G.carregar(), escolhidos)
    finally:
        con.close()
    print(f"e2_semear: semeados {r['novos']} de {r['escolhidos']} (teto {a.teto})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
