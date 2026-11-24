"""Credenciais compartilhadas entre as 3 máquinas (dono, 24/11/2026: "que possam usar credenciais umas das outras").

Fonte de verdade: a VM-1 (~/JFN/.env e ~/.config/jfn/*.env). Para cada destino (vm2 e it-campo WSL →
~/JFN-worker/.env e ~/.config/jfn/*.env):
  - só ACRESCENTA chave que falta no destino — nunca sobrescreve (chave específica da máquina, ex. JFN_MAQUINA,
    continua a do destino);
  - arquivo de ~/.config/jfn que não existe no destino nasce com as chaves da fonte;
  - permissão 600, diretório 700; backup .bak-<data> antes de alterar um arquivo existente;
  - NUNCA imprime valor: só nome de arquivo e contagem de chaves.
Os valores trafegam só pelo stdin do ssh (Tailnet) — nunca em linha de comando nem em log. Nada disto vai ao git.
Credencial OAuth do Claude Code NÃO é copiada: o token de renovação gira e duas máquinas com o mesmo token
derrubam uma à outra — cada máquina faz o próprio login (memória celular-sem-prompts-3-maquinas).

Uso:
  python -m tools.credenciais_sync              # ensaio: mostra o que acrescentaria
  python -m tools.credenciais_sync --aplicar
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
FONTE_ENV = HOME / "JFN" / ".env"
FONTE_CFG = HOME / ".config" / "jfn"
DESTINOS = {
    "vm2": ["ssh", "vm2", "python3 -"],
    "itcampo": ["ssh", "it-campo", "wsl -d Ubuntu python3 -"],
}

# Programa executado no destino. Os dados entram embutidos em base64 (no lugar de __DADOS__).
_REMOTO = r'''
import base64, json, os, re, time
dados = json.loads(base64.b64decode("__DADOS__").decode())
aplicar = dados.pop("__aplicar__")
CH = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
out = {}
for destino, texto in dados.items():
    p = os.path.expanduser(destino)
    existe = os.path.exists(p)
    atual = open(p, encoding="utf-8", errors="replace").read() if existe else ""
    tem = {m.group(1) for m in map(CH.match, atual.splitlines()) if m}
    novas = [ln for ln in texto.splitlines() if (m := CH.match(ln)) and m.group(1) not in tem]
    out[destino] = {"existia": existe, "acrescentar": len(novas)}
    if aplicar and novas:
        os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
        if existe:
            bak = p + ".bak-" + time.strftime("%Y%m%d%H%M")
            with open(bak, "w") as b:
                b.write(atual)
            os.chmod(bak, 0o600)
        corpo = (atual.rstrip("\n") + "\n" if atual else "") + \
            "# --- acrescentado por credenciais_sync (fonte VM-1) ---\n" + "\n".join(novas) + "\n"
        fd = os.open(p + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(corpo)
        os.replace(p + ".tmp", p)
        os.chmod(p, 0o600)
print(json.dumps(out))
'''


# Chaves que descrevem a MÁQUINA (caminho, terminal, gateway do Yoda, depuração), não credencial: não viajam —
# senão o destino passa a se comportar como a VM-1.
_DA_MAQUINA = re.compile(r"^(JFN_MAQUINA|JFN_HOST|JFN_NO|DISPLAY|RCLONE_BIN|HERMES_.*|TERMINAL_.*|GATEWAY_.*|.*_DEBUG"
                         r"|.*_PATH|.*_DIR|.*_BIN)=")


def _so_credenciais(texto: str) -> str:
    return "\n".join(ln for ln in texto.splitlines() if not _DA_MAQUINA.match(ln))


def pacote() -> dict[str, str]:
    pac = {"~/JFN-worker/.env": _so_credenciais(FONTE_ENV.read_text(encoding="utf-8", errors="replace"))}
    for f in sorted(FONTE_CFG.glob("*.env")):
        pac[f"~/.config/jfn/{f.name}"] = f.read_text(encoding="utf-8", errors="replace")
    return pac


def programa(pac: dict, aplicar: bool) -> str:
    dados = dict(pac, __aplicar__=aplicar)
    return _REMOTO.replace("__DADOS__", base64.b64encode(json.dumps(dados).encode()).decode())


def sincronizar(destino: str, aplicar: bool) -> dict:
    r = subprocess.run(DESTINOS[destino], input=programa(pacote(), aplicar), capture_output=True, text=True,
                       timeout=90)
    linhas = (r.stdout or "").strip().splitlines()
    if r.returncode != 0 or not linhas:
        return {"erro": ((r.stderr or "").strip().splitlines() or ["falhou"])[-1][:200]}
    return json.loads(linhas[-1])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--destino", choices=sorted(DESTINOS), action="append")
    a = ap.parse_args(argv)
    for d in a.destino or sorted(DESTINOS):
        print(f"[{d}] {'APLICADO' if a.aplicar else 'ensaio'}:", json.dumps(sincronizar(d, a.aplicar), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
