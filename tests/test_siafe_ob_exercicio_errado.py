# -*- coding: utf-8 -*-
"""OB de um ano NÃO pode entrar rotulada como outro exercício.

MEDIDO EM 11/11/2026: pedi ao SIAFE 2 o exercício 2022 da UG 133100. A tela de login só oferece
2023–2027, o `select_option('2022')` lançou exceção, o laço de retry fez `break` calado e o login
seguiu no exercício PADRÃO (2026). Resultado: 592 OBs `2026OB…` gravadas com `exercicio=2022`,
duplicando a UG/ano na base (600 → 1.192 linhas). Reparado à mão; estes testes impedem a volta.
"""
from __future__ import annotations

import sqlite3

import pytest

import compliance_agent.siafe_ob_orcamentaria as M


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "c.db"
    monkeypatch.setattr(M, "_DB", p)
    return p


def _linha(numero: str, ug: str = "133100") -> list:
    return [{"numero_ob": numero, "ug_emitente": ug, "valor": "1,00"}.get(c, "") for c in M._COLS_SIAFE]


def test_ob_de_outro_ano_e_recusada(db):
    r = M.ingerir(2022, [], [_linha("2026OB00015"), _linha("2022OB00003")])
    con = sqlite3.connect(db)
    nums = {x[0] for x in con.execute("SELECT numero_ob FROM ob_orcamentaria_siafe")}
    assert nums == {"2022OB00003"}, f"OB de 2026 entrou como exercício 2022: {nums}"
    assert r["ingeridas"] == 1 and r["recusadas_outro_ano"] == 1


def test_numero_sem_ano_no_prefixo_continua_entrando(db):
    M.ingerir(2023, [], [_linha("OB000001")])
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe").fetchone()[0] == 1


def test_lote_todo_de_outro_ano_nao_grava_nada(db):
    r = M.ingerir(2022, [], [_linha("2026OB00015"), _linha("2026OB00016")])
    assert r["ingeridas"] == 0 and r["recusadas_outro_ano"] == 2


def test_login_em_ano_fora_da_lista_e_erro_nomeado(monkeypatch):
    """O SIAFE 2 não oferece 2022: o `select_option` lança e o login NÃO pode seguir no ano padrão."""
    import asyncio

    from tests.test_siafe_login_senha_expirada import _PaginaSenhaExpirada

    class _SemAno(_PaginaSenhaExpirada):
        async def select_option(self, *a, **k):
            raise RuntimeError("did not find some options")

        async def evaluate(self, js):
            if "map(o=>o.label)" in js:
                return ["2023", "2024", "2025", "2026", "2027"]
            if "cbxExercicio" in js:
                return "2026"
            return await super().evaluate(js)

    monkeypatch.setenv("SIAFE_USER", "u")
    monkeypatch.setenv("SIAFE_PASS", "p")
    monkeypatch.delenv("SIAFE2_USER", raising=False)
    monkeypatch.delenv("SIAFE2_PASS", raising=False)
    pg = _SemAno()
    r = asyncio.run(M._login(pg, 2022))
    assert r["ok"] is False and r["erro"] == "exercicio_indisponivel"
    assert r["disponiveis"][0] == "2023" and not pg.clicou_ok, "não pode clicar Entrar no ano errado"
