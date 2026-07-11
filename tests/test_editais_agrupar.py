# -*- coding: utf-8 -*-
"""T4 — agrupamento semântico (clustering puro, embeddings sintéticos)."""
from compliance_agent.editais import agrupar


def test_agrupa_por_similaridade():
    itens = [
        {"id": 1, "material_servico": "M", "valor_estimado": 1000, "emb": [1.0, 0.0]},
        {"id": 2, "material_servico": "M", "valor_estimado": 1200, "emb": [0.99, 0.01]},
        {"id": 3, "material_servico": "M", "valor_estimado": 900,  "emb": [0.0, 1.0]},
    ]
    grupos = agrupar.agrupar(itens, limiar=0.9)
    ids = sorted(sorted(itens[i]["id"] for i in g) for g in grupos)
    assert [1, 2] in ids and [3] in ids


def test_particao_por_material():
    itens = [{"id": 1, "material_servico": "M", "valor_estimado": 1, "emb": [1.0, 0.0]},
             {"id": 2, "material_servico": "S", "valor_estimado": 1, "emb": [1.0, 0.0]}]
    grupos = agrupar.agrupar(itens, limiar=0.5)
    assert all(len(g) == 1 for g in grupos)   # M e S nunca no mesmo grupo


def test_cosseno():
    assert abs(agrupar.cosseno([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9
    assert abs(agrupar.cosseno([1.0, 0.0], [0.0, 1.0])) < 1e-9
