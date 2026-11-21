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
    assert avaliar_integracao([preso], [], 60.0) == []                       # poucos presos e disco folgado: nada
    (p,) = avaliar_integracao([pode, preso], [], 60.0)        # integrado sai sempre, sem esperar o disco (decisão 6)
    assert p["assinatura"] == "integracao:worktrees" and "integracao_conferir worktrees --aplicar" in p["remediar"]
    (p,) = avaliar_integracao([pode, preso], [], 94.0)
    assert p["assinatura"] == "integracao:worktrees" and "integracao_conferir worktrees --aplicar" in p["remediar"]
    (p,) = avaliar_integracao([preso] * 10, [], 60.0)
    assert p["assinatura"] == "integracao:worktrees_presos" and not p["remediar"]
    (p,) = avaliar_integracao([], ["tools/x.py"], 60.0)
    assert p["assinatura"] == "integracao:remocao_em_stage" and not p["remediar"] and "tools/x.py" in p["detalhe"]


# ── decisão 6 (20/11/2026): só sai worktree cujo trabalho já está no HEAD ──────────────────────────────────
def _commit_no_agente(w, nome="novo.py", txt="x = 1\n"):
    (w / nome).write_text(txt)
    _git(w, "add", nome)
    _git(w, "commit", "-qm", f"agente cria {nome}")


def _por_branch(repo):
    return {w["branch"]: w for w in I.worktrees(repo, agora=time.time() + 13 * 3600, horas=12)}


def test_worktree_com_commit_fora_do_head_nao_sai(repo):
    _commit_no_agente(_agente(repo, "solto"))
    w = _por_branch(repo)["worktree-solto"]
    assert w["sujo"] == 0 and w["processos"] == 0 and w["integrado"] is None and not w["pode_sair"]


def test_worktree_cuja_ponta_esta_no_head_sai(repo):
    w = _agente(repo, "merge")
    _commit_no_agente(w)
    _git(repo, "merge", "-q", "--no-edit", "worktree-merge")
    item = _por_branch(repo)["worktree-merge"]
    assert item["integrado"] == "ancestral" and item["pode_sair"]
    assert I.remover([item], repo) == [str(w)] and not w.exists()
    assert "worktree-merge" in subprocess.run(["git", "branch", "--list"], cwd=repo, capture_output=True,
                                              text=True).stdout              # a branch fica


def test_worktree_integrado_por_patch_sai_e_patch_parcial_fica(repo):
    w = _agente(repo, "patch")
    _commit_no_agente(w, "a.py", "a = 1\n")
    _commit_no_agente(w, "b.py", "b = 2\n")
    (repo / "a.py").write_text("a = 1\n")                    # integração por patch: só o a.py chegou
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-qm", "integra a.py")
    assert _por_branch(repo)["worktree-patch"]["integrado"] is None          # b.py ainda só no agente
    (repo / "b.py").write_text("b = 2\n")
    (repo / "outro.py").write_text("# o HEAD andou com outra coisa\n")
    _git(repo, "add", "b.py", "outro.py")
    _git(repo, "commit", "-qm", "integra b.py e segue")
    item = _por_branch(repo)["worktree-patch"]
    assert item["integrado"] == "aplicado" and item["pode_sair"]


def test_worktree_destacado_so_sai_se_ancestral(repo):
    w = repo / ".claude" / "worktrees" / "solto"
    _git(repo, "worktree", "add", "-q", "--detach", str(w))
    _commit_no_agente(w, "a.py", "a = 1\n")
    (repo / "a.py").write_text("a = 1\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-qm", "conteúdo igual, commit diferente")
    (item,) = I.worktrees(repo, agora=time.time() + 13 * 3600, horas=12)
    assert "branch" not in item and item["integrado"] is None and not item["pode_sair"]   # sem branch, o commit sumiria
