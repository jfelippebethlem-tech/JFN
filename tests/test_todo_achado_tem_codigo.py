# -*- coding: utf-8 -*-
"""Catraca: todo achado do 360 nasce com CÓDIGO.

Medido em 2026-08-05: **532 dos 667 achados do acervo (80%)** chegavam sem `codigo`, e o painel
os empilhava num balde único rotulado "—". O diff da pós-correção herdava a cegueira: correção
dentro de `fases.lacunas` (473), `acatamento` (34), `cadeia` (24) ou `suficiencia_emissor` (1)
não aparecia para o instrumento que existe justamente para medir o efeito de uma correção.

A verificação é ESTÁTICA de propósito. Rodar o 360 sobre um processo real para conferir isto
dependeria de qual processo tem qual achado — o teste passaria a medir o acervo, não o código.
"""
from __future__ import annotations

import ast
from pathlib import Path

ALVO = Path(__file__).resolve().parents[1] / "compliance_agent" / "processo_360.py"


def _appends_de_achados(arvore: ast.AST) -> list[ast.Call]:
    fora = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call) or not isinstance(no.func, ast.Attribute):
            continue
        if no.func.attr != "append":
            continue
        alvo = no.func.value
        if isinstance(alvo, ast.Name) and alvo.id == "achados":
            fora.append(no)
    return fora


def test_todo_achado_do_360_nasce_com_codigo():
    arvore = ast.parse(ALVO.read_text(encoding="utf-8"))
    faltando = []
    for chamada in _appends_de_achados(arvore):
        if not chamada.args or not isinstance(chamada.args[0], ast.Dict):
            continue
        d = chamada.args[0]
        chaves = {k.value for k in d.keys if isinstance(k, ast.Constant)}
        # `None` como chave é o `**a` — o dicionário vem do detector, que já traz o seu código
        # (é o caso da triagem A1–A5 e das famílias que rodam em módulo próprio).
        espalha = any(k is None for k in d.keys)
        if "codigo" not in chaves and not espalha:
            faltando.append(f"linha {d.lineno}: {sorted(chaves)}")
    assert not faltando, (
        "achado sem `codigo` — ele chegaria ao painel e ao diff como \"—\":\n  "
        + "\n  ".join(faltando))
