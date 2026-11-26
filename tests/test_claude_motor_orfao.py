# -*- coding: utf-8 -*-
"""O9.0 frente B (26/11/2026): o CLI da assinatura não sobrevive a quem o chamou.

`_executar_cli` sobe o CLI em sessão própria (para matar o grupo no prazo). Quando o chamador morre de SIGKILL — o
governador, o lease perdido, a parada do supervisor e o teto do `legado` matam o grupo do JOB, não o do CLI — o
`claude -p` seguia vivo, órfão no escopo, gastando a assinatura e furando o teto `assinatura_claude` da reserva."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PR_SET_PDEATHSIG é do Linux")


def _vivo(pid: int) -> bool:
    try:
        st = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return st != "Z"


def test_cli_morre_quando_o_chamador_morre_de_sigkill(tmp_path):
    pidf = tmp_path / "cli.pid"
    chamador = (
        "import sys; from pathlib import Path\n"
        "from compliance_agent.llm import claude_motor as M\n"
        f"M._executar_cli(['bash', '-c', 'echo $$ > {pidf}; exec sleep 120'], '', {{}}, Path('{tmp_path}'), 300)\n")
    p = subprocess.Popen([sys.executable, "-c", chamador], cwd=RAIZ,
                         env={**os.environ, "PYTHONPATH": str(RAIZ)}, start_new_session=True)
    try:
        for _ in range(100):
            if pidf.exists() and pidf.read_text().strip():
                break
            time.sleep(0.1)
        cli = int(pidf.read_text())
        assert _vivo(cli)
        os.killpg(p.pid, signal.SIGKILL)          # o grupo do chamador (o que o supervisor mata), não o do CLI
        p.wait(timeout=10)
        for _ in range(50):
            if not _vivo(cli):
                break
            time.sleep(0.1)
        assert not _vivo(cli), "CLI órfão: sobreviveu ao SIGKILL de quem o chamou"
    finally:
        if pidf.exists():
            try:
                os.kill(int(pidf.read_text()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass


def test_prazo_estourado_segue_matando_o_grupo(tmp_path):
    from compliance_agent.llm import claude_motor as M
    with pytest.raises(subprocess.TimeoutExpired):
        M._executar_cli(["sleep", "30"], "", dict(os.environ), tmp_path, 0.5)
