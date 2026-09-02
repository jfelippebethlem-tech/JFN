# -*- coding: utf-8 -*-
"""Corte por POSIÇÃO não pode decidir AUSÊNCIA.

Havia um `[:40]` no `docs_ac` do 360. Medido em 2026-08-05: **26 processos perdiam documentos no
corte** — 1.165 despachos e 54 pareceres ao todo — e rodando os 26 com e sem teto **2 vereditos
mudavam, os dois retratando acusação**:

  · SEI-070002/015404/2022 · `SEM_PARECER_LOCALIZADO` → `ACOLHIDO` (o parecer estava do 41º em diante)
  · SEI-070026/000410/2021 · `SILENTE`                → `ACOLHIDO`

"Nenhum parecer jurídico entre os documentos lidos (art. 53)" é afirmação de ausência, e um corte
por posição a fabrica sem esforço. Ler tudo custa 1.508 documentos a mais no acervo inteiro
(+16,9%), diluídos em 26 processos.

Este teste tem duas metades porque uma sozinha não basta: a estática impede que o teto volte a
aparecer no código, e a funcional prova que o 41º documento realmente decide.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from compliance_agent import sei_recomendacoes as R

ALVO = Path(__file__).resolve().parents[1] / "compliance_agent" / "processo_360.py"


def test_a_lista_do_acatamento_nao_tem_corte_por_posicao():
    fonte = ALVO.read_text(encoding="utf-8")
    m = re.search(r"docs_ac\s*=\s*\[(?:.|\n)*?\]\s*(\[:\s*\d+\s*\])?", fonte)
    assert m, "não encontrei a construção de `docs_ac` — o teste precisa ser reescrito junto"
    assert not m.group(1), (
        f"voltou o teto posicional {m.group(1)} em `docs_ac`: corte por posição fabrica "
        "acusação de ausência (2 vereditos já mudaram por causa dele)")
    # e nenhuma fatia numérica escondida na mesma expressão
    trecho = ast.parse(fonte)
    assert trecho is not None


def _peca(i: int, titulo: str, tipo: str, texto: str) -> dict:
    return {"ref": f"{titulo} ({100000 + i})", "tipo": tipo, "texto": texto}


def test_o_parecer_no_41o_documento_decide_o_veredito():
    """Quarenta despachos de encaminhamento, e só então o parecer e o acolhimento."""
    docs = [_peca(i, f"Despacho de Encaminhamento de Processo {i}", "despacho",
                  "Encaminho os autos à Coordenação para as providências cabíveis.")
            for i in range(40)]
    docs.append(_peca(40, "Parecer 462", "parecer",
                      "PROCURADORIA GERAL DO ESTADO. Parecer nº 462. Esta Procuradoria "
                      "RECOMENDA a juntada da pesquisa de preços antes da contratação, "
                      "condicionando a validade do ajuste ao saneamento apontado."))
    docs.append(_peca(41, "Despacho de Autorização", "despacho",
                      "ACOLHO o parecer da PGE e autorizo a contratação nos seus termos."))

    assert R.auditar_acatamento(docs[:40]).get("veredito") == "SEM_PARECER_LOCALIZADO", \
        "cenário mal montado: com o teto de 40 o parecer tem de ficar invisível"
    assert R.auditar_acatamento(docs).get("veredito") == "ACOLHIDO"
