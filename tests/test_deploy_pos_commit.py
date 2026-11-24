# -*- coding: utf-8 -*-
"""Deploy pós-commit (tools/deploy_pos_commit.sh, 24/11/2026): reinicia o jfn.service só quando o commit toca
código do servidor, confere 200 e, se falhar, grava o estado que o sensor `deploy` da automelhoria lê — sem laço."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path, http: str) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    (repo / "rotas").mkdir(parents=True)
    (repo / "data").mkdir()
    env0 = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    g = lambda *a: subprocess.run(["git", *a], cwd=repo, env=env0, check=True, capture_output=True)  # noqa: E731
    g("init", "-q")
    (repo / "docs.md").write_text("a")
    g("add", "docs.md"); g("commit", "-qm", "base")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "systemctl").write_text(f"#!/bin/bash\necho \"$@\" >> {tmp_path}/systemctl.log\n")
    (fake / "curl").write_text(f"#!/bin/bash\nprintf {http}\n")
    for f in fake.iterdir():
        f.chmod(0o755)
    src = (RAIZ / "tools" / "deploy_pos_commit.sh").read_text().replace("cd /home/ubuntu/JFN", f"cd {repo}")
    (tmp_path / "deploy.sh").write_text(src)
    env = dict(env0, PATH=f"{fake}:/usr/bin:/bin", DEPLOY_ESPERA_S="0", DEPLOY_SAUDE_S="0", XDG_RUNTIME_DIR="/tmp")
    return repo, dict(env, _g=g)


def _rodar(tmp_path, env):
    e = {k: v for k, v in env.items() if k != "_g"}
    return subprocess.run(["bash", str(tmp_path / "deploy.sh")], env=e, timeout=60)


def test_commit_so_de_docs_nao_reinicia(tmp_path):
    repo, env = _repo(tmp_path, "200")
    (repo / "docs.md").write_text("b")
    env["_g"]("commit", "-qam", "docs")
    assert _rodar(tmp_path, env).returncode == 0
    assert not (tmp_path / "systemctl.log").exists()


def test_commit_em_rotas_reinicia_e_confere_200(tmp_path):
    repo, env = _repo(tmp_path, "200")
    (repo / "rotas" / "x.py").write_text("x = 1")
    env["_g"]("add", "rotas/x.py"); env["_g"]("commit", "-qm", "rota")
    assert _rodar(tmp_path, env).returncode == 0
    assert "restart jfn.service" in (tmp_path / "systemctl.log").read_text()
    est = json.loads((repo / "data" / "deploy_estado.json").read_text())
    assert est["ok"] is True
    assert not (repo / "data" / ".deploy_em_curso").exists()      # a marca que pausa os caches sai no fim
    assert (repo / "data" / "deploy_ultimo_commit.txt").exists()
    os.remove(tmp_path / "systemctl.log")
    assert _rodar(tmp_path, env).returncode == 0                   # mesmo HEAD: não reinicia de novo
    assert not (tmp_path / "systemctl.log").exists()


def test_saude_ruim_grava_falha_sem_laco_e_o_sensor_acusa(tmp_path):
    repo, env = _repo(tmp_path, "500")
    (repo / "rotas" / "x.py").write_text("x = 1")
    env["_g"]("add", "rotas/x.py"); env["_g"]("commit", "-qm", "rota quebrada")
    assert _rodar(tmp_path, env).returncode == 0
    est = json.loads((repo / "data" / "deploy_estado.json").read_text())
    assert est["ok"] is False and "500" in est["motivo"]
    assert (tmp_path / "systemctl.log").read_text().count("restart") == 1
    from tools.automelhoria_geral import sensor_deploy
    itens = sensor_deploy(repo / "data" / "deploy_estado.json")
    assert [i["assinatura"] for i in itens] == ["deploy:falhou"]
    assert sensor_deploy(tmp_path / "nao_existe.json") == []
