"""
Cron não enxerga o barramento do systemd --user.

O cron roda com um ambiente mínimo (sem XDG_RUNTIME_DIR nem DBUS_SESSION_BUS_ADDRESS),
então `systemctl --user ...` falha com "Failed to connect to bus: No medium found" —
e falha SILENCIOSAMENTE dentro de um script `set -u` sem `set -e`. Foi assim que o
vigia do "database disk image is malformed" registrou 68 reinícios de jfn.service em
2026-07-23 sem que UM sequer acontecesse (journal mostra 2 starts no dia inteiro).

Regra da casa (§ "0 sem erro" é a pior falha): quem manda reiniciar precisa conferir
que reiniciou. Aqui a catraca é anterior — garantir que o comando sequer alcança o
systemd quando chamado pelo cron.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
HELPER = RAIZ / "tools" / "lib" / "systemd_user_env.sh"

# Ambiente que o cron entrega (man 5 crontab): só HOME, LOGNAME, PATH e SHELL.
ENV_CRON = {
    "HOME": os.path.expanduser("~"),
    "LOGNAME": os.environ.get("LOGNAME", "ubuntu"),
    "PATH": "/usr/bin:/bin",
    "SHELL": "/bin/sh",
}


def _rodar(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script], env=ENV_CRON, capture_output=True, text=True, timeout=30
    )


def test_ambiente_do_cron_realmente_quebra_systemctl_user():
    """Prova do defeito: sem o guard, o comando não chega no systemd."""
    r = _rodar("systemctl --user is-active jfn.service")
    assert r.returncode != 0
    assert "bus" in (r.stderr + r.stdout).lower()


def test_helper_existe_e_e_sourceavel():
    assert HELPER.exists(), f"falta o guard de ambiente: {HELPER}"


def test_helper_faz_systemctl_user_funcionar_sob_cron():
    """Com o guard sourceado, o mesmo comando alcança o barramento do usuário."""
    r = _rodar(f'. "{HELPER}" && systemctl --user is-active jfn.service')
    assert r.returncode == 0, f"guard não restaurou o barramento: {r.stderr.strip()}"
    assert r.stdout.strip() in {"active", "activating", "inactive", "failed"}


def _scripts_do_cron() -> list[Path]:
    """Scripts de tools/ que o crontab do dono chama."""
    crontab = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True
    ).stdout
    achados = set()
    for linha in crontab.splitlines():
        if linha.lstrip().startswith("#"):
            continue
        for caminho in re.findall(r"\S*/JFN/tools/\S+\.sh", linha):
            p = Path(caminho)
            if p.exists():
                achados.add(p)
    return sorted(achados)


def test_todo_script_de_cron_que_reinicia_servico_carrega_o_guard():
    scripts = _scripts_do_cron()
    if not scripts:
        pytest.skip("crontab sem scripts de tools/ (máquina não é a VM de produção)")
    faltando = [
        p.name
        for p in scripts
        if "systemctl --user" in p.read_text() and "systemd_user_env.sh" not in p.read_text()
    ]
    assert not faltando, f"scripts de cron usam systemctl --user sem o guard: {faltando}"
