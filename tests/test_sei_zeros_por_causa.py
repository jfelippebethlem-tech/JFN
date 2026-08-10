# -*- coding: utf-8 -*-
"""Zero documento é 'não trouxe nada', não 'não havia nada' — e a diferença vale bilhões.

O sweep dizia `N sem (fora de escopo/vazio)`, afirmando uma causa que ninguém mediu. Medido em
2026-08-10: dos 3.775 processos zerados, só 930 têm motivo registrado; 2.577 seguem sem causa e sem
arquivo, e carregam **R$ 3,78 bi** em OB contabilizada. O número só ficou honesto depois de duas
correções — a ponte processo→OB certa e a conferência do arquivo — e a segunda só apareceu porque o
CONTROLE POSITIVO do glob falhou.
"""
from __future__ import annotations

import json

import tools.sei_zeros_por_causa as Z


def _monta(tmp_path, feitos, registro, arquivos=()):
    prog = tmp_path / "prog.json"
    prog.write_text(json.dumps({"feitos": feitos}), encoding="utf-8")
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps(registro), encoding="utf-8")
    arq = tmp_path / "arquivo"
    arq.mkdir()
    for p in arquivos:
        (arq / p.replace("SEI-", "").replace("/", "_")).mkdir()
    Z._ARQ = arq
    return prog, reg


def test_separa_causa_conhecida_de_desconhecida(tmp_path):
    prog, reg = _monta(
        tmp_path,
        {"SEI-1/1/2024": {"n_docs": 0}, "SEI-2/2/2024": {"n_docs": 0},
         "SEI-3/3/2024": {"n_docs": 0}, "SEI-4/4/2024": {"n_docs": 12}},
        {"112024": {"status": "RESTRITO"}, "222024": {"status": "NAO_LOCALIZADO"}},
    )
    r = Z.medir(prog=prog, reg=reg, db=tmp_path / "nao_existe.db")
    assert r["zeros"] == 3
    assert r["por_causa"]["RESTRITO"] == 1
    assert r["por_causa"]["NAO_LOCALIZADO"] == 1
    assert r["sem_causa"] == 1


def test_restrito_com_interrogacao_NAO_explica(tmp_path):
    """`RESTRITO?` é hipótese da casa. Contá-la como explicação é fechar por osmose um processo que
    ninguém confirmou estar fechado."""
    prog, reg = _monta(tmp_path, {"SEI-9/9/2024": {"n_docs": 0}}, {"992024": {"status": "RESTRITO?"}})
    r = Z.medir(prog=prog, reg=reg, db=tmp_path / "x.db")
    assert r["por_causa"]["RESTRITO?"] == 1
    assert "RESTRITO?" not in Z.EXPLICAM


def test_zero_no_progresso_mas_COM_arquivo_sai_da_fila(tmp_path):
    """O processo chegou por outro caminho (colheita da VM-2, recaptura). Mandar rebuscá-lo é
    gastar browser com o que já está em casa — 216 casos no acervo real."""
    prog, reg = _monta(tmp_path, {"SEI-7/7/2024": {"n_docs": 0}}, {}, arquivos=["SEI-7/7/2024"])
    r = Z.medir(prog=prog, reg=reg, db=tmp_path / "x.db")
    assert r["sem_causa"] == 0
    assert r["ja_no_arquivo_por_outro_caminho"] == 1
    assert not r["fila"]


def test_contradicao_e_so_quem_esta_OK_e_sem_arquivo(tmp_path):
    """Se o cadastro diz OK e não há arquivo, o zero é falha NOSSA — é o subconjunto mais acionável."""
    prog, reg = _monta(
        tmp_path,
        {"SEI-5/5/2024": {"n_docs": 0}, "SEI-6/6/2024": {"n_docs": 0}},
        {"552024": {"status": "OK"}, "662024": {"status": "OK"}},
        arquivos=["SEI-6/6/2024"],
    )
    r = Z.medir(prog=prog, reg=reg, db=tmp_path / "x.db")
    assert r["contradicao_ok_mas_vazio"] == ["SEI-5/5/2024"]


def test_progresso_ilegivel_declara_indisponivel(tmp_path):
    r = Z.medir(prog=tmp_path / "nao_existe.json", reg=tmp_path / "x.json", db=tmp_path / "x.db")
    assert r["ok"] is False and r["estado"] == "indisponivel"
