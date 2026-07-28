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
    """Com o guard sourceado, o mesmo comando alcança o barramento do usuário.

    Exige o serviço `jfn.service` instalado: só a VM que o roda pode responder isto. Em
    máquina de processamento é `skip` — o guard não tem barramento a restaurar, e cobrar
    dele o contrário seria testar o ambiente, não o guard.
    """
    # A checagem roda no ambiente NORMAL, não em `_rodar` — este simula o ambiente pelado do
    # cron (sem XDG_RUNTIME_DIR), que é exatamente a doença que o guard cura. Perguntar ali se
    # o serviço existe daria "não" numa máquina onde ele está ativo, e o skip mascararia a
    # falha real. Primeira versão deste guard fez isso; o skip apareceu na VM que roda o
    # serviço.
    existe = subprocess.run(["systemctl", "--user", "list-unit-files", "jfn.service"],
                            capture_output=True, text=True)
    if existe.returncode != 0 or "jfn.service" not in existe.stdout:
        pytest.skip("jfn.service não instalado nesta máquina — nada que o guard deva alcançar")
    r = _rodar(f'. "{HELPER}" && systemctl --user is-active jfn.service')
    assert r.returncode == 0, f"guard não restaurou o barramento: {r.stderr.strip()}"
    assert r.stdout.strip() in {"active", "activating", "inactive", "failed"}


def _scripts_do_cron() -> list[Path]:
    """Scripts de tools/ que o crontab do dono chama.

    Sem o binário `crontab` (máquina de processamento, contêiner), isto é `skip` declarado e
    não falha: o teste afirma algo sobre a VM de produção, e ausência de crontab não é
    violação da regra — é ausência do objeto examinado.
    """
    try:
        crontab = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        pytest.skip("sem o binário `crontab` nesta máquina — nada de cron a examinar")
    achados = set()
    for linha in crontab.splitlines():
        if linha.lstrip().startswith("#"):
            continue
        for caminho in re.findall(r"\S*/JFN/tools/\S+\.sh", linha):
            p = Path(caminho)
            if p.exists():
                achados.add(p)
    return sorted(achados)


def usa_systemctl_user(texto: str) -> bool:
    """`systemctl --user` EXECUTADO — comentário que só o menciona não conta.

    `sweep_fiscalizacao_247.sh` documenta, num comentário, como desligar o timer da VM-2
    ("`systemctl --user disable --now jfn-sweeps.timer`"). O teste lia o arquivo inteiro como
    texto e acusava um script que não executa nada disso: zero ocorrências fora de comentário.
    Explicar um comando na documentação do script não é rodá-lo — é a mesma armadilha de
    contar o enunciado como resposta.
    """
    return any("systemctl --user" in linha
               for linha in (texto or "").splitlines()
               if not linha.lstrip().startswith("#"))


def test_todo_script_de_cron_que_reinicia_servico_carrega_o_guard():
    scripts = _scripts_do_cron()
    if not scripts:
        pytest.skip("crontab sem scripts de tools/ (máquina não é a VM de produção)")
    faltando = [
        p.name
        for p in scripts
        if usa_systemctl_user(p.read_text()) and "systemd_user_env.sh" not in p.read_text()
    ]
    assert not faltando, f"scripts de cron usam systemctl --user sem o guard: {faltando}"


def test_comentario_que_so_documenta_o_comando_nao_conta():
    texto = "#!/bin/bash\n# Para desligar: `systemctl --user disable --now jfn-sweeps.timer`\necho ok\n"
    assert usa_systemctl_user(texto) is False


def test_comando_de_verdade_continua_sendo_pego():
    assert usa_systemctl_user("#!/bin/bash\nsystemctl --user restart jfn.service\n") is True


def test_comando_indentado_tambem_e_pego():
    assert usa_systemctl_user("if [ -f x ]; then\n    systemctl --user restart jfn\nfi\n") is True
