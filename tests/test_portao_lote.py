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
    """Saída no contrato do portao_no.sh; `comportamento[k]` ∈ ok | teto | sem_resumo | coleta_parcial | falha_ambiente
    | vazio (1º arquivo sem caso no junit, lote limpo) | zero (idem, e o `--co` do nó confirmou 0 itens)."""
    testes, par = _cab(script, "TESTES").split(), int(_cab(script, "PAR"))
    out, final = [], 0
    for k in range(1, par + 1):
        lote = [t for i, t in enumerate(testes) if i % par == k - 1]
        if not lote:
            continue
        c = comportamento.get(k, "ok")
        if c == "teto":
            final = 1
            out += [f"PORTAO_LOTE {k} rc=124 ", f"PORTAO_COLETA {k} 0 {' '.join(lote)}", f"PORTAO_VISTOS {k} ",
                    f"PORTAO_FALHA lote {k}: TETO de 2340 s estourado (não terminou)"]
        elif c == "sem_resumo":
            out += [f"PORTAO_LOTE {k} rc=0 ", f"PORTAO_COLETA {k} {len(lote)} {' '.join(lote)}",
                    f"PORTAO_VISTOS {k} {' '.join(lote)}"]
        elif c == "coleta_parcial":           # nó antigo, sem PORTAO_VISTOS: regra tudo-ou-nada do lote
            out += [f"PORTAO_LOTE {k} rc=0 7 passed in 1.0s", f"PORTAO_COLETA {k} {len(lote) - 1} {' '.join(lote)}"]
        elif c in ("vazio", "zero"):
            out += [f"PORTAO_LOTE {k} rc=0 7 passed in 1.0s", f"PORTAO_COLETA {k} {len(lote) - 1} {' '.join(lote)}",
                    f"PORTAO_VISTOS {k} {' '.join(lote[1:])}"]
            if c == "zero":
                out.append(f"PORTAO_ZERO {k} {lote[0]}")
        elif c == "falha_ambiente":
            final = 1
            out += [f"PORTAO_LOTE {k} rc=1 1 failed, 4 passed in 1.0s",
                    f"PORTAO_COLETA {k} {len(lote)} {' '.join(lote)}", f"PORTAO_VISTOS {k} {' '.join(lote)}",
                    f"PORTAO_FALHA FAILED {lote[0]}::t - sem unzip"]
        else:
            out += [f"PORTAO_LOTE {k} rc=0 {3 * len(lote)} passed in 1.0s",
                    f"PORTAO_COLETA {k} {len(lote)} {' '.join(lote)}", f"PORTAO_VISTOS {k} {' '.join(lote)}"]
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


@pytest.mark.parametrize("defeito, n", [("teto", 4), ("sem_resumo", 4), ("coleta_parcial", 4), ("vazio", 1)])
def test_no_unico_que_nao_termina_reprova_e_nunca_aprova(monkeypatch, defeito, n):
    """`vazio` sem 2ª rodada (nenhum outro nó, `--co` não confirmou 0 itens) reprova só o arquivo sem caso."""
    monkeypatch.setattr(portao, "_rodar", FakeNos(vm2=[{1: defeito}]))
    v = portao.executar(SHA, _testes(4))
    assert v.estado == "reprovado" and v.motivo.startswith(f"não medido: {n} arquivo(s)")
    assert v.sem_casos == []


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


# ── por arquivo (25/11): UM arquivo sem caso não derruba o lote; "sem casos" só com 2 rodadas limpas ──────────────
def test_lote_conta_por_arquivo_com_vistos():
    r = _interp(["PORTAO_LOTE 1 rc=0 12 passed in 2s", "PORTAO_COLETA 1 2 tests/a.py tests/b.py tests/c.py",
                 "PORTAO_VISTOS 1 tests/a.py tests/c.py"], ["tests/a.py", "tests/b.py", "tests/c.py"])
    assert r.estado == "ok"
    assert r.nao_medidos == ["tests/b.py"] and r.vazios == ["tests/b.py"] and r.sem_casos == []


def test_vazio_confirmado_pelo_co_vira_sem_casos():
    r = _interp(["PORTAO_LOTE 1 rc=0 12 passed in 2s", "PORTAO_COLETA 1 1 tests/a.py tests/b.py",
                 "PORTAO_VISTOS 1 tests/a.py", "PORTAO_ZERO 1 tests/b.py"], ["tests/a.py", "tests/b.py"])
    assert r.estado == "ok" and r.nao_medidos == [] and r.sem_casos == ["tests/b.py"]


@pytest.mark.parametrize("visto", ["./tests/b.py", "/home/ubuntu/JFN-portao-run/x/w1/tests/b.py", "tests//b.py"])
def test_caminho_com_ponto_absoluto_ou_relativo_casa(visto):
    r = _interp(["PORTAO_LOTE 1 rc=0 4 passed in 1s", "PORTAO_COLETA 1 2 tests/a.py ./tests/b.py",
                 f"PORTAO_VISTOS 1 tests/a.py {visto}"], ["tests/a.py", "./tests/b.py"])
    assert r.nao_medidos == [] and r.vazios == []


@pytest.mark.parametrize("lote", [
    ["PORTAO_LOTE 1 rc=124 9 passed", "PORTAO_COLETA 1 2 tests/a.py tests/b.py", "PORTAO_VISTOS 1 tests/a.py tests/b.py",
     "PORTAO_ZERO 1 tests/b.py"],                                                     # TETO
    ["PORTAO_LOTE 1 rc=0 ", "PORTAO_COLETA 1 2 tests/a.py tests/b.py", "PORTAO_VISTOS 1 tests/a.py tests/b.py",
     "PORTAO_ZERO 1 tests/b.py"],                                                     # sem resumo
    ["PORTAO_LOTE 1 rc=5 no tests ran in 0.01s", "PORTAO_COLETA 1 0 tests/a.py tests/b.py", "PORTAO_VISTOS 1 ",
     "PORTAO_ZERO 1 tests/b.py"],                                                     # "no tests ran"
])
def test_teto_sem_resumo_continuam_nao_medidos_mesmo_com_vistos_e_zero(lote):
    r = _interp(lote, ["tests/a.py", "tests/b.py"], fim=1)
    assert r.nao_medidos == ["tests/a.py", "tests/b.py"] and r.sem_casos == [] and r.vazios == []


def test_arquivo_ausente_de_lote_com_falha_nao_e_candidato_a_sem_casos():
    """rc=1 (erro de coleta interrompe a sessão): o ausente é só pendente, nunca "sem casos"."""
    r = _interp(["PORTAO_LOTE 1 rc=1 1 failed, 3 passed in 1s", "PORTAO_COLETA 1 1 tests/a.py tests/b.py",
                 "PORTAO_VISTOS 1 tests/a.py", "PORTAO_ZERO 1 tests/b.py", "PORTAO_FALHA FAILED tests/a.py::t"],
                ["tests/a.py", "tests/b.py"], fim=1)
    assert r.estado == "falhou" and r.nao_medidos == ["tests/b.py"] and r.sem_casos == [] and r.vazios == []


def test_caso_de_25_11_um_arquivo_sem_casos_nao_derruba_os_71(monkeypatch, capsys):
    """VM-2, 71 arquivos, 683 passed, e tests/test_goal_modes_smoke.py (script sem test_*) fora do junit: antes os 71
    iam a "não medido"; agora 70 medidos e o script é "sem casos" (junit vazio + `--co` 0 itens), listado."""
    todos = _testes(71)
    monkeypatch.setattr(portao, "_rodar", FakeNos(vm2=[{1: "zero"}]))
    v = portao.executar(SHA, todos)
    assert v.estado == "aprovado", v.motivo
    assert v.sem_casos == [todos[0]]
    portao._imprimir(v)
    assert f"sem casos: 1 arquivo(s): {todos[0]}" in capsys.readouterr().out


def test_vazio_em_dois_nos_vira_sem_casos(monkeypatch):
    """Sem confirmação do `--co`: vazio no it-campo, refeito na VM-2, vazio de novo → 2 rodadas limpas em nós
    diferentes → "sem casos"; os demais arquivos do lote seguem medidos no it-campo."""
    fake = FakeNos(vm2=[{1: "vazio"}], itcampo=[{1: "vazio"}])
    monkeypatch.setattr(portao, "_rodar", fake)
    todos = _testes(4)
    monkeypatch.setattr(portao, "NOS", (portao.NOS[1], portao.NOS[0]))     # it-campo primeiro: parte única nele
    v = portao.executar(SHA, todos)
    assert fake.chamadas["itcampo"] == [todos] and fake.chamadas["vm2"] == [[todos[0]]]
    assert v.estado == "aprovado", v.motivo
    assert v.sem_casos == [todos[0]]


def test_vazio_que_o_outro_no_executa_e_medido_nao_sem_casos(monkeypatch):
    fake = FakeNos(vm2=[{}], itcampo=[{1: "vazio"}])
    monkeypatch.setattr(portao, "_rodar", fake)
    monkeypatch.setattr(portao, "NOS", (portao.NOS[1], portao.NOS[0]))
    v = portao.executar(SHA, _testes(4))
    assert v.estado == "aprovado" and v.sem_casos == []


def _snippet(nome: str) -> str:
    corpo = (RAIZ / "tools" / "portao_no.sh").read_text(encoding="utf-8")
    m = re.search(rf"^{nome}='(.*?)'$", corpo, re.S | re.M)
    assert m, f"portao_no.sh sem {nome}"
    assert "PORTAO_VISTOS" in corpo and "PORTAO_ZERO" in corpo and "--co -q" in corpo
    return m.group(1)


def test_vistos_do_no_normaliza_caminho_e_devolve_nome_enviado(tmp_path):
    xml = tmp_path / "j.xml"
    xml.write_text(f'<testsuites><testsuite><testcase file="./tests/a.py" name="t1"/><testcase '
                   f'file="{tmp_path}/tests/b.py" name="t2"/><testcase name="sem_file"/></testsuite></testsuites>',
                   encoding="utf-8")
    cod = _snippet("_VISTOS")

    def vistos(arq, *lote):
        return subprocess.run([sys.executable, "-c", cod, str(arq), *lote], capture_output=True, text=True,
                              check=True, cwd=tmp_path).stdout.split()

    assert vistos(xml, "tests/a.py", "./tests/b.py", "tests/c.py") == ["tests/a.py", "./tests/b.py"]
    assert vistos(tmp_path / "nao_existe.xml", "tests/a.py") == []


# ── carga do nó (25/11): acelerador saturado não recebe lote; teto proporcional; vigia de progresso ───────────────
class FakeCarga(FakeNos):
    """FakeNos com a resposta da sonda por nó (`PORTAO_VIVO <nproc> <load1> <psi>`) e o registro dos tetos."""

    def __init__(self, sondas: dict[str, str], **roteiro):
        super().__init__(**roteiro)
        self.sondas = sondas
        self.tetos: dict[str, list[tuple[int, int]]] = {}      # nó → [(timeout do ssh, TETO do cabeçalho)]

    def __call__(self, argv, script, timeout):
        no = "vm2" if "vm2-ts" in argv else "itcampo"
        if script.startswith("echo PORTAO_VIVO") and no in self.roteiro:
            return 0, self.sondas.get(no, "PORTAO_VIVO 24") + "\n"
        if no in self.roteiro:
            self.tetos.setdefault(no, []).append((timeout, int(_cab(script, "TETO"))))
        return super().__call__(argv, script, timeout)


def test_sonda_real_do_bash_e_lida(monkeypatch):
    monkeypatch.setattr(portao, "_rodar", lambda argv, script, timeout: (
        0, subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30).stdout))
    sd = portao.sondar(portao.NOS[0])
    assert sd.vivo and sd.nproc and sd.nproc >= 1 and sd.load is not None


@pytest.mark.parametrize("saida, alem", [
    ("PORTAO_VIVO 24 27.0 0.00", "load 27.0/24 = 1.12 > 1.00"),
    ("PORTAO_VIVO 24 3.0 75.10", "PSI cpu some avg10 75% > 60%"),
    ("PORTAO_VIVO 24 3.0 12.00", ""),
    ("PORTAO_VIVO 24 3.0", ""),                       # sem /proc/pressure: vale o load
    ("PORTAO_VIVO 24", ""),                           # sonda antiga: carga não medida, não pula (e diz)
])
def test_sobrecarga_pelo_limiar(monkeypatch, saida, alem):
    monkeypatch.setattr(portao, "_rodar", lambda argv, script, timeout: (0, saida + "\n"))
    sd = portao.sondar(portao.NOS[1])
    assert sd.vivo and sd.sobrecarga() == alem
    if saida == "PORTAO_VIVO 24":
        assert sd.carga() == "carga não medida"


def test_itcampo_saturado_e_pulado_e_registrado_no_log(monkeypatch):
    todos = _testes(portao.LIMIAR_PARALELO + 60)
    fake = FakeCarga({"itcampo": "PORTAO_VIVO 24 27.3 80.0", "vm2": "PORTAO_VIVO 2 0.4 3.0"}, vm2=[{}], itcampo=[{}])
    monkeypatch.setattr(portao, "_rodar", fake)
    monkeypatch.setattr(portao.portao_grafo, "selecionar", lambda repo, base, sha: type(
        "S", (), {"mudados": ["x.py"], "testes": todos, "motivos": {}})())
    monkeypatch.setattr(portao, "_git", lambda *a, **k: "")
    monkeypatch.setattr(portao, "_custo", lambda repo, sha, testes: {})
    v = portao.medir(RAIZ, "a" * 40, SHA)
    assert v.estado == "aprovado"
    assert "itcampo" not in fake.chamadas and fake.chamadas["vm2"] == [todos]     # nenhum lote foi ao it-campo
    assert v.pulados == ["itcampo pulado: carga PSI cpu some avg10 80% > 60%"]
    assert "itcampo pulado: carga PSI cpu some avg10 80% > 60%" in portao.LOG.read_text(encoding="utf-8")


def test_referencia_sobrecarregada_nunca_e_pulada(monkeypatch):
    fake = FakeCarga({"vm2": "PORTAO_VIVO 2 8.0 70.0"}, vm2=[{}], itcampo=[{}])
    monkeypatch.setattr(portao, "_rodar", fake)
    v = portao.executar(SHA, _testes(4))
    assert v.estado == "aprovado" and v.pulados == [] and fake.chamadas["vm2"] == [_testes(4)]


def test_acelerador_saturado_unico_vivo_vai_assim_mesmo(monkeypatch):
    fake = FakeCarga({"itcampo": "PORTAO_VIVO 24 27.0 80.0"}, itcampo=[{}])
    monkeypatch.setattr(portao, "_rodar", fake)
    v = portao.executar(SHA, _testes(4))
    assert v.estado == "aprovado" and fake.chamadas["itcampo"] == [_testes(4)]


def test_teto_proporcional_ao_lote(monkeypatch):
    monkeypatch.setattr(portao, "TETO_BASE", 300)
    monkeypatch.setattr(portao, "TETO_POR_ARQ", 4.0)
    monkeypatch.setattr(portao, "TETO_NO", 2400)
    assert portao.teto_lote(71, 1) == 300 + 4 * 71
    assert portao.teto_lote(1111, 6) == 300 + 4 * 186          # o maior lote (ceil 1111/6)
    assert portao.teto_lote(1040, 1) == 2400                   # nunca acima do TETO_NO
    assert portao.teto_lote(3, 6) == 304                       # PAR efetivo = min(paralelo, arquivos)
    fake = FakeCarga({}, vm2=[{}])
    monkeypatch.setattr(portao, "_rodar", fake)
    portao.executar(SHA, _testes(10))
    assert fake.tetos["vm2"] == [(340 + portao.MARGEM_SSH, 340)]


def test_lote_abortado_por_parado_e_nao_medido_e_refeito(monkeypatch):
    """O nó diz rc=124 do lote parado (vigia): conta como não medido e vai para o outro nó, como o TETO."""
    r = _interp(["PORTAO_LOTE 1 rc=124 ", "PORTAO_COLETA 1 0 tests/a.py", "PORTAO_VISTOS 1 ",
                 "PORTAO_FALHA lote 1: parado — log sem crescer por 600 s (abortado, não terminou)"],
                ["tests/a.py"], fim=1)
    assert r.nao_medidos == ["tests/a.py"]


def _vigiar() -> str:
    corpo = (RAIZ / "tools" / "portao_no.sh").read_text(encoding="utf-8")
    m = re.search(r"^# >>> vigiar\n(.*?)^# <<< vigiar$", corpo, re.S | re.M)
    assert m, "portao_no.sh sem a função vigiar entre marcadores"
    assert "PYTHONUNBUFFERED=1" in corpo and '"$BASE_RUN/parado$k" ] && r=124' in corpo
    return m.group(1)


def test_vigia_aborta_lote_parado_e_poupa_o_que_anda(tmp_path):
    """Lote 1: processo vivo que não escreve (parado) → morto, parado1 gravado. Lote 2: escreve sempre → intacto
    até terminar sozinho. Lote 3: já terminou (rc3). A função sai quando todos têm rc."""
    script = _vigiar() + """
BASE_RUN=$1; PAR=3; PARADO=2; VIGIA_PASSO=1
: > "$BASE_RUN/log1"; : > "$BASE_RUN/log2"; echo 0 > "$BASE_RUN/rc3"
( sleep 60 & echo $! > "$BASE_RUN/pid1"; wait $!; echo $? > "$BASE_RUN/rc1" ) &
( for i in $(seq 1 8); do echo . >> "$BASE_RUN/log2"; sleep 1; done & echo $! > "$BASE_RUN/pid2"; wait $!
  echo 0 > "$BASE_RUN/rc2" ) &
t0=$(date +%s)
vigiar
echo "seg=$(( $(date +%s) - t0 ))"
"""
    r = subprocess.run(["bash", "-c", script, "vigia", str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "parado1").exists() and not (tmp_path / "parado2").exists()
    assert (tmp_path / "rc2").read_text().strip() == "0"
    assert int(r.stdout.split("seg=")[1]) < 30                 # não esperou os 60 s do processo parado
