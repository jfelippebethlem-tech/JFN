# -*- coding: utf-8 -*-
"""A leitura de CONJUNTO tem de estar no PDF — é o entregável que o fiscal leva.

A síntese já chegava ao painel e à API; faltava a peça. Um relatório que lista achados sem
mostrar o esqueleto do processo obriga quem lê a reconstruir a narrativa de cabeça — e é
exatamente a narrativa que a leitura do conjunto produz.
"""
from compliance_agent.reporting import processo_360_ctx as C

_BASE = {"numero_sei": "X/1/2026", "versao": "v1", "fases": {}, "achados": [],
         "lacunas_processo": [], "lacunas_captura": [], "cobertura": {}, "escalada": {},
         "acatamento": {}, "cadeia": {}, "score100": 50.0, "faixa": "ALTO",
         "grau": {"grau": "C", "rotulo": "FLAG"}}


def _titulos(ctx):
    return [s["titulo"] for s in ctx["secoes"]]


def test_a_secao_da_leitura_de_conjunto_entra_no_pdf():
    ctx = C.render_processo_ctx({**_BASE, "sintese": {
        "n_docs": 40, "chars": 217448, "leitura": "o conjunto mostra X",
        "fases": {"controle": {"n_docs": 1, "de": "22/05/2024", "ate": "22/05/2024",
                               "viciados": 0, "assinantes": ["Fulano"], "maior_valor": None}},
        "contradicoes": [{"codigo": "G1_FASES_SOBREPOSTAS", "diz": "as fases se sobrepõem",
                          "evidencia": "execucao × despesa"}]}})
    assert any("conjunto" in t.lower() for t in _titulos(ctx)), _titulos(ctx)
    html = "".join(s["html"] for s in ctx["secoes"])
    assert "o conjunto mostra X" in html
    assert "G1_FASES_SOBREPOSTAS" in html and "as fases se sobrepõem" in html


def test_processo_sem_sintese_nao_ganha_secao_vazia():
    assert not any("conjunto" in t.lower() for t in _titulos(C.render_processo_ctx(_BASE)))


def test_sintese_indisponivel_e_DECLARADA_e_nao_silenciada():
    ctx = C.render_processo_ctx({**_BASE, "sintese": {"indisponivel": True, "motivo": "sem docs"}})
    html = "".join(s["html"] for s in ctx["secoes"])
    assert "INDISPON" in html.upper()


def test_o_html_escapa_o_que_vem_do_documento():
    ctx = C.render_processo_ctx({**_BASE, "sintese": {
        "n_docs": 1, "chars": 10, "leitura": "<script>alert(1)</script>", "fases": {},
        "contradicoes": []}})
    html = "".join(s["html"] for s in ctx["secoes"])
    assert "<script>" not in html
