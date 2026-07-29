# -*- coding: utf-8 -*-
"""Todo PDF da casa passa pelo gate de citações — não só o parecer Lex.

O `reporting/gate_citacoes` existe desde 2026-07-27 e é bom: suprime acórdão aritmeticamente
impossível, corrige colegiado divergente e declara o que não foi confirmado. Só que estava ligado
em **dois** lugares — `lex_render.sanear_parecer` e `hermes_agent.sanear_canal`. Tudo o mais
(`dossie_mestre`, `capitulos_dossie`, `intel_md`, `intel_pdf`, `pericia_fisc_rico`) desembocava
direto em `render_html` e saía impresso sem conferência nenhuma.

Como `render_html` é o funil por onde passa todo entregável em PDF, o gate vai aqui: um lugar,
cobertura total, sem precisar lembrar de chamá-lo em cada produtor novo.

Invariantes travados abaixo:
  · citação impossível não chega ao PDF;
  · o leitor é avisado de que houve conferência (nota no rodapé);
  · índice ausente NÃO é silêncio — o documento declara que não conferiu;
  · o gate jamais derruba a geração do relatório.
"""
from __future__ import annotations

import pathlib

from compliance_agent.reporting.render_html import render_html

_SEM_INDICE = pathlib.Path("/tmp/jfn-indice-que-nao-existe.db")

# 9.999 extrapola com folga a série anual de qualquer colegiado do TCU — é o caso "aritmeticamente
# impossível" que o índice detecta sem precisar ter o acórdão.
_INVENTADO = "Acórdão 9999/2024-Plenário"


def _ctx(html: str) -> dict:
    return {"titulo": "Relatório de teste", "score": 10, "faixa": "BAIXO",
            "secoes": [{"titulo": "Fundamentação", "html": html}]}


def test_citacao_impossivel_nao_sai_no_html():
    saida = render_html(_ctx(f"<p>Conforme o {_INVENTADO}, o gestor responde.</p>"))
    assert _INVENTADO not in saida, "acórdão inexistente chegou ao entregável"
    assert "citação suprimida" in saida


def test_documento_declara_que_conferiu():
    saida = render_html(_ctx(f"<p>Vide {_INVENTADO}.</p>"))
    assert "conferência" in saida.lower() or "conferida" in saida.lower()


def test_texto_sem_citacao_nao_ganha_ruido():
    limpo = "<p>O contrato foi executado conforme a planilha.</p>"
    saida = render_html(_ctx(limpo))
    assert limpo in saida
    assert "citação suprimida" not in saida
    assert "conferência" not in saida.lower()


def test_indice_ausente_e_declarado_nunca_calado():
    """INDISPONÍVEL ≠ OK, inclusive dentro do próprio gate."""
    ctx = _ctx(f"<p>Vide {_INVENTADO}.</p>")
    ctx["_gate_db"] = _SEM_INDICE
    saida = render_html(ctx)
    assert "não" in saida.lower() and "conferid" in saida.lower(), (
        "sem índice, o documento tem de dizer que não conferiu")


def test_gate_nunca_derruba_a_geracao():
    """Uma dúvida de citação não pode impedir a emissão do relatório."""
    import compliance_agent.reporting.render_html as rh

    original = rh._sanear_secoes

    def explode(*_a, **_k):
        raise RuntimeError("índice corrompido")

    rh._sanear_secoes = explode
    try:
        saida = render_html(_ctx("<p>qualquer coisa</p>"))
        assert "qualquer coisa" in saida
    finally:
        rh._sanear_secoes = original


def test_hash_de_integridade_continua_sendo_dos_DADOS():
    """O hash atesta a origem, não o texto saneado — sanear não pode mudá-lo."""
    ctx_a = _ctx("<p>texto A</p>")
    ctx_b = _ctx(f"<p>texto A e {_INVENTADO}</p>")
    ctx_a["_dados"] = ctx_b["_dados"] = {"fonte": "SIAFE", "n": 3}
    import re
    h = lambda s: re.search(r"SHA-256: ([0-9a-f]+)", s).group(1)  # noqa: E731
    assert h(render_html(ctx_a)) == h(render_html(ctx_b))
