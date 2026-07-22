# -*- coding: utf-8 -*-
"""C7 (sancionada contratada) e P6 (dispensa acima do teto) — fecham vícios `parcial` do catálogo.
Rodar:  .venv/bin/python -m pytest tests/test_detectores_c7_p6.py -q"""
from __future__ import annotations

from compliance_agent.detectores.c7_sancionada_contratada import C7SancionadaContratada
from compliance_agent.detectores.p6_direta_indevida import P6DiretaIndevida
from compliance_agent.editais.flags import grau_flag


def _sancao(categoria, ini="2024-01-01", fim="2026-12-31", cadastro="CEIS"):
    return {"cadastro": cadastro, "categoria": categoria, "data_inicio": ini, "data_fim": fim,
            "orgao": "CGU", "uf": "RJ"}


def test_c7_impeditiva_vigente_e_flag_a():
    res = C7SancionadaContratada().avaliar({
        "processo": "X", "contratado_cnpj": "11.111.111/0001-11", "data_referencia": "2025-06-10",
        "sancoes": [_sancao("Impedimento/proibição de contratar com prazo determinado")]})
    assert res.status == "confirmado" and res.score == 1.0
    assert res.valores["teste_objetivo"] == "violado"
    g = grau_flag(origem="deterministico", teste_status="violado", score=res.score)
    assert g["grau"] == "A"  # vedação objetiva → único caminho legítimo para flag CERTO


def test_c7_multa_nao_impede_e_sancao_expirada_descarta():
    det = C7SancionadaContratada()
    r1 = det.avaliar({"processo": "X", "data_referencia": "2025-06-10",
                      "sancoes": [_sancao("Multa", cadastro="CNEP")]})
    assert r1.status == "confirmado" and r1.score == 0.6
    assert r1.valores["teste_objetivo"] == "nao_aferivel"
    r2 = det.avaliar({"processo": "X", "data_referencia": "2025-06-10",
                      "sancoes": [_sancao("Declaração de Inidoneidade com prazo determinado",
                                          ini="2019-01-01", fim="2021-01-01")]})
    assert r2.status == "descartado"  # histórico ≠ vedação atual
    r3 = det.avaliar({"processo": "X", "sancoes": []})
    assert r3.status == "nao_avaliavel"  # sem data de referência → INDISPONÍVEL ≠ 0


def test_c7_sem_prazo_determinado_conta_vigente():
    res = C7SancionadaContratada().avaliar({
        "processo": "X", "data_referencia": "2025-06-10",
        "sancoes": [_sancao("Declaração de Inidoneidade sem prazo determinado", fim=None)]})
    assert res.status == "confirmado" and res.score == 1.0


def test_p6_acima_do_teto_de_obras_viola():
    res = P6DiretaIndevida().avaliar({"processo": "X", "modalidade_id": 8,
                                      "valor_total": 300000.0, "ano": 2024})
    assert res.status == "confirmado" and res.score == 1.0
    assert res.valores["teste_objetivo"] == "violado"
    assert "Decreto 11.871" in res.valores["ato"]


def test_p6_zona_cinzenta_e_dentro_do_teto():
    det = P6DiretaIndevida()
    # entre teto de compras (59.906,02) e de obras (119.812,02) em 2024 → dúvida declarada
    r1 = det.avaliar({"processo": "X", "modalidade_id": 8, "valor_total": 80000.0, "ano": 2024})
    assert r1.status == "confirmado" and r1.score == 0.6
    assert r1.valores["teste_objetivo"] == "nao_aferivel"
    r2 = det.avaliar({"processo": "X", "modalidade_id": 8, "valor_total": 50000.0, "ano": 2024})
    assert r2.status == "descartado"


def test_p6_amparo_diverso_e_inexigibilidade():
    det = P6DiretaIndevida()
    r1 = det.avaliar({"processo": "X", "modalidade_id": 8, "valor_total": 300000.0, "ano": 2024,
                      "amparo_declarado": "art. 75 III"})
    assert r1.status == "descartado"  # deserto/fracassado: outro instituto, teto não se aplica
    r2 = det.avaliar({"processo": "X", "modalidade_id": 9, "valor_total": 300000.0, "ano": 2024})
    assert r2.status == "nao_avaliavel"  # inexigibilidade não tem teto


def test_registro_e_catalogo_integros():
    from compliance_agent.detectores import REGISTRO
    assert "C7" in REGISTRO and "P6" in REGISTRO
    from compliance_agent.knowledge.catalogo_vicios import validar
    assert validar() == []  # todo vício `coberto` aponta p/ detector real
