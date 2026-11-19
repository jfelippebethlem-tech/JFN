# -*- coding: utf-8 -*-
"""Cliente do SEGUNDO CÉREBRO compartilhado (jfn-brain, VM-2) — pedido do dono, 14/11/2026:
"novas descobertas, segundo cérebro".

O cérebro é a memória comum dos agentes (Claude VM-1/VM-2, Yoda/Hermes). Aqui fica o lado da VM-1 que NÃO depende
de uma sessão do Claude estar aberta: rotinas e o despachante de propagação gravam e consultam pela API REST do
próprio cérebro (mesmo serviço do MCP, só na Tailnet).

Regras (as do cérebro, mais as da casa):
  · um fato por memória; `source` = quem grava (padrão `claude-vm1`); `kind` fechado (`KINDS`);
  · correção = `supersedes=<id antigo>` — nunca sobrescrever. Quem controla isso é o REGISTRO local
    (`data/propagacao.db`, tabela `cerebro`): cada descoberta tem uma CHAVE estável; mesma chave com texto novo
    substitui a memória anterior; mesma chave com o mesmo texto não grava de novo (idempotente);
  · `recusar()` barra segredo e dado pessoal ANTES de sair da máquina: CPF (inteiro ou mascarado), e-mail,
    credencial, endereço com caminho secreto, sequência longa de aparência aleatória. Recusado não é enviado nem
    fica na fila — fica registrado com o motivo;
  · cérebro fora do ar = a descoberta fica PENDENTE no registro e o próximo ciclo tenta de novo (nada se perde,
    nada é dado como gravado sem a resposta do cérebro). INDISPONÍVEL ≠ vazio: `buscar`/`recordar` levantam
    `CerebroIndisponivel` em vez de devolver lista vazia.

CLI (para agentes sem o MCP carregado — subagentes, cron, /cc):
    python -m compliance_agent.cerebro_compartilhado caso "<fornecedor | processo | órgão | tema>"
    python -m compliance_agent.cerebro_compartilhado buscar "<texto>" [-k 8]
    python -m compliance_agent.cerebro_compartilhado recordar "<texto>" [--kind decisoria]
    python -m compliance_agent.cerebro_compartilhado lembrar --chave K --kind semantica [--assunto A] "<fato>"
    python -m compliance_agent.cerebro_compartilhado entidade "<CNPJ | nº SEI | UG 133100 | nº OB>" [--com "<outra>"]
    python -m compliance_agent.cerebro_compartilhado historico "<chave | id>"
    python -m compliance_agent.cerebro_compartilhado estado
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("JFN_DATA_DIR") or RAIZ / "data")
URL = (os.environ.get("JFN_BRAIN_URL") or "https://jfn-agent-2.tailbbe6c9.ts.net:8443").rstrip("/")
FONTE = os.environ.get("JFN_BRAIN_SOURCE") or "claude-vm1"
KINDS = ("episodica", "semantica", "procedural", "decisoria", "experiencial", "identidade")
TETO_S = 25
MAX_CHARS = 1500

DDL = """CREATE TABLE IF NOT EXISTS cerebro(
  chave TEXT PRIMARY KEY, kind TEXT, assunto TEXT, conteudo TEXT, hash TEXT,
  mem_id INTEGER, hash_enviado TEXT, enviado_em REAL, tentativas INTEGER DEFAULT 0, erro TEXT, criado_em REAL)"""


class CerebroIndisponivel(RuntimeError):
    """O cérebro não respondeu (rede, serviço parado, resposta ilegível)."""


_RECUSAS = (
    ("cpf", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("cpf mascarado", re.compile(r"\*{3}\.?\d{3}\.?\d{3}-?\*{2}|\b\d{3}\.\*{3}\.\*{3}-\d{2}\b")),
    ("e-mail", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("credencial", re.compile(r"(?i)\b(senha|password|passwd|token|secret|api[_-]?key|bearer|authorization)\b\s*[:=]\s*\S+")),
    ("endereço com caminho secreto", re.compile(r"https?://[^\s/]+/[^\s]*[A-Za-z0-9_-]{20,}")),
    ("sequência com aparência de segredo", re.compile(r"\b(?=[A-Za-z0-9_-]*[0-9])(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{32,}\b")),
)


def recusar(texto: str) -> str | None:
    """Motivo para NÃO mandar o texto ao cérebro, ou None se pode ir. CNPJ (14 dígitos) passa: é dado público."""
    sem_cnpj = re.sub(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b", " ", texto or "")
    for nome, rx in _RECUSAS:
        if rx.search(sem_cnpj):
            return nome
    return None


def _http(caminho: str, corpo: dict | None = None, mcp: bool = False):
    req = urllib.request.Request(URL + caminho, method="POST" if corpo is not None else "GET",
                                 data=json.dumps(corpo).encode() if corpo is not None else None,
                                 headers={"Content-Type": "application/json", "Accept":
                                          "application/json, text/event-stream" if mcp else "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TETO_S) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise CerebroIndisponivel(f"{type(exc).__name__}: {exc}") from exc


def buscar(q: str, k: int = 8) -> list[dict]:
    """Notas do vault/graphify indexadas pelo cérebro (busca híbrida)."""
    return _http(f"/api/search?q={urllib.parse.quote(q)}&k={int(k)}")


def recordar(q: str, k: int = 8, kind: str | None = None) -> list[dict]:
    """Memórias ativas gravadas pelos agentes."""
    extra = f"&kind={kind}" if kind else ""
    return _http(f"/api/recall?q={urllib.parse.quote(q)}&k={int(k)}{extra}")


def stats() -> dict:
    return _http("/api/stats")


def entidade(ref: str, com: str | None = None) -> dict:
    """Cruzamento por entidade (fase 4): o que cita o CNPJ / processo SEI / UG / OB — e, com `com`, só o que cita os dois."""
    extra = f"&com={urllib.parse.quote(com)}" if com else ""
    return _http(f"/api/entity?ref={urllib.parse.quote(ref)}{extra}")


def historico(ref: str) -> list[dict]:
    """Versões de um fato (chave ou id): o que se disse, quando foi registrado, quando deixou de valer."""
    return _http(f"/api/history?ref={urllib.parse.quote(ref)}")


def mcp(ferramenta: str, argumentos: dict):
    """Chama uma ferramenta do MCP do cérebro como um agente chama (JSON-RPC em /mcp/)."""
    res = _http("/mcp/", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": ferramenta, "arguments": argumentos}}, mcp=True)
    try:
        res = res["result"]
        if res.get("isError"):
            raise CerebroIndisponivel(f"mcp {ferramenta}: {str(res.get('content'))[:160]}")
        sc = res.get("structuredContent")
        if sc is None:                              # ferramenta que devolve dict livre: o JSON vem como texto
            return json.loads(res["content"][0]["text"])
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise CerebroIndisponivel(f"mcp {ferramenta}: resposta ilegível ({exc})") from exc


def _con(db: Path | None = None) -> sqlite3.Connection:
    alvo = db or DATA / "propagacao.db"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(alvo, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(DDL)
    return con


def _hash(kind: str, conteudo: str) -> str:
    return hashlib.sha1(f"{kind}\n{conteudo}".encode()).hexdigest()


def registrar(chave: str, conteudo: str, kind: str = "semantica", assunto: str | None = None,
              con: sqlite3.Connection | None = None) -> str:
    """Põe a descoberta no registro (fila). Devolve: 'novo' | 'corrigido' | 'igual' | 'recusado: <motivo>'.

    Não fala com a rede — quem envia é `enviar_pendentes`. Assim a rotina que descobre nunca espera o cérebro."""
    if kind not in KINDS:
        raise ValueError(f"kind deve ser um de {KINDS}")
    conteudo = " ".join((conteudo or "").split())[:MAX_CHARS]
    motivo = recusar(f"{assunto or ''} {conteudo}")
    proprio = con is None
    con = con or _con()
    try:
        h = _hash(kind, conteudo)
        ant = con.execute("SELECT hash, hash_enviado FROM cerebro WHERE chave=?", (chave,)).fetchone()
        if motivo:
            if ant is None:               # guarda só o motivo, nunca o texto recusado
                con.execute("INSERT INTO cerebro(chave,kind,assunto,conteudo,hash,erro,criado_em) VALUES (?,?,?,?,?,?,?)",
                            (chave, kind, None, None, None, f"RECUSADO: {motivo}", time.time()))
                con.commit()
            return f"recusado: {motivo}"
        if ant and ant[0] == h:
            return "igual"
        if ant is None:
            con.execute("INSERT INTO cerebro(chave,kind,assunto,conteudo,hash,criado_em) VALUES (?,?,?,?,?,?)",
                        (chave, kind, assunto, conteudo, h, time.time()))
            r = "novo"
        else:
            con.execute("UPDATE cerebro SET kind=?, assunto=?, conteudo=?, hash=?, erro=NULL, tentativas=0 WHERE chave=?",
                        (kind, assunto, conteudo, h, chave))
            r = "corrigido"
        con.commit()
        return r
    finally:
        if proprio:
            con.close()


def enviar_pendentes(limite: int = 20, con: sqlite3.Connection | None = None) -> dict:
    """Manda ao cérebro o que o registro tem de novo ou corrigido. Correção vai com `supersedes`.

    Só marca como enviado com a resposta do cérebro em mãos ('gravada' ou 'duplicada' + id)."""
    proprio = con is None
    con = con or _con()
    r = {"enviadas": 0, "corrigidas": 0, "duplicadas": 0, "falhas": 0, "erro": None}
    try:
        linhas = con.execute(
            "SELECT chave, kind, assunto, conteudo, hash, mem_id FROM cerebro "
            "WHERE conteudo IS NOT NULL AND (hash_enviado IS NULL OR hash_enviado<>hash) "
            "ORDER BY criado_em LIMIT ?", (limite,)).fetchall()
        for chave, kind, assunto, conteudo, h, mem_id in linhas:
            corpo = {"content": conteudo, "kind": kind, "subject": assunto, "source": FONTE, "confidence": 0.9,
                     "supersedes": mem_id, "tags": ["jfn", "propagacao"], "chave": chave}
            try:
                resp = _http("/api/memories", corpo)
                novo_id = int(resp["id"])
            except (CerebroIndisponivel, KeyError, TypeError, ValueError) as exc:
                con.execute("UPDATE cerebro SET tentativas=tentativas+1, erro=? WHERE chave=?", (str(exc)[:300], chave))
                con.commit()
                r["falhas"] += 1
                r["erro"] = str(exc)[:300]
                if isinstance(exc, CerebroIndisponivel):
                    break                 # fora do ar: não insiste nas demais neste ciclo
                continue
            if resp.get("status") == "duplicada" and " ".join(str(resp.get("existente") or "").split()) != conteudo:
                # o cérebro fundiu com OUTRO fato (similaridade > 0,96) e devolveu o id dele: herdar esse id faria a
                # próxima correção desta chave substituir a memória alheia. Fica sem id, com o motivo, e não reenvia
                # até o texto mudar (o texto precisa ficar mais distinto para entrar).
                con.execute("UPDATE cerebro SET mem_id=NULL, hash_enviado=?, enviado_em=?, erro=? WHERE chave=?",
                            (h, time.time(), f"DUPLICADA: o cérebro fundiu com a memória #{novo_id} (outro texto)", chave))
                con.commit()
                r["duplicadas"] += 1
                continue
            con.execute("UPDATE cerebro SET mem_id=?, hash_enviado=?, enviado_em=?, erro=NULL WHERE chave=?",
                        (novo_id, h, time.time(), chave))
            con.commit()
            r["corrigidas" if mem_id else "enviadas"] += 1
        return r
    finally:
        if proprio:
            con.close()


def lembrar(chave: str, conteudo: str, kind: str = "semantica", assunto: str | None = None) -> dict:
    """Registra e envia na hora (uso interativo). Rotina use `registrar` e deixe o despachante enviar."""
    con = _con()
    try:
        r = registrar(chave, conteudo, kind, assunto, con=con)
        if r.startswith("recusado") or r == "igual":
            return {"status": r}
        env = enviar_pendentes(con=con)
        lin = con.execute("SELECT mem_id, erro FROM cerebro WHERE chave=?", (chave,)).fetchone()
        return {"status": r, "id": lin[0], "erro": lin[1], "envio": env}
    finally:
        con.close()


def resumo(con: sqlite3.Connection | None = None) -> dict:
    """Estado do registro para o painel (Sistema › Propagação). Não fala com a rede."""
    proprio = con is None
    con = con or _con()
    try:
        tot, env, pend, rec, ult = con.execute(
            "SELECT COUNT(*), SUM(hash_enviado IS NOT NULL AND hash_enviado=hash), "
            "SUM(conteudo IS NOT NULL AND (hash_enviado IS NULL OR hash_enviado<>hash)), "
            "SUM(conteudo IS NULL), MAX(enviado_em) FROM cerebro").fetchone()
        erro = con.execute("SELECT erro FROM cerebro WHERE erro IS NOT NULL AND conteudo IS NOT NULL "
                           "ORDER BY criado_em DESC LIMIT 1").fetchone()
        ultimas = [{"chave": c, "kind": k, "assunto": a, "id": i, "quando": q, "texto": (t or "")[:220]}
                   for c, k, a, i, q, t in con.execute(
                       "SELECT chave, kind, assunto, mem_id, enviado_em, conteudo FROM cerebro "
                       "WHERE enviado_em IS NOT NULL ORDER BY enviado_em DESC LIMIT 12")]
        return {"registradas": tot or 0, "gravadas": env or 0, "pendentes": pend or 0, "recusadas": rec or 0,
                "ultimo_envio": ult, "ultimo_erro": erro[0] if erro else None, "ultimas": ultimas}
    finally:
        if proprio:
            con.close()


def caso(termo: str, k: int = 6) -> str:
    """O que o cérebro já sabe sobre um caso — para ler ANTES de reabri-lo. Texto curto, pronto para o agente."""
    mem = recordar(termo, k=k)
    aviso = None
    if os.environ.get("JFN_CEREBRO_FUNDIDO", "1") != "0":
        # fase 1 (19/11/2026): BM25 por nota do vault local dá a ordem, o cérebro resgata — recall@10 de 33 para
        # 56 em 56 na bateria (tools/cerebro_bateria.py). Import tardio: cerebro_busca importa este módulo.
        from compliance_agent import cerebro_busca
        r = cerebro_busca.buscar_fundido(termo, k=k)
        notas = [{"path": f["nota"], "heading": None, "snippet": f["trecho"] or ""} for f in r["notas"]]
        fora = [f"{p} {v}" for p, v in r["pernas"].items() if v.startswith("INDISPONÍVEL")]
        aviso = "  ATENÇÃO — parte da busca não respondeu: " + "; ".join(fora) if fora else None
    else:
        notas = buscar(termo, k=k)
    out = [f"CÉREBRO · o que já se sabe sobre: {termo}", ""]
    out.append(f"Memórias dos agentes ({len(mem)}):" if mem else "Memórias dos agentes: nenhuma sobre este termo.")
    for m in mem:
        out.append(f"  [#{m['id']} · {m['kind']} · {m['source']} · {str(m['created_at'])[:10]}] {m['content'][:420]}")
    out.append("")
    out.append(f"Notas do vault ({len(notas)}):" if notas else "Notas do vault: nenhuma sobre este termo.")
    for n in notas:
        out.append(f"  [{n['path']} › {n.get('heading') or '—'}] {' '.join(n['snippet'].split())[:300]}")
    if aviso:
        out.append(aviso)
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Segundo cérebro compartilhado (jfn-brain)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("caso", "buscar", "recordar"):
        p = sub.add_parser(nome)
        p.add_argument("texto")
        p.add_argument("-k", type=int, default=6)
        if nome == "recordar":
            p.add_argument("--kind", choices=KINDS)
    p = sub.add_parser("lembrar")
    p.add_argument("texto")
    p.add_argument("--chave", required=True)
    p.add_argument("--kind", choices=KINDS, default="semantica")
    p.add_argument("--assunto")
    p = sub.add_parser("entidade")
    p.add_argument("texto", help="CNPJ, nº de processo SEI, 'UG 133100' ou nº de OB")
    p.add_argument("--com", help="segunda entidade: só o que cita as duas")
    p = sub.add_parser("historico")
    p.add_argument("texto", help="chave ou id do fato")
    sub.add_parser("estado")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "caso":
            print(caso(a.texto, a.k))
        elif a.cmd == "buscar":
            print(json.dumps(buscar(a.texto, a.k), ensure_ascii=False, indent=1))
        elif a.cmd == "recordar":
            print(json.dumps(recordar(a.texto, a.k, a.kind), ensure_ascii=False, indent=1))
        elif a.cmd == "entidade":
            print(json.dumps(entidade(a.texto, a.com), ensure_ascii=False, indent=1))
        elif a.cmd == "historico":
            print(json.dumps(historico(a.texto), ensure_ascii=False, indent=1))
        elif a.cmd == "lembrar":
            print(json.dumps(lembrar(a.chave, a.texto, a.kind, a.assunto), ensure_ascii=False))
        else:
            print(json.dumps({"registro": resumo(), "cerebro": stats()}, ensure_ascii=False, indent=1, default=str))
    except CerebroIndisponivel as exc:
        print(f"CÉREBRO INDISPONÍVEL ({exc}) — isto não é 'nada encontrado'.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
