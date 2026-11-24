# -*- coding: utf-8 -*-
"""conferencia_executor — ONDE roda o CLI do Claude que confere a fila do Opus (plano mestre v2, O1.9 / §3.5 c).

Dois executores da MESMA assinatura (a conta é uma só; nunca gasto em dobro):
  itcampo — `tools/claude_no_itcampo.sh` (CLI no Windows do it-campo, receptor `C:\\JFN-Nativo\\claude_remoto.py`);
  vm2     — o CLI da VM-2 por ssh (login do dono, P8). O prompt e os argumentos vão num script Python pela entrada
            padrão (nada atravessa o ssh como argumento — o prompt não aparece na lista de processos).
Escolha: `JFN_CONFERENCIA_EXECUTOR` (itcampo|vm2) força; senão o primeiro DISPONÍVEL na ordem acima. Disponível =
heartbeat do nó em `fluxo.nos` com menos de `HEARTBEAT_S` OU, sem heartbeat (supervisor parado, PG fora), um teste
rápido por ssh (8 s). Sem it-campo, cai na VM-2. Nenhum disponível ⇒ a rodada não confere (a fila espera).

A TRAVA DE RITMO é a mesma para os dois: `motivo_ritmo` lê a medição publicada no PG (`fluxo/ritmo.motivo`, porta
FECHADA sem medição) e, sem o PG, a do arquivo local (`llm/ritmo_assinatura`) — que o próprio `claude_motor.pensar`
reaplica com o orçamento diário e a trava do motor. Este módulo só troca o lugar do processo.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]
ORDEM = ("itcampo", "vm2")
HEARTBEAT_S = 300
SONDA_S = 20
_SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=4"]
HOST = {"itcampo": "it-campo", "vm2": "vm2"}
_SONDA_CMD = {"itcampo": "if (Test-Path 'C:\\JFN-Nativo\\claude_remoto.py') { exit 0 } else { exit 3 }",
              "vm2": "test -s ~/.claude/.credentials.json && { test -x ~/.npm-global/bin/claude || "
                     "test -x ~/.local/bin/claude; }"}

# Roda NA VM-2 (python3 do sistema). Mesmas regras do motor: nunca --bare (vem no `args`), pasta vazia fora de
# repositório, ambiente sem as variáveis de `claude_motor.VARIAVEIS_PROIBIDAS` (vão no payload), prazo com morte do
# grupo de processo.
_RECEPTOR_VM2 = r'''
import json, os, signal, subprocess, sys
P = json.loads(__PAYLOAD__)
casa = os.path.expanduser("~")
b = next((p for p in (casa + "/.npm-global/bin/claude", casa + "/.local/bin/claude") if os.access(p, os.X_OK)), "claude")
cwd = casa + "/.local/state/jfn-claude-motor"
os.makedirs(cwd, mode=0o700, exist_ok=True)
env = {k: v for k, v in os.environ.items() if k not in P["tirar"]}
p = subprocess.Popen(["nice", "-n", "10", b] + P["args"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, env=env, cwd=cwd, start_new_session=True)
try:
    out, err = p.communicate(P["entrada"], timeout=P["timeout"])
except subprocess.TimeoutExpired:
    os.killpg(p.pid, signal.SIGKILL)
    p.communicate()
    sys.exit(124)
sys.stdout.write(out)
sys.stderr.write(err)
sys.exit(p.returncode)
'''


def heartbeats(con=None) -> dict[str, float] | None:
    """{nó: idade do heartbeat em s} de `fluxo.nos`; None = PG indisponível (não é "nó morto")."""
    try:
        import psycopg
        from compliance_agent.fluxo import fila
    except ImportError:
        return None
    try:
        proprio = con is None
        con = con or fila.conectar()
        try:
            return {n: float(i) for n, i in con.execute("SELECT no, extract(epoch FROM now() - heartbeat_em) FROM nos")}
        finally:
            if proprio:
                con.close()
    except (psycopg.Error, RuntimeError, OSError) as e:
        logger.debug("conferência: heartbeat ilegível (%s)", type(e).__name__)
        return None


def sonda(nome: str) -> bool:
    """Teste rápido por ssh: a máquina responde e tem o CLI/receptor (não chama o Claude, não gasta cota)."""
    try:
        r = subprocess.run([*_SSH, HOST[nome], _SONDA_CMD[nome]], stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=SONDA_S)
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def disponivel(nome: str, hb: dict | None, sondar=sonda) -> tuple[bool, str]:
    idade = (hb or {}).get(nome)
    if idade is not None and idade <= HEARTBEAT_S:
        return True, f"heartbeat {idade:.0f} s"
    ok = sondar(nome)
    return ok, ("teste rápido ok" if ok else "teste rápido falhou") + (f" (heartbeat {idade:.0f} s)" if idade else "")


def escolher(*, hb=None, sondar=sonda, ler_hb=heartbeats) -> tuple[str | None, str]:
    """(executor, porquê). Forçado por `JFN_CONFERENCIA_EXECUTOR`; senão o 1º disponível de `ORDEM`."""
    forcado = (os.environ.get("JFN_CONFERENCIA_EXECUTOR") or "").strip().lower()
    if forcado:
        if forcado not in ORDEM:
            return None, f"JFN_CONFERENCIA_EXECUTOR={forcado!r} desconhecido"
        return forcado, "forçado por JFN_CONFERENCIA_EXECUTOR"
    hb = ler_hb() if hb is None else hb
    porques = []
    for nome in ORDEM:
        ok, como = disponivel(nome, hb, sondar)
        if ok:
            return nome, f"{nome}: {como}" + (f" — {'; '.join(porques)}" if porques else "")
        porques.append(f"{nome} indisponível ({como})")
    return None, "; ".join(porques)


def _args_do_cmd(cmd: list[str]) -> list[str]:
    """Do comando do motor (`nice -n 10 <bin> -p ...`) só o que vem depois do binário."""
    return list(cmd[cmd.index("-p"):])


def executar_em(nome: str, rodar=None):
    """Executor no contrato de `claude_motor.pensar(executar=...)`: (cmd, entrada, env, cwd, timeout) → (rc, out, err)."""
    from compliance_agent.llm import claude_motor
    rodar = rodar or claude_motor._executar_cli
    if nome == "itcampo":
        wrapper = str(_REPO / "tools" / "claude_no_itcampo.sh")

        def ex(cmd, entrada, env, cwd, timeout):
            return rodar(["nice", "-n", "10", wrapper, *_args_do_cmd(cmd)], entrada, env, cwd, timeout)
        return ex
    if nome == "vm2":
        def ex(cmd, entrada, env, cwd, timeout):
            payload = json.dumps({"args": _args_do_cmd(cmd), "entrada": entrada, "timeout": max(1.0, timeout - 15),
                                  "tirar": list(claude_motor.VARIAVEIS_PROIBIDAS)})
            script = _RECEPTOR_VM2.replace("__PAYLOAD__", repr(payload))
            return rodar([*_SSH, HOST["vm2"], "python3", "-"], script, env, cwd, timeout)
        return ex
    raise ValueError(f"executor desconhecido: {nome}")


def motivo_ritmo(tarefa: str, *, con_pg=None, nivel_local=None) -> str | None:
    """A trava de ritmo dos dois executores (None = pode). PG com medição → `fluxo.ritmo.motivo`; PG sem medição
    ou fora → arquivo local medido (o motor reaplica a regra); nenhum medido → porta FECHADA."""
    from compliance_agent.llm import ritmo_assinatura
    m_pg = None
    try:
        import psycopg
        from compliance_agent.fluxo import fila, ritmo
        try:
            proprio = con_pg is None
            con = con_pg or fila.conectar()
            try:
                m_pg = ritmo.motivo(con, tarefa)
                if m_pg is None or not m_pg.startswith("porta fechada"):
                    return m_pg
            finally:
                if proprio:
                    con.close()
        except (psycopg.Error, RuntimeError, OSError) as e:
            m_pg = f"porta fechada: PG indisponível ({type(e).__name__})"
    except ImportError:
        m_pg = "porta fechada: fluxo indisponível"
    from compliance_agent.llm import contingencia
    c = (nivel_local or ritmo_assinatura.nivel)()
    if not c.get("medido"):
        return f"{m_pg}; medição local também ausente ({c.get('motivo')})"
    if c.get("nivel") == "contido" and tarefa != "canario":         # mesma regra de `fluxo/ritmo.motivo`
        return f"ritmo semanal da assinatura — {c.get('motivo')}"
    if c.get("nivel") == "economia" and tarefa not in contingencia.RESERVA_OPUS:
        return f"ritmo semanal da assinatura — {c.get('motivo')}"
    return None
