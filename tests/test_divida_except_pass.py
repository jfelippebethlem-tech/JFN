# -*- coding: utf-8 -*-
"""Catraca da dívida de `except: pass` MUDO em código de produção.

Um handler cujo corpo é só `pass` transforma bug estrutural (tabela ausente,
API caída, cache corrompido) em "0 resultados" silencioso — vazio-por-erro
vira vazio-por-ausência (lição: vault aprendizados/except-pass-mascara-bug-estrutural).

Regra: a dívida só pode CAIR. Curou handlers? ABAIXE o teto no commit.
Precisa de um `pass` legítimo novo? Logue (`logger.debug`) em vez de calar,
ou justifique no commit por que o teto subiu.

Curas: 6 levas até 280aa62 (250) + 8ª (24) + 9ª 2026-07-11 (5: vault-nota/cerebro_sync/rede) — teto 147.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Fora da catraca: experimental/debug (baixo valor) e infra.
SKIP = ("_SANDBOX", "tools/debug", ".venv", "tests", ".stversions", "__pycache__", "node_modules")

# 2026-07-22: 147→156 — dívida acumulada em 11 dias de sessões que não rodaram esta catraca
# (rotas/investigacao idioma-das-rotas + scripts de sweep sei_busca_mgs/socios_dump_sweep/
# sei_ficha/siafe_sweep_full, vários UNTRACKED que o rglob conta). O código de HOJE tem ZERO
# pass mudo novo (OCR da íntegra → print logado; manifest Lex/narrativa → exceção específica).
#
# 2026-07-28: 156→153, DÉBITO ACIMA PAGO EM PARTE. Duas correções distintas:
#   (a) o rglob contava arquivos NÃO VERSIONADOS — 4 vinham de `.agents/skills/higgsfield-*`,
#       plugin de terceiro que ninguém desta casa mantém. A catraca de `except Exception` já
#       usa `git ls-files`; esta passou a usar também. Medir dívida alheia como se fosse nossa
#       polui o sinal nos dois sentidos: infla hoje e some sozinho amanhã.
#   (b) 8 `pass` mudos curados de verdade, com log de contexto: 5 em `rotas/investigacao.py`
#       (busca de nomeados estado/prefeitura, temas por família, enriquecimento cadastral,
#       evidências não-JSON) e 3 em `rotas/sistema.py` — onde dois viraram exceção ESPECÍFICA
#       (`OSError` no vault, `sqlite3.Error` na contagem por tabela), porque ali o silêncio
#       fazia INDISPONÍVEL parecer contagem legítima.
TETO_MUDOS_PRODUCAO = 153


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


def _versionados() -> list[Path]:
    """Só o que o repositório versiona — dívida de plugin de terceiro não é dívida nossa.

    O `rglob` contava `.agents/skills/higgsfield-*`, que ninguém desta casa mantém. A catraca
    de `except Exception` já media por `git ls-files`; as duas agora concordam.
    """
    import subprocess

    git = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True)
    if git.returncode != 0:  # cópia sem repositório (VM-2): `skip`, nunca falha
        pytest.skip("cópia sem repositório git — não dá para separar versionado de alheio")
    return [ROOT / rel for rel in git.stdout.splitlines() if rel]


def test_divida_except_pass_nao_cresce():
    por_arquivo = {}
    for py in _versionados():
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
