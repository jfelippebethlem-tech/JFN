#!/usr/bin/env python3
"""Teste passo a passo de quantas sessões SEI simultâneas o it-campo sustenta.

Dono, 15/11/2026: "veja passo a passo quantas sessões funcionam simultaneamente". Medido no mesmo dia: com 12–18
navegadores do mesmo IP a conexão do it-campo ao SEI caía minutos depois; com 1–2 (VM-1, VM-2) segue o dia todo.

Roda na VM-1, dirige o it-campo por ssh. Espera a conexão voltar; então, a cada degrau de `--degrau-min`, lê o status
POR PROCESSO nos logs das sessões (não as rodadas, que só fecham em até 30 min) e decide:
  saudável (conexão ok, ≥1 ok, nenhum login falho)  → sobe UMA sessão de íntegras;
  degradou (conexão caiu, login falho, ou 3+ tentativas sem ok) → volta ao último nível bom e encerra;
  sem dados → estende o degrau (até 3×).
A varredura fica fixa em 1. O resultado vai ao Telegram do dono e a `data/itcampo_degraus.log`.

    nohup .venv/bin/python -m tools.itcampo_degraus --max 12 &
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LOG = RAIZ / "data" / "itcampo_degraus.log"
URL_SEI = "https://sei.rj.gov.br/sip/login.php?sigla_orgao_sistema=ERJ&sigla_sistema=SEI"
# só a linha de STATUS ("proc: ok|login|erro…"); a linha "proc: LOGIN FALHOU" que a precede contaria a falha 2×
_RX = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]\s+\d{6}/\d{6}/\d{4}: (\w+)\s*$", re.M)


def contar(texto: str, desde: str) -> dict:
    c: dict = {}
    for ts, st in _RX.findall(texto):
        if ts >= desde:
            c[st] = c.get(st, 0) + 1
    return c


def veredito(c: dict, *, conexao: bool) -> str:
    if not conexao or c.get("login"):
        return "degradou"
    if c.get("ok"):
        return "saudavel"
    tentativas = sum(v for k, v in c.items() if k != "sem_arvore")
    return "degradou" if tentativas >= 3 else "sem_dados"


def _ic(script: str, timeout: int = 120) -> str:
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "it-campo", "wsl -d Ubuntu -e bash -s"], input=script,
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout


def conexao() -> bool:
    return _ic(f"curl -sk -m 20 -o /dev/null -w '%{{http_code}}' '{URL_SEI}'").strip() == "200"


def logs_sessoes() -> str:
    return _ic("cat ~/JFN-sessoes/s*/data/sei_integra_fila.log 2>/dev/null | tail -n 4000", timeout=180)


def definir(n: int) -> None:
    _ic(f"cd ~/JFN-worker && echo {n} > data/itcampo_n && echo 1 > data/itcampo_varredura_n && touch data/.sem_acelerar")


def anotar(msg: str) -> None:
    linha = f"[{time.strftime('%F %T')}] {msg}"
    print(linha, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")


def telegram(msg: str) -> None:
    env = Path.home() / ".hermes" / ".env"
    m = re.search(r"^TELEGRAM_BOT_TOKEN=(.+)$", env.read_text(encoding="utf-8"), re.M)
    if not m:
        return
    tok = m.group(1).strip().strip("'\"")
    dados = urllib.parse.urlencode({"chat_id": "45338178", "text": msg}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=dados, timeout=30)
    except OSError as e:
        anotar(f"telegram falhou: {type(e).__name__}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inicio", type=int, default=1)
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--degrau-min", type=int, default=15)
    a = ap.parse_args(argv)
    while not conexao():
        anotar("sem conexão do it-campo ao SEI — aguardo 5 min antes de começar")
        time.sleep(300)
    n, bom, historico = a.inicio, 0, []
    while True:
        definir(n)
        inicio = time.strftime("%F %T")
        anotar(f"DEGRAU {n} íntegras + 1 varredura — início")
        for extensao in range(3):
            time.sleep(a.degrau_min * 60)
            c = contar(logs_sessoes(), inicio)
            v = veredito(c, conexao=conexao())
            if v != "sem_dados":
                break
            anotar(f"degrau {n}: sem dados ainda ({c}) — estendo")
        historico.append({"n": n, "status": c, "veredito": v})
        anotar(f"DEGRAU {n}: {v} {json.dumps(c, ensure_ascii=False)}")
        if v == "saudavel":
            bom = n
            if n >= a.max:
                break
            n += 1
            continue
        break
    final = max(bom, 1)
    definir(final)
    resumo = " · ".join(f"{h['n']}: {h['veredito']} {h['status']}" for h in historico)
    msg = (f"it-campo — teste passo a passo das sessões SEI: funciona com até {bom} sessão(ões) de íntegras + 1 de "
           f"varredura simultâneas. Fixado em {final}+1. Degraus: {resumo}")
    anotar(msg)
    telegram(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
