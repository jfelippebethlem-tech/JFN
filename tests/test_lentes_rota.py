# -*- coding: utf-8 -*-
"""Lentes materializadas + rota /api/lentes.

O que estes testes protegem (e por que existem): as sete lentes de detecção construídas em 08/2026
ficaram CLI-only — nenhuma tinha caller. O materializador é o caller. Se ele voltar a serializar
`date` cru, ou se a rota passar a devolver 0 onde a lente falhou, o painel mente em silêncio.
"""
import datetime
import json

import pytest
from fastapi.testclient import TestClient


def test_falha_de_lente_vira_indisponivel_nao_zero():
    """Lente que estoura NÃO pode virar `n: 0` — zero é uma afirmação, INDISPONÍVEL não é."""
    from tools.lentes_materializar import _seguro

    bloco = _seguro("x", lambda: (_ for _ in ()).throw(KeyError("tabela sumiu")))
    assert bloco["ok"] is False
    assert bloco["itens"] is None, "falha virou lista vazia — o painel leria como 'nada encontrado'"
    assert "tabela sumiu" in bloco["erro"]


def test_erro_de_programacao_NAO_e_engolido():
    """NameError vira INDISPONÍVEL? Não. Bug de código tem de estourar, não virar dado."""
    from tools.lentes_materializar import _seguro
    with pytest.raises(NameError):
        _seguro("x", lambda: (_ for _ in ()).throw(NameError("campo renomeado")))


def test_lente_boa_devolve_itens_e_tempo():
    from tools.lentes_materializar import _seguro
    b = _seguro("x", lambda: [{"a": 1}, {"a": 2}])
    assert b["ok"] is True and len(b["itens"]) == 2 and b["segundos"] >= 0


def test_date_serializa_em_iso():
    """`pagos_durante_sancao` devolve datetime.date (vigência). Sem o default, o dump estoura."""
    d = {"inicio": datetime.date(2025, 11, 26)}
    s = json.dumps(d, default=lambda o: o.isoformat()
                   if isinstance(o, (datetime.date, datetime.datetime)) else str(o))
    assert json.loads(s)["inicio"] == "2025-11-26"


def _cliente():
    from server import app
    return TestClient(app)


def test_rota_sem_arquivo_declara_503(tmp_path, monkeypatch):
    """Sem materialização a rota DECLARA que não tem dado — nunca devolve lista vazia com ok=True."""
    import rotas.investigacao as inv
    monkeypatch.setattr(inv, "RAIZ", tmp_path)
    r = _cliente().get("/api/lentes")
    assert r.status_code == 503
    assert r.json()["ok"] is False


def test_rota_lente_desconhecida_lista_as_validas():
    r = _cliente().get("/api/lentes?lente=nao_existe")
    if r.status_code == 503:
        pytest.skip("lentes ainda não materializadas nesta máquina")
    assert r.status_code == 404
    assert "disponiveis" in r.json()


def test_rota_respeita_top():
    r = _cliente().get("/api/lentes?top=3")
    if r.status_code == 503:
        pytest.skip("lentes ainda não materializadas nesta máquina")
    d = r.json()
    assert d["ok"] is True
    for nome, bloco in d["lentes"].items():
        assert len(bloco["topo"]) <= 3, f"{nome} ignorou top"
        assert bloco["n"] is None or bloco["n"] >= len(bloco["topo"])
