# -*- coding: utf-8 -*-
"""
yoda_autoauditoria — o loop de automelhoria que faltava: o Yoda audita as PRÓPRIAS falhas de conversa.

POR QUE EXISTE. Os loops da casa (auto_melhoria, sono REM) melhoram o MÉTODO investigativo a partir dos
vereditos dos casos — nenhum olhava para o Yoda falhando com o dono. Medido em 24/10/2026 no state.db:
o uso pelo Telegram caiu de 311 mensagens (jun) para 2-3/mês (ago-out), e quase toda interação recente
FALHOU: "Siafe codigo wmNY6bkR" (18/08) e "Siafe codigo 4ZuteXbN" (24/10) responderam "o comando não
está disponível"; 5 imagens seguidas "não consegui ver" (25/07); documento > 20 MB recusado (29/09).
Ninguém soube — falha de assistente não gera alarme, gera desuso.

O CICLO (determinístico, sem LLM — não depende do modelo que está sendo auditado):
  1. DETECTA, nas mensagens do Telegram da janela: resposta de incapacidade, dono repetindo a mesma
     mensagem (= a 1ª falhou), erro de ferramenta, entrada perdida (imagem/arquivo), mensagem sem
     resposta e sinal de frustração.
  2. AGRUPA por assinatura (tipo + começo normalizado do pedido) numa FILA persistente com contagem.
  3. VERIFICA O EFEITO: item marcado `resolvido` que volta a acontecer vira REINCIDIU — conserto que não
     pegou é o achado mais importante da fila (ver `reparar-e-verificar-o-efeito-nao-a-acao`).
  4. AVISA no Telegram só quando há falha NOVA ou REINCIDÊNCIA (zero falha = silêncio, não "tudo ok").

Trechos são curtos e passam por redação de segredos (o dono já mandou chave de API ao Yoda).

Uso:
  python tools/yoda_autoauditoria.py                 # janela de 24 h, grava relatório + fila, avisa se preciso
  python tools/yoda_autoauditoria.py --dias 120 --sem-aviso
  python tools/yoda_autoauditoria.py --resolver "<assinatura>" --nota "plugin jfn-siafe"
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
STATE_DB = Path.home() / ".hermes" / "state.db"
FILA = _REPO / "data" / "yoda_melhorias_fila.json"
RELATORIOS = Path.home() / "vault" / "aprendizados" / "yoda-autoauditoria"

INCAPAZ = re.compile(
    r"n[aã]o (est[aá]|[eé]) (dispon[ií]vel|uma ferramenta v[aá]lida)|n[aã]o consigo|n[aã]o tenho (acesso|como)|"
    r"n[aã]o foi poss[ií]vel|n[aã]o reconhe|n[aã]o existe (essa|esta|a) ferramenta|couldn'?t|unable to|"
    r"not (a valid|available)|i can'?t|sem acesso|falhou|deu erro", re.I)
ENTRADA_PERDIDA = re.compile(r"couldn'?t quite see|too large or its size could not be verified|"
                             r"could not (download|process)|unsupported (file|media)", re.I)
FRUSTRACAO = re.compile(r"n[aã]o reconhe|burr[oa]|n[aã]o funcion|t[aá] errad|est[aá] errad|de novo|"
                        r"n[aã]o entendeu|n[aã]o fez|cad[eê]|porra|merda|in[uú]til", re.I)
ERRO_FERRAMENTA = re.compile(r"Traceback \(most recent|\"exit_code\": ?[1-9]|\bHTTP [45]\d\d\b|"
                             r"\bError:|command not found|No such file", re.I)
_SEGREDO = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
                      r"xox[abp]-[A-Za-z0-9-]{10,}|\b[A-Za-z0-9+/_-]{32,}\b)")
_PREFIXO = re.compile(r"^\[[^\]]{0,60}id=\d+\]\s*")
# "user" que NÃO é o dono: injeções do próprio gateway/agente. Contá-las fabricava falha (medido: 1ª rodada
# de 150 dias tinha "falhas" em avisos de processo em background e em resumos de compactação).
_INJECAO = re.compile(r"^\[(IMPORTANT: Background process|CONTEXT COMPACTION|System:|Continuing toward)", re.I)
_SKILL = re.compile(r'^\[IMPORTANT: The user has invoked the "([\w-]+)" skill')


def _redigir(txt: str, n: int = 140) -> str:
    t = _SEGREDO.sub("‹segredo›", (txt or "").replace("\n", " ").strip())
    return t[:n] + ("…" if len(t) > n else "")


def _norm(txt: str) -> str:
    t = unicodedata.normalize("NFKD", _PREFIXO.sub("", txt or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[*_`~>\"'.,;:!?()\[\]]", " ", t)
    # tokens com dígito (códigos, CNPJ, anos) viram '#': "siafe codigo 4ZuteXbN" e "...wmNY6bkR" = mesma falha
    toks = ["#" if any(ch.isdigit() for ch in w) or (len(w) >= 6 and w != w.lower()) else w for w in t.split()]
    return " ".join(toks)


def _assinatura(tipo: str, pedido: str) -> str:
    m = _SKILL.match(pedido or "")
    if m:                                   # skill invocada: a falha é DA SKILL, não do texto injetado
        return f"{tipo}:/{m.group(1)}"
    return f"{tipo}:{' '.join(_norm(pedido).split()[:6]) or '(vazio)'}"


def mensagens(dias: float, db: Path = STATE_DB) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT m.session_id, m.role, COALESCE(m.content,''), COALESCE(m.tool_name,''), m.timestamp "
            "FROM messages m JOIN sessions s ON s.id = m.session_id "
            "WHERE s.source = 'telegram' AND m.timestamp > ? ORDER BY m.session_id, m.timestamp, m.id",
            (time.time() - dias * 86400,)).fetchall()
    finally:
        con.close()
    return [{"sessao": r[0], "papel": r[1], "texto": r[2], "ferramenta": r[3], "ts": float(r[4] or 0)}
            for r in rows]


def detectar(msgs: list[dict]) -> list[dict]:
    """Uma falha por (pedido do dono, tipo). Cada pedido é julgado pelo que veio até o próximo pedido."""
    falhas = []
    pedidos = [i for i, m in enumerate(msgs) if m["papel"] == "user" and not _INJECAO.match(m["texto"])]
    ultimo_por_texto: dict[str, float] = {}
    for k, i in enumerate(pedidos):
        u = msgs[i]
        fim = pedidos[k + 1] if k + 1 < len(pedidos) else len(msgs)
        depois = [m for m in msgs[i + 1:fim] if m["sessao"] == u["sessao"]]
        resp = " ".join(m["texto"] for m in depois
                        if m["papel"] == "assistant" and not _INJECAO.match(m["texto"]))
        base = {"ts": u["ts"], "quando": datetime.fromtimestamp(u["ts"]).strftime("%Y-%m-%d %H:%M"),
                "pedido": _redigir(_PREFIXO.sub("", u["texto"])), "resposta": _redigir(resp)}
        tipos = []
        if ENTRADA_PERDIDA.search(u["texto"]):
            tipos.append("entrada_perdida")
        if not resp.strip():
            tipos.append("sem_resposta")
        elif INCAPAZ.search(resp):
            tipos.append("incapaz")
        erros = [m for m in depois if m["papel"] == "tool" and ERRO_FERRAMENTA.search(m["texto"][:4000])]
        if erros:
            tipos.append("erro_ferramenta")
            base["ferramenta"] = erros[0]["ferramenta"] or "?"
        if FRUSTRACAO.search(_PREFIXO.sub("", u["texto"])):
            tipos.append("frustracao")
        chave = _norm(u["texto"])
        if chave and u["ts"] - ultimo_por_texto.get(chave, -1e12) < 600:
            tipos.append("repeticao")
        ultimo_por_texto[chave] = u["ts"]
        for t in tipos:
            falhas.append({**base, "tipo": t, "assinatura": _assinatura(t, u["texto"])})
    return falhas


def atualizar_fila(falhas: list[dict], fila_path: Path = FILA) -> dict:
    """Soma à fila persistente. Devolve {'novas': [...], 'reincidiu': [...]} desta rodada."""
    try:
        fila = json.loads(fila_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fila = {}
    novas, reinc = [], []
    for f in falhas:
        it = fila.get(f["assinatura"])
        if it is None:
            fila[f["assinatura"]] = {"tipo": f["tipo"], "n": 1, "primeiro": f["quando"], "ultimo": f["quando"],
                                     "ultimo_ts": f["ts"], "exemplo": {k: f[k] for k in ("pedido", "resposta")},
                                     "status": "aberto"}
            novas.append(f["assinatura"])
            continue
        if f["ts"] <= it.get("ultimo_ts", 0):      # já contada numa rodada anterior (janelas se sobrepõem)
            continue
        it.update(n=it["n"] + 1, ultimo=f["quando"], ultimo_ts=f["ts"],
                  exemplo={k: f[k] for k in ("pedido", "resposta")})
        if it["status"] == "resolvido" and f["ts"] > it.get("resolvido_ts", 0):
            it["status"] = "REINCIDIU"
            reinc.append(f["assinatura"])
    fila_path.parent.mkdir(parents=True, exist_ok=True)
    fila_path.write_text(json.dumps(fila, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"novas": novas, "reincidiu": reinc, "fila": fila}


def resolver(assinatura: str, nota: str, fila_path: Path = FILA, licao: str = "") -> bool:
    """Marca o conserto. `licao` (opcional) é a regra que o PRÓPRIO Yoda passa a ler na memória dele."""
    fila = json.loads(fila_path.read_text(encoding="utf-8"))
    if assinatura not in fila:
        return False
    fila[assinatura].update(status="resolvido", resolvido_ts=time.time(), nota=nota,
                            resolvido_em=datetime.now().strftime("%Y-%m-%d %H:%M"))
    if licao:
        fila[assinatura]["licao"] = licao
    fila_path.write_text(json.dumps(fila, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


YODA_MEMORY = Path.home() / ".hermes" / "memories" / "MEMORY.md"
_MARCA = "LIÇÕES DAS MINHAS FALHAS"
_LIMITE_MEMORIA = 6000          # memory.memory_char_limit do ~/.hermes/config.yaml
_DELIM = "\n§\n"              # ENTRY_DELIMITER do memory_tool_store do Hermes


def entrada_licoes(fila: dict, teto: int = 900) -> str:
    """A entrada que o Yoda lê em TODA conversa: lições dos consertos + o que reincidiu. Fecha o laço:
    a falha medida vira regra no prompt do próprio Yoda (não só num relatório que ele nunca lê)."""
    licoes = sorted({it["licao"] for it in fila.values() if it.get("licao")})
    reinc = [it for it in fila.values() if it.get("status") == "REINCIDIU"]
    if not licoes and not reinc:
        return ""
    L = [f"{_MARCA} (gerado todo dia por ~/JFN/tools/yoda_autoauditoria.py a partir das conversas reais — "
         "não editar à mão):"]
    L += [f"• {x}" for x in licoes]
    L += [f"• ⚠ VOLTOU A FALHAR ({it['tipo']}): “{it['exemplo']['pedido'][:70]}” — cuidado redobrado" for it in reinc[:3]]
    # O modelo NÃO executa comando de barra: com "→ comando /melhorias" ele respondia "o comando /melhorias não foi
    # encontrado" (medido 28/10/2026, pergunta "o que está quebrado?" fora do gateway). A lição tem de ser algo que
    # ele consegue FAZER com as ferramentas dele: o terminal.
    L.append("• Estado do sistema / o que está quebrado / automelhoria: se não veio a resposta automática do /melhorias, "
             "rode no terminal `cd ~/JFN && .venv/bin/python tools/automelhoria_geral.py --resumo` e mostre a saída. "
             "Nunca diga que /melhorias não existe.")
    txt = "\n".join(L)
    return txt if len(txt) <= teto else txt[:teto - 1] + "…"


def gravar_licoes_no_yoda(fila: dict, memoria: Path = YODA_MEMORY) -> str:
    """Substitui SÓ a nossa entrada no MEMORY.md do Yoda, com o mesmo protocolo do Hermes: flock exclusivo
    no `.lock` irmão, entradas separadas por `§`, escrita atômica (tmp + rename), modo 600. Nunca estoura o
    limite: se não couber, não grava e diz por quê (perder memória do dono é pior que perder a lição)."""
    import fcntl
    import os
    nova = entrada_licoes(fila)
    with open(memoria.with_suffix(memoria.suffix + ".lock"), "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            bruto = memoria.read_text(encoding="utf-8") if memoria.exists() else ""
            entradas = [e.strip() for e in bruto.split("\n§\n") if e.strip() and not e.strip().startswith(_MARCA)]
            if nova:
                entradas.append(nova)
            texto = _DELIM.join(entradas)
            if len(texto) > _LIMITE_MEMORIA:
                return f"não gravado: {len(texto)} > {_LIMITE_MEMORIA} caracteres na memória do Yoda"
            if texto == bruto:
                return "sem mudança"
            tmp = memoria.with_name(f".mem_jfn_{os.getpid()}")
            tmp.write_text(texto, encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, memoria)
            return f"gravado ({len(nova)} caracteres de lições)"
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def relatorio_md(falhas: list[dict], r: dict, dias: float) -> str:
    fila = r["fila"]
    abertos = sorted(((a, it) for a, it in fila.items() if it["status"] != "resolvido"),
                     key=lambda x: (x[1]["status"] != "REINCIDIU", -x[1]["n"]))
    L = [f"# Autoauditoria do Yoda — {datetime.now():%Y-%m-%d %H:%M}", "",
         f"Janela: {dias:g} dia(s) · falhas detectadas: **{len(falhas)}** · novas: {len(r['novas'])} · "
         f"**reincidências: {len(r['reincidiu'])}** · itens abertos na fila: {len(abertos)}", "",
         "> Detecção determinística (sem LLM). *Incapaz* = o Yoda disse que não podia; *repetição* = o dono "
         "mandou de novo em < 10 min; *REINCIDIU* = falha marcada como resolvida que voltou.", ""]
    if abertos:
        L += ["## Fila aberta", "", "| status | tipo | vezes | último | pedido | resposta |", "|---|---|---:|---|---|---|"]
        for a, it in abertos[:40]:
            ex = it["exemplo"]
            L.append(f"| {it['status']} | {it['tipo']} | {it['n']} | {it['ultimo']} | "
                     f"{ex['pedido'].replace('|', '/')} | {ex['resposta'][:90].replace('|', '/')} |")
        L.append("")
    res = [(a, it) for a, it in fila.items() if it["status"] == "resolvido"]
    if res:
        L += ["## Resolvidos (vigiados — voltam como REINCIDIU)", ""]
        L += [f"- `{a}` — {it.get('nota', '')} ({it.get('resolvido_em', '')})" for a, it in res]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=float, default=1.0)
    ap.add_argument("--sem-aviso", action="store_true")
    ap.add_argument("--resolver")
    ap.add_argument("--nota", default="")
    ap.add_argument("--licao", default="", help="regra que o Yoda passa a ler na memória dele")
    a = ap.parse_args()
    if a.resolver:
        ok = resolver(a.resolver, a.nota, licao=a.licao)
        if ok:
            print("memória do Yoda:", gravar_licoes_no_yoda(json.loads(FILA.read_text(encoding="utf-8"))))
        print("resolvido" if ok else "assinatura não encontrada na fila")
        return 0 if ok else 1
    falhas = detectar(mensagens(a.dias))
    r = atualizar_fila(falhas)
    try:
        print("memória do Yoda:", gravar_licoes_no_yoda(r["fila"]))
    except OSError as exc:
        print(f"memória do Yoda: não gravada ({exc})")
    md = relatorio_md(falhas, r, a.dias)
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    (RELATORIOS / f"{datetime.now():%Y-%m-%d}.md").write_text(md, encoding="utf-8")
    print(md)
    if (r["novas"] or r["reincidiu"]) and not a.sem_aviso:
        from compliance_agent.siafe_coord import notificar
        linhas = [f"🪞 Yoda — autoauditoria: {len(r['novas'])} falha(s) nova(s), "
                  f"{len(r['reincidiu'])} reincidência(s) de conserto."]
        for s in (r["reincidiu"] + r["novas"])[:6]:
            it = r["fila"][s]
            linhas.append(f"• {'🔁 ' if s in r['reincidiu'] else ''}{it['tipo']}: “{it['exemplo']['pedido'][:70]}”")
        linhas.append("Fila: data/yoda_melhorias_fila.json · relatório no vault (yoda-autoauditoria).")
        notificar("\n".join(linhas))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(_REPO))
    sys.exit(main())
