# -*- coding: utf-8 -*-
"""Testes do orquestrador de captação municipal (``pcrj/harvester.py``).

Sem rede: monkeypatcha os coletores. Verifica orquestração serial, isolamento de
falha (um coletor que quebra não derruba a varredura) e agregação do resumo.
"""
from compliance_agent.pcrj import harvester


def test_varre_agrega(monkeypatch):
    monkeypatch.setattr(harvester.esfera, "construir_mapa",
                        lambda db_path=None: {"orgaos": 2, "por_esfera": {"municipal-rio": 1}})
    monkeypatch.setattr(harvester.doweb, "coletar_termo",
                        lambda termo, **k: {"gravadas": 3, "por_tipo": {"edital": 3},
                                            "com_processo": 2, "processos": ["09/1/2022"]})
    monkeypatch.setattr(harvester.ppp_ccpar, "coletar_projeto",
                        lambda slug, **k: {"fase": "Assinatura", "n_docs": 14})
    monkeypatch.setattr(harvester.db, "inicializar", lambda db_path=None: None)
    monkeypatch.setattr(harvester.time, "sleep", lambda s: None)

    r = harvester.varrer(termos=["A", "B"], anos=[2022], max_paginas=1)
    assert r["esfera"]["orgaos"] == 2
    assert len(r["doe"]) == 2
    assert r["doe"][0]["gravadas"] == 3
    assert len(r["ppp"]) == 1 and r["ppp"][0]["n_docs"] == 14


def test_falha_de_coletor_nao_derruba(monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(harvester.esfera, "construir_mapa", explode)
    monkeypatch.setattr(harvester.doweb, "coletar_termo", explode)
    monkeypatch.setattr(harvester.ppp_ccpar, "coletar_projeto", explode)
    monkeypatch.setattr(harvester.db, "inicializar", lambda db_path=None: None)
    monkeypatch.setattr(harvester.time, "sleep", lambda s: None)

    r = harvester.varrer(termos=["A"], anos=[2022], max_paginas=1)
    assert "erro" in r["esfera"]
    assert "erro" in r["doe"][0]
    assert "erro" in r["ppp"][0]  # varredura completou apesar das falhas


def test_sem_ppp_nem_esfera(monkeypatch):
    monkeypatch.setattr(harvester.doweb, "coletar_termo",
                        lambda termo, **k: {"gravadas": 0, "por_tipo": {}, "com_processo": 0, "processos": []})
    monkeypatch.setattr(harvester.db, "inicializar", lambda db_path=None: None)
    monkeypatch.setattr(harvester.time, "sleep", lambda s: None)
    r = harvester.varrer(termos=["A"], anos=[2022], incluir_ppp=False, incluir_esfera=False)
    assert r["esfera"] is None
    assert r["ppp"] == []
