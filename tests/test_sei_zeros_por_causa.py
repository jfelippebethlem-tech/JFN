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


def test_caixa_e_leitura_que_FALHOU_nao_processo_vazio(tmp_path):
    """`rel > 15` com 0 documento é a CAIXA de entrada do SEI (~40 itens), não o processo.

    O próprio `sei_sweep` decide por esse limiar (`len(relacionados) > 15` → retenta, depois cai no
    método CRACKED). Quer dizer: quando essa entrada foi gravada, a casa JÁ sabia que a leitura
    falhou — e mesmo assim o zero saía como "sem causa registrada". Medido no acervo em 2026-08-11:
    **1.057 dos 3.206** sem causa são CAIXA. Chamar isso de causa desconhecida é jogar fora
    evidência que está no próprio arquivo de progresso."""
    prog, reg = _monta(
        tmp_path,
        {"SEI-1/1/2024": {"n_docs": 0, "rel": 40, "arvore_docs": 0, "tentativas": 3},
         "SEI-2/2/2024": {"n_docs": 0, "rel": 0, "arvore_docs": 0, "tentativas": 3}},
        {},
    )
    r = Z.medir(prog=prog, reg=reg, db=tmp_path / "x.db")
    assert r["por_causa"]["CAIXA (leitura falhou)"] == 1
    assert r["por_causa"]["sem causa registrada"] == 1
    # A CAIXA é falha NOSSA: o processo continua na fila de diligência, com a causa declarada.
    assert [x["processo"] for x in r["fila"]] == ["SEI-1/1/2024"] or any(
        x["processo"] == "SEI-1/1/2024" for x in r["fila"])
    assert sum(r["por_causa"].values()) == r["zeros"] == 2


def test_caixa_com_arquivo_nao_conta_duas_vezes(tmp_path):
    """Quem já chegou por outro caminho sai de QUALQUER cesta de origem — inclusive da CAIXA."""
    prog, reg = _monta(
        tmp_path,
        {"SEI-1/1/2024": {"n_docs": 0, "rel": 40}, "SEI-2/2/2024": {"n_docs": 0, "rel": 40}},
        {}, arquivos=["SEI-2/2/2024"],
    )
    r = Z.medir(prog=prog, reg=reg, db=tmp_path / "x.db")
    assert r["por_causa"]["CAIXA (leitura falhou)"] == 1
    assert r["por_causa"]["zero no progresso, mas COM arquivo (outro caminho)"] == 1
    assert sum(r["por_causa"].values()) == r["zeros"] == 2


def test_registro_manda_mais_que_o_progresso(tmp_path):
    """RESTRITO confirmado explica o zero mesmo que a leitura tenha caído na caixa: o registro é
    apuração; `rel` é sintoma. Sem essa ordem, a CAIXA roubaria os restritos já apurados."""
    prog, reg = _monta(tmp_path, {"SEI-1/1/2024": {"n_docs": 0, "rel": 40}},
                       {"112024": {"status": "RESTRITO"}})
    r = Z.medir(prog=prog, reg=reg, db=tmp_path / "x.db")
    assert r["por_causa"]["RESTRITO"] == 1
    assert "CAIXA (leitura falhou)" not in r["por_causa"]


def test_esgotou_tentativas_e_atributo_do_item_nao_causa(tmp_path):
    """3+ tentativas com 0 documento NÃO diz se o processo é vazio ou se falhamos — diz só que o
    sweep desistiu. Vira ATRIBUTO na fila (quem já foi martelado 3× precisa de outro caminho, não
    de uma 4ª tentativa igual), nunca uma causa a mais na tabela."""
    prog, reg = _monta(
        tmp_path,
        {"SEI-1/1/2024": {"n_docs": 0, "rel": 0, "tentativas": 3},
         "SEI-2/2/2024": {"n_docs": 0, "rel": 0, "tentativas": 1}},
        {},
    )
    r = Z.medir(prog=prog, reg=reg, db=tmp_path / "x.db")
    assert r["por_causa"]["sem causa registrada"] == 2
    assert "esgotou tentativas" not in r["por_causa"]
    por = {x["processo"]: x for x in r["fila"]}
    assert por["SEI-1/1/2024"]["esgotou_tentativas"] is True
    assert por["SEI-2/2/2024"]["esgotou_tentativas"] is False


def test_as_causas_somam_o_total(tmp_path):
    """Contador que não fecha com a lista é a mesma mentira do painel que mostrava 51 contradições
    ao lado de uma lista com 4. A soma das causas TEM de dar o número de zeros."""
    prog, reg = _monta(
        tmp_path,
        {f"SEI-{i}/{i}/2024": {"n_docs": 0} for i in range(1, 7)},
        {"112024": {"status": "RESTRITO"}, "222024": {"status": "OK"}, "332024": {"status": "OK"}},
        arquivos=["SEI-3/3/2024", "SEI-4/4/2024"],
    )
    r = Z.medir(prog=prog, reg=reg, db=tmp_path / "x.db")
    assert sum(r["por_causa"].values()) == r["zeros"] == 6
    assert r["por_causa"]["OK (contradição)"] == len(r["contradicao_ok_mas_vazio"]) == 1
    # SEI-3 (OK, com arquivo) e SEI-4 (sem causa, com arquivo) caem na mesma cesta
    assert r["por_causa"]["zero no progresso, mas COM arquivo (outro caminho)"] == 2
