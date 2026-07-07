# -*- coding: utf-8 -*-
"""Catraca da dívida de `except: pass` MUDO em código de produção.

Um handler cujo corpo é só `pass` transforma bug estrutural (tabela ausente,
API caída, cache corrompido) em "0 resultados" silencioso — vazio-por-erro
vira vazio-por-ausência (lição: vault aprendizados/except-pass-mascara-bug-estrutural).

Regra: a dívida só pode CAIR. Curou handlers? ABAIXE o teto no commit.
Precisa de um `pass` legítimo novo? Logue (`logger.debug`) em vez de calar,
ou justifique no commit por que o teto subiu.

Curas: 643fa4e (75), be49d46 (45), ccf7ce2 (59), 4ª (14), 5ª (27), 6ª (20) — teto 184 em 2026-07-07.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Fora da catraca: experimental/debug (baixo valor) e infra.
SKIP = ("_SANDBOX", "tools/debug", ".venv", "tests", ".stversions", "__pycache__", "node_modules")

TETO_MUDOS_PRODUCAO = 184  # 2026-07-07 — só abaixar (ou subir com justificativa no commit)


def _mudos(py: Path) -> list[int]:
    try:
        tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    return [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.ExceptHandler)
        and len(n.body) == 1
        and isinstance(n.body[0], ast.Pass)
    ]


def test_divida_except_pass_nao_cresce():
    por_arquivo = {}
    for py in ROOT.rglob("*.py"):
        s = str(py)
        if any(k in s for k in SKIP):
            continue
        linhas = _mudos(py)
        if linhas:
            por_arquivo[str(py.relative_to(ROOT))] = linhas
    total = sum(len(v) for v in por_arquivo.values())
    piores = sorted(por_arquivo.items(), key=lambda kv: -len(kv[1]))[:5]
    assert total <= TETO_MUDOS_PRODUCAO, (
        f"Dívida de except-pass mudos CRESCEU: {total} > teto {TETO_MUDOS_PRODUCAO}. "
        f"Troque `pass` por logger.debug/warning com contexto. Piores: {piores}"
    )
