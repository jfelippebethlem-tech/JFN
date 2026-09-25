# -*- coding: utf-8 -*-
"""Par de elo já explicado por PROVA externa não pode voltar ao topo a cada passada.

`AMIL × COI` divide o e-mail jurídico `@uhgbrasil.com.br` e encabeçava a fila do fiscal com
R$ 216,5 mi somados. Nem a marca ("AMIL" ≠ "COI") nem o QSA brasileiro as unem — a COI pertence à
Amil, e a Amil é controlada pela UnitedHealthCare International IV S.à r.l. via Polar II FIP, fato
que só aparece no demonstrativo financeiro. Sem um lugar para GRAVAR essa prova o par reaparece
sempre; e a alternativa preguiçosa — rebaixar todo domínio corporativo compartilhado — esconderia
elo REAL (contador e holding compartilham a mesma assinatura de e-mail).

A guarda é estrutural, no molde de `fachada_veredito`: o veredito é dado uma vez, com fonte e data,
e o par continua VISÍVEL na lista com o motivo escrito. `elo_real` é o veredito que NÃO tira o par
da fila — apuração que confirma o elo não pode sumir junto com as explicadas.
"""
from __future__ import annotations

import sqlite3

import pytest

from tools.elos_ocultos import _chave_par, decidir, vereditos


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "t.db"
    sqlite3.connect(p).close()
    return str(p)


def test_chave_do_par_independe_da_ordem():
    assert _chave_par("29309127000179", "39086160001374") == _chave_par("39086160", "29309127")


def test_veredito_gravado_volta_na_leitura(db):
    decidir("29309127000179", "39086160001374", "mesmo_grupo",
            "COI pertence à Amil; Amil controlada pela UnitedHealthCare International IV S.à r.l.",
            "demonstrativo financeiro Amil 2018, p. controle acionário", db=db)
    v = vereditos(db)[_chave_par("29309127", "39086160")]
    assert v["veredito"] == "mesmo_grupo"
    assert "UnitedHealth" in v["motivo"] and v["fonte"]


def test_redecidir_corrige_sem_duplicar(db):
    decidir("11111111", "22222222", "mesmo_grupo", "achei", "palpite", db=db)
    decidir("22222222", "11111111", "elo_real", "apurado: sócio oculto", "diligência", db=db)
    d = vereditos(db)
    assert len(d) == 1 and d[_chave_par("11111111", "22222222")]["veredito"] == "elo_real"


def test_sem_tabela_nao_derruba(tmp_path):
    """Base nova, sem a tabela: devolve vazio e a fila segue como antes."""
    p = tmp_path / "vazio.db"
    sqlite3.connect(p).close()
    assert vereditos(str(p)) == {}
