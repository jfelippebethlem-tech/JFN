# -*- coding: utf-8 -*-
"""O registro de restritos é um índice read-modify-write — e a casa roda sweeps CONCORRENTES.

`sei_restritos._save` grava o arquivo INTEIRO a partir do que aquele processo carregou. Dois
sweeps ao mesmo tempo (o do ciclo, o de recaptura, o dos bombeiros — todos vivos nesta VM ao mesmo
tempo, medido em 2026-08-12) fazem o clássico: A carrega, B carrega, A grava, B grava por cima. O
registro de A desaparece sem erro nenhum.

O QUE ESTÁ MEDIDO, e o que NÃO está. Medido: **4.314 processos foram lidos desde 2026-07-14** (data
em que a chamada a `registrar` entrou no sweep) e o registro tem **630 entradas** — 3.689 leituras
não deixaram rastro. Também medido: hoje o mecanismo funciona (124 das 125 leituras de 11-12/08
estão registradas) e o arquivo nunca foi revertido por git (só dois commits, ambos de 16/07). NÃO
está determinado que a perda histórica tenha sido causada por esta corrida — pode ter havido outro
caminho de leitura no período. O que se conserta aqui é a corrida, que é real e demonstrável.

É a mesma família de [[indice-read-modify-write-sem-merge]]: índice sem merge apaga trabalho.
"""
from __future__ import annotations

import json

from tools import sei_restritos as R


def _entrada(n: str) -> dict:
    return {"numero": n, "status": "OK", "n_leituras": 1}


def test_gravar_faz_MERGE_com_o_que_chegou_depois_da_leitura(tmp_path, monkeypatch):
    """A prova da corrida: um processo carrega o registro, OUTRO grava, e o primeiro grava depois.
    Sem merge, a entrada do segundo some."""
    reg = tmp_path / "r.json"
    monkeypatch.setattr(R, "REG", reg)
    reg.write_text(json.dumps({"1": _entrada("1")}), encoding="utf-8")

    visao_antiga = {"1": _entrada("1"), "2": _entrada("2")}      # o que A tem em memória
    reg.write_text(json.dumps({"1": _entrada("1"), "3": _entrada("3")}),
                   encoding="utf-8")                              # B gravou nesse meio-tempo
    R._save(visao_antiga)                                         # A grava agora

    final = json.loads(reg.read_text(encoding="utf-8"))
    assert set(final) == {"1", "2", "3"}, "a entrada de B foi apagada pela gravação de A"


def test_a_versao_MAIS_LIDA_da_entrada_prevalece(tmp_path, monkeypatch):
    """Quando os dois tocaram o MESMO processo, fica quem tem mais leituras acumuladas — o
    contador é monotônico, e escolher o menor jogaria fora uma leitura de verdade."""
    reg = tmp_path / "r.json"
    monkeypatch.setattr(R, "REG", reg)
    reg.write_text(json.dumps({"1": {"numero": "1", "status": "RESTRITO", "n_leituras": 5}}),
                   encoding="utf-8")
    R._save({"1": {"numero": "1", "status": "OK", "n_leituras": 2}})
    final = json.loads(reg.read_text(encoding="utf-8"))
    assert final["1"]["n_leituras"] == 5 and final["1"]["status"] == "RESTRITO"


def test_a_entrada_NOVA_de_quem_grava_entra(tmp_path, monkeypatch):
    reg = tmp_path / "r.json"
    monkeypatch.setattr(R, "REG", reg)
    reg.write_text(json.dumps({}), encoding="utf-8")
    R._save({"9": _entrada("9")})
    assert "9" in json.loads(reg.read_text(encoding="utf-8"))


def test_arquivo_ilegivel_no_disco_nao_apaga_o_que_esta_em_memoria(tmp_path, monkeypatch):
    """Se o disco tem lixo, o merge não tem com o que mesclar — mas jogar fora o que se ia gravar
    seria trocar um problema por outro."""
    reg = tmp_path / "r.json"
    monkeypatch.setattr(R, "REG", reg)
    reg.write_text("{isto não é json", encoding="utf-8")
    R._save({"7": _entrada("7")})
    assert "7" in json.loads(reg.read_text(encoding="utf-8"))


def test_registrar_continua_devolvendo_o_status(tmp_path, monkeypatch):
    """O contrato de quem chama não muda."""
    reg = tmp_path / "r.json"
    monkeypatch.setattr(R, "REG", reg)
    monkeypatch.setattr(R, "existe_no_cadastro", lambda n: None)
    st = R.registrar("SEI-123456/000001/2024",
                     {"documentos": [], "arvore_carregou": False, "indisponivel": True})
    assert st == "NAO_LOCALIZADO"
    assert json.loads(reg.read_text(encoding="utf-8"))
