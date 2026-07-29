# -*- coding: utf-8 -*-
"""Integridade do ENTREGÁVEL — as quatro propriedades que o produto tem de ter, sempre.

Nasceu de uma auditoria dos PDFs em `reports/` (2026-07-29) que achou quatro defeitos que nenhuma
revisão de código tinha pego, porque todos só aparecem no documento pronto:

  1. o PDF de órgão perdia ~55% do Markdown (a §1-L, com 45 fornecedores nominados, nunca era
     renderizada) — e não avisava;
  2. o MD e o PDF de fornecedor eram documentos DIFERENTES, com seções exclusivas de cada lado;
  3. ~20 cortes silenciosos (`[:10]`..`[:120]`) somiam com linhas de cartel, laranja e rede
     societária sem emitir "+N restantes";
  4. o gate de neutralidade tratava **ITERJ** — órgão público real, UG 133100, alvo declarado do
     projeto — como se fosse nome interno da ferramenta, o que fazia qualquer dossiê de fornecedor
     com contrato do ITERJ explodir em AssertionError.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_entregavel_integro.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────────────
# 1. Neutralidade: nome de ÓRGÃO PÚBLICO não é termo interno
# ─────────────────────────────────────────────────────────────────────────────

def test_orgao_publico_real_nao_e_termo_interno():
    """ITERJ é o Instituto de Terras e Cartografia do ERJ (UG 133100), citado no próprio CLAUDE.md
    como alvo. Bloqueá-lo impedia de entregar o relatório do órgão que mais auditamos."""
    from compliance_agent.reporting.neutralidade import garantir_neutro, termos_proibidos

    assert termos_proibidos("Contrato 005/2021 firmado com o ITERJ") == []
    garantir_neutro("Pagamentos do ITERJ (UG 133100) no exercício de 2024")  # não pode levantar


def test_neutralidade_ainda_barra_o_que_importa():
    """A flexibilização acima não pode abrir a porteira: a sigla da ferramenta segue barrada."""
    from compliance_agent.reporting.neutralidade import termos_proibidos

    assert termos_proibidos("relatório do JFN via Yoda") == ["jfn", "yoda"]
    assert termos_proibidos("parecer Lex") == ["Lex"]
    assert termos_proibidos("gerado por jfelippe") == ["jfelippe"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Sem numeração de página no rodapé
# ─────────────────────────────────────────────────────────────────────────────

def test_rodape_do_pdf_nao_numera_pagina():
    """Diretriz do dono (2026-07-29): o documento é do tamanho que a verdade exigir — numerar
    página convida a cortar para caber. O rodapé mantém só a faixa de honestidade."""
    fonte = (_RAIZ / "compliance_agent/reporting/render_html.py").read_text()
    assert "pageNumber" not in fonte, "o rodapé voltou a numerar página"
    assert "totalPages" not in fonte, "o rodapé voltou a contar páginas"
    assert "indícios, nunca acusação" in fonte, "a faixa de honestidade sumiu do rodapé"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Corte silencioso: fatiar lista em caminho de render exige declarar o resto
# ─────────────────────────────────────────────────────────────────────────────

# Módulos de render já saneados. A lista SÓ PODE CRESCER — módulo saneado nunca volta atrás.
# (mesmo espírito do teto de `tests/test_divida_except_pass.py`.)
_RENDER_SANEADOS = (
    "compliance_agent/reporting/intel_md.py",
    "compliance_agent/reporting/inteligencia_orgao.py",
    "compliance_agent/intel_relatorio.py",
    "compliance_agent/reporting/capitulos_dossie.py",
)

# Dois defeitos diferentes moram no mesmo `[:N]`, e o conserto de cada um é outro:
#
#   (a) FATIA DE LISTA — `for c in contratos[:50]` — perde ITENS inteiros. O leitor vê 50 e não tem
#       como saber que havia 300. Conserto: `completude.top_declarado()`, que devolve a nota.
#   (b) CORTE DE CAMPO — `(c["objeto"] or "—")[:90]` — perde CARACTERES dentro da célula, e sem
#       reticência o leitor nem percebe. Conserto: `completude.campo()`, que sempre marca o corte.
#
# A fatia de lista é a grave: some com o fato. O corte de campo é cosmético, salvo quando cai
# justamente sobre o objeto contratual — que é a informação que mais importa numa carteira.

# `for x in ALGO[:N]:` / `= ALGO[:N]` / `enumerate(ALGO[:N])` — a coleção é fatiada
_RE_FATIA_LISTA = re.compile(
    r"(?:for\s+\w+(?:,\s*\w+)*\s+in\s+|enumerate\(|=\s*|return\s+|\bin\s+)"
    r"[\w\)\]\"']\S*\[:\s*\d+\s*\]"
)
# `(expr)[:N]` colado num f-string/concatenação de texto — corte de caractere
_RE_CORTE_CAMPO = re.compile(r"\[:\s*\d+\s*\]")

# truncar mensagem de erro / timestamp / raiz de CNPJ não é perda de conteúdo do relatório
_CONTEXTO_LEGITIMO = re.compile(
    r"(str\(exc|str\(e\)|repr\(|traceback|\.strftime|isoformat|\bcnpj\b|\bcpf\b|img\[|_txt\b|msg\b|erro\b)",
    re.I,
)


# base da coleção fatiada: `grupos[:8]` -> "grupos"; `pd["confirmados"][:5]` -> "confirmados"
_RE_BASE = re.compile(r"(\w+)(?:\"\]|'\])?\[:\s*\d+\s*\]")


def _declara_o_total(base: str, vizinhas: str) -> bool:
    """A frase já diz quantos existem? `f"{len(grupos)} grupo(s) — ex.: ..."` é honesto: o leitor
    sabe que viu uma amostra e sabe de quantos. Isso não é corte silencioso."""
    if re.search(rf"len\(\s*{re.escape(base)}\b", vizinhas):
        return True
    # contadores já materializados no ctx: n_confirmados, total_grupos, qtd_x…
    return bool(re.search(rf"\b(?:n|qtd|total|num)_{re.escape(base).rstrip('s')}", vizinhas))


def _fatias_de_lista(caminho: Path) -> list[tuple[int, str]]:
    """Linhas que fatiam uma COLEÇÃO sem passar pelo helper de completude nem declarar o total."""
    linhas = caminho.read_text().splitlines()
    achados = []
    for i, linha in enumerate(linhas, 1):
        limpa = linha.split("#", 1)[0]
        if not _RE_FATIA_LISTA.search(limpa):
            continue
        if "top_declarado" in limpa or "completude" in limpa or "campo(" in limpa:
            continue
        if _CONTEXTO_LEGITIMO.search(limpa):
            continue
        # a linha pode ter várias fatias (`g['favorecido'][:30] ... for g in grupos[:8]`);
        # basta que UMA das coleções fatiadas tenha o total declarado por perto.
        bases = _RE_BASE.findall(limpa)
        vizinhas = "\n".join(linhas[max(0, i - 4):i + 3])
        if any(_declara_o_total(b, vizinhas) for b in bases):
            continue
        achados.append((i, linha.strip()))
    return achados


@pytest.mark.parametrize("rel", _RENDER_SANEADOS)
def test_render_nao_corta_lista_em_silencio(rel: str):
    """Quem corta, declara. `top_declarado()` emite a nota; `tudo()` não corta."""
    caminho = _RAIZ / rel
    assert caminho.exists(), f"{rel} sumiu — atualize a lista de saneados"
    nuas = _fatias_de_lista(caminho)
    assert not nuas, (
        f"{rel} fatia coleção sem declarar o resto (use reporting.completude.top_declarado/tudo):\n"
        + "\n".join(f"  :{n}  {t}" for n, t in nuas)
    )


def test_campo_marca_o_corte():
    """Célula truncada sem reticência mente por omissão: 'Fornecimento de medicamentos para a rede'
    e 'Fornecimento de medicamentos para a re' são visualmente a mesma coisa."""
    from compliance_agent.reporting.completude import campo

    assert campo("Fornecimento de medicamentos", 12) == "Fornecimento…"
    assert campo("curto", 40) == "curto"
    assert campo(None, 10) == "—"
    assert campo("", 10) == "—"


def test_helper_de_completude_declara_o_resto():
    from compliance_agent.reporting.completude import top_declarado, tudo

    itens = list(range(100))
    assert tudo(itens) == itens, "tudo() não pode cortar"

    vistos, nota = top_declarado(itens, 10, "OBs")
    assert len(vistos) == 10
    assert "90" in nota and "OBs" in nota, f"nota não declarou o resto: {nota!r}"

    vistos, nota = top_declarado(itens[:5], 10, "OBs")
    assert len(vistos) == 5
    assert nota == "", "sem corte, sem nota"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Paridade MD ↔ PDF — o mesmo caso não pode virar dois documentos
# ─────────────────────────────────────────────────────────────────────────────

def test_orgao_renderiza_contratos_por_fornecedor_no_pdf():
    """A §1-L (contratos por fornecedor: CNPJ, objeto, contratado × pago) é a seção mais
    substantiva do relatório de órgão e existia só no Markdown."""
    from compliance_agent.reporting import inteligencia_orgao as io

    assert hasattr(io, "_secao_contratos_fornecedor_pdf"), (
        "§1-L não tem render de PDF — o PDF de órgão perde a seção mais substantiva, sem avisar"
    )
    fonte = (_RAIZ / "compliance_agent/reporting/inteligencia_orgao.py").read_text()
    corpo_render = fonte.split("def render_pdf", 1)[-1]
    assert "_secao_contratos_fornecedor_pdf" in corpo_render, (
        "§1-L tem render de PDF mas `render_pdf` não a chama"
    )


def test_orgao_usa_o_mesmo_teto_de_ob_no_md_e_no_pdf():
    """Mesma UG, dois números: o MD mostrava 40 OBs/ano e o PDF 12 — e o comentário do código
    afirmava 'sem limite, tudo no PDF'."""
    from compliance_agent.reporting import inteligencia_orgao as io

    assert io.TOP_OB_ANO is None, (
        f"TOP_OB_ANO={io.TOP_OB_ANO!r}: o entregável voltou a ter teto de OBs por exercício"
    )
