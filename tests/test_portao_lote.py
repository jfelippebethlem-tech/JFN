# -*- coding: utf-8 -*-
"""Portão v2 (tools/portao.py, O2.5): lote que não terminou NUNCA conta como ok — "0 execuções não é 0 erros".

25/11/2026: o lote 5 do it-campo (173 arquivos, load 27 no nó) estourou o TETO. A linha de falha dele não tinha
nodeid; a confirmação na VM-2 refez só os arquivos COM nodeid dos outros lotes, trocou as falhas pelas dela e o
portão disse "aprovado" sem ter executado os 173. Aqui o ssh é falso (`portao._rodar`) e o nó responde lote a lote
como o tools/portao_no.sh: com TETO, sem linha de resumo, com coleta parcial. O que se prova: o arquivo não medido é
refeito no outro nó e, se ninguém terminar, o portão REPROVA com "não medido: N arquivo(s)".
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools import portao

SHA = "b" * 40
RAIZ = Path(__file__).resolve().parent.parent


def _cab(script: str, nome: str) -> str:
    linha = next(ln for ln in script.splitlines() if ln.startswith(f"{nome}="))
    return linha.split("=", 1)[1].strip("'")


def _saida_do_no(script: str, comportamento: dict[int, str]) -> str:
    """Saída no contrato do portao_no.sh; `comportamento[k]` ∈ ok | teto | sem_resumo | coleta_parcial | falha_ambiente."""
    testes, par = _cab(script, "TESTES").split(), int(_cab(script, "PAR"))
    out, final = [], 0
    for k in range(1, par + 1):
        lote = [t for i, t in enumerate(testes) if i % par == k - 1]
        if not lote:
            continue
        c = comportamento.get(k, "ok")
        if c == "teto":
            final = 1
            out += [f"PORTAO_LOTE {k} rc=124 ", f"PORTAO_COLETA {k} 0 {' '.join(lote)}",
                    f"PORTAO_FALHA lote {k}: TETO de 2340 s estourado (não terminou)"]
        elif c == "sem_resumo":
            out += [f"PORTAO_LOTE {k} rc=0 ", f"PORTAO_COLETA {k} {len(lote)} {' '.join(lote)}"]
        elif c == "coleta_parcial":
            out += [f"PORTAO_LOTE {k} rc=0 7 passed in 1.0s", f"PORTAO_COLETA {k} {len(lote) - 1} {' '.join(lote)}"]
        elif c == "falha_ambiente":
            final = 1
            out += [f"PORTAO_LOTE {k} rc=1 1 failed, 4 passed in 1.0s",
                    f"PORTAO_COLETA {k} {len(lote)} {' '.join(lote)}", f"PORTAO_FALHA FAILED {lote[0]}::t - sem unzip"]
        else:
            out += [f"PORTAO_LOTE {k} rc=0 {3 * len(lote)} passed in 1.0s",
                    f"PORTAO_COLETA {k} {len(lote)} {' '.join(lote)}"]
    return "\n".join([*out, f"PORTAO_FIM rc={final}", ""])


class FakeNos:
    """`roteiro[no]` = lista de comportamentos por chamada (o último se repete); cada um é {lote: comportamento}."""

    def __init__(self, **roteiro):
        self.roteiro = roteiro
        self.chamadas: dict[str, list[list[str]]] = {}

    def __call__(self, argv, script, timeout):
        no = "vm2" if "vm2-ts" in argv else "itcampo"
        if no not in self.roteiro:
            return 255, "ssh: connect to host: Connection timed out"
        if script.startswith("echo PORTAO_VIVO"):
            return 0, "PORTAO_VIVO 24\n"
        feitas = self.chamadas.setdefault(no, [])
        feitas.append(_cab(script, "TESTES").split())
        passos = self.roteiro[no]
        return 0, _saida_do_no(script, passos[min(len(feitas), len(passos)) - 1])


def _testes(n):
    return [f"tests/test_{i:03d}.py" for i in range(n)]


@pytest.fixture(autouse=True)
def _log(tmp_path, monkeypatch):
    monkeypatch.setattr(portao, "LOG", tmp_path / "portao.log")


# ── interpretar: o que é lote medido ─────────────────────────────────────────────────────────────────────────────
def _interp(linhas: list[str], testes: list[str], fim: int = 0) -> portao.Resultado:
    return portao.interpretar("itcampo", testes, 0, "\n".join([*linhas, f"PORTAO_FIM rc={fim}", ""]))


def test_lote_com_teto_nao_e_medido():
    r = _interp(["PORTAO_LOTE 1 rc=0 4 passed in 1s", "PORTAO_COLETA 1 2 tests/a.py tests/b.py",
                 "PORTAO_LOTE 2 rc=124 ", "PORTAO_COLETA 2 0 tests/c.py tests/d.py",
                 "PORTAO_FALHA lote 2: TETO de 2340 s estourado (não terminou)"],
                ["tests/a.py", "tests/b.py", "tests/c.py", "tests/d.py"], fim=1)
    assert r.nao_medidos == ["tests/c.py", "tests/d.py"]
    assert "não medido" in r.motivo


def test_lote_com_teto_mesmo_com_resumo_e_coleta_cheia_nao_e_medido():
    r = _interp(["PORTAO_LOTE 1 rc=124 9 passed", "PORTAO_COLETA 1 1 tests/a.py"], ["tests/a.py"], fim=1)
    assert r.nao_medidos == ["tests/a.py"]


def test_lote_sem_linha_de_resumo_nao_e_medido():
    r = _interp(["PORTAO_LOTE 1 rc=0 ", "PORTAO_COLETA 1 1 tests/a.py"], ["tests/a.py"])
    assert r.nao_medidos == ["tests/a.py"]
    r = _interp(["PORTAO_LOTE 1 rc=5 no tests ran in 0.01s", "PORTAO_COLETA 1 0 tests/a.py"], ["tests/a.py"])
    assert r.nao_medidos == ["tests/a.py"]                       # "no tests ran" não é resumo de execução


def test_lote_com_coleta_parcial_nao_e_medido():
    r = _interp(["PORTAO_LOTE 1 rc=0 12 passed in 2s", "PORTAO_COLETA 1 2 tests/a.py tests/b.py tests/c.py"],
                ["tests/a.py", "tests/b.py", "tests/c.py"])
    assert r.nao_medidos == ["tests/a.py", "tests/b.py", "tests/c.py"]


def test_lote_sem_linha_de_coleta_e_arquivo_fora_de_todo_lote_nao_sao_medidos():
    r = _interp(["PORTAO_LOTE 1 rc=0 3 passed in 1s"], ["tests/a.py"])
    assert r.nao_medidos == ["tests/a.py"]
    r = _interp(["PORTAO_LOTE 1 rc=0 3 passed in 1s", "PORTAO_COLETA 1 1 tests/a.py"], ["tests/a.py", "tests/z.py"])
    assert r.nao_medidos == ["tests/z.py"]


def test_lote_completo_e_medido():
    r = _interp(["PORTAO_LOTE 1 rc=0 3 passed, 1 skipped in 1s", "PORTAO_COLETA 1 2 tests/a.py tests/b.py"],
                ["tests/a.py", "tests/b.py"])
    assert r.estado == "ok" and r.nao_medidos == []


def test_lote_medido_com_rc_de_erro_sem_nodeid_continua_falha():
    r = _interp(["PORTAO_LOTE 1 rc=1 3 passed in 1s", "PORTAO_COLETA 1 1 tests/a.py",
                 "PORTAO_LOTE 2 rc=124 ", "PORTAO_COLETA 2 0 tests/b.py"], ["tests/a.py", "tests/b.py"], fim=1)
    assert r.estado == "falhou" and r.nao_medidos == ["tests/b.py"]


# ── executar: a parte não medida é refeita; se ninguém terminar, reprova ──────────────────────────────────────────
def test_caso_de_25_11_teto_no_itcampo_e_falha_de_ambiente_refaz_na_vm2(monkeypatch):
    """O cenário exato: lote 5 com TETO, outro lote com falha só de ambiente. Antes: aprovado sem os 173."""
    todos = _testes(portao.LIMIAR_PARALELO + 60)
    fake = FakeNos(vm2=[{}], itcampo=[{5: "teto", 3: "falha_ambiente"}])
    monkeypatch.setattr(portao, "_rodar", fake)
    v = portao.executar(SHA, todos, custo={t: 100 for t in todos})
    assert v.estado == "aprovado", v.motivo
    parte_it = fake.chamadas["itcampo"][0]
    lote5 = [t for i, t in enumerate(parte_it) if i % 6 == 4]
    assert lote5 in fake.chamadas["vm2"]                          # os do TETO foram executados na VM-2
    assert not any(r.nao_medidos for r in v.resultados)


def test_teto_nos_dois_nos_reprova_nao_medido(monkeypatch):
    todos = _testes(portao.LIMIAR_PARALELO + 60)
    fake = FakeNos(vm2=[{}, {1: "teto"}], itcampo=[{5: "teto"}])
    monkeypatch.setattr(portao, "_rodar", fake)
    v = portao.executar(SHA, todos, custo={t: 100 for t in todos})
    lote5 = [t for i, t in enumerate(fake.chamadas["itcampo"][0]) if i % 6 == 4]
    assert v.estado == "reprovado"
    assert v.motivo.startswith(f"não medido: {len(lote5)} arquivo(s)")


@pytest.mark.parametrize("defeito", ["teto", "sem_resumo", "coleta_parcial"])
def test_no_unico_que_nao_termina_reprova_e_nunca_aprova(monkeypatch, defeito):
    monkeypatch.setattr(portao, "_rodar", FakeNos(vm2=[{1: defeito}]))
    v = portao.executar(SHA, _testes(4))
    assert v.estado == "reprovado" and v.motivo.startswith("não medido: 4 arquivo(s)")


def test_vm2_nao_termina_e_o_itcampo_refaz(monkeypatch):
    fake = FakeNos(vm2=[{1: "sem_resumo"}], itcampo=[{}])
    monkeypatch.setattr(portao, "_rodar", fake)
    v = portao.executar(SHA, _testes(4))
    assert v.estado == "aprovado"
    assert fake.chamadas["itcampo"] == [_testes(4)]


def test_confirmacao_que_nao_termina_nao_vira_ok(monkeypatch):
    """Falha do it-campo refeita na VM-2: se a VM-2 não terminar, a falha fica (bloquear é o lado seguro)."""
    todos = _testes(portao.LIMIAR_PARALELO + 10)
    fake = FakeNos(vm2=[{}, {1: "teto"}], itcampo=[{2: "falha_ambiente"}])
    monkeypatch.setattr(portao, "_rodar", fake)
    v = portao.executar(SHA, todos, custo={t: 100 for t in todos})
    assert v.estado == "reprovado"


# ── o nó: a contagem do junit que alimenta PORTAO_COLETA ─────────────────────────────────────────────────────────
def _snippet_coleta() -> str:
    corpo = (RAIZ / "tools" / "portao_no.sh").read_text(encoding="utf-8")
    m = re.search(r"^_COLETA='(.*?)'$", corpo, re.S | re.M)
    assert m, "portao_no.sh sem o contador de coleta"
    assert "--junitxml" in corpo and "junit_family=xunit1" in corpo and "PORTAO_COLETA" in corpo
    return m.group(1)


def test_contador_do_no_conta_arquivo_com_caso_e_zero_sem_junit(tmp_path):
    xml = tmp_path / "j.xml"
    xml.write_text('<testsuites><testsuite><testcase file="tests/a.py" name="t1"/><testcase file="tests/a.py" '
                   'name="t2"/><testcase file="tests/b.py" name="x"><skipped/></testcase></testsuite></testsuites>',
                   encoding="utf-8")
    cod = _snippet_coleta()

    def contar(arq, *lote):
        return subprocess.run([sys.executable, "-c", cod, str(arq), *lote], capture_output=True, text=True,
                              check=True).stdout.strip()

    assert contar(xml, "tests/a.py", "tests/b.py", "tests/c.py") == "2"
    assert contar(tmp_path / "nao_existe.xml", "tests/a.py") == "0"          # TETO: pytest morto não grava junit
    (tmp_path / "quebrado.xml").write_text("<testsuites><testcase", encoding="utf-8")
    assert contar(tmp_path / "quebrado.xml", "tests/a.py") == "0"
