# -*- coding: utf-8 -*-
"""Amostra independente (23/11/2026): sorteio estratificado por nó produtor (taxa + ≥1/nó/dia + teto), leitura feita
por uma máquina que NÃO produziu a entrega (it-campo → lida na VM-2; VM-2 → lida na VM-1), e a VM-1 só compara."""
from __future__ import annotations

import json
import os

import pytest

import tools.vm2_conferencia as C
import tools.vm2_lote as L
from tests.test_vm2_conferencia import TEXTO, _isolar, _pasta

ITC, VM2 = "Jorge", "JFN-Agent-2"


@pytest.fixture(autouse=True)
def _no_neutro(monkeypatch):
    """25/11/2026: o hostname do WSL do it-campo É "Jorge" (= ITC) — lá a entrega "de outra máquina" virava a do
    próprio nó e era pulada (3 testes falhavam só no it-campo). O teste roda como um nó que não é nenhum dos dois."""
    real = os.uname()
    neutro = type(real)((real.sysname, "no-de-teste", real.release, real.version, real.machine))
    monkeypatch.setattr(os, "uname", lambda: neutro)


@pytest.fixture
def d(monkeypatch, tmp_path):
    base = _isolar(monkeypatch, tmp_path)
    monkeypatch.setattr(C, "SORTEIO", base / "sorteio.json")
    monkeypatch.setenv("JFN_VM2_AMOSTRA", "estratificada")
    return base


def _fila(d):
    return json.loads((d / "amostra.json").read_text(encoding="utf-8"))


def _procs(n, ini=0):
    return [f"100000/{i:06d}/2025" for i in range(ini, ini + n)]


def test_sorteio_taxa_minimo_por_no_e_teto(d, monkeypatch):
    monkeypatch.setattr(C, "AMOSTRA_MAX_DIA", 30)
    C.enfileirar_amostra(_procs(1000), ITC)
    C.enfileirar_amostra(_procs(1, 5000), VM2)              # um só do dia: entra pelo mínimo, sorteado ou não
    por_no = {}
    for e in _fila(d):
        por_no[e["origem"]] = por_no.get(e["origem"], 0) + 1
    assert 10 <= por_no[ITC] <= 30 and por_no[VM2] == 1     # ~3% de 1.000, nunca acima do teto
    C.enfileirar_amostra(_procs(2000, 10000), ITC)
    assert sum(1 for e in _fila(d) if e["origem"] == ITC) == 30   # teto do dia


def test_sorteio_e_reprodutivel():
    assert [C._sorteado(p) for p in _procs(300)] == [C._sorteado(p) for p in _procs(300)]


def test_chave_desligada_enfileira_tudo_no_formato_antigo(d, monkeypatch):
    monkeypatch.setenv("JFN_VM2_AMOSTRA", "fifo")
    C.enfileirar_amostra(_procs(5), ITC)
    assert _fila(d) == _procs(5)                             # lista de números: o código antigo continua lendo


def test_exportar_nunca_manda_ao_produtor_nem_o_que_cabe_a_vm1(d):
    (d / "amostra.json").write_text(json.dumps(
        ["999999/000001/2025",                               # formato antigo: origem desconhecida ⇒ VM-1
         {"proc": "100000/000001/2025", "origem": ITC},
         {"proc": "100000/000002/2025", "origem": VM2},
         {"proc": "100000/000003/2025", "origem": ITC}]), encoding="utf-8")
    assert [e["proc"] for e in C.amostra_exportar(VM2, 1)] == ["100000/000001/2025"]
    assert [e["proc"] for e in C.amostra_exportar(VM2, 5)] == ["100000/000003/2025"]   # despachado não sai de novo
    assert C.amostra_exportar(ITC, 5) == []                 # o it-campo não lê a própria entrega; a da VM-2 é da VM-1


def _lida(titulos, texto=TEXTO):
    return {"documentos": [{"titulo": t} for t in titulos],
            "conteudo_documentos": [{"doc": t, "conteudo": texto} for t in titulos[:2]]}


def test_lote_amostra_confere_diverge_e_recusa_leitor_produtor(d):
    for t in ("100000_000011_2025", "100000_000012_2025", "100000_000013_2025"):
        _pasta(d / "sei_arquivo", t)
    titulos = [f"Despacho {i} ({1000 + i})" for i in range(3)]
    (d / "amostra.json").write_text(json.dumps(
        [{"proc": f"100000/0000{i}/2025", "origem": ITC, "despachado": 1e12} for i in (11, 12, 13)]), encoding="utf-8")
    eu = os.uname().nodename                                 # o lote sai com a origem desta máquina (o "leitor")
    base = L.montar("amostra", {}, {
        "100000/000011/2025": {"origem_entrega": ITC, "lida": _lida(titulos)},
        "100000/000012/2025": {"origem_entrega": ITC, "lida": _lida(["Contrato de obra"] * 3, "Planta baixa " * 40)},
        "100000/000013/2025": {"origem_entrega": eu, "lida": _lida(titulos)}})
    r = C.importar(base.name)
    assert r["aprovados"] == ["100000/000011/2025"]
    assert set(r["reprovados"]) == {"100000/000012/2025", "100000/000013/2025"}
    assert not (d / "sei_arquivo" / "100000_000012_2025").exists()         # divergiu ⇒ quarentena
    assert (d / "sei_arquivo" / "100000_000013_2025").exists()             # leitura do produtor não vale nada
    assert [e["proc"] for e in _fila(d)] == ["100000/000013/2025"]         # segue esperando leitor independente
    log = (d / "vm2_conferencia.log").read_text(encoding="utf-8")
    assert "100000/000011/2025: CONFERE" in log and "RECUSADA" in log


def test_leitura_indisponivel_fica_e_volta_a_ser_despachavel(d):
    _pasta(d / "sei_arquivo", "100000_000021_2025")
    (d / "amostra.json").write_text(json.dumps(
        [{"proc": "100000/000021/2025", "origem": ITC, "despachado": 1e12}]), encoding="utf-8")
    base = L.montar("amostra", {}, {"100000/000021/2025": {"origem_entrega": ITC, "lida": {"erro": "INDISPONÍVEL"}}})
    C.importar(base.name)
    assert _fila(d) == [{"proc": "100000/000021/2025", "origem": ITC}]


def test_amostra_ler_no_no_pula_a_propria_entrega_e_reduz_a_leitura(d, monkeypatch):
    import tools.sei_reader as SR
    lidos = []

    async def _ler(numero, usar_cache=True):
        lidos.append(numero)
        return {"documentos": [{"titulo": "T", "texto": "x"}] * 3,
                "conteudo_documentos": [{"doc": "T", "conteudo": "a" * 50_000}] * 9, "html": "<lixo/>"}
    monkeypatch.setattr(SR, "ler", _ler)
    monkeypatch.setattr(L, "reenviar_pendentes", lambda: [])
    enviados = []
    monkeypatch.setattr(L, "enviar", lambda base: enviados.append(base) or {"ok": 1})
    C.amostra_ler([{"proc": "100000/000031/2025", "origem": ITC},
                   {"proc": "100000/000032/2025", "origem": os.uname().nodename}])
    assert lidos == ["SEI-100000/000031/2025"]
    man = json.loads((enviados[0] / "MANIFESTO.json").read_text(encoding="utf-8"))
    lida = man["processos"]["100000/000031/2025"]["lida"]
    assert man["tipo"] == "amostra" and "html" not in lida
    assert len(lida["conteudo_documentos"]) == 6 and len(lida["conteudo_documentos"][0]["conteudo"]) == C.LIDA_MAX_CHARS


def test_vm1_so_le_o_que_cabe_a_ela(d, monkeypatch):
    import tools.sei_reader as SR
    lidos = []

    async def _ler(numero, usar_cache=True):
        lidos.append(numero)
        return {"erro": "INDISPONÍVEL: teste"}
    monkeypatch.setattr(SR, "ler", _ler)
    (d / "amostra.json").write_text(json.dumps(
        [{"proc": "100000/000041/2025", "origem": ITC}, {"proc": "100000/000042/2025", "origem": VM2}]),
        encoding="utf-8")
    C.amostra(2)
    assert lidos == ["SEI-100000/000042/2025"]


def test_reduzir_guarda_o_original_e_estratifica(d, monkeypatch):
    original = _procs(200) + _procs(10, 900)
    (d / "amostra.json").write_text(json.dumps(original), encoding="utf-8")
    imp = d / "vm2_entrega" / "_importados"
    imp.mkdir(parents=True)
    for nome, ori, procs in (("integras-20261122-1", ITC, _procs(200)), ("integras-20261122-2", VM2, _procs(10, 900))):
        (imp / f"{nome}.json").write_text(json.dumps(
            {"origem": ori, "conferencia": {"aprovados": {p: {} for p in procs}}}), encoding="utf-8")
    monkeypatch.setenv("JFN_VM2_AMOSTRA", "fifo")
    with pytest.raises(SystemExit):
        C.reduzir_fila_amostra(aplicar=True)
    monkeypatch.setenv("JFN_VM2_AMOSTRA", "estratificada")
    r = C.reduzir_fila_amostra(aplicar=True)
    assert r["por_no"] == {ITC: [200, 6], VM2: [10, 1]}
    assert json.loads((d / "amostra.json.bak-20261123").read_text()) == original
    assert {e["origem"] for e in _fila(d)} == {ITC, VM2} and len(_fila(d)) == 7
