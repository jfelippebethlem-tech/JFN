# -*- coding: utf-8 -*-
"""
agenda_jobs — visão ÚNICA do metabolismo do ecossistema (observabilidade central).

Consolida num relatório só o que antes vivia espalhado em ~20 logs: timers systemd
(--user), sweeps do crontab e flags de pausa. Determinístico, zero LLM, leitura-só.
Consumido pelo GET /api/agenda (Yoda: "como está a agenda/os jobs?").

Honestidade: last=- significa "nunca rodou nesta sessão do systemd", não falha.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DATA = _REPO / "data"


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except Exception:  # noqa: BLE001
        return ""


def timers() -> list[dict]:
    """Timers systemd --user: unidade, próxima execução, última, resultado do service."""
    import json
    out = _run(["systemctl", "--user", "list-timers", "--all", "--output=json"])
    try:
        rows = json.loads(out or "[]")
    except Exception:  # noqa: BLE001
        rows = []

    def _ts(us) -> str:  # µs epoch → dd/mm HH:MM ("-" se nunca/desconhecido)
        try:
            return datetime.fromtimestamp(int(us) / 1e6).strftime("%d/%m %H:%M") if us else "-"
        except Exception:  # noqa: BLE001
            return "-"

    itens = []
    for r in rows:
        activates = r.get("activates") or ""
        svc_info = _run(["systemctl", "--user", "show", activates,
                         "-p", "Result", "-p", "ExecMainStatus", "-p", "ActiveState"])
        props = dict(l.split("=", 1) for l in svc_info.splitlines() if "=" in l)
        itens.append({"timer": r.get("unit") or "?", "service": activates,
                      "proxima": _ts(r.get("next")), "ultima": _ts(r.get("last")),
                      "resultado": props.get("Result", "?"),
                      "exit": props.get("ExecMainStatus", "?"),
                      "estado": props.get("ActiveState", "?")})
    return itens


def crons() -> list[dict]:
    """Entradas do crontab do usuário + frescor do log de cada uma (mtime = último sinal de vida)."""
    out = _run(["crontab", "-l"])
    itens = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or ln.startswith("@reboot"):
            continue
        m = re.match(r"^([\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+)\s+(.+)$", ln)
        if not m:
            continue
        agendamento, comando = m.group(1), m.group(2)
        logm = re.search(r">>\s*(\S+\.log)", comando)
        log_path = Path(logm.group(1)) if logm else None
        frescor = ""
        if log_path and log_path.exists():
            frescor = datetime.fromtimestamp(log_path.stat().st_mtime).strftime("%d/%m %H:%M")
        # rótulo curto: o script/módulo chamado
        alvo = re.search(r"([\w./-]+\.(?:sh|py)|-m\s+[\w.]+)", comando)
        itens.append({"agenda": agendamento, "job": (alvo.group(1) if alvo else comando[:50]).strip(),
                      "ultimo_sinal": frescor or "-"})
    return itens


def pausas() -> list[str]:
    """Flags de pausa vivas (data/.pause_*) — sweeps intencionalmente parados."""
    return sorted(p.name for p in _DATA.glob(".pause_*"))


def render() -> str:
    """Texto Telegram-friendly com a agenda consolidada (⏰ timers, 🔁 crons, ⏸ pausas)."""
    L = ["🗓 **Agenda do ecossistema** (timers + crons + pausas)", ""]
    L.append("⏰ **Timers systemd:**")
    for t in timers():
        icone = "✅" if t["resultado"] == "success" else ("❌" if t["resultado"] not in ("success", "?") else "·")
        L.append(f"{icone} `{t['timer']}` → próx {t['proxima'] or '-'} · última {t['ultima'] or '-'}"
                 + (f" · result={t['resultado']}" if t["resultado"] not in ("success",) else ""))
    L.append("")
    L.append("🔁 **Crons (último sinal = mtime do log):**")
    for c in crons():
        L.append(f"· `{c['job']}` [{c['agenda']}] — {c['ultimo_sinal']}")
    p = pausas()
    if p:
        L.append("")
        L.append("⏸ **Pausas ativas:** " + ", ".join(f"`{x}`" for x in p))
    return "\n".join(L)


if __name__ == "__main__":
    print(render())
