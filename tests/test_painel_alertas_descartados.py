# -*- coding: utf-8 -*-
"""Card "Alertas" do cockpit (`/api/compliance/painel`): só conta alerta NÃO descartado.

Defeito medido em 13/11/2026: os 58.253 alertas de emprego múltiplo (agrupados por CPF mascarado — 99,6% de
colisão) foram marcados `descartado` e a regra refeita, mas o card seguia "64.539 · 59.024 de gravidade alta":
a rota contava a tabela inteira, sem olhar o status. Dados sintéticos.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture()
def painel(tmp_path, monkeypatch):
    db = tmp_path / "c.db"
    monkeypatch.setenv("JFN_DB", str(db))
    from compliance_agent.database.models import Alerta, get_engine, get_session, init_db
    init_db(str(db))
    s = get_session(get_engine(str(db)))
    linhas = ([("acumulacao", "alta", "descartado")] * 5 + [("acumulacao", "média", "novo")] * 3
              + [("enriquecimento", "alta", "novo")] * 2 + [("doerj_anomalia", "media", "investigando")]
              + [("pcrj_d7", "baixa", "novo")] + [("enriquecimento", "alta", "confirmado")]
              + [("fantasma", "alta", None)])                      # status ausente não é descarte
    for i, (tipo, sev, st) in enumerate(linhas):
        s.add(Alerta(tipo=tipo, severidade=sev, status=st, titulo=f"{tipo} {i}", descricao="x"))
    s.commit()
    s.close()
    from rotas import investigacao as R
    monkeypatch.setattr(R, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(R, "_cache_put", lambda chave, val: val)
    return json.loads(R.api_painel().body)


def test_card_nao_conta_alerta_descartado(painel):
    a = painel["alertas"]
    assert a["total"] == 9                 # 14 linhas − 5 descartadas
    assert a["alta"] == 4                  # 2 novo + 1 confirmado + 1 sem status; as 5 descartadas fora
    assert a["media"] == 4                 # 'média' e 'media' somados
    assert a["baixa"] == 1
    assert a["alta"] + a["media"] + a["baixa"] == a["total"]   # a gravidade exibida bate com o total


def test_lista_da_tela_nao_traz_descartado(painel):
    lst = painel["lista_alertas"]
    assert len(lst) == 9 and all(not x["titulo"].startswith("acumulacao") or x["severidade"] == "média" for x in lst)
