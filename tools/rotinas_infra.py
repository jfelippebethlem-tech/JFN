# -*- coding: utf-8 -*-
"""Rotinas de infraestrutura do JFN que moravam SOLTAS no crontab da VM-1/VM-2 e vão para o config/fluxo.yaml (pedido
do dono, 24/11/2026; plano mestre v2 §3.3). Cada subcomando faz o mesmo que a linha do cron fazia e termina com UMA
linha `rotinas_infra <nome>: …` que a rotina confere no log (efeito). Caminhos de casa e hosts ficam AQUI (resolvidos
em tempo de execução), nunca no fluxo.yaml (ADR-011: sem topologia no yaml).

    python -m tools.rotinas_infra graphify_retencao             # 3 snapshots datados em graphify-out/
    python -m tools.rotinas_infra graph_report_brain            # GRAPH_REPORT.md → inputs do brain (VM-2)
    python -m tools.rotinas_infra logrotate --perfil vm1|vm2    # logrotate do usuário com estado próprio
    python -m tools.rotinas_infra nuvens                        # sessões das nuvens grátis (script do dono)
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MANTER_SNAPSHOTS = 3
_RX_SNAPSHOT = re.compile(r"^20\d\d-")
DESTINO_BRAIN = "vm2-ts:brain/inputs/"          # alias do ~/.ssh/config (rota Tailscale), como o cron fazia


def snapshots_a_apagar(nomes: list[str], manter: int = MANTER_SNAPSHOTS) -> list[str]:
    """Os snapshots datados (AAAA-…) além dos `manter` mais recentes — a mesma regra do `ls -d 20* | head -n -3`."""
    datados = sorted(n for n in nomes if _RX_SNAPSHOT.match(n))
    return datados[:-manter] if len(datados) > manter else []


def graphify_retencao(raiz: Path = RAIZ) -> tuple[int, str]:
    base = raiz / "graphify-out"
    if not base.is_dir():
        return 1, "graphify-out ausente"
    apagar = snapshots_a_apagar([p.name for p in base.iterdir() if p.is_dir()])
    for n in apagar:
        shutil.rmtree(base / n)
    ficam = len(snapshots_a_apagar([p.name for p in base.iterdir() if p.is_dir()], manter=0))
    return 0, f"{len(apagar)} apagado(s), {ficam} snapshot(s) datado(s) ficam"


def graph_report_brain(raiz: Path = RAIZ) -> tuple[int, str]:
    arq = raiz / "graphify-out" / "GRAPH_REPORT.md"
    if not arq.is_file():
        return 1, "GRAPH_REPORT.md ausente"
    r = subprocess.run(["rsync", "-a", "--timeout=60", str(arq), DESTINO_BRAIN], capture_output=True, text=True,
                       timeout=180)
    return (0, "GRAPH_REPORT.md entregue ao brain") if r.returncode == 0 else \
        (r.returncode, f"rsync falhou: {(r.stderr or '').strip()[-200:]}")


def logrotate(perfil: str) -> tuple[int, str]:
    conf = Path.home() / ".config" / "logrotate" / f"jfn-{perfil}.conf"
    estado = Path.home() / ".local" / "state" / "jfn-logrotate.state"
    if not conf.is_file():
        return 1, f"jfn-{perfil}.conf ausente"
    r = subprocess.run(["nice", "-n", "19", "ionice", "-c3", "/usr/sbin/logrotate", "-s", str(estado), str(conf)],
                       capture_output=True, text=True, timeout=900)
    return (0, f"perfil {perfil} rodado") if r.returncode == 0 else \
        (r.returncode, f"logrotate rc={r.returncode}: {(r.stderr or '').strip()[-200:]}")


def nuvens() -> tuple[int, str]:
    script = Path.home() / "bin" / "nuvens-manter-vivas.sh"
    if not script.is_file():
        return 1, "nuvens-manter-vivas.sh ausente"
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=1800)
    return (0, "sessões renovadas (detalhe no log próprio do script)") if r.returncode == 0 else \
        (r.returncode, f"script rc={r.returncode}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.rotinas_infra")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("graphify_retencao", "graph_report_brain", "nuvens"):
        sub.add_parser(n)
    lr = sub.add_parser("logrotate")
    lr.add_argument("--perfil", required=True, choices=["vm1", "vm2"])
    a = ap.parse_args(argv)
    rc, msg = {"graphify_retencao": graphify_retencao, "graph_report_brain": graph_report_brain,
               "nuvens": nuvens}[a.cmd]() if a.cmd != "logrotate" else logrotate(a.perfil)
    print(f"rotinas_infra {a.cmd}: {'ok' if rc == 0 else 'FALHOU'} — {msg}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
