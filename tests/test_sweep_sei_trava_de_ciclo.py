# -*- coding: utf-8 -*-
"""O cron abria um ciclo por cima do anterior, e cada colisão queimava 10 minutos.

`sweep_sei.sh` roda `*/30` e diz no cabeçalho que "roda SOZINHO" — mas o único guard testava
`pgrep -f 'tools\\.sei_swee[p]'`, que enxerga só o PRIMEIRO estágio. Quando o ciclo anterior está
num estágio posterior (sei_cpf, refichar, depurar), o pgrep não vê nada, o novo ciclo entra e
fica 600s parado no `browser_lock` até morrer com "não adquiriu em 600s (outro browser ativo)".

Medido em 2026-08-04: **406 ocorrências** dessa mensagem no log, 4 a 10 por dia — ~10 minutos de
sweep perdidos em cada uma, com a fila de captura em anos de atraso.

A trava é por PID em arquivo, NÃO `flock`: um flock em descritor é herdado pelos filhos, e um
chromium órfão que sobreviva a um SIGKILL do Python seguraria o lock para sempre — o sweep
pararia calado, que é pior que a contenção que se quer resolver. Com PID, o ciclo morto (ou o PID
reciclado por outro comando) simplesmente libera.
"""
import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "sweep_sei.sh"

# O bloco da trava, extraído do script real — o teste roda a MESMA lógica que o cron roda.
_GUARD = '''#!/bin/bash
set -u
PIDF="$1"
say(){ echo "$*"; }
'''


def _bloco_do_script() -> str:
    src = SCRIPT.read_text(encoding="utf-8")
    ini = src.index('PIDF=data/.sweep_sei.pid')
    fim = src.index("trap 'rm -f \"$PIDF\"' EXIT")
    return src[ini:fim].replace('PIDF=data/.sweep_sei.pid', '') + '\necho $$ > "$PIDF"\necho SEGUE\n'


def _rodar(tmp_path, pid_no_arquivo=None) -> str:
    guard = tmp_path / "guard.sh"
    guard.write_text(_GUARD + _bloco_do_script(), encoding="utf-8")
    pidf = tmp_path / "ciclo.pid"
    if pid_no_arquivo is not None:
        pidf.write_text(str(pid_no_arquivo), encoding="utf-8")
    r = subprocess.run(["bash", str(guard), str(pidf)], capture_output=True, text=True, timeout=30)
    return (r.stdout + r.stderr).strip()


def test_sem_ciclo_anterior_o_sweep_segue(tmp_path):
    assert "SEGUE" in _rodar(tmp_path)


def test_pid_morto_nao_trava_o_sweep_para_sempre(tmp_path):
    """Ciclo que morreu (OOM, SIGKILL, reboot) não pode deixar a fila parada — é justamente o
    modo de falha que o `flock` teria introduzido."""
    assert "SEGUE" in _rodar(tmp_path, pid_no_arquivo=999999)


def test_pid_reciclado_por_outro_comando_nao_trava(tmp_path):
    """PID vivo mas de um processo que NÃO é o sweep: o cmdline desmente o arquivo."""
    p = subprocess.Popen(["sleep", "20"])
    try:
        assert "SEGUE" in _rodar(tmp_path, pid_no_arquivo=p.pid)
    finally:
        p.kill()


def test_ciclo_anterior_VIVO_faz_o_novo_pular(tmp_path):
    """O caso que custava 600s: o ciclo anterior existe, em qualquer estágio."""
    p = subprocess.Popen(["bash", "-c",
                          'exec -a "bash /home/ubuntu/JFN/tools/sweep_sei.sh" sleep 20'])
    try:
        time.sleep(0.5)
        saida = _rodar(tmp_path, pid_no_arquivo=p.pid)
        assert "ainda rodando" in saida and "SEGUE" not in saida
    finally:
        p.kill()


def test_a_trava_libera_no_fim_do_ciclo():
    """`trap ... EXIT` tem de existir: sem ele o primeiro ciclo trava todos os seguintes."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "trap 'rm -f \"$PIDF\"' EXIT" in src


def test_nao_usa_flock_em_descritor():
    """Registro explícito da decisão: fd herdado por chromium órfão seguraria o lock para sempre.

    Verifica USO, não menção — o comentário do script explica justamente por que não se usa flock.
    """
    codigo = [ln.split("#", 1)[0].strip()
              for ln in SCRIPT.read_text(encoding="utf-8").splitlines()]
    assert not [ln for ln in codigo if ln.startswith("flock ") or "exec 9>" in ln]
