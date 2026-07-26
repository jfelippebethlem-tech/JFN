"""
`. .env` no cron não carrega nada — e mata a linha inteira, calada.

O crontab não declara `SHELL=`, então o cron usa `/bin/sh` = dash. E o `.` do dash
segue o POSIX ao pé da letra: procura o arquivo **só no $PATH**, nunca no diretório
atual (o bash é que tem o fallback para o cwd). Como `.env` não tem barra, dá
`.: .env: not found` — e um `.` que falha em shell não-interativo **encerra a shell**.
Resultado: o `python` depois do `;` nunca roda e o `>> data/xxx.log` nunca cria o log.

Foi assim que dois crons ficaram 100% mortos sem deixar rastro — o `tools.pipelines_slo
--alerta` (o vigia HORÁRIO de todos os pipelines, quem dispara o Telegram) e o
`tools.obra_fase_sei`. O sintoma que denuncia é o log que NUNCA existiu; e o dano em
cascata é o vermelho que ninguém viu: `pcrj-fisc-refresh` com 366h contra SLO de 192h.

Regra da casa (§ "0 sem erro" é a pior falha): testar do jeito que a produção executa —
à mão, no bash, as duas linhas passavam. Correção: sourcear com caminho (`. ./.env`).
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
MARCA = "CHEGUEI-AO-PYTHON"

# Ambiente que o cron entrega (man 5 crontab): só HOME, LOGNAME, PATH e SHELL.
ENV_CRON = {
    "HOME": os.path.expanduser("~"),
    "LOGNAME": os.environ.get("LOGNAME", "ubuntu"),
    "PATH": "/usr/bin:/bin",
    "SHELL": "/bin/sh",
}

# `.` ou `source` no início da linha ou depois de ; && || ( — captura o alvo.
FONTE = re.compile(r"(?:^|[;&(]|\|\|)\s*(?:\.|source)\s+(\S+)")


def _sh(script: str) -> subprocess.CompletedProcess:
    """Roda como o cron roda: /bin/sh (dash), ambiente mínimo."""
    return subprocess.run(
        ["/bin/sh", "-c", script], env=ENV_CRON, capture_output=True, text=True, timeout=30
    )


def test_dash_nao_acha_env_sem_barra():
    """Prova do defeito: `. .env` não carrega e ainda derruba o resto da linha."""
    r = _sh(f'cd "{RAIZ}" && set -a; . .env; set +a; echo {MARCA}')
    assert "not found" in (r.stderr + r.stdout), "dash deveria recusar `.env` sem barra"
    assert MARCA not in r.stdout, (
        "a shell deveria ter morrido no `.` — se a marca apareceu, o dash mudou "
        "de comportamento e a catraca abaixo perdeu o sentido"
    )


def test_com_barra_a_linha_sobrevive():
    """A correção: caminho relativo explícito faz o dash achar e seguir em frente."""
    r = _sh(f'cd "{RAIZ}" && set -a; . ./.env; set +a; echo {MARCA}')
    assert MARCA in r.stdout, f"`. ./.env` deveria funcionar no dash: {r.stderr.strip()}"


def _linhas_do_cron() -> list[str]:
    crontab = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    return [
        linha
        for linha in crontab.splitlines()
        # "JFN" solto, não "/JFN/": as linhas que interessam dizem `cd /home/ubuntu/JFN &&`,
        # sem barra depois — filtrar com barra deixava o teste verde sem olhar nada.
        if linha.strip() and not linha.lstrip().startswith("#") and "JFN" in linha
    ]


def test_nenhum_cron_sourceia_arquivo_sem_caminho():
    """Catraca: no cron, todo source precisa de barra — senão o dash não acha."""
    linhas = _linhas_do_cron()
    if not linhas:
        pytest.skip("crontab sem linhas do JFN (máquina não é a VM de produção)")
    culpadas = [
        linha
        for linha in linhas
        for alvo in FONTE.findall(linha)
        if "/" not in alvo
    ]
    assert not culpadas, (
        "cron sourceia arquivo sem caminho — o dash não acha e mata a linha:\n"
        + "\n".join(culpadas)
    )
