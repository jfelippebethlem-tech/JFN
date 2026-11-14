# -*- coding: utf-8 -*-
"""O progresso do sweep é gravado por vários escritores (sweep da VM-1, bombeiros, e a incorporação do que a VM-2
leu). O merge-on-save dava prioridade a TUDO o que o escritor tinha em memória — inclusive entradas que ele só
carregou no início e nunca tocou —, então qualquer sweep vivo apagava, ao salvar, o que outro escritor gravou
depois. Medido em 13/11/2026: a incorporação da VM-2 ficou pendente a noite toda porque sempre havia sweep vivo.
Regra nova: por processo, vence a leitura MAIS NOVA (`em`), venha da memória ou do disco."""
import json

import tools.sei_sweep as S


def test_salvar_nao_apaga_entrada_mais_nova_do_disco(monkeypatch, tmp_path):
    prog_arq = tmp_path / "sei_sweep_progress.json"
    monkeypatch.setattr(S, "PROG", prog_arq)
    prog_arq.write_text(json.dumps({"feitos": {"A": {"n_docs": 0, "em": "2026-11-13T10:00:00"}}}))
    memoria = S._carregar_prog()                                      # sweep carregou às 10h…
    # …outro escritor (incorporação da VM-2) grava uma leitura mais nova de A
    prog_arq.write_text(json.dumps({"feitos": {"A": {"n_docs": 57, "em": "2026-11-13T21:17:50"}}}))
    memoria["feitos"]["B"] = {"n_docs": 3, "em": "2026-11-13T21:30:00"}  # o sweep leu B
    S._salvar_prog(memoria)
    fe = json.loads(prog_arq.read_text())["feitos"]
    assert fe["A"]["n_docs"] == 57 and fe["B"]["n_docs"] == 3


def test_salvar_mantem_o_proprio_mais_novo(monkeypatch, tmp_path):
    prog_arq = tmp_path / "p.json"
    monkeypatch.setattr(S, "PROG", prog_arq)
    prog_arq.write_text(json.dumps({"feitos": {"A": {"n_docs": 0, "em": "2026-11-13T10:00:00"}}}))
    S._salvar_prog({"feitos": {"A": {"n_docs": 9, "em": "2026-11-13T11:00:00"}}})
    assert json.loads(prog_arq.read_text())["feitos"]["A"]["n_docs"] == 9


def test_sem_data_a_memoria_vence_como_antes(monkeypatch, tmp_path):
    prog_arq = tmp_path / "p.json"
    monkeypatch.setattr(S, "PROG", prog_arq)
    prog_arq.write_text(json.dumps({"feitos": {"A": {"n_docs": 1}}}))
    S._salvar_prog({"feitos": {"A": {"n_docs": 2}}})
    assert json.loads(prog_arq.read_text())["feitos"]["A"]["n_docs"] == 2
