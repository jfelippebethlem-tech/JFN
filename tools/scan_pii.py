"""Scanner de CPF (com dígito verificador) para pre-commit/pre-push — O0.5 do plano Esteira Única.

O repositório é público: nenhum CPF íntegro novo pode entrar. Só acusa CPF com DV válido, isolado
(não é pedaço de número maior) e não mascarado. Nunca imprime o CPF inteiro: mostra só os 3 primeiros
dígitos + arquivo/linha, para o relatório não virar ele mesmo um vazamento.

Uso:
  python -m tools.scan_pii --staged            # linhas adicionadas no índice (pre-commit)
  python -m tools.scan_pii --faixa A..B        # linhas adicionadas entre commits (pre-push)
  python -m tools.scan_pii ARQUIVO [...]       # arquivos
Saída 1 se achar; 0 se limpo.
"""
from __future__ import annotations

import re
import subprocess
import sys

# 11 dígitos crus ou ###.###.###-##, sem dígito/ponto colado dos lados (evita chave de NF, nº de processo).
_RE = re.compile(r"(?<![\d.\-/])(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})(?![\d\-/])")


def cpf_valido(c: str) -> bool:
    d = [int(x) for x in c if x.isdigit()]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        s = sum(v * p for v, p in zip(d[:n], range(n + 1, 1, -1)))
        r = (s * 10) % 11
        if (0 if r == 10 else r) != d[n]:
            return False
    return True


def achar_cpfs(texto: str) -> list[str]:
    out = []
    for m in _RE.finditer(texto):
        c = re.sub(r"\D", "", m.group(1))
        if cpf_valido(c):
            out.append(c)
    return out


def _linhas_adicionadas(diff: str):
    arq = "?"
    for ln in diff.splitlines():
        if ln.startswith("+++ "):
            arq = ln[6:] if ln.startswith("+++ b/") else ln[4:]
        elif ln.startswith("+") and not ln.startswith("+++"):
            yield arq, ln[1:]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout


def main(argv: list[str]) -> int:
    achados: list[tuple[str, str]] = []
    if argv[:1] == ["--staged"]:
        for arq, ln in _linhas_adicionadas(_git("diff", "--cached", "-U0", "--no-color")):
            achados += [(arq, c) for c in achar_cpfs(ln)]
    elif argv[:1] == ["--faixa"] and len(argv) > 1:
        for arq, ln in _linhas_adicionadas(_git("diff", "-U0", "--no-color", argv[1])):
            achados += [(arq, c) for c in achar_cpfs(ln)]
    else:
        for p in argv:
            try:
                txt = open(p, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            achados += [(p, c) for c in achar_cpfs(txt)]
    for arq, c in achados:
        print(f"[scan_pii] CPF com DV válido em {arq}: {c[:3]}.***.***-** — mascare antes de versionar")
    return 1 if achados else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
