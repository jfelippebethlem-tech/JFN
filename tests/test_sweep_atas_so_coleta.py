# -*- coding: utf-8 -*-
"""O9.0 frente B (26/11/2026): a rotina `sweep_atas_julgamento` é E1 (coletar), mas o script também derivava —
`backfill_dossie_mestre` (certame_julgamento), `coletor_propostas --backfill` (proposta_item) e
`indice_certame.calcular_e_persistir`, que grava `caso` (E14, tipo_achado='direcionamento'). Com só E1–E7 liberados,
o job E1 escrevia tabelas de E10/E14 por fora da liberação. Modo `coleta` (2º argumento) = só o passo 1."""
import os
import re
import stat
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "tools" / "sweep_atas_julgamento.sh"


def _rodar(tmp_path: Path, *args: str) -> list[str]:
    raiz = tmp_path / "jfn"
    (raiz / ".venv" / "bin").mkdir(parents=True)
    (raiz / "data").mkdir()
    (raiz / "tools" / "lib").mkdir(parents=True)
    chamadas = raiz / "chamadas.txt"
    py = raiz / ".venv" / "bin" / "python"
    py.write_text(f'#!/bin/bash\necho "$*" >> {chamadas}\ncat >/dev/null 2>&1 || true\n')
    py.chmod(py.stat().st_mode | stat.S_IEXEC)
    texto = SCRIPT.read_text(encoding="utf-8").replace("cd /home/ubuntu/JFN", f"cd {raiz}")
    texto = texto.replace("/tmp/sweep_atas_julgamento.lock", str(tmp_path / "trava"))
    copia = raiz / "tools" / "sweep_atas_julgamento.sh"
    copia.write_text(texto, encoding="utf-8")
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}"}
    (tmp_path / "bin").mkdir()
    for nome in ("nice", "ionice"):                   # sem prioridade no teste: só repassa o comando
        b = tmp_path / "bin" / nome
        b.write_text('#!/bin/bash\nwhile [[ "$1" == -* || "$1" =~ ^[0-9]+$ ]]; do shift; done\nexec "$@"\n')
        b.chmod(0o755)
    r = subprocess.run(["bash", str(copia), *args], cwd=raiz, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return chamadas.read_text().splitlines() if chamadas.exists() else []


def test_modo_coleta_so_baixa_as_atas(tmp_path):
    feitas = _rodar(tmp_path, "50", "coleta")
    assert feitas == ["-m compliance_agent.collectors.atas_julgamento 50"]


def test_sem_modo_segue_o_comportamento_antigo(tmp_path):
    feitas = _rodar(tmp_path, "50")
    assert any(re.search(r"backfill_dossie_mestre", f) for f in feitas)
    assert any("coletor_propostas" in f for f in feitas)



def test_modo_coleta_devolve_o_rc_da_coleta(tmp_path):
    raiz = tmp_path / "jfn"
    _rodar(tmp_path, "1", "coleta")                       # monta a árvore falsa
    (raiz / ".venv" / "bin" / "python").write_text("#!/bin/bash\nexit 5\n")
    r = subprocess.run(["bash", str(raiz / "tools" / "sweep_atas_julgamento.sh"), "1", "coleta"], cwd=raiz,
                       env={**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}"}, capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 5                              # coleta que falha = job que falha
