#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sincroniza o `?v=<hash8>` de painel.css/painel.js em static/jfn-painel.html com o conteúdo real.

O PROBLEMA, MEDIDO (2026-07-31). `tools/painel_extrair.py` calcula o `?v=` UMA vez, no momento da
extração. Depois disso ninguém mais o toca: cada edição em `static/js/painel.js` saía com a mesma
catraca `?v=66af4ca4` e o navegador servia o arquivo do cache — a correção existia no repositório e
não chegava a ninguém. Era o `?v=` que ficava congelado no HTML, não o cache que estava errado.

Este script é a peça que faltava: recalcula os dois hashes (mesma função do painel_extrair) e
reescreve as tags. Em `--check` não escreve nada e sai != 0 se estiver defasado — é o modo que o
gate do pre-commit usa.

Uso:
    .venv/bin/python -m tools.painel_bump_versao            # corrige o HTML
    .venv/bin/python -m tools.painel_bump_versao --check    # só verifica (pre-commit)
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_HTML = _REPO / "static" / "jfn-painel.html"
# v58: o CONTROLE tambem carrega o CSS e o icon-set do painel. Ficar de fora da catraca
# significaria servir a folha VELHA de cache nessa tela — o mesmo defeito que este script
# existe para matar, so que numa pagina que ninguem lembra de olhar.
_CONTROLE = _REPO / "static" / "jfn-controle.html"
# v58: o fonte virou `static/js/src/` e o que o navegador baixa é o BUNDLE. Os dois papéis do
# antigo painel.js se separaram e precisam ser nomeados a parte:
#   _BUNDLE  — o ARTEFATO servido; é o hash dele que vai para a tag `?v=` do HTML.
#   _MALHA_SRC — o PORTADOR do `s.src='/static/assets/rj-malha.js?v=...'`, que mora no fonte.
# Apontar o portador da malha para o bundle faria a catraca reescrever o artefato e o rebuild
# seguinte apagaria a correção — defasagem em looping, silenciosa.
_BUNDLE = _REPO / "static" / "js" / "painel.bundle.js"
_MALHA_SRC = _REPO / "static" / "js" / "src" / "cena" / "malha-rj.js"
if not _MALHA_SRC.exists():                       # a cena ainda e um modulo so
    _MALHA_SRC = _REPO / "static" / "js" / "src" / "cena" / "index.js"
if not _MALHA_SRC.exists():                       # antes da quebra por dominio, era o entrypoint
    _MALHA_SRC = _REPO / "static" / "js" / "src" / "entrada.js"
if not _MALHA_SRC.exists():                       # e antes do build, era o próprio monolito
    _MALHA_SRC = _REPO / "static" / "js" / "painel.js"
# (nome, arquivo cujo conteúdo dá o hash, arquivo que carrega a tag, regex da tag).
# ORDEM IMPORTA: rj-malha é referenciado DENTRO de painel.js, então precisa ser reescrito
# antes de painel.js virar hash — senão a catraca do painel nasce defasada no mesmo passo.
# caps.js, jfn-icones.js e rj-malha.js são GERADOS; ficavam de fora e o navegador servia a
# cópia velha (medido 2026-07-31: caps.js regenerado com os ícones de grupo não chegava à tela).
_ALVOS = (
    ("css", _REPO / "static" / "css" / "painel.css", _HTML, re.compile(r'(painel\.css\?v=)([0-9a-f]{8})')),
    ("caps", _REPO / "static" / "js" / "caps.js", _HTML, re.compile(r'(caps\.js\?v=)([0-9a-f]{8})')),
    ("icones", _REPO / "static" / "assets" / "jfn-icones.js", _HTML, re.compile(r'(jfn-icones\.js\?v=)([0-9a-f]{8})')),
    ("malha", _REPO / "static" / "assets" / "rj-malha.js", _MALHA_SRC, re.compile(r'(rj-malha\.js\?v=)([0-9a-f]{8})')),
    ("js", _BUNDLE, _HTML, re.compile(r'(painel\.bundle\.js\?v=)([0-9a-f]{8})')),
    ("css/controle", _REPO / "static" / "css" / "painel.css", _CONTROLE,
     re.compile(r'(painel\.css\?v=)([0-9a-f]{8})')),
    ("icones/controle", _REPO / "static" / "assets" / "jfn-icones.js", _CONTROLE,
     re.compile(r'(jfn-icones\.js\?v=)([0-9a-f]{8})')),
)


def _hash8(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:8]


def _rebuild() -> None:
    """Reconstrói o bundle. Sem toolchain, AVISA e segue — não derruba quem só mexeu em Python."""
    import shutil
    import subprocess
    npm = shutil.which("npm")
    if not npm:
        print("[bump] npm ausente — bundle NÃO reconstruído. A tag do painel vai refletir o "
              "artefato antigo; rode `npm run build:painel` numa máquina com Node.", file=sys.stderr)
        return
    r = subprocess.run([npm, "run", "--silent", "build:painel"], cwd=_REPO,
                       capture_output=True, text=True)
    if r.returncode:
        print(f"[bump] build do painel FALHOU:\n{r.stderr.strip()[:800]}", file=sys.stderr)
        raise SystemExit(3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="não escreve; sai 1 se estiver defasado")
    a = ap.parse_args()

    texto = {}  # portador -> conteúdo em memória (um portador pode ser alvo de outra catraca)
    defasados: list[str] = []

    def _passar(alvos) -> int | None:
        """Aplica um lote de catracas em memória. Devolve código de erro, ou None se tudo certo."""
        for nome, arquivo, portador, rx in alvos:
            if not arquivo.exists():
                continue
            if portador not in texto:
                texto[portador] = portador.read_text(encoding="utf-8")
            fonte = texto.get(arquivo, arquivo.read_text(encoding="utf-8"))
            novo = _hash8(fonte)
            m = rx.search(texto[portador])
            if not m:
                print(f"[bump] tag de {nome} não encontrada em {portador.name} — reveja à mão",
                      file=sys.stderr)
                return 2
            if m.group(2) != novo:
                defasados.append(f"{nome}: {m.group(2)} -> {novo}")
                texto[portador] = rx.sub(lambda mm, n=novo: mm.group(1) + n, texto[portador], count=1)
        return None

    def _gravar() -> None:
        for portador, conteudo in texto.items():
            if conteudo != portador.read_text(encoding="utf-8"):
                portador.write_text(conteudo, encoding="utf-8")

    # v58 — DUAS PASSADAS, e a ordem é o ponto. A catraca da malha reescreve `?v=` DENTRO do
    # fonte (`src/entrada.js`); o do painel lê o hash do BUNDLE. Numa passada só, o bundle seria
    # hasheado antes de o rebuild incorporar a malha nova, e a tag do HTML nasceria apontando um
    # artefato que a próxima build muda — defasagem em looping, silenciosa, que é exatamente a
    # classe de bug que este script existe para matar.
    fora_js = [x for x in _ALVOS if x[0] != "js"]
    so_js = [x for x in _ALVOS if x[0] == "js"]

    if (err := _passar(fora_js)) is not None:
        return err

    if defasados and not a.check:
        _gravar()
        texto.clear()
        # o fonte pode ter mudado (a tag da malha mora nele) — o artefato precisa acompanhar
        if _BUNDLE.exists() and "js/src/" in _MALHA_SRC.as_posix():
            _rebuild()

    if (err := _passar(so_js)) is not None:
        return err

    if not defasados:
        print("[bump] catracas em dia")
        return 0
    if a.check:
        print("[bump] catraca do painel DEFASADA (" + "; ".join(defasados) + ")\n"
              "       rode: .venv/bin/python -m tools.painel_bump_versao", file=sys.stderr)
        return 1
    _gravar()
    print("[bump] " + "; ".join(defasados))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
