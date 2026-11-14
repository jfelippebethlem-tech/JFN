# -*- coding: utf-8 -*-
"""Linha de base que só desce — o motor das catracas de regra.

Uma catraca de regra conta ocorrências de um defeito por arquivo VERSIONADO (`git ls-files`: dívida de arquivo
não rastreado não é nossa e some sozinha) e compara com `tests/golden/qualidade_base.json`:

  · arquivo com mais ocorrências do que a base ⇒ vermelho (a dívida cresceu);
  · arquivo que não está na base nasce em ZERO (código novo não herda licença);
  · curou? rode `python -m compliance_agent.qualidade base --apertar` e commite a base menor.

A base nunca sobe por ferramenta: subir exige editar o JSON à mão e dizer o motivo no commit (CST-05).
"""
from __future__ import annotations

import fcntl
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Iterable

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "tests" / "golden" / "qualidade_base.json"


def versionados(padroes: Iterable[str], repo: Path = REPO) -> list[str]:
    """Arquivos rastreados que casam os padrões (pathspec do git), em ordem."""
    r = subprocess.run(["git", "ls-files", "--", *padroes], cwd=repo, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-files falhou: {r.stderr[:200]}")
    return sorted(ln for ln in r.stdout.splitlines() if ln)


def candidatos(regex: str, padroes: Iterable[str], repo: Path = REPO) -> list[str]:
    """Arquivos rastreados que CONTÊM a regex (git grep, rápido); o verificador em Python só abre esses."""
    r = subprocess.run(["git", "grep", "-lIE", regex, "--", *padroes], cwd=repo, capture_output=True, text=True, timeout=120)
    if r.returncode not in (0, 1):                      # 1 = nenhum arquivo casa
        raise RuntimeError(f"git grep falhou: {r.stderr[:200]}")
    return sorted(ln for ln in r.stdout.splitlines() if ln)


def contar(arquivos: Iterable[str], achar: Callable[[str, str], list], repo: Path = REPO) -> dict[str, int]:
    """`achar(caminho_relativo, texto)` devolve a lista de ocorrências; só entram arquivos com ≥ 1."""
    out = {}
    for rel in arquivos:
        try:
            texto = (repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n = len(achar(rel, texto))
        if n:
            out[rel] = n
    return out


def ler_base(nome: str, base: Path = BASE) -> dict[str, int]:
    if not base.exists():
        return {}
    return json.loads(base.read_text(encoding="utf-8")).get(nome, {})


def cresceu(atual: dict[str, int], base: dict[str, int]) -> list[str]:
    """O que impede o commit: arquivos acima da base (ou novos acima de zero)."""
    return [f"{rel}: {n} (base {base.get(rel, 0)})" for rel, n in sorted(atual.items()) if n > base.get(rel, 0)]


def folga(atual: dict[str, int], base: dict[str, int]) -> int:
    """Quanto a base está acima do real — dívida já paga que ainda não foi travada."""
    return sum(max(0, b - atual.get(rel, 0)) for rel, b in base.items())


def gravar_base(nome: str, atual: dict[str, int], base: Path = BASE, *, so_apertar: bool = True) -> dict[str, int]:
    """Grava a base de uma catraca. `so_apertar` (padrão): nunca sobe — por arquivo, fica o MENOR entre o
    real e o que já estava; arquivo novo não entra. A primeira gravação (catraca sem base) registra o real."""
    base.parent.mkdir(parents=True, exist_ok=True)
    # trava: várias catracas gravam a mesma base (ler-modificar-gravar sem trava já perdeu índice nesta casa)
    with open(Path(tempfile.gettempdir()) / "jfn_qualidade_base.lock", "w") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        tudo = json.loads(base.read_text(encoding="utf-8")) if base.exists() else {}
        antiga = tudo.get(nome)
        if antiga is None or not so_apertar:
            nova = dict(sorted(atual.items()))
        else:
            nova = {rel: min(n, atual.get(rel, 0)) for rel, n in sorted(antiga.items())
                    if min(n, atual.get(rel, 0)) > 0}
        tudo[nome] = nova
        base.write_text(json.dumps(dict(sorted(tudo.items())), ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    return nova


def mensagem(regra: str, o_que: str, excesso: list[str]) -> str:
    return (f"{regra}: {o_que} — a dívida CRESCEU em {len(excesso)} arquivo(s):\n  " + "\n  ".join(excesso[:40])
            + "\nConserte o código novo. Base em tests/golden/qualidade_base.json só desce (regra CST-05).")
