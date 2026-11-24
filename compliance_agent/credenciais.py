"""Resolvedor de credenciais entre as 3 máquinas — ACHA, não copia (dono, 24/11/2026: "não bagunce nada. apenas as
faça achar as credenciais umas nas outras ou no documento que temos com todas as chaves").

Ordem de busca de um NOME (para no primeiro que tiver):
  1. ambiente do processo (os.environ);
  2. arquivos locais: ~/JFN/.env, ~/JFN-worker/.env, ~/.config/jfn/*.env, ~/CREDENCIAIS.md;
  3. a VM-1 por ssh (mesmos arquivos de lá), pelo primeiro alias que responder (vm1, vm1-ts, jfn-core).
Nada é gravado em disco: o valor fica só na memória do processo (cache por nome). O nome vai ao ssh pelo stdin,
e o valor volta pelo canal cifrado do ssh. A CLI nunca imprime valor.

CLI:
  python -m compliance_agent.credenciais onde NOME [NOME...]      # diz ONDE achou (nunca o valor)
  python -m compliance_agent.credenciais com NOME[,NOME] -- cmd …  # roda cmd com as variáveis no ambiente
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
ALIASES_VM1 = ("vm1", "vm1-ts", "jfn-core")
_KV = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})=(.*)$")
_LISTA = re.compile(r"^\s*[-*]\s*\**`?([A-Z][A-Z0-9_]{2,})`?\**\s*[:=]\s*(.+)$")
_cache: dict[str, tuple[str, str]] = {}


def _limpar(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"`":
        v = v[1:-1]
    return v.strip()


def ler_texto(nome: str, texto: str) -> str | None:
    """Procura NOME num texto .env ou Markdown (KEY=valor ou '- KEY: valor'). Último valor não vazio vence."""
    achado = None
    for ln in texto.splitlines():
        m = _KV.match(ln) or _LISTA.match(ln)
        if m and m.group(1) == nome:
            v = _limpar(m.group(2))
            if v:
                achado = v
    return achado


def arquivos_locais(home: Path = HOME) -> list[Path]:
    fixos = [home / "JFN" / ".env", home / "JFN-worker" / ".env"]
    cfg = sorted((home / ".config" / "jfn").glob("*.env")) if (home / ".config" / "jfn").is_dir() else []
    return [p for p in [*fixos, *cfg, home / "CREDENCIAIS.md"] if p.is_file()]


def _local(nome: str, home: Path = HOME) -> tuple[str, str] | None:
    for p in arquivos_locais(home):
        v = ler_texto(nome, p.read_text(encoding="utf-8", errors="replace"))
        if v:
            return v, f"local:{p.name}"
    return None


# Roda na VM-1: lê o nome pelo stdin, procura nos mesmos arquivos e devolve "fonte\tvalor" (ou nada).
_REMOTO = r'''
import sys, re
from pathlib import Path
nome = sys.stdin.readline().strip()
KV = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})=(.*)$")
LI = re.compile(r"^\s*[-*]\s*\**`?([A-Z][A-Z0-9_]{2,})`?\**\s*[:=]\s*(.+)$")
h = Path.home()
arqs = [h/"JFN"/".env", *sorted((h/".config"/"jfn").glob("*.env")), h/"CREDENCIAIS.md"]
for p in arqs:
    if not p.is_file():
        continue
    v = None
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = KV.match(ln) or LI.match(ln)
        if m and m.group(1) == nome:
            x = m.group(2).strip()
            if len(x) >= 2 and x[0] == x[-1] and x[0] in "'\"`":
                x = x[1:-1]
            if x.strip():
                v = x.strip()
    if v:
        print(p.name + "\t" + v)
        break
'''


def _remoto(nome: str) -> tuple[str, str] | None:
    for alias in ALIASES_VM1:
        try:
            # o ssh junta os argumentos numa string para o shell remoto: o código vai com aspas (shlex)
            r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", alias,
                                "python3 -c " + shlex.quote(_cmd_remoto())], input=nome + "\n",
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 255:          # alias não resolve / não conecta: tenta o próximo
            continue
        linha = (r.stdout or "").strip().splitlines()
        if linha and "\t" in linha[-1]:
            fonte, v = linha[-1].split("\t", 1)
            return v, f"vm1({alias}):{fonte}"
        return None                      # VM-1 respondeu e não tem
    return None


def _cmd_remoto() -> str:
    import base64
    return "import base64;exec(base64.b64decode('" + base64.b64encode(_REMOTO.encode()).decode() + "').decode())"


def obter(nome: str, *, remoto: bool = True) -> str | None:
    """Valor da credencial NOME, ou None se nenhuma máquina tiver. Nunca grava em disco."""
    if os.environ.get(nome):
        return os.environ[nome]
    if nome in _cache:
        return _cache[nome][0]
    achado = _local(nome) or (_remoto(nome) if remoto else None)
    if achado:
        _cache[nome] = achado
        return achado[0]
    return None


def onde(nome: str, *, remoto: bool = True) -> str:
    if os.environ.get(nome):
        return "ambiente"
    if obter(nome, remoto=remoto) is None:
        return "NAO ENCONTRADA"
    return _cache[nome][1]


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "onde":
        for n in argv[1:]:
            print(f"{n}: {onde(n)}")
        return 0
    if len(argv) >= 3 and argv[0] == "com" and "--" in argv:
        nomes = [n for n in argv[1].split(",") if n]
        cmd = argv[argv.index("--") + 1:]
        env = dict(os.environ)
        faltam = []
        for n in nomes:
            v = obter(n)
            if v is None:
                faltam.append(n)
            else:
                env[n] = v
        if faltam:
            print("credencial não encontrada em nenhuma máquina: " + ", ".join(faltam), file=sys.stderr)
            return 2
        return subprocess.run(cmd, env=env).returncode
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
