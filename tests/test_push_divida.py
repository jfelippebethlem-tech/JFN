# -*- coding: utf-8 -*-
"""Executor do portão v2 e push_divida (tools/portao.py, tools/push_divida.py — O2.5) com o ssh FALSO.

O único ponto que fala com os nós é `portao._rodar`; aqui ele é trocado por um fake que responde como VM-2/it-campo
vivos, mortos, com teste falhando ou caindo no meio. O que se prova: push sem nó NÃO passa (bloqueia e registra), a
parte de um nó caído vai para o outro, seleção grande é dividida, e `drenar` só empurra pelo `git push` normal.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools import portao, portao_grafo, push_divida

SHA = "a" * 40


class FakeSSH:
    """Responde pelo nome do host no argv. `estado[no]` ∈ vivo | morto | falha | cai_no_meio."""

    def __init__(self, **estado):
        self.estado = estado
        self.scripts: dict[str, list[str]] = {}

    def __call__(self, argv, script, timeout):
        no = "vm2" if "vm2-ts" in argv else "itcampo"
        self.scripts.setdefault(no, []).append(script)
        e = self.estado.get(no, "morto")
        if e == "morto":
            return 255, "ssh: connect to host: Connection timed out"
        if script.startswith("echo PORTAO_VIVO"):
            return 0, "PORTAO_VIVO 24\n"
        if e == "cai_no_meio":
            return 255, "PORTAO_LOTE 1 rc=0 3 passed\n"                     # sem PORTAO_FIM: não conta
        if e == "falha":
            return 0, ("PORTAO_LOTE 1 rc=1 1 failed, 2 passed\nPORTAO_FALHA FAILED tests/test_x.py::t - boom\n"
                       "PORTAO_FIM rc=1\n")
        return 0, "PORTAO_LOTE 1 rc=0 3 passed in 1.0s\nPORTAO_FIM rc=0\n"


@pytest.fixture
def divida(tmp_path, monkeypatch):
    monkeypatch.setattr(push_divida, "ARQ", tmp_path / "push_divida.json")
    monkeypatch.setattr(portao, "LOG", tmp_path / "portao.log")
    return tmp_path / "push_divida.json"


def _testes(n):
    return [f"tests/test_{i:03d}.py" for i in range(n)]


def _testes_no_script(script: str) -> list[str]:
    linha = next(ln for ln in script.splitlines() if ln.startswith("TESTES="))
    return linha.split("=", 1)[1].strip("'").split()


# ── interpretar: só o contrato de linhas conta ────────────────────────────────────────────────────────────────────
def test_sem_portao_fim_e_infra_nunca_aprovacao():
    r = portao.interpretar("vm2", ["t"], 0, "PORTAO_LOTE 1 rc=0 3 passed\n")
    assert r.estado == "infra"


def test_infra_declarada_e_falha_com_nodeid():
    assert portao.interpretar("vm2", [], 90, "PORTAO_INFRA venv não montou\n").motivo == "venv não montou"
    r = portao.interpretar("vm2", [], 0, "PORTAO_FALHA FAILED tests/a.py::t\nPORTAO_FIM rc=1\n")
    assert r.estado == "falhou" and r.falhas == ["FAILED tests/a.py::t"]
    assert portao.interpretar("vm2", [], 0, "PORTAO_FIM rc=1\n").falhas      # falha sem linha FAILED não some


# ── executar: nós ────────────────────────────────────────────────────────────────────────────────────────────────
def test_nenhum_no_responde_nao_mede(monkeypatch):
    monkeypatch.setattr(portao, "_rodar", FakeSSH())
    v = portao.executar(SHA, _testes(3))
    assert v.estado == "nao_medido" and "nenhum nó" in v.motivo


def test_nos_lidos_na_hora_e_nao_presos_no_default(monkeypatch):
    """O ensaio de 24/11 trocou portao.NOS por hosts inexistentes e o executar seguiu nos reais: o default do
    parâmetro tinha congelado a tupla na definição."""
    monkeypatch.setattr(portao, "NOS", (portao.No("so_este", ("ssh", "vm2-ts"), 1, 1.0, True),))
    monkeypatch.setattr(portao, "_rodar", FakeSSH(vm2="vivo"))
    v = portao.executar(SHA, _testes(2))
    assert [r.no for r in v.resultados] == ["so_este"]


def test_selecao_pequena_vai_so_para_a_vm2(monkeypatch):
    fake = FakeSSH(vm2="vivo", itcampo="vivo")
    monkeypatch.setattr(portao, "_rodar", fake)
    v = portao.executar(SHA, _testes(5))
    assert v.estado == "aprovado" and [r.no for r in v.resultados] == ["vm2"]
    assert len(fake.scripts["itcampo"]) == 1                    # só a sonda


def test_vm2_fora_o_itcampo_assume(monkeypatch):
    monkeypatch.setattr(portao, "_rodar", FakeSSH(itcampo="vivo"))
    v = portao.executar(SHA, _testes(5))
    assert v.estado == "aprovado" and [r.no for r in v.resultados] == ["itcampo"]


def test_selecao_grande_e_dividida_entre_os_dois_sem_perder_arquivo(monkeypatch):
    fake = FakeSSH(vm2="vivo", itcampo="vivo")
    monkeypatch.setattr(portao, "_rodar", fake)
    todos = _testes(portao.LIMIAR_PARALELO + 10)
    v = portao.executar(SHA, todos, custo={t: 100 for t in todos})
    assert v.estado == "aprovado" and {r.no for r in v.resultados} == {"vm2", "itcampo"}
    enviados = [t for no in ("vm2", "itcampo") for t in _testes_no_script(fake.scripts[no][-1])]
    assert sorted(enviados) == sorted(todos)
    vm2 = len(_testes_no_script(fake.scripts["vm2"][-1]))
    assert vm2 < len(todos) / 2                                  # peso 1 × 4: o it-campo leva a maior parte


def test_no_que_cai_no_meio_tem_a_parte_refeita_no_outro(monkeypatch):
    fake = FakeSSH(vm2="cai_no_meio", itcampo="vivo")
    monkeypatch.setattr(portao, "_rodar", fake)
    todos = _testes(portao.LIMIAR_PARALELO + 4)
    v = portao.executar(SHA, todos)
    assert v.estado == "aprovado"
    refeito = _testes_no_script(fake.scripts["itcampo"][-1])
    parte_vm2 = _testes_no_script(fake.scripts["vm2"][-1])
    assert refeito == parte_vm2


def test_os_dois_caem_nao_mede(monkeypatch):
    monkeypatch.setattr(portao, "_rodar", FakeSSH(vm2="cai_no_meio", itcampo="cai_no_meio"))
    assert portao.executar(SHA, _testes(portao.LIMIAR_PARALELO + 1)).estado == "nao_medido"


def test_teste_falhando_reprova(monkeypatch):
    monkeypatch.setattr(portao, "_rodar", FakeSSH(vm2="falha", itcampo="vivo"))
    v = portao.executar(SHA, _testes(3))
    assert v.estado == "reprovado" and "tests/test_x.py::t" in v.resultados[0].falhas[0]


def test_falha_so_no_itcampo_e_confirmada_na_vm2_antes_de_reprovar(monkeypatch):
    """24/11: o WSL do it-campo não tem `unzip`; test_socio_pj_raiz falhava lá e passava na VM-2 (referência)."""
    fake = FakeSSH(vm2="vivo", itcampo="falha")
    monkeypatch.setattr(portao, "_rodar", fake)
    v = portao.executar(SHA, _testes(portao.LIMIAR_PARALELO + 5))
    assert v.estado == "aprovado"
    assert _testes_no_script(fake.scripts["vm2"][-1]) == ["tests/test_x.py"]     # só o arquivo acusado
    assert any("refeita na vm2" in r.motivo for r in v.resultados)


def test_falha_no_itcampo_sem_vm2_para_confirmar_reprova(monkeypatch):
    monkeypatch.setattr(portao, "_rodar", FakeSSH(itcampo="falha"))
    v = portao.executar(SHA, _testes(3))
    assert v.estado == "reprovado" and "sem nó de referência" in v.resultados[0].motivo


def test_script_do_no_leva_commit_ref_e_lote_limitado(monkeypatch):
    s = portao.montar_script(SHA, ["tests/a b.py"], paralelo=6, run="r1", teto=100, ref="refs/portao/r1")
    cab = dict(ln.split("=", 1) for ln in s.splitlines()[:7] if "=" in ln and ln[0].isupper())
    assert cab["SHA"] == SHA and cab["REF"] == "refs/portao/r1" and cab["PAR"] == "1"
    assert cab["TESTES"] == "'tests/a b.py'"                    # citado para o bash do nó
    assert "PORTAO_FIM" in s


def test_dividir_guloso_por_peso():
    nos = [portao.No("a", ("x",), 1, 1.0), portao.No("b", ("y",), 6, 3.0)]
    partes = portao.dividir(_testes(8), nos, {t: 10 for t in _testes(8)})
    assert sorted(partes["a"] + partes["b"]) == _testes(8)
    assert len(partes["a"]) == 2 and len(partes["b"]) == 6


# ── pre_push: o hook ─────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def repo_git(tmp_path):
    r = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / "a.txt").write_text("1", encoding="utf-8")
    for args in (["add", "a.txt"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "1"]):
        subprocess.run(["git", "-C", str(r), *args], check=True)
    sha = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return r, sha


def _preparar(monkeypatch, fake):
    monkeypatch.setattr(portao, "_rodar", fake)
    monkeypatch.setattr(portao, "_scan_pii", lambda *a: True)
    monkeypatch.setattr(portao_grafo, "selecionar",
                        lambda repo, base, sha: portao_grafo.Selecao(["tests/test_a.py"], {"grafo": 1}, ["a.py"]))


def test_push_sem_no_bloqueia_e_registra_divida(monkeypatch, divida, repo_git):
    repo, sha = repo_git
    _preparar(monkeypatch, FakeSSH())
    linha = f"refs/heads/x {sha} refs/heads/x {'0' * 40}"
    assert portao.pre_push("origin", "git@h:r.git", [linha], repo) == 1
    itens = json.loads(divida.read_text(encoding="utf-8"))
    assert [(i["commit"], i["ref_remota"], i["remoto"]) for i in itens] == [(sha, "refs/heads/x", "origin")]
    assert itens[0]["motivo"] and itens[0]["quando"]
    assert portao.pre_push("origin", "git@h:r.git", [linha], repo) == 1      # de novo: mesma entrada, +1 tentativa
    itens = json.loads(divida.read_text(encoding="utf-8"))
    assert len(itens) == 1 and itens[0]["tentativas"] == 2
    assert not list(Path(repo).joinpath(".git", "refs", "portao").glob("*"))  # ref temporária removida


def test_push_com_teste_falhando_bloqueia_sem_divida(monkeypatch, divida, repo_git):
    repo, sha = repo_git
    _preparar(monkeypatch, FakeSSH(vm2="falha"))
    assert portao.pre_push("origin", "u", [f"refs/heads/x {sha} refs/heads/x {'0' * 40}"], repo) == 1
    assert not divida.exists()


def test_push_aprovado_quita_divida_antiga(monkeypatch, divida, repo_git):
    repo, sha = repo_git
    push_divida.registrar(sha=sha, ref_local="refs/heads/x", ref_remota="refs/heads/x", remoto="origin", url="u",
                          repo=str(repo), motivo="vm2 fora")
    _preparar(monkeypatch, FakeSSH(vm2="vivo"))
    assert portao.pre_push("origin", "u", [f"refs/heads/x {sha} refs/heads/x {'0' * 40}"], repo) == 0
    assert push_divida.listar() == []


def test_remocao_de_ref_nao_testa(monkeypatch, divida, repo_git):
    repo, _ = repo_git
    _preparar(monkeypatch, FakeSSH())
    assert portao.pre_push("origin", "u", [f"(delete) {'0' * 40} refs/heads/x {'b' * 40}"], repo) == 0


# ── drenar ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _registrar(repo, sha="c" * 40):
    push_divida.registrar(sha=sha, ref_local="refs/heads/x", ref_remota="refs/heads/x", remoto="origin", url="u",
                          repo=str(repo), motivo="nenhum nó")


def test_drenar_sem_no_continua_devendo(monkeypatch, divida, tmp_path):
    _registrar(tmp_path)
    monkeypatch.setattr(portao, "_rodar", FakeSSH())
    empurrou = []
    monkeypatch.setattr(push_divida, "_empurrar", lambda it: empurrou.append(it) or 0)
    assert push_divida.drenar() == 3
    assert not empurrou and len(push_divida.listar()) == 1


def test_drenar_com_no_empurra_pelo_push_normal_e_quita(monkeypatch, divida, tmp_path):
    _registrar(tmp_path)
    monkeypatch.setattr(portao, "_rodar", FakeSSH(itcampo="vivo"))
    monkeypatch.setattr(push_divida, "ja_subiu", lambda it: False)
    empurrou = []
    monkeypatch.setattr(push_divida, "_empurrar", lambda it: empurrou.append(it["commit"]) or 0)
    assert push_divida.drenar() == 0
    assert empurrou == ["c" * 40] and push_divida.listar() == []


def test_drenar_push_recusado_fica_pendente(monkeypatch, divida, tmp_path):
    _registrar(tmp_path)
    monkeypatch.setattr(portao, "_rodar", FakeSSH(vm2="vivo"))
    monkeypatch.setattr(push_divida, "ja_subiu", lambda it: False)
    monkeypatch.setattr(push_divida, "_empurrar", lambda it: 1)
    assert push_divida.drenar() == 1
    assert len(push_divida.listar()) == 1


def test_drenar_o_que_ja_subiu_so_quita(monkeypatch, divida, tmp_path):
    _registrar(tmp_path)
    monkeypatch.setattr(portao, "_rodar", FakeSSH(vm2="vivo"))
    monkeypatch.setattr(push_divida, "ja_subiu", lambda it: True)
    monkeypatch.setattr(push_divida, "_empurrar", lambda it: pytest.fail("não devia empurrar"))
    assert push_divida.drenar() == 0 and push_divida.listar() == []


def test_empurrar_nunca_usa_no_verify(monkeypatch):
    chamadas = []
    monkeypatch.setattr(push_divida.subprocess, "run",
                        lambda argv, **kw: chamadas.append((argv, kw)) or subprocess.CompletedProcess(argv, 0))
    push_divida._empurrar({"repo": "/r", "remoto": "origin", "commit": "c" * 40, "ref_remota": "refs/heads/x"})
    argv, kw = chamadas[0]
    assert "--no-verify" not in argv and "-n" not in argv
    assert kw["env"]["JFN_PORTAO_V2"] == "1"
