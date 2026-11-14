# -*- coding: utf-8 -*-
"""VM-2 como nó de íntegras: a fila exportada segue a ordem da VM-1, a VM-1 cede a vez enquanto a VM-2 bate
o ponto, e captura vazia da VM-2 não sobrescreve arquivo com conteúdo na VM-1."""
from __future__ import annotations

import json
import os
import time

import tools.sei_integra_fila as F
import tools.sei_integra_vm2 as V


def _arquivo_bom(pasta):
    (pasta / "texto").mkdir(parents=True)
    (pasta / "texto" / "000_a.txt").write_text("x" * 100, encoding="utf-8")
    (pasta / "manifest.json").write_text(json.dumps({"docs": [{"chars": 100}], "gerado_em": "2026-11-01"}),
                                         encoding="utf-8")


def _isolar(monkeypatch, tmp_path):
    (tmp_path / "data" / "sei_arquivo").mkdir(parents=True)
    monkeypatch.setattr(F, "ARQUIVO", tmp_path / "data" / "sei_arquivo")
    monkeypatch.setattr(V, "RAIZ", tmp_path)
    monkeypatch.setattr(V, "PRE", tmp_path / "pre_ausente.json")   # sem isto lia o pré-cálculo REAL da VM-1
    monkeypatch.setattr(F, "_fila_reler_por_ob", lambda: [])
    monkeypatch.setattr(F, "_fila_inscrita", lambda: ["SEI-300000/000003/2025"])
    monkeypatch.setattr(F, "_fila_geral", lambda: [{"sei": "SEI-300000/000004/2025"}])


def test_ordem_bombeiros_dinheiro_geral_e_score_preserva_ordem(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    d = tmp_path / "data"
    (d / "bombeiros_sei_fila.json").write_text(json.dumps(
        [{"sei": "SEI-100000/000001/2025", "score": 10}, {"sei": "SEI-100000/000002/2025", "score": 40}]))
    (d / "sei_fila_dinheiro.json").write_text(json.dumps(
        [{"sei": "SEI-200000/000001/2025", "score": 9e9}, {"sei": "SEI-100000/000002/2025", "score": 1}]))
    _arquivo_bom(F.ARQUIVO / "200000_000001_2025")          # já arquivado com conteúdo: pula
    fila = V.montar_fila(10, k_bombeiros=1)
    assert [e["sei"] for e in fila] == ["SEI-100000/000002/2025", "SEI-300000/000003/2025",
                                        "SEI-300000/000004/2025"]
    assert [e["fonte"] for e in fila] == ["bombeiros", "geral", "geral"]
    # `--fila` reordena por score desc — o score tem de reproduzir a ordem exportada
    assert sorted(fila, key=lambda e: -e["score"]) == fila


def test_vazio_nao_sobrescreve_arquivo_bom(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    _arquivo_bom(F.ARQUIVO / "100000_000001_2025")
    assert V.aceita(["100000_000001_2025", "100000_000009_2025", "../etc"]) == ["100000_000009_2025"]


def test_vm1_cede_a_vez_so_com_batida_fresca(monkeypatch, tmp_path):
    marca = tmp_path / ".integras_na_vm2"
    monkeypatch.setattr(F, "DELEGADO_VM2", marca)
    assert not F._delegado_vm2()
    marca.write_text("x")
    assert F._delegado_vm2()
    velho = time.time() - 31 * 3600
    os.utime(marca, (velho, velho))
    assert not F._delegado_vm2()


def test_reserva_expira(monkeypatch, tmp_path):
    r = tmp_path / "reserva.json"
    monkeypatch.setattr(F, "RESERVA_VM2", r)
    r.write_text(json.dumps({"ts": time.time(), "procs": ["100000/000001/2025"]}))
    assert F._reservados_vm2() == {"100000/000001/2025"}
    r.write_text(json.dumps({"ts": time.time() - 13 * 3600, "procs": ["100000/000001/2025"]}))
    assert F._reservados_vm2() == set()


def test_devolver_monta_lote_sem_falha_do_navegador(monkeypatch, tmp_path):
    log = tmp_path / "fila.log"
    log.write_text(
        "[2026-11-13 16:51:08]   270032/000052/2023: SEM ÁRVORE (processo não abriu) — via='cracked' "
        "erro_cracked=\"link 'Pesquisa' NÃO ESTÁ no DOM (o clique nunca aconteceu)\"\n"
        "[2026-11-13 16:51:08]   270032/000052/2023: sem_arvore\n"
        "[2026-11-13 17:00:00]   270003/004118/2024: ok\n", encoding="utf-8")
    arq = tmp_path / "sei_arquivo"
    _arquivo_bom(arq / "270003_004118_2024")
    monkeypatch.setattr(F, "LOG", log)
    monkeypatch.setattr(F, "ARQUIVO", arq)
    monkeypatch.setattr(F, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(V, "RESUMO", tmp_path / "resumo.jsonl")
    import tools.vm2_lote as L
    monkeypatch.setattr(L, "LOTES", tmp_path / "lotes")
    monkeypatch.setattr(L, "julgar", lambda *a: {"legivel": True, "corresponde": True})
    enviados = []
    monkeypatch.setattr(L, "enviar", lambda base: enviados.append(base) or {"aprovados": ["270003/004118/2024"]})
    monkeypatch.setattr(L, "reenviar_pendentes", lambda: [])
    V.devolver(0)
    man = json.loads((enviados[0] / "MANIFESTO.json").read_text())
    assert list(man["processos"]) == ["270003/004118/2024"]
    assert "270032/000052/2023" in man["nao_entregues"]
    assert "arquivo/270003_004118_2024/manifest.json" in man["arquivos"]
    assert not (arq / "270003_004118_2024").exists()          # cópia local sai depois de ir para o lote


def test_tirar_da_fila_mantem_adiados(tmp_path):
    fila = tmp_path / "f.json"
    fila.write_text(json.dumps([{"sei": "SEI-100000/000001/2025"}, {"sei": "SEI-100000/000002/2025"}]))
    V._tirar_da_fila(fila, ["100000/000001/2025"])
    assert [e["sei"] for e in json.loads(fila.read_text())] == ["SEI-100000/000002/2025"]


def test_fila_usa_precalculo_fresco_e_ignora_velho(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    monkeypatch.setattr(V, "PRE", tmp_path / "pre.json")
    caro = []
    monkeypatch.setattr(F, "_fila_geral", lambda: caro.append(1) or [{"sei": "SEI-300000/000004/2025"}])
    (tmp_path / "pre.json").write_text(json.dumps({"ts": time.time(), "reler": [], "geral": ["SEI-400000/000001/2025"]}))
    assert "SEI-400000/000001/2025" in [e["sei"] for e in V.montar_fila(10)] and not caro
    (tmp_path / "pre.json").write_text(json.dumps({"ts": time.time() - 27 * 3600, "reler": [], "geral": []}))
    assert "SEI-300000/000004/2025" in [e["sei"] for e in V.montar_fila(10)] and caro


def test_nos_nao_pegam_processo_reservado_por_outro(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    monkeypatch.setattr(V, "RESERVA", tmp_path / "data" / ".integras_vm2_reserva.json")
    monkeypatch.setattr(V, "PRE", tmp_path / "pre.json")
    (tmp_path / "data" / ".integras_vm2_reserva.json").write_text(json.dumps(
        {"ts": time.time(), "procs": ["300000/000003/2025"]}))
    fila = V.exportar(10, no="itcampo", validade_h=3)
    assert [e["sei"] for e in fila] == ["SEI-300000/000004/2025"]
    reg = json.loads((tmp_path / "data" / ".integras_itcampo_reserva.json").read_text())
    assert reg["procs"] == ["300000/000004/2025"] and reg["validade_h"] == 3
    # a fila da VM-1 enxerga as duas reservas; a de 3 h vence sozinha (nó fora do ar devolve a fila)
    monkeypatch.setattr(F, "RESERVA_VM2", tmp_path / "data" / ".integras_vm2_reserva.json")
    assert F._reservados_vm2() == {"300000/000003/2025", "300000/000004/2025"}
    reg["ts"] = time.time() - 4 * 3600
    (tmp_path / "data" / ".integras_itcampo_reserva.json").write_text(json.dumps(reg))
    assert F._reservados_vm2() == {"300000/000003/2025"}


def test_batida_de_qualquer_no_faz_a_vm1_ceder(monkeypatch, tmp_path):
    monkeypatch.setattr(F, "DELEGADO_VM2", tmp_path / ".integras_na_vm2")
    assert not F._delegado_vm2()
    (tmp_path / ".integras_na_itcampo").write_text("x")
    assert F._delegado_vm2()
    velho = time.time() - 5 * 3600                      # nó de rodadas curtas vale 4 h, não 30
    os.utime(tmp_path / ".integras_na_itcampo", (velho, velho))
    assert not F._delegado_vm2()


def test_restrito_confirmado_nao_vai_para_a_fila(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    (tmp_path / "data" / "sei_restritos.json").write_text(json.dumps({
        "3000000000032025": {"numero": "300000/000003/2025", "status": "RESTRITO"},
        "3000000000042025": {"numero": "300000/000004/2025", "status": "RESTRITO?"}}))
    assert [e["sei"] for e in V.montar_fila(10)] == ["SEI-300000/000004/2025"]


def test_restrito_confirmado_volta_a_fila_depois_de_30_dias(monkeypatch, tmp_path):
    # 14/11/2026: acesso de unidade muda — restrito confirmado é retentado após 30 dias da última leitura
    _isolar(monkeypatch, tmp_path)
    (tmp_path / "data" / "sei_restritos.json").write_text(json.dumps({
        "a": {"numero": "300000/000003/2025", "status": "RESTRITO", "ultima": "2026-01-02 10:00"},
        "b": {"numero": "300000/000004/2025", "status": "RESTRITO",
              "ultima": time.strftime("%Y-%m-%d %H:%M")},
        "c": {"numero": "300000/000005/2025", "status": "RESTRITO"}}))   # sem data: segue fora (conservador)
    assert [e["sei"] for e in V.montar_fila(10)] == ["SEI-300000/000003/2025"]
