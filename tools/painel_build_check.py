#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""painel_build_check — o bundle do painel corresponde ao fonte, ou esta servindo codigo velho?

POR QUE ESTE SCRIPT EXISTE, E POR QUE ELE E NOVO. Ate a v57 o painel era UM arquivo: fonte e
artefato eram a mesma coisa, e `tools/painel_bump_versao.py` comparava `sha256(painel.js)` com a
tag `?v=` do HTML. Nesse mundo, "editei e nao bumpei" era impossivel de esconder — o hash mudava.

Com build (`static/js/src/**` -> `static/js/painel.bundle.js`) aparece um estado que a catraca NAO
enxerga: fonte editado, bundle nao reconstruido. O hash do artefato continua batendo com a tag, a
catraca diz "em dia", e a correcao simplesmente nao chega a ninguem — que e exatamente o defeito
que o bump_versao foi escrito para matar, reintroduzido um nivel acima.

Por isso este check e a etapa 0-A do `precommit_painel.sh`: roda ANTES do bump. Se o bundle estiver
defasado, bloqueia com a instrucao de conserto. Se nao houver Node na maquina, AVISA e passa — o
mesmo principio que o `painel_boot_check` ja usa no precommit: um gate que exige toolchain derruba
o commit de quem so mexeu em Python, e um gate que atrapalha e um gate que sera desligado.

Uso:
    python -m tools.painel_build_check           # bloqueia se defasado
    python -m tools.painel_build_check --build   # reconstroi em vez de reclamar
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "static" / "js" / "src"
_ENTRADA = _SRC / "entrada.js"
_BUNDLE = _REPO / "static" / "js" / "painel.bundle.js"

# TEM de ser identico ao `build:painel` do package.json — inclusive `--sourcemap=linked`, que
# acrescenta a linha `//# sourceMappingURL=...` ao fim do bundle. Divergir num flag faz este check
# acusar defasagem eterna por 42 bytes, e um gate que grita sem motivo e um gate que sera desligado.
_FLAGS = ["--bundle", "--format=iife", "--target=es2020", "--charset=utf8", "--sourcemap=linked"]


def _esbuild() -> list[str] | None:
    """Comando para chamar o esbuild instalado, ou None se a toolchain nao existe aqui."""
    local = _REPO / "node_modules" / ".bin" / ("esbuild.cmd" if sys.platform == "win32" else "esbuild")
    if local.exists():
        return [str(local)]
    achado = shutil.which("esbuild")
    return [achado] if achado else None


def construir(destino: Path) -> tuple[bool, str]:
    cmd = _esbuild()
    if not cmd:
        return False, "esbuild ausente"
    r = subprocess.run([*cmd, str(_ENTRADA), *_FLAGS, f"--outfile={destino}"],
                       cwd=_REPO, capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", action="store_true", help="reconstroi o bundle em vez de bloquear")
    a = ap.parse_args(argv)

    if not _ENTRADA.exists():
        print("[build] painel ainda sem build (static/js/src/entrada.js nao existe) — nada a checar")
        return 0
    if not _esbuild():
        print("[build] esbuild ausente nesta maquina — bundle NAO verificado.\n"
              "        Se voce editou static/js/src/, rode `npm run build:painel` antes do commit; "
              "a catraca ?v= sozinha nao percebe bundle defasado.", file=sys.stderr)
        return 0

    if a.build:
        ok, saida = construir(_BUNDLE)
        if not ok:
            print(f"[build] FALHOU:\n{saida[:1200]}", file=sys.stderr)
            return 1
        print(f"[build] bundle reconstruido ({_BUNDLE.stat().st_size // 1024} KB)")
        return 0

    if not _BUNDLE.exists():
        print("[build] static/js/painel.bundle.js NAO existe e o fonte existe.\n"
              "        Rode: npm run build:painel", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as d:
        prova = Path(d) / "painel.bundle.js"
        ok, saida = construir(prova)
        if not ok:
            print(f"[build] o fonte do painel NAO COMPILA:\n{saida[:1200]}", file=sys.stderr)
            return 1
        atual = _BUNDLE.read_bytes()
        novo = prova.read_bytes()

    if atual == novo:
        print("[build] bundle em dia com static/js/src/")
        return 0
    print(f"[build] BUNDLE DEFASADO — static/js/src/ mudou e o artefato nao acompanhou\n"
          f"        artefato no disco : {len(atual)} bytes\n"
          f"        recompilado agora : {len(novo)} bytes\n"
          f"        Conserto: npm run build:painel  (e adicione o artefato ao commit)\n"
          f"        Sem isso o navegador recebe a tag ?v= do arquivo VELHO e a correcao nao "
          f"chega a ninguem — sem erro, sem aviso.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
