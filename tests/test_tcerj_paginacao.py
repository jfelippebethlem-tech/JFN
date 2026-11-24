# -*- coding: utf-8 -*-
"""Paginação do TCE-RJ dados abertos para quando a página se REPETE (O4.11, 24/11/2026).

A API não devolve página vazia depois do fim: repete página cheia. `_ingerir_paginado` só parava em página vazia
ou curta — o cron girou até o `timeout 3000` (log: 23.637.012 "ingeridos" para 40.620 contratos) e as bases
seguintes do mesmo `--ingerir` (compras diretas, penalidades) ficaram paradas desde 09/08/2026. Fixtures
sintéticas; nenhum teste toca a rede.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.collectors import tcerj_aberto as ta
from compliance_agent.collectors.tcerj_licitantes import coletar


def _mapper(r, agora):
    return (r["id"], r.get("Processo", ""), "", None, None, None, None, None, None, None, None, None, None,
            None, None, None, None, None, agora)


def _pagina(ini, n):
    return [{"id": f"{i:020d}", "Processo": f"SEI-{i}"} for i in range(ini, ini + n)]


class _API:
    """Serve páginas por `inicio`; além do fim REPETE a última página cheia (o comportamento medido)."""

    def __init__(self, total, limite=1000, repete="ultima"):
        self.total, self.limite, self.repete, self.chamadas = total, limite, repete, 0

    def __call__(self, _endpoint, inicio, limite):
        self.chamadas += 1
        if self.chamadas > 10_000:
            raise AssertionError("laço sem fim — o guarda de página repetida não disparou")
        if inicio < self.total:
            return _pagina(inicio, min(limite, self.total - inicio))
        if self.repete == "ultima":
            return _pagina(self.total - limite, limite)
        return _pagina(0, limite)          # volta ao começo


def _contar(db):
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT COUNT(*) FROM contratos_tcerj").fetchone()[0]
    finally:
        con.close()


@pytest.mark.parametrize("repete", ["ultima", "primeira"])
def test_pagina_repetida_encerra_sem_laco(tmp_path, monkeypatch, repete):
    db = tmp_path / "c.db"
    monkeypatch.setenv("JFN_DB", str(db))
    api = _API(total=3000, repete=repete)      # múltiplo exato do limite: nunca vem página curta
    n = ta._ingerir_paginado("contratos_estado", "contratos_tcerj", _mapper, buscar=api)
    assert n == 3000                             # ids DISTINTOS, não soma de len(lote)
    assert _contar(db) == 3000
    assert api.chamadas == 4                     # 3 páginas + a repetida que encerra


def test_pagina_curta_continua_encerrando(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_DB", str(tmp_path / "c.db"))
    api = _API(total=2500)
    assert ta._ingerir_paginado("contratos_estado", "contratos_tcerj", _mapper, buscar=api) == 2500
    assert api.chamadas == 3


def test_teto_de_paginas_e_base_incompleta_nunca_fim(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_DB", str(tmp_path / "c.db"))
    api = _API(total=10_000_000)
    with pytest.raises(RuntimeError, match="INCOMPLETA"):
        ta._ingerir_paginado("contratos_estado", "contratos_tcerj", _mapper, buscar=api, teto_paginas=5)
    assert api.chamadas == 5


def test_pagina_reordenada_sem_id_novo_tambem_encerra(tmp_path, monkeypatch):
    """Hash diferente (ordem trocada) mas nenhum id novo = a API está dando voltas."""
    monkeypatch.setenv("JFN_DB", str(tmp_path / "c.db"))
    paginas = [_pagina(0, 1000), _pagina(1000, 1000), list(reversed(_pagina(0, 1000)))]
    it = iter(paginas)
    n = ta._ingerir_paginado("contratos_estado", "contratos_tcerj", _mapper, buscar=lambda *_: next(it))
    assert n == 2000


def test_teto_padrao_cabe_a_maior_base_com_folga():
    assert ta.TETO_PAGINAS * 1000 >= 4 * 40_620   # 200 páginas ≈ 4,9× a maior base


# ── licitantes: mesmo guarda no gerador ──────────────────────────────────────────────────────────

def _reg(i):
    return {"Ente": "X", "Ano": 2024, "ProcessoLicitatorio": f"P{i}", "Participante": f"EMP {i}"}


def test_licitantes_pagina_repetida_encerra():
    chamadas = []

    def buscar(_rota, params):
        chamadas.append(params["inicio"])
        if len(chamadas) > 100:
            raise AssertionError("laço sem fim")
        ini = min(params["inicio"], 1000)       # além do fim, repete a 2ª página
        return {"LicitantesPerdedores": [_reg(i) for i in range(ini, ini + 1000)]}

    assert len(list(coletar("perdedor", buscar=buscar))) == 2000
    assert len(chamadas) == 3


def test_licitantes_teto_encerra_e_avisa(caplog):
    def buscar(_rota, params):
        ini = params["inicio"]
        return {"LicitantesPerdedores": [_reg(i) for i in range(ini, ini + 10)]}

    linhas = list(coletar("perdedor", pagina=10, teto_paginas=3, buscar=buscar))
    assert len(linhas) == 30
    assert "INCOMPLETA" in caplog.text
