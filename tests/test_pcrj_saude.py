# -*- coding: utf-8 -*-
"""Laudo de saúde dos pipelines PCRJ (15/09/2026): mede, gradua e diz a ação — nunca cai por etapa ausente."""
from __future__ import annotations

import sqlite3

from tools.pcrj_saude import _veredito, laudo, md


def test_veredito_por_frescor():
    assert _veredito(0, None, 48)[0] == "🔴"
    assert _veredito(10, "2000-01-01 00:00:00", 48)[0] == "🔴"
    assert _veredito(10, None, None)[0] == "🟢"
    assert _veredito(10, "sem data", 48)[0] == "🟡"


def test_laudo_em_base_vazia_nao_quebra_e_marca_vermelho(tmp_path):
    db = tmp_path / "pcrj.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE pcrj_processo (numero_processo, sistema, assunto, orgao, disponivel, coletado_em)")
    c.execute("INSERT INTO pcrj_processo VALUES ('000100.000001/2026-00','SEI.RIO','x','y',NULL,datetime('now','localtime'))")
    c.commit(); c.close()
    l = laudo(db)
    por = {e["etapa"]: e for e in l["etapas"]}
    assert por["catálogo SEI (enum → pcrj_processo)"]["grau"] == "🟢" and por["catálogo SEI (enum → pcrj_processo)"]["n"] == 1
    assert por["contratos ContasRio (contasrio_contrato)"]["grau"] == "🔴" and l["grau_geral"] == "🔴"
    texto = md(l)
    assert "| etapa |" in texto and "contasrio_contrato" in texto and "ação se parado" in texto
