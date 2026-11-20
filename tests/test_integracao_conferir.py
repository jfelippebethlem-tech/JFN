# -*- coding: utf-8 -*-
"""Integração do trabalho de agentes: a remoção que o patch fez tem de chegar, e worktree esquecido tem de sair.

As duas falhas são de 20/11/2026: 14 arquivos "apagados" seguiram no repositório (o commit filtrava os caminhos por
"existe no disco") e 45 worktrees (14 GB) encheram o disco a 100%. Aqui o repositório é de mentira, em tmp_path."""
import subprocess
import time

import pytest

from tools import integracao_conferir as I


def _git(repo, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    for nome in ("fica.py", "sai.py", "renomeia.py"):
        (r / nome).write_text(f"# {nome}\n" * 30)
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    return r


def _agente(repo, nome="a1"):
    w = repo / ".claude" / "worktrees" / nome
    _git(repo, "worktree", "add", "-q", "-b", f"worktree-{nome}", str(w))
    return w


def test_remocao_do_agente_que_nao_chegou_e_apontada(repo):
    w = _agente(repo)
    _git(w, "rm", "-q", "sai.py")
    _git(w, "mv", "renomeia.py", "novo_nome.py")
    (w / "fica.py").write_text("# mudou\n")
    _git(w, "commit", "-qam", "agente apaga, renomeia e muda")
    # a integração que errou: levou o conteúdo novo e deixou a origem das remoções
    (repo / "fica.py").write_text("# mudou\n")
    (repo / "novo_nome.py").write_text("# renomeia.py\n" * 30)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "integra (errado)")
    assert I.remocoes_pendentes("worktree-a1", "HEAD", repo) == ["renomeia.py", "sai.py"]
    _git(repo, "rm", "-q", "sai.py", "renomeia.py")
    assert I.remocoes_em_stage(repo) == ["renomeia.py", "sai.py"]          # parada no índice: ainda não chegou
    _git(repo, "commit", "-qm", "integra as remoções")
    assert I.remocoes_pendentes("worktree-a1", "HEAD", repo) == [] and I.remocoes_em_stage(repo) == []


def test_worktree_so_sai_limpo_parado_e_sem_uso(repo):
    limpo, sujo = _agente(repo, "limpo"), _agente(repo, "sujo")
    (sujo / "rascunho.py").write_text("x = 1\n")
    depois = time.time() + 7 * 3600
    por_nome = {w["branch"]: w for w in I.worktrees(repo, agora=depois, horas=6)}
    assert por_nome["worktree-limpo"]["pode_sair"] and not por_nome["worktree-sujo"]["pode_sair"]
    assert not any(w["pode_sair"] for w in I.worktrees(repo, horas=6))     # recém-criado nunca sai
    feitos = I.remover(list(por_nome.values()), repo)
    assert feitos == [str(limpo)] and not limpo.exists() and (sujo / "rascunho.py").exists()
    branches = subprocess.run(["git", "branch", "--list"], cwd=repo, capture_output=True, text=True).stdout
    assert "worktree-limpo" in branches                                      # os commits do agente ficam


def test_worktree_com_processo_dentro_nao_sai(repo):
    w = _agente(repo, "vivo")
    p = subprocess.Popen(["sleep", "30"], cwd=w)
    try:
        (item,) = I.worktrees(repo, agora=time.time() + 99 * 3600, horas=6)
        assert item["processos"] >= 1 and not item["pode_sair"]
    finally:
        p.kill()
        p.wait()


def test_sensor_da_automelhoria_remedia_worktree_e_escala_remocao():
    from tools.automelhoria_geral import avaliar_integracao
    pode = {"caminho": "/r/.claude/worktrees/a", "pode_sair": True, "sujo": 0, "parado_h": 20.0, "processos": 0}
    preso = {"caminho": "/r/.claude/worktrees/b", "pode_sair": False, "sujo": 3, "parado_h": 1.0, "processos": 0}
    assert avaliar_integracao([pode, preso], [], 60.0) == []                 # poucos e disco folgado: não é problema
    (p,) = avaliar_integracao([pode, preso], [], 94.0)
    assert p["assinatura"] == "integracao:worktrees" and "integracao_conferir worktrees --aplicar" in p["remediar"]
    (p,) = avaliar_integracao([preso] * 10, [], 60.0)
    assert p["assinatura"] == "integracao:worktrees_presos" and not p["remediar"]
    (p,) = avaliar_integracao([], ["tools/x.py"], 60.0)
    assert p["assinatura"] == "integracao:remocao_em_stage" and not p["remediar"] and "tools/x.py" in p["detalhe"]
