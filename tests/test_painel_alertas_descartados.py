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
    assert a["total"] == 8                 # 14 linhas − 5 descartadas − 1 da Prefeitura (pcrj_d7), contada à parte
    assert a["alta"] == 4                  # 2 novo + 1 confirmado + 1 sem status; as 5 descartadas fora
    assert a["media"] == 4                 # 'média' e 'media' somados
    assert a["baixa"] == 0
    assert a["alta"] + a["media"] + a["baixa"] == a["total"]   # a gravidade exibida bate com o total


def test_card_do_estado_nao_soma_alerta_da_prefeitura_nem_de_emenda_federal(painel):
    """20/11/2026: de 6.762 alertas "do Estado", 2.464 eram da perícia de gastos da Prefeitura e 1.202 de emendas
    federais. Cada esfera é contada em separado; o total do card é só o do Estado."""
    a = painel["alertas"]
    assert a["esfera"] == "estado"
    assert a["por_esfera"]["estado"]["total"] == a["total"] == 8
    assert a["por_esfera"]["prefeitura"] == {"alta": 0, "media": 0, "baixa": 1, "total": 1}
    assert {x["tipo"]: x["esfera"] for x in a["por_tipo"]}["pcrj_d7"] == "prefeitura"
    assert all("esfera" in x for x in painel["lista_alertas"])


def test_lista_da_tela_nao_traz_descartado(painel):
    lst = painel["lista_alertas"]
    assert len(lst) == 9 and all(not x["titulo"].startswith("acumulacao") or x["severidade"] == "média" for x in lst)


def test_card_diz_de_que_produtor_vem_cada_alerta_e_quando_ele_rodou(painel):
    """Pente fino 17/11/2026: 1.300+ alertas abertos vinham de produtores que não rodam desde 10/08/2026 (emendas,
    PCRJ D7/D10) e o card os somava como se fossem de hoje. Cada tipo diz quantos abertos e a última criação."""
    t = {x["tipo"]: x for x in painel["alertas"]["por_tipo"]}
    assert t["enriquecimento"]["n"] == 3 and t["acumulacao"]["n"] == 3
    assert sum(x["n"] for x in t.values() if x["esfera"] == "estado") == painel["alertas"]["total"]
    assert all("ultima_criacao" in x and "alta" in x for x in t.values())
    assert t["enriquecimento"]["alta"] == 3
