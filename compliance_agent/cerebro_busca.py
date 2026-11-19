# -*- coding: utf-8 -*-
"""Busca FUNDIDA do segundo cérebro — fase 1 de docs/ARQUITETURA-SEGUNDO-CEREBRO-ALVO.md (19/11/2026).

Por quê: na bateria de 56 perguntas (config/cerebro_bateria.yaml) a busca do jfn-brain devolvia a nota certa entre
as 10 primeiras em 33 (59%). O que se mediu sobre a causa: tirar a repetição de trechos da mesma nota quase não
muda (34); trocar o "todas as palavras" do ramo textual por OR também não (31) — o `ts_rank_cd` do Postgres não é
BM25 (não pesa palavra rara) e o cérebro ordena TRECHOS sem dar peso ao título nem ao nome do arquivo. A causa do
ramo de vetor não foi isolada (o modelo NÃO corta em 128 tokens nesta instalação: medido, lê até 512).

O que a medição escolheu (e o que ela descartou): BM25 por NOTA INTEIRA sobre o vault local, com título e nome do
arquivo pesando mais, acerta 56 de 56. Fundir as listas por voto (RRF) com o cérebro e o Khoj PIOROU o primeiro
lugar (46 → 36 a 42), porque duas pernas fracas vencem uma forte. Por isso o desenho é PRIMÁRIA + RESGATE:

  entidade  CNPJ / nº de processo / UG citados na pergunta → índice determinístico `ponte_entidade` e a frase exata
            nas notas. Vem na frente: identificador é a pergunta mais precisa que existe.
  local     BM25 (SQLite FTS5) do vault local — dá a ORDEM da lista.
  brain     jfn-brain /api/search (vetor + texto). Só RESGATA: até 2 notas que o BM25 não trouxe entram no fim da
            lista — é a rede para pergunta sem nenhuma palavra em comum com a nota, e para o que não está no vault
            (shared-brain, relatório do graphify).
  khoj      piloto Khoj — perna opcional (`com=("khoj",)`), mantida para a bateria poder medi-lo se for religado.

Só leitura, sem LLM, sem API paga, nada escrito na VM-2. Perna fora do ar NÃO vira lista vazia calada:
`buscar_fundido` devolve `pernas` com o estado de cada uma e levanta `CerebroIndisponivel` se nenhuma respondeu.
Desligar no `caso` do cerebro_compartilhado: `JFN_CEREBRO_FUNDIDO=0`.

CLI:
    python -m compliance_agent.cerebro_busca "<pergunta>" [-k 10] [--com khoj] [--sem brain]
    python -m compliance_agent.cerebro_busca --indexar        # atualiza o índice local (incremental; roda sozinho)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from compliance_agent import cerebro_compartilhado as cerebro
from compliance_agent import cerebro_fts as F
from compliance_agent.cerebro_compartilhado import CerebroIndisponivel

VAULT = Path(os.environ.get("JFN_VAULT") or Path.home() / "vault")
INDICE = cerebro.DATA / "cerebro_busca" / "notas_fts.db"
KHOJ_URL = (os.environ.get("JFN_KHOJ_URL") or "http://jfn-agent-2.tailbbe6c9.ts.net:42110").rstrip("/")
PERNAS = ("entidade", "local", "brain")   # padrão; "khoj" só quando pedido
K_RRF = 60
PROFUNDIDADE = 40          # quantos resultados se pede a cada perna
RESGATE = 2                # quantas notas as pernas de vetor podem pôr no fim da lista
TETO_KHOJ_S = 6
FRESCOR_INDICE_S = 600     # o índice local é conferido de novo, no máximo, a cada 10 min (igual ao cérebro)
PULAR_PASTAS = {".obsidian", ".trash", ".stfolder", ".stversions", ".git", "node_modules", "_handoff", ".claude"}

termos = F.termos
entidades = F.entidades


def _nota(caminho: str) -> str:
    """Caminho da nota relativo ao vault (as pernas devolvem relativo, absoluto ou com prefixo de fonte)."""
    c = caminho.replace("\\", "/")
    for marca in ("/sync/vault/", "/vault/"):
        if marca in c:
            return c.split(marca, 1)[1]
    return c.lstrip("/")


# ---------- perna local: BM25 (FTS5) sobre o vault — regra de busca em cerebro_fts (a mesma da VM-2) ----------

def indexar(forcar: bool = False) -> dict:
    """Atualiza o índice local: só relê nota nova ou alterada (mtime+tamanho) e tira a que sumiu do vault."""
    con = F.abrir(INDICE)
    try:
        ult = con.execute("SELECT v FROM meta WHERE k='conferido_em'").fetchone()
        if not forcar and ult and time.time() - float(ult[0]) < FRESCOR_INDICE_S:
            return {"pulado": True}
        if not VAULT.is_dir():
            raise CerebroIndisponivel(f"vault não encontrado em {VAULT}")
        conhecidos = F.conhecidos(con)
        vistos, novos = set(), 0
        for p in VAULT.rglob("*.md"):
            rel = p.relative_to(VAULT)
            if any(x in PULAR_PASTAS for x in rel.parts) or ".sync-conflict" in p.name:
                continue
            st = p.stat()
            chave, assinatura = str(rel), f"{st.st_mtime}:{st.st_size}"
            vistos.add(chave)
            if conhecidos.get(chave) == assinatura:
                continue
            F.gravar(con, chave, assinatura, p.read_text(encoding="utf-8", errors="replace"), p.stem)
            novos += 1
        sumidos = set(conhecidos) - vistos
        for chave in sumidos:
            F.remover(con, chave)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('conferido_em', ?)", (str(time.time()),))
        con.commit()
        return {"notas": len(vistos), "regravadas": novos, "removidas": len(sumidos)}
    finally:
        con.close()


def _perna_local(pergunta: str) -> list[dict]:
    if not F.termos(pergunta):
        return []
    indexar()
    con = F.abrir(INDICE)
    try:
        return F.consultar(con, pergunta, PROFUNDIDADE)
    finally:
        con.close()


# ---------- pernas remotas ----------

def _perna_brain(pergunta: str) -> list[dict]:
    return [{"nota": r["path"] if r["source"] == "vault" else f"{r['source']}:{r['path']}", "titulo": r.get("title"),
             "trecho": " ".join((r.get("snippet") or "").split())[:300], "secao": r.get("heading")}
            for r in cerebro.buscar(pergunta, k=PROFUNDIDADE)]


def _perna_khoj(pergunta: str) -> list[dict]:
    url = f"{KHOJ_URL}/api/search?q={urllib.parse.quote(pergunta)}&t=markdown&n=25&r=false"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}),
                                    timeout=TETO_KHOJ_S) as r:
            dados = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise CerebroIndisponivel(f"khoj: {type(exc).__name__}: {exc}") from exc
    out = []
    for x in dados:
        arq = (x.get("additional") or {}).get("file")
        if arq:
            out.append({"nota": _nota(arq), "titulo": None, "trecho": " ".join((x.get("entry") or "").split())[:300]})
    return out


def _perna_entidade(pergunta: str) -> list[dict]:
    ents = F.entidades(pergunta)
    if not ents:
        return []
    out: list[dict] = []
    db = cerebro.DATA / "propagacao.db"
    if db.exists():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
        try:
            for tipo, valor in ents:
                for (chave,) in con.execute("SELECT DISTINCT chave FROM ponte_entidade WHERE tipo=? AND valor=? "
                                            "AND chave LIKE 'pericia-agente:%' LIMIT 20", (tipo, valor)):
                    out.append({"nota": f"jfn/pericias-agente/{chave.split(':', 1)[1]}.md", "titulo": None,
                                "trecho": f"{tipo} {valor} no índice de entidade"})
        except sqlite3.OperationalError:
            pass                              # banco sem a tabela (ponte nunca rodou): a perna fica vazia
        finally:
            con.close()
    indexar()
    con = F.abrir(INDICE)                     # o identificador escrito no texto das notas (frase exata)
    try:
        for tipo, valor in ents:
            out += F.por_identificador(con, tipo, valor)
    finally:
        con.close()
    return sorted(out, key=lambda it: not it["nota"].startswith("casos/"))   # nota de caso antes da gerada (estável)


_FUNCOES = {"entidade": _perna_entidade, "local": _perna_local, "brain": _perna_brain, "khoj": _perna_khoj}
_PRIMARIAS = ("entidade", "local")


def _notas_distintas(itens: list[dict]) -> list[dict]:
    vistos, out = set(), []
    for it in itens:
        if it["nota"] not in vistos:
            vistos.add(it["nota"])
            out.append(it)
    return out


def buscar_fundido(pergunta: str, k: int = 10, sem: tuple[str, ...] = (), com: tuple[str, ...] = ()) -> dict:
    """Notas que respondem à pergunta. Devolve
    {"notas": [{nota, titulo, trecho, pernas: {perna: posição}, resgate: bool}], "pernas": {perna: "ok N" | "INDISPONÍVEL: …"}}.

    Ordem: notas da entidade citada, depois o BM25 local; as pernas de vetor resgatam até RESGATE notas que as
    primárias não trouxeram. Sem nenhuma primária de pé, a ordem é a fusão (RRF) das pernas de vetor."""
    usar = [p for p in (*PERNAS, *com) if p not in sem]
    estado: dict[str, str] = {}
    listas: dict[str, list[dict]] = {}

    def rodar(perna: str):
        try:
            return perna, _notas_distintas(_FUNCOES[perna](pergunta)), None
        except CerebroIndisponivel as exc:
            return perna, [], str(exc)[:160]

    with ThreadPoolExecutor(max_workers=len(usar) or 1) as ex:
        for perna, lista, erro in ex.map(rodar, usar):
            listas[perna] = lista
            estado[perna] = f"INDISPONÍVEL: {erro}" if erro else f"ok {len(lista)}"
    if not usar or all(v.startswith("INDISPONÍVEL") for v in estado.values()):
        raise CerebroIndisponivel("; ".join(f"{p}: {v}" for p, v in estado.items()) or "nenhuma perna pedida")

    ficha: dict[str, dict] = {}
    for perna in usar:
        for pos, it in enumerate(listas[perna], 1):
            f = ficha.setdefault(it["nota"], {"nota": it["nota"], "titulo": None, "trecho": None, "pernas": {},
                                              "resgate": False})
            f["pernas"][perna] = pos
            f["titulo"] = f["titulo"] or it.get("titulo")
            f["trecho"] = f["trecho"] or it.get("trecho")
    base = list(dict.fromkeys(it["nota"] for p in _PRIMARIAS if p in usar for it in listas[p]))[:k]
    vetor: dict[str, float] = {}
    for perna in usar:
        if perna not in _PRIMARIAS:
            for pos, it in enumerate(listas[perna], 1):
                vetor[it["nota"]] = vetor.get(it["nota"], 0.0) + 1.0 / (K_RRF + pos)
    fora = [n for n in sorted(vetor, key=lambda n: -vetor[n]) if n not in base]
    resgatadas = fora[:max(RESGATE, k - len(base))]
    for n in resgatadas:
        ficha[n]["resgate"] = True
    ordem = base[:k - min(len(resgatadas), RESGATE)] + resgatadas
    return {"notas": [ficha[n] for n in ordem[:k]], "pernas": estado}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Busca fundida do segundo cérebro (fase 1)")
    ap.add_argument("pergunta", nargs="?")
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--sem", default="", help="pernas a desligar, separadas por vírgula")
    ap.add_argument("--com", default="", help="pernas opcionais a ligar (khoj)")
    ap.add_argument("--indexar", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.indexar:
            print(json.dumps(indexar(forcar=True), ensure_ascii=False))
            return 0
        if not a.pergunta:
            ap.error("pergunta obrigatória")
        r = buscar_fundido(a.pergunta, a.k, sem=tuple(x for x in a.sem.split(",") if x),
                           com=tuple(x for x in a.com.split(",") if x))
    except CerebroIndisponivel as exc:
        print(f"CÉREBRO INDISPONÍVEL ({exc}) — isto não é 'nada encontrado'.", file=sys.stderr)
        return 2
    print("pernas: " + " · ".join(f"{p}={v}" for p, v in r["pernas"].items()))
    for i, f in enumerate(r["notas"], 1):
        de = ",".join(f"{p}#{n}" for p, n in f["pernas"].items())
        print(f"{i:2d}. [{f['nota']}] ({de}{' · resgate' if f['resgate'] else ''}) {(f['trecho'] or '')[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
