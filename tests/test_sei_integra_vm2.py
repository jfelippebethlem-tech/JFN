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


def test_devolver_nao_entrega_falha_do_navegador_e_rebaixa_o_log(monkeypatch, tmp_path):
    log = tmp_path / "fila.log"
    log.write_text(
        "[2026-11-13 16:51:08]   270032/000052/2023: SEM ÁRVORE (processo não abriu) — via='cracked' "
        "erro_cracked=\"link 'Pesquisa' NÃO ESTÁ no DOM (o clique nunca aconteceu)\"\n"
        "[2026-11-13 16:51:08]   270032/000052/2023: sem_arvore\n"
        "[2026-11-13 17:00:00]   270003/004118/2024: ok\n", encoding="utf-8")
    monkeypatch.setattr(F, "LOG", log)
    monkeypatch.setattr(V, "RESUMO", tmp_path / "resumo.jsonl")
    monkeypatch.setattr(V, "_limpar_local", lambda tag: None)
    enviados, chamadas = [], []
    monkeypatch.setattr(V, "_entregar", lambda tag: (enviados.append(tag) or True, "", 44))

    class R:
        returncode, stdout = 0, ""
    monkeypatch.setattr(V, "_ssh", lambda cmd, entrada=None, timeout=300: chamadas.append(entrada) or R())
    r = V.devolver(0)
    assert enviados == ["270003_004118_2024"]
    assert r["entregues"] == {"270003/004118/2024": 44}
    texto_vm1 = chamadas[-1]
    assert "270003/004118/2024: ok\n" in texto_vm1
    assert "270032/000052/2023: sem_arvore-vm2-nao-entregue" in texto_vm1


def test_tirar_da_fila_mantem_adiados(tmp_path):
    fila = tmp_path / "f.json"
    fila.write_text(json.dumps([{"sei": "SEI-100000/000001/2025"}, {"sei": "SEI-100000/000002/2025"}]))
    V._tirar_da_fila(fila, ["100000/000001/2025"])
    assert [e["sei"] for e in json.loads(fila.read_text())] == ["SEI-100000/000002/2025"]
