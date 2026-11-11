# -*- coding: utf-8 -*-
"""Segundo voto também onde há MÉRITO: parecer, homologação e pesquisa de preços com escala ≥ 2.

Medido em 11/11/2026 (rubrica v3): o 2º voto só existia em `contratacao_direta` (102 docs). Parecer (1.376),
homologação (290) e pesquisa de preços (760) tinham voto único — e são eles que carregam mérito: 805 juízos
com escala ≥ 2 nesses três tipos. Custo medido: 61 nos últimos 10 dias ≈ 6 chamadas extras por dia, só onde o
primeiro voto aponta problema (escala 1 não pede revisão).
"""
from __future__ import annotations

import json

import pytest

from compliance_agent.sei import doc_juizo as J

TXT = "Parecer com ressalvas. Opina-se pela regularidade, condicionada à juntada da pesquisa de preços."


def _rodar(tmp_path, tipo, respostas):
    (tmp_path / "texto").mkdir()
    (tmp_path / "texto/000.txt").write_text(TXT, encoding="utf-8")
    titulo = {"parecer": "Parecer PGE (1)", "homologacao": "Termo de Homologação (1)",
              "pesquisa_precos": "Pesquisa de Preços (1)", "despacho": "Despacho (1)"}[tipo]
    man = {"processo": "SEI-1", "docs": [{"i": 0, "titulo": titulo, "tipo": tipo, "fase": "x",
                                          "texto": "texto/000.txt"}]}
    fila = list(respostas)
    chamadas = []

    def _g(p, s=""):
        chamadas.append(1)
        return json.dumps({"escala": fila.pop(0), "trecho_literal": "condicionada à juntada",
                           "justificativa_curta": "x"})

    out = J.julgar_docs(man, tmp_path, gerar=_g, con=None)
    return out["vereditos"][0], len(chamadas)


@pytest.mark.parametrize("tipo", ["parecer", "homologacao", "pesquisa_precos"])
def test_merito_com_escala_alta_ganha_segundo_voto_e_divergencia_rebaixa(tmp_path, tipo):
    v, n = _rodar(tmp_path, tipo, [3, 1])
    assert n == 2
    assert v["escala"] == 1 and "divergentes" in v["aviso"]


def test_escala_1_nao_pede_segundo_voto(tmp_path):
    v, n = _rodar(tmp_path, "parecer", [1])
    assert n == 1 and v["escala"] == 1


def test_votos_concordes_mantem_a_escala(tmp_path):
    v, n = _rodar(tmp_path, "parecer", [3, 3])
    assert n == 2 and v["escala"] == 3 and not v.get("aviso")
