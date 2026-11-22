"""Receptor no Windows do it-campo: roda o Claude Code (assinatura do dono) para o motor da VM-1.

POR QUE (dono, 22/11/2026 00h: "pode levar pro it-campo o que precisar de Claude de lá também"). O CLI do Claude
(node) consome CPU da VM-1 (2 vCPU) por ~5,5 h/dia de chamadas. Aqui só muda ONDE o processo roda: a cota é a
MESMA conta, então TODA a governança fica na VM-1, intocada — `claude_motor.pensar()` confere o ritmo semanal
(`llm/ritmo_assinatura`), reserva no orçamento diário (`llm/orcamento`), segura a trava e registra o uso ANTES de
chamar o binário; o binário dele (`JFN_CLAUDE_BIN`) é `tools/claude_no_itcampo.sh`, que traz o pedido até aqui.

Protocolo (entrada padrão, bytes UTF-8): um JSON {"args": [...], "entrada": "<prompt>"}. Saída padrão e de erro do
CLI voltam como vieram; o código de saída é o do CLI. Sem `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` no ambiente
(nunca chave paga) e cwd numa pasta vazia (o CLI não carrega CLAUDE.md nenhum). Prazo próprio (`TETO_S`): o motor
mata o ssh no prazo dele, e o processo daqui não pode ficar órfão gastando a conta.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

EXE = Path(os.environ.get("APPDATA", r"C:\Users\iterj\AppData\Roaming")) / "npm" / "node_modules" / "@anthropic-ai" \
    / "claude-code" / "bin" / "claude.exe"
VAZIA = Path(r"C:\JFN-Nativo\claude-vazio")
TETO_S = 1800
PROIBIDAS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
LOG = Path(r"C:\JFN-Nativo\claude_remoto.log")   # só hora, modelo, rc e segundos — nunca prompt nem resposta


def _registrar(modelo: str, rc: int, ini: float) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"em": time.strftime("%Y-%m-%d %H:%M:%S"), "modelo": modelo, "rc": rc,
                            "s": round(time.time() - ini, 1)}) + "\n")


def main() -> int:
    pedido = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    args = [str(a) for a in pedido["args"]]
    if "--bare" in args:                      # --bare troca a assinatura por chave de API: nunca
        sys.stderr.write("claude_remoto: --bare recusado\n")
        return 2
    if args[:1] == ["--eco"]:                   # teste do transporte, sem chamar o CLI (não gasta cota)
        sys.stdout.buffer.write(json.dumps(pedido, ensure_ascii=False).encode("utf-8"))
        return 0
    VAZIA.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in PROIBIDAS}
    ini = time.time()
    modelo = args[args.index("--model") + 1] if "--model" in args[:-1] else ""
    try:
        r = subprocess.run([str(EXE), *args], input=pedido.get("entrada", "").encode("utf-8"), capture_output=True,
                           cwd=VAZIA, env=env, timeout=TETO_S, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"claude_remoto: prazo de {TETO_S} s estourado no it-campo\n")
        _registrar(modelo, 124, ini)
        return 124
    _registrar(modelo, r.returncode, ini)
    sys.stdout.buffer.write(r.stdout)
    sys.stderr.buffer.write(r.stderr)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
