# -*- coding: utf-8 -*-
"""automelhoria_executor — o braço que FALTAVA na automelhoria: toda madrugada, o Opus pega os itens mais graves da fila
única (`data/automelhoria_fila.json`), prepara o conserto COM TESTE numa branch separada e manda ao Yoda para o ✅.

POR QUE EXISTE (20/11/2026). A fila tinha 24 itens abertos, 8 reincidindo desde 11/11, e ninguém agia: o sensor via, o
aviso chegava, e o conserto dependia de alguém lembrar. O dono: "pode ligar o executor noturno da automelhoria".

O QUE NUNCA FAZ: não mexe na branch viva nem na árvore de trabalho do ~/JFN (trabalha num `git worktree` próprio), não dá
push, não toca em .env/credencial, não roda SIAFE/SEI/navegador. Aplicar é do dono: o resumo vai ao Telegram e o ✅ é
pelo /cc do Yoda ("aplique a branch automelhoria/…"), o mesmo fluxo plano→✅→execução.

Cota: tarefa `automelhoria_executor` da reserva (`llm/contingencia.RESERVA_OPUS`) — passa no nível ECONOMIA do ritmo
semanal, nunca no CONTIDO. No máximo `--max` itens por noite, cada um com prazo.

  python tools/automelhoria_executor.py --max 2            # cron 01:00
  python tools/automelhoria_executor.py --listar           # só mostra o que pegaria
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
from tools.automelhoria_geral import DATA, FILA  # noqa: E402 — a fila que o loop de sensores concilia

LEDGER = DATA / "automelhoria_executor.json"
WT_BASE = Path.home() / "JFN-automelhoria"
TAREFA = "automelhoria_executor"
PRAZO_S = 40 * 60
REPETIR_DIAS = 7
# só o que se conserta em código/texto do repositório; serviço, SLO, SIAFE e máquina não são deste braço
AREAS = {"catraca": 0, "detector": 1, "qualidade": 2, "pareceres": 3, "certeza": 4, "dados": 5}
PY = str(_REPO / ".venv" / "bin" / "python")

_PERMITIDAS = ["Read", "Grep", "Glob", "Edit", "Write", "MultiEdit",
               f"Bash({PY} -m pytest:*)", f"Bash({PY} -m ruff:*)", f"Bash({PY} -c:*)",
               "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
               "Bash(git add:*)", "Bash(git commit:*)", "Bash(ls:*)", "Bash(grep:*)", "Bash(sed -n:*)",
               "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)"]
# o `rtk` reescreve `git x` → `rtk git x`: sem a variante a regra não casa e o commit é negado (1ª rodada, 20/11/2026)
_PERMITIDAS += [f"Bash(rtk {r[5:]}" for r in _PERMITIDAS if r.startswith("Bash(git ")]
_NEGADAS = ["Bash(git push:*)", "Bash(git reset:*)", "Bash(git checkout:*)", "Bash(rm:*)", "Bash(sudo:*)",
            "Bash(pkill:*)", "Bash(ssh:*)", "Bash(curl:*)", "WebFetch", "WebSearch",
            f"Read(/{_REPO}/.env*)", f"Read(/{Path.home()}/.config/**)", f"Read(/{Path.home()}/.claude/.credentials*)"]


def slug(assinatura: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", assinatura.lower()).strip("-")[:50]


def escolher(fila: dict, ledger: dict, n: int, agora: float | None = None) -> list[dict]:
    """REINCIDIU antes de aberto; dentro disso, pela ordem de AREAS. Item tentado há < REPETIR_DIAS fica de fora."""
    agora = agora or time.time()
    cands = []
    for it in fila.values():
        if it.get("status") not in ("aberto", "REINCIDIU") or it.get("area") not in AREAS or it.get("ao_dono"):
            continue                                   # ⚖️/🔒 é do dono: o executor nunca prepara (O8.4)
        ult = (ledger.get(it["assinatura"]) or {}).get("ts", 0)
        if agora - ult < REPETIR_DIAS * 86400:
            continue
        cands.append(it)
    cands.sort(key=lambda x: (x["status"] != "REINCIDIU", AREAS[x["area"]], x.get("primeiro") or ""))
    return cands[:n]


def criterio_forte(arquivos: list[str]) -> tuple[bool, str]:
    """CRITÉRIO FORTE do executor (O8.4): conserto só vale com teste no diff (reproduz → passa). Conserto sem teste
    fica na branch, mas marcado FRACO — o aviso diz para não aplicar sem revisão. Puro."""
    testes = [a for a in arquivos if a.startswith("tests/") and a.rsplit("/", 1)[-1].startswith("test_")]
    if not arquivos:
        return False, "sem diff"
    if not testes:
        return False, "FRACO: nenhum teste no diff — não aplicar sem revisão"
    return True, f"forte: {len(testes)} teste(s) no diff ({', '.join(testes[:3])})"


def prompt(it: dict) -> str:
    return (f"Você é o executor noturno da automelhoria do JFN. Este diretório é um git worktree SÓ SEU, numa branch "
            f"própria; a árvore viva é {_REPO} (pode LER de lá, inclusive data/, nunca escrever).\n\n"
            f"ITEM DA FILA ({it['status']}): [{it['area']}] {it['titulo']}\n"
            f"detalhe: {it.get('detalhe') or '-'}\nação indicada: {it.get('acao_humana') or '-'}\n"
            f"aberto desde {it.get('primeiro')}, {it.get('rodadas')} rodadas.\n\n"
            "Faça, nesta ordem: (1) ache a CAUSA no código/dado real (não no texto da mensagem); (2) se o conserto é de "
            "código ou de texto versionado, escreva primeiro um teste que reproduz, depois o conserto mínimo, rode os "
            f"testes casados com `{PY} -m pytest -q -p no:cacheprovider <arquivos>` e o ruff; (3) commite na branch "
            "com mensagem semântica em português. Regras da casa: indício≠acusação, INDISPONÍVEL≠0, só OB é pago, CPF "
            "mascarado, nada federal (escopo só RJ), nunca inventar número, mudança cirúrgica. Se o conserto exige "
            "decisão do dono, acesso externo ou dado que você não tem, NÃO force: não commite e explique.\n"
            "PERMISSÕES: um comando por vez — `|`, `;`, `&&` e redireção são NEGADOS (modo sem aprovação); use as "
            "ferramentas Read/Grep/Glob para ler e filtrar em vez de pipe. Negado não é motivo para desistir: refaça "
            "do jeito permitido.\n"
            "Termine com 4 linhas exatamente assim:\nCAUSA: ...\nCONSERTO: ... (ou NENHUM)\nTESTES: ...\nRISCO: ...")


def _git(*args, cwd=_REPO, check=True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def executar(it: dict) -> dict:
    hoje = datetime.now().strftime("%Y%m%d")
    br_viva = _git("branch", "--show-current")
    branch = f"automelhoria/{slug(it['assinatura'])}-{hoje}"
    wt = WT_BASE / f"{slug(it['assinatura'])}-{hoje}"
    if wt.exists():
        _git("worktree", "remove", "--force", str(wt), check=False)
    _git("fetch", "-q", "origin", br_viva, check=False)
    _git("worktree", "add", "-q", "-B", branch, str(wt), f"origin/{br_viva}")
    claude = shutil.which("claude") or str(Path.home() / ".npm-global" / "bin" / "claude")
    cmd = ["nice", "-n", "10", claude, "-p", prompt(it), "--model", "opus", "--output-format", "json",
           "--permission-mode", "dontAsk", "--add-dir", str(_REPO),
           "--allowedTools", *_PERMITIDAS, "--disallowedTools", *_NEGADAS]
    t0 = time.time()
    # As travas do motor (revisão do untangle de llm/, 20/11/2026): ambiente SEM a chave da API paga (com ela o CLI
    # cobra pela API paga — Opus nunca pela API, regra do dono), motor desligado/kill-switch respeitado e UM claude por
    # vez na VM (a mesma trava de arquivo do claude_motor; espera até 15 min pela vez).
    from compliance_agent.llm import arquivo_estado as arq
    from compliance_agent.llm import claude_motor as M
    m = M.motivo_desligado(tarefa=TAREFA)
    if m:
        texto = f"não rodou: {m}"
    else:
        with arq.trava(M._trava_arq(), 900) as pegou:
            if not pegou:
                texto = "não rodou: outro claude do JFN ocupou o motor por mais de 15 min"
            else:
                try:
                    r = subprocess.run(cmd, cwd=wt, capture_output=True, text=True, timeout=PRAZO_S,
                                       env=M.ambiente_limpo())
                    try:
                        texto = json.loads(r.stdout).get("result") or ""
                    except ValueError:
                        texto = (r.stdout or r.stderr)[-1500:]
                except subprocess.TimeoutExpired:
                    texto = f"prazo de {PRAZO_S // 60} min estourado"
    resumo = "\n".join(ln for ln in texto.splitlines() if re.match(r"(CAUSA|CONSERTO|TESTES|RISCO):", ln)) or texto[-600:]
    # Conserto deixado na árvore sem commit (permissão negada, prazo): o EXECUTOR commita — nunca apagar trabalho feito.
    if _git("status", "--porcelain", cwd=wt, check=False) and not re.search(r"CONSERTO:\s*NENHUM", resumo, re.I):
        _git("add", "-A", cwd=wt, check=False)
        msg = (re.search(r"CONSERTO:\s*(.+)", resumo) or re.search(r"(.+)", it["titulo"])).group(1)[:72]
        _git("-c", "user.name=Executor da automelhoria", "commit", "-q", "-m",
             f"fix(automelhoria): {msg}\n\nItem: {it['assinatura']}\n\n{resumo[:1500]}", cwd=wt, check=False)
    commits = _git("log", "--oneline", f"origin/{br_viva}..{branch}", check=False)
    stat = _git("diff", "--stat", f"origin/{br_viva}..{branch}", check=False) if commits else ""
    nomes = _git("diff", "--name-only", f"origin/{br_viva}..{branch}", check=False).splitlines() if commits else []
    forte, criterio = criterio_forte(nomes)
    if not commits:                                   # sem conserto: não deixa branch nem worktree órfãos
        _git("worktree", "remove", "--force", str(wt), check=False)
        _git("branch", "-D", branch, check=False)
    return {"assinatura": it["assinatura"], "titulo": it["titulo"], "branch": branch if commits else None,
            "commits": commits, "stat": stat.splitlines()[-1] if stat else "", "segundos": round(time.time() - t0),
            "resumo": resumo, "ts": time.time(), "criterio_forte": forte, "criterio": criterio}


def avisar(res: list[dict]) -> None:
    import asyncio
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
    from compliance_agent.notifications.telegram import enviar_mensagem
    partes = ["🔧 Executor noturno da automelhoria"]
    for r in res:
        if r["branch"] and r.get("criterio_forte"):
            partes.append(f"\n✅ {r['titulo'][:120]}\n{r['resumo'][:700]}\nbranch {r['branch']} · {r['stat']}\n"
                          f"{r['criterio']}\n"
                          f"Para aplicar: /cc aplique a branch {r['branch']} na branch viva, rode os testes e dê push")
        elif r["branch"]:
            partes.append(f"\n🟡 {r['titulo'][:120]}\n{r['resumo'][:500]}\nbranch {r['branch']} · {r['stat']}\n"
                          f"{r['criterio']}")
        else:
            partes.append(f"\n⚪ {r['titulo'][:120]} — sem conserto commitado\n{r['resumo'][:500]}")
    # Pedido do dono ("pode ligar o executor"), não aviso de sistema: sem o chat explícito o filtro de silêncio de
    # 17/11 engolia o resumo e devolvia ok=True (20/11/2026: 3 resumos sumiram assim).
    from compliance_agent.notifications.telegram import _get_chat_id
    r = asyncio.run(enviar_mensagem("\n".join(partes)[:4000], chat_id=_get_chat_id()))
    if not r.get("ok") or r.get("silenciado"):
        print(f"aviso NÃO entregue: {r}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=2)
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--sem-aviso", action="store_true")
    a = ap.parse_args()
    fila = json.loads(FILA.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    itens = escolher(fila, ledger, a.max)
    if a.listar:
        for it in itens:
            print(it["status"], it["area"], it["titulo"][:100])
        return 0
    from compliance_agent.llm import contingencia
    bloq = contingencia.motivo_bloqueio(TAREFA)
    if bloq:
        print(f"[{datetime.now():%F %T}] não roda: {bloq}")
        return 0
    res = []
    for it in itens:
        print(f"[{datetime.now():%F %T}] item: {it['assinatura']}", flush=True)
        r = executar(it)
        res.append(r)
        ledger[it["assinatura"]] = {k: r[k] for k in ("ts", "branch", "segundos", "criterio")}
        LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(r, ensure_ascii=False), flush=True)      # o resumo no log: sem ele não se audita a rodada
    if res and not a.sem_aviso:
        avisar(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
