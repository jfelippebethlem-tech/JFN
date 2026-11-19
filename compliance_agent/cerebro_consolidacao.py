# -*- coding: utf-8 -*-
"""Consolidação noturna do segundo cérebro — FILA + TETO (docs/ARQUITETURA-SEGUNDO-CEREBRO-ALVO.md §5.5).

Decisão do dono (19/11/2026): a consolidação roda de madrugada, pela ASSINATURA do Claude, no máximo 50 chamadas por
noite; o modelo SÓ PROPÕE, numa fila de revisão; nunca API paga.

O que faz, em ordem:
  1. COLHER (sem modelo): pede ao jfn-brain os pares de memórias ATIVAS muito parecidas, fora das séries geradas
     (`/api/consolidacao/pares`), e põe na fila o que é novo. Mesmo par nunca entra duas vezes.
  2. PROPOR (assinatura, com teto): para cada par aberto, do mais parecido para o menos, pergunta ao Claude se é o
     MESMO FATO dito duas vezes, uma CONTRADIÇÃO (mesmo fato, número ou data diferente) ou fatos DISTINTOS. Mesmo fato
     e contradição viram PROPOSTA (status 'proposta' no cérebro — fora do recall — e linha na fila); distintos fecha.
  3. Nada é fundido, corrigido ou apagado aqui. Aceitar é ato de gente: `aceitar <id>` / `recusar <id>`.

Tetos (os três valem ao mesmo tempo; o que estourar primeiro para a rodada e o resto fica para a noite seguinte):
  · 50 chamadas por noite (`JFN_CONSOLIDACAO_MAX`) — e o teto por tarefa do motor (`JFN_CLAUDE_MAX_CEREBRO_CONSOLIDACAO`);
  · 900 s de assinatura por noite (`JFN_CONSOLIDACAO_MAX_S`) — 6% do orçamento diário do motor (14.400 s);
  · reserva: não começa uma chamada se sobrarem menos de 1.800 s no orçamento do dia (`JFN_CONSOLIDACAO_RESERVA_S`)
    — medido em 19/11/2026: a perícia integral gasta ~3.000 s por hora desde 00h e esgota o dia por volta das 05h;
    a consolidação é a primeira a ceder.
Só `backend="cli"`: se a assinatura não puder, a rodada PARA (não cai na API paga, não cai na cascata).

    python -m compliance_agent.cerebro_consolidacao noite          # colher + propor (o que o cron chama)
    python -m compliance_agent.cerebro_consolidacao colher         # só a parte sem modelo
    python -m compliance_agent.cerebro_consolidacao fila [--estado proposto]
    python -m compliance_agent.cerebro_consolidacao aceitar <id> | recusar <id> ["motivo"]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

from compliance_agent import cerebro_compartilhado as cerebro

TAREFA = "cerebro_consolidacao"
MAX_CHAMADAS = 50
MAX_SEGUNDOS = 900
RESERVA_S = 1800
SIM_MINIMA = 0.90

DDL = """CREATE TABLE IF NOT EXISTS fila(
  id INTEGER PRIMARY KEY AUTOINCREMENT, a INTEGER NOT NULL, b INTEGER NOT NULL, sim REAL,
  a_texto TEXT, b_texto TEXT, a_chave TEXT, b_chave TEXT, kind TEXT, assunto TEXT,
  estado TEXT NOT NULL DEFAULT 'aberto',      -- aberto | proposto | distintos | aceito | recusado
  veredito TEXT, proposta TEXT, motivo TEXT, modelo TEXT, mem_proposta INTEGER,
  criado_em REAL, proposto_em REAL, decidido_em REAL, decisao_motivo TEXT, UNIQUE(a, b))"""

SISTEMA = ("Você compara dois registros de memória de um sistema de auditoria pública. Responda em português do "
           "Brasil. Nunca invente fato, número, data ou nome que não esteja em um dos dois registros.")

PROMPT = """Dois registros de memória do mesmo cérebro, gravados em datas diferentes.

REGISTRO A (#{a}, {a_data}):
{a_texto}

REGISTRO B (#{b}, {b_data}):
{b_texto}

Classifique:
- "mesmo_fato": dizem a mesma coisa (um pode ser mais completo). Em `texto`, escreva UM registro que preserve tudo o
  que os dois afirmam, sem acrescentar nada.
- "contradicao": tratam do mesmo fato mas divergem em número, data, nome ou conclusão. Em `texto`, diga exatamente o
  que diverge (cite os dois valores). NÃO escolha qual está certo.
- "distintos": são fatos diferentes, ainda que parecidos. `texto` vazio.
Em `motivo`, uma frase."""

ESQUEMA = {"veredito": "mesmo_fato | contradicao | distintos", "texto": "", "motivo": ""}


def _int(nome: str, padrao: int) -> int:
    try:
        return int(os.environ.get(nome, "") or padrao)
    except ValueError:
        return padrao


def _con(db: Path | None = None) -> sqlite3.Connection:
    alvo = db or cerebro.DATA / "cerebro_consolidacao" / "fila.db"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(alvo, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute(DDL)
    return con


def colher(con: sqlite3.Connection, pares: list[dict] | None = None) -> dict:
    """Põe na fila os pares novos. `pares` injetável (teste); padrão = o que o cérebro devolve."""
    if pares is None:
        pares = cerebro._http(f"/api/consolidacao/pares?minimo={SIM_MINIMA}&limite=300")
    novos = 0
    for p in pares:
        a, b = p["a"], p["b"]
        cur = con.execute(
            "INSERT OR IGNORE INTO fila(a,b,sim,a_texto,b_texto,a_chave,b_chave,kind,assunto,criado_em) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (a["id"], b["id"], p["sim"], f"[{a['created_at'][:10]}] {a['content']}", f"[{b['created_at'][:10]}] {b['content']}",
             a.get("chave"), b.get("chave"), a.get("kind"), a.get("subject"), time.time()))
        novos += cur.rowcount
    con.commit()
    return {"pares_no_cerebro": len(pares), "novos_na_fila": novos}


def _folga_do_motor() -> tuple[float, str | None]:
    """(segundos que sobram no orçamento diário da assinatura, motivo para NÃO chamar agora ou None)."""
    from compliance_agent.llm import claude_motor
    uso = claude_motor.ler_uso()
    sobra = claude_motor.teto_segundos() - float(uso["total"]["segundos"])
    return sobra, claude_motor.motivo_desligado(tarefa=TAREFA)


def propor(con: sqlite3.Connection, *, pensar=None, folga=None, registrar_proposta=None) -> dict:
    """Pede a proposta ao Claude da ASSINATURA para os pares abertos, dentro dos três tetos. `pensar`, `folga` e
    `registrar_proposta` são injetáveis (teste)."""
    from compliance_agent.llm import claude_motor
    pensar = pensar or claude_motor.pensar
    folga = folga or _folga_do_motor
    registrar_proposta = registrar_proposta or _proposta_no_cerebro
    max_n, max_s, reserva = (_int("JFN_CONSOLIDACAO_MAX", MAX_CHAMADAS), _int("JFN_CONSOLIDACAO_MAX_S", MAX_SEGUNDOS),
                             _int("JFN_CONSOLIDACAO_RESERVA_S", RESERVA_S))
    r = {"chamadas": 0, "segundos": 0.0, "propostas": 0, "distintos": 0, "parou_por": None}
    ocupado = 0
    for it in con.execute("SELECT * FROM fila WHERE estado='aberto' ORDER BY sim DESC, id").fetchall():
        if r["chamadas"] >= max_n:
            r["parou_por"] = f"teto de {max_n} chamadas por noite"
            break
        if r["segundos"] >= max_s:
            r["parou_por"] = f"teto de {max_s} s de assinatura por noite"
            break
        sobra, motivo = folga()
        if motivo or sobra < reserva:
            r["parou_por"] = motivo or f"reserva: sobram {sobra:.0f} s no orçamento do dia (mínimo {reserva})"
            break
        p = pensar(TAREFA, PROMPT.format(a=it["a"], b=it["b"], a_data=it["a_texto"][1:11], b_data=it["b_texto"][1:11],
                                         a_texto=it["a_texto"][13:], b_texto=it["b_texto"][13:]),
                   schema=ESQUEMA, modelo=claude_motor.MODELO_VOLUME, sistema=SISTEMA, timeout=120.0, espera=150.0,
                   backend="cli")
        if p is None:                                # assinatura não pôde: PARA — nunca API paga, nunca cascata
            motivo = claude_motor.ultimo_motivo or "sem motivo informado"
            if "ocupado" in motivo and ocupado < 2:  # outra tarefa segurando a assinatura: cede a vez e tenta o próximo
                ocupado += 1
                continue
            r["parou_por"] = f"assinatura indisponível: {motivo}"
            break
        ocupado = 0
        if str(p.modelo).endswith("@api"):           # cinto e suspensório: resposta que não veio da assinatura é descartada
            r["parou_por"] = "resposta veio da API paga — descartada"
            break
        r["chamadas"] += 1
        r["segundos"] += float(p.segundos or 0)
        d = p.dados if isinstance(p.dados, dict) else {}
        veredito = str(d.get("veredito") or "").strip().lower()
        if veredito not in ("mesmo_fato", "contradicao", "distintos"):
            con.execute("UPDATE fila SET motivo=?, modelo=? WHERE id=?", ("resposta fora do formato", p.modelo, it["id"]))
            con.commit()
            continue
        if veredito == "distintos":
            con.execute("UPDATE fila SET estado='distintos', veredito=?, motivo=?, modelo=?, proposto_em=? WHERE id=?",
                        (veredito, str(d.get("motivo") or "")[:500], p.modelo, time.time(), it["id"]))
            r["distintos"] += 1
        else:
            texto = " ".join(str(d.get("texto") or "").split())[:cerebro.MAX_CHARS]
            mem = registrar_proposta(it, veredito, texto)
            con.execute("UPDATE fila SET estado='proposto', veredito=?, proposta=?, motivo=?, modelo=?, mem_proposta=?, "
                        "proposto_em=? WHERE id=?",
                        (veredito, texto, str(d.get("motivo") or "")[:500], p.modelo, mem, time.time(), it["id"]))
            r["propostas"] += 1
        con.commit()
    r["segundos"] = round(r["segundos"], 1)
    return r


def _proposta_no_cerebro(it, veredito: str, texto: str) -> int | None:
    """Grava a proposta no cérebro com status 'proposta' (fora do recall; visível em /api/proposals). Texto que o
    cliente recusaria (CPF, e-mail, segredo) não sai da máquina: a proposta fica só na fila local."""
    rotulo = "MESMO FATO" if veredito == "mesmo_fato" else "CONTRADIÇÃO A CONFERIR"
    conteudo = f"PROPOSTA DE CONSOLIDAÇÃO ({rotulo}; memórias #{it['a']} e #{it['b']}; não validada): {texto}"[:cerebro.MAX_CHARS]
    if cerebro.recusar(conteudo):
        return None
    try:
        resp = cerebro._http("/api/memories", {"content": conteudo, "kind": it["kind"] or "semantica",
                                               "subject": it["assunto"], "source": "consolidacao-claude-vm1",
                                               "confidence": 0.5, "tags": ["consolidacao", veredito], "proposta": True})
        return int(resp["id"])
    except (cerebro.CerebroIndisponivel, KeyError, TypeError, ValueError):
        return None


def decidir(con: sqlite3.Connection, item: int, aceitar: bool, motivo: str = "") -> dict:
    """Decisão de GENTE sobre uma proposta. Aceitar um 'mesmo_fato' grava o texto proposto como versão nova de A
    (a anterior fica no histórico) e deixa B indicada para revogação; contradição aceita só fica registrada."""
    it = con.execute("SELECT * FROM fila WHERE id=?", (item,)).fetchone()
    if not it or it["estado"] != "proposto":
        return {"erro": f"item {item} não está 'proposto'"}
    aplicado = None
    if aceitar and it["veredito"] == "mesmo_fato" and it["proposta"]:
        if cerebro.recusar(it["proposta"]):
            return {"erro": "o texto proposto tem dado que não pode ir ao cérebro"}
        aplicado = cerebro._http("/api/memories", {
            "content": it["proposta"], "kind": it["kind"] or "semantica", "subject": it["assunto"],
            "source": cerebro.FONTE, "confidence": 0.9, "supersedes": it["a"], "chave": it["a_chave"],
            "tags": ["consolidacao", "aceita"]})
    con.execute("UPDATE fila SET estado=?, decidido_em=?, decisao_motivo=? WHERE id=?",
                ("aceito" if aceitar else "recusado", time.time(), motivo[:500], item))
    con.commit()
    return {"item": item, "estado": "aceito" if aceitar else "recusado", "aplicado": aplicado,
            "revogar_a_mao": it["b"] if aplicado else None}


def resumo(con: sqlite3.Connection) -> dict:
    return {e: n for e, n in con.execute("SELECT estado, COUNT(*) FROM fila GROUP BY 1")}


def noite() -> dict:
    con = _con()
    try:
        out = {"quando": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        try:
            out["colher"] = colher(con)
        except cerebro.CerebroIndisponivel as exc:
            out["colher"] = {"erro": f"CÉREBRO INDISPONÍVEL: {exc}"}
        out["propor"] = propor(con)
        out["fila"] = resumo(con)
        arq = cerebro.DATA / "cerebro_consolidacao" / "estado.json"
        arq.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return out
    finally:
        con.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Consolidação noturna do segundo cérebro (fila + teto)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("noite")
    sub.add_parser("colher")
    f = sub.add_parser("fila")
    f.add_argument("--estado", default="proposto")
    for nome in ("aceitar", "recusar"):
        p = sub.add_parser(nome)
        p.add_argument("id", type=int)
        p.add_argument("motivo", nargs="?", default="")
    a = ap.parse_args(argv)
    if a.cmd == "noite":
        print(json.dumps(noite(), ensure_ascii=False))
        return 0
    con = _con()
    try:
        if a.cmd == "colher":
            print(json.dumps({**colher(con), "fila": resumo(con)}, ensure_ascii=False))
        elif a.cmd == "fila":
            print(json.dumps(resumo(con), ensure_ascii=False))
            for it in con.execute("SELECT * FROM fila WHERE estado=? ORDER BY sim DESC LIMIT 50", (a.estado,)):
                print(f"\n#{it['id']} · {it['estado']} · {it['veredito'] or '—'} · semelhança {it['sim']:.3f} · "
                      f"memórias #{it['a']} e #{it['b']}")
                print(f"  A: {it['a_texto'][:300]}\n  B: {it['b_texto'][:300]}")
                if it["proposta"]:
                    print(f"  PROPOSTA ({it['modelo']}): {it['proposta'][:400]}\n  motivo: {it['motivo']}")
        else:
            print(json.dumps(decidir(con, a.id, a.cmd == "aceitar", a.motivo), ensure_ascii=False))
    except cerebro.CerebroIndisponivel as exc:
        print(f"CÉREBRO INDISPONÍVEL ({exc}) — isto não é 'fila vazia'.", file=sys.stderr)
        return 2
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
