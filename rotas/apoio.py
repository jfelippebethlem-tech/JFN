# -*- coding: utf-8 -*-
"""O que mais de um módulo de rotas precisa e não é rota: a raiz do repo e o Python que roda os scripts dela.

Sem router — `server.py` só inclui os módulos de rota. Cada coisa daqui existia copiada em dois arquivos de rota.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def python_do_repo() -> str:
    """`.venv` do repositório quando existe; senão o intérprete que serve a rota — o venv limpo da rotina noturna e
    da VM-2 não tem `.venv` no repositório, e o caminho fixo dava 500 (15/11/2026)."""
    py = RAIZ / ".venv" / "bin" / "python"
    return str(py) if py.exists() else sys.executable


# ── Pausa dos sweeps ────────────────────────────────────────────────────────────────────────────────────────────
# Protocolo por ARQUIVO, lido por existência: `.pause_sweeps` (todos os scripts do cron), `.pause_sei_sweep`
# (`tools/sei_sweep.py` checa a cada processo; `sei_supervisor.sh`), `.pause_sweep_<n>` (`siafe_supervisor.sh`).
# Duas pausas usam os mesmos arquivos: a do RELATÓRIO (produtos competem pela CPU) e a MANUAL (botão do painel,
# scripts como `tools/ler_medviva_fserj.sh`). O relatório marca no conteúdo as flags que ELE criou e só apaga essas
# — até 20/11/2026 apagava a lista inteira e desfazia a pausa manual do SEI ao fim de qualquer relatório.
DATA = RAIZ / "data"
_PAUSA_RELATORIO = (".pause_sweep_2", ".pause_sweep_1", ".pause_sei_sweep")
_PAUSA_PAINEL = (".pause_sweeps", ".pause_sei_sweep")
_MARCA_RELATORIO = "relatorio\n"
_SWEEPS_PESADOS = ("tools[.]sei_sweep", "siafe[_]sweep_full")   # colchete: o padrão não casa o próprio pgrep


def _encerrar(padrao: str) -> None:
    """SIGTERM por PID a quem casa `padrao` — regra 8 da casa: `pgrep` + `kill` por PID, nunca o pkill por padrão."""
    import os
    import signal
    import subprocess
    out = subprocess.run(["pgrep", "-f", padrao], capture_output=True, text=True, timeout=5, check=False).stdout
    for pid in (int(p) for p in out.split() if p.isdigit()):
        if pid != os.getpid():
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass                                    # terminou entre o pgrep e o kill


def pausar_para_relatorio() -> None:
    for nome in _PAUSA_RELATORIO:
        f = DATA / nome
        if not f.exists():
            f.write_text(_MARCA_RELATORIO, encoding="utf-8")
    for padrao in _SWEEPS_PESADOS:
        _encerrar(padrao)


def retomar_apos_relatorio() -> None:
    for nome in _PAUSA_RELATORIO:
        f = DATA / nome
        try:
            if f.read_text(encoding="utf-8") == _MARCA_RELATORIO:
                f.unlink(missing_ok=True)
        except FileNotFoundError:
            continue


def pausar_pelo_painel() -> None:
    """A pausa manual é dona das suas flags: sobrescreve a marca de um relatório em curso, que então não as apaga."""
    for nome in _PAUSA_PAINEL:
        (DATA / nome).write_text("painel\n", encoding="utf-8")


def retomar_pelo_painel() -> None:
    for nome in _PAUSA_PAINEL:
        (DATA / nome).unlink(missing_ok=True)


def sei_pausado() -> bool:
    """O que as telas de status chamam de "pausado": o SEI parado pela flag própria ou o SIAFE 2 pela dele."""
    return (DATA / ".pause_sei_sweep").exists() or (DATA / ".pause_sweep_2").exists()
