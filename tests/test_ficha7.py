# -*- coding: utf-8 -*-
"""Ficha de 7 seções GENÉRICA (reporting/ficha7) — extensão do padrão-representação de
editais para contratos/emendas/pcrj. Sem LLM: colegiado stubado via monkeypatch.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_ficha7.py -q
"""
from __future__ import annotations

import sqlite3

from compliance_agent.reporting import ficha7
from compliance_agent.reporting.pericia_fisc_rico import ctx_de_achados_rico

_SECOES = ["I. Identificação", "II. Objeto do achado", "III. Análise comparativa",
           "IV. Fundamentação jurídica", "V. Parecer do colegiado", "VI. Beneficiário",
           "VII. Conclusão"]

_VOTOS = {lente: {"voto": 8, "justificativa": "x", "citacao": ""}
          for lente in ("proporcionalidade", "jurisprudencia", "competicao", "refutador", "beneficiario")}


def _achado(risco=8, votos=None, score=None):
    a = {"detector": "d3_favorecido_sancionado", "risco": risco,
         "titulo": "Favorecido sancionado — ACME LTDA",
         "descricao": "Beneficiário inscrito no CEIS à época do repasse.",
         "evidencias": {"cadastro": "CEIS", "cnpj": "11222333000181", "match_exato": True},
         "codigo_emenda": "202612345"}
    if votos is not None:
        a["votos"], a["score_colegiado"], a["veredito"] = votos, score, "direcionamento"
    return a


# ── render genérico ──────────────────────────────────────────────────────────

def test_ficha_traz_as_7_secoes_e_matriz():
    html = ficha7.ficha_html(1, {
        "titulo": "t", "superficie": "emendas", "ident": [("Alvo", "ACME")],
        "objeto_html": "<p>fatos</p>", "comparativa_html": None,
        "fundamentacao_html": ficha7.fundamentacao_html(dispositivos=["Lei 14.133 art. 14"]),
        "votos": _VOTOS, "score_colegiado": 8, "veredito": "direcionamento", "risco_det": 8,
    })
    for s in _SECOES:
        assert s in html, f"seção ausente: {s}"
    assert "Matriz de risco" in html and "voto-gate" in html


def test_sem_colegiado_e_honesto_e_limita_verossimilhanca():
    html = ficha7.ficha_html(1, {"titulo": "t", "superficie": "pcrj", "ident": [],
                                 "objeto_html": "", "risco_det": 9})
    assert "Colegiado não convocado" in html
    assert "INDISPONÍVEL ≠ 0" in html
    # sem colegiado, verossimilhança máxima é 3 → produto ≤ 12 (nunca CRÍTICO)
    assert "CRÍTICO" not in html


def test_matriz_sem_comparativa_limita_verossimilhanca():
    m = ficha7.matriz_risco(risco_det=9, score_colegiado=10, comparativa_ok=False)
    assert "verossimilhança <b>3/5</b>" in m


# ── gate de custo do colegiado ───────────────────────────────────────────────

def test_deliberar_respeita_limiar_e_cap(monkeypatch):
    chamados = []
    monkeypatch.setattr(ficha7, "_avaliar",
                        lambda d, gerar=None: (chamados.append(d) or
                                               {"score_final": 8, "veredito": "direcionamento",
                                                "votos": _VOTOS}))
    con = sqlite3.connect(":memory:")
    achados = [_achado(risco=r) for r in (9, 8, 7, 6, 3)] + [_achado(risco=8) for _ in range(10)]
    n = ficha7.deliberar_achados(con, achados, "emendas", limiar=7, cap=4)
    assert n == 4 and len(chamados) == 4          # cap respeitado
    assert all((a.get("risco") or 0) >= 7 for a in achados if "votos" in a)  # limiar respeitado


def test_deliberar_nao_avaliavel_nao_anota(monkeypatch):
    monkeypatch.setattr(ficha7, "_avaliar",
                        lambda d, gerar=None: {"score_final": 0, "veredito": "nao_avaliavel", "votos": {}})
    con = sqlite3.connect(":memory:")
    a = _achado(risco=9)
    assert ficha7.deliberar_achados(con, [a], "emendas") == 0
    assert "votos" not in a                        # INDISPONÍVEL ≠ 0: ficha sai honesta


# ── integração com o montador rico (emendas/pcrj) ────────────────────────────

def _ctx(achados):
    return ctx_de_achados_rico("T", "S", {"achados": achados, "cobertura": {}}, fontes=[],
                               superficie="emendas")


def test_achado_deliberado_sai_na_ficha_de_7_secoes():
    ctx = _ctx([_achado(votos=_VOTOS, score=8)])
    corpo = "".join(s["html"] for s in ctx["secoes"])
    for s in _SECOES:
        assert s in corpo
    assert "Matriz de risco" in corpo


def test_achado_sem_votos_mantem_ficha_rica_de_sempre():
    ctx = _ctx([_achado()])
    corpo = "".join(s["html"] for s in ctx["secoes"])
    assert "gravidade 8/10" in corpo               # formato antigo preservado
    assert "V. Parecer do colegiado" not in corpo  # sem seção de colegiado inventada


# ── contratos: parecer usa a mesma ficha ─────────────────────────────────────

def test_parecer_contratos_rende_ficha7():
    from compliance_agent.contratos.parecer import render_parecer_ctx
    parecer = {
        "numero_controle_pncp": "999",
        "relatorio": {"controle": "999", "orgao": "Órgão X", "fornecedor": "ACME (11222333000181)",
                      "objeto": "obra", "valor_inicial": "R$ 1,00", "valor_global": "R$ 2,00",
                      "empenhado": "R$ 1,00", "liquidado": "R$ 1,00", "pago": "R$ 1,00",
                      "n_aditivos": 1, "vigencia": "2025 a 2026"},
        "fundamentacao": [{"dimensao": "aditivo_acima_limite", "fatos": "aditivo de 60%",
                           "norma": "Lei 14.133/2021 art. 125", "veredito_enxame": "direcionamento",
                           "score": 8, "risco": 8, "votos": _VOTOS, "jurisprudencia": ""}],
        "conclusao": "indício de irregularidade", "score": 8, "voto": "Pela representação.",
        "dimensoes": ["aditivo_acima_limite"], "aditivos": [], "itens": [],
        "sinais_fornecedor": ["CEIS vigente"], "pagamentos": {},
    }
    ctx = render_parecer_ctx(parecer)
    corpo = "".join(s["html"] for s in ctx["secoes"])
    for s in _SECOES:
        assert s in corpo
    assert "Defesa do contrato (refutador)" in corpo
    assert "CEIS vigente" in corpo                 # sinais entram no beneficiário da ficha
