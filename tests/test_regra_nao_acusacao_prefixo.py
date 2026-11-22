# -*- coding: utf-8 -*-
"""Catraca: descrição de alerta que se declara NÃO acusatória começa com "NÃO é acusação".

Classe de falso positivo (21/11/2026): a triagem pula só o PREFIXO "NÃO é acusação" (`triagem_alertas._SEM_ACUSACAO`).
O D3 tinha dois ramos que diziam a mesma coisa com outras palavras ("A sanção estava vigente, mas NÃO alcança o
pagador…", "…categoria que NÃO veda contratar") — 17 de 17 triados voltaram "provável falso positivo" repetindo a
descrição, e o detector inteiro ficou suspenso da triagem (57% de FP). Esta catraca lê o FONTE de todo
`compliance_agent/` e acusa a instrução (logical line) cujo texto literal tem um marcador de não-acusação e não abre
com o prefixo. Controle positivo: o texto do D3 antes da correção. Controle negativo: o texto corrigido e o
"Indício grave" (que acusa e deve seguir para a triagem).
"""
from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "compliance_agent"
PREFIXO = "NÃO é acusação"
# marcadores de "o próprio detector diz que isto não é irregularidade" (caixa alta = afirmação do detector)
MARCADORES = re.compile(r"NÃO alcança o pagador|categoria que NÃO veda|Não sustenta acusação|"
                        r"não vedação de contratar")
STR_TOK = {tokenize.STRING} | {getattr(tokenize, n) for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
                              if hasattr(tokenize, n)}


def _instrucoes_com_texto(fonte: str):
    """[(linha, texto literal da instrução)] — docstrings (instrução só de string) ficam fora."""
    out, partes, so_str, ini = [], [], True, None
    for tok in tokenize.generate_tokens(io.StringIO(fonte).readline):
        if tok.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
            if partes and not so_str:
                out.append((ini, "".join(partes)))
            partes, so_str, ini = [], True, None
            continue
        if tok.type in (tokenize.NL, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT):
            continue
        ini = ini or tok.start[0]
        if tok.type in STR_TOK:
            partes.append(tok.string)
        else:
            so_str = False
    return out


def _violacoes(fonte: str) -> list[int]:
    ruins = []
    for linha, texto in _instrucoes_com_texto(fonte):
        if MARCADORES.search(texto):
            m = re.search(r"""(?:[rbfRBF]{0,2})(['"]{1,3})(.*)""", texto, re.S)
            corpo = m.group(2) if m else texto
            if not corpo.lstrip().startswith(PREFIXO) and PREFIXO not in texto[:80]:
                ruins.append(linha)
    return ruins


def test_controle_positivo_texto_antigo_do_d3_e_acusado():
    antigo = ('explica = (f"A sanção estava vigente, mas NÃO alcança o pagador da emenda federal "\n'
              '           f"({x}). Risco reputacional a conferir, não vedação de contratar")\n')
    assert _violacoes(antigo) == [1]


def test_controle_negativo_texto_corrigido_e_indicio_grave_passam():
    novo = ('explica = (f"NÃO é acusação: a sanção estava vigente, mas NÃO alcança o pagador da emenda federal "\n'
            '           f"({x}). Risco reputacional a conferir, não vedação de contratar")\n'
            'grave = "Indício grave: a sanção já estava VIGENTE no ano da emenda"\n')
    assert _violacoes(novo) == []


def test_nenhuma_descricao_de_alerta_declara_nao_acusacao_sem_o_prefixo():
    ruins = []
    for p in sorted(RAIZ.rglob("*.py")):
        try:
            v = _violacoes(p.read_text(encoding="utf-8"))
        except (tokenize.TokenError, SyntaxError, UnicodeDecodeError):
            continue
        ruins += [f"{p.relative_to(RAIZ.parent)}:{n}" for n in v]
    assert not ruins, ("descrição que se declara não-acusatória sem o prefixo 'NÃO é acusação' (a triagem não a "
                       f"pula e o juiz julga o erro do detector): {ruins}")
