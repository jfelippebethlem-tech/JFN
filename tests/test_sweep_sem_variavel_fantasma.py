# -*- coding: utf-8 -*-
"""Script de sweep com `set -u` não pode citar variável que ninguém define — ele morre CALADO.

O CASO (2026-08-08). `tools/sweep_sei.sh` ganhou um passo que usava `"$REPO/tools/colher_vm2.sh"`
— e `REPO` nunca foi definido ali. Com `set -u`, o shell morre na hora em que expande a variável:
o erro vai para o stderr do cron, que ninguém lê, e o script simplesmente PARA no meio. Medido no
log: nenhum `say "fim"` desde que o bloco entrou (06/08 21:58), e TODO passo depois daquela linha
— cpf, refichar, depurar, árvore, direcionamento, lex — ficou um dia e meio sem rodar, em
silêncio. O `bash -n` não pega: sintaxe válida, variável fantasma.

É a pior forma da família "roda e sempre falha": aqui nem o rc mente, porque não há rc — o cron
enxerga o processo terminar e nada registra o que deixou de acontecer.

A regra: toda `$MAIUSCULA` citada num script de sweep tem de ser (a) atribuída no próprio arquivo,
(b) herdada de ambiente sabidamente presente (PATH, HOME, USER...), ou (c) protegida por default
(`${X:-...}`). Fora disso é fantasma.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SCRIPTS = sorted((RAIZ / "tools").glob("sweep_*.sh")) + [
    RAIZ / "tools" / "colher_vm2.sh", RAIZ / "tools" / "vm2_suite.sh",
    RAIZ / "tools" / "vm2_analise.sh"]

# ambiente que o cron/systemd garante, mais as que o próprio bash define
_AMBIENTE = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "PWD", "LANG", "TERM",
             "PYTHONPATH", "RANDOM", "SECONDS", "PPID", "PID", "BASHPID", "OLDPWD",
             "HOSTNAME", "UID", "EUID"}


def _fantasmas(texto: str) -> set[str]:
    # remove comentários e heredocs 'EOF' quotados (conteúdo não é shell)
    linhas = []
    em_heredoc = None
    for ln in texto.split("\n"):
        if em_heredoc:
            if ln.strip() == em_heredoc:
                em_heredoc = None
            continue
        m = re.search(r"<<\s*'(\w+)'", ln)
        if m:
            em_heredoc = m.group(1)
        linhas.append(ln.split("#", 1)[0])
    corpo = "\n".join(linhas)

    # atribuição vale no INÍCIO da linha, depois de `;` (`local L; L=$(...)`) e em `local`/`read`
    # — a primeira versão só via o início de linha e acusou `L` de uma função como fantasma.
    definidas = set(re.findall(r"(?:^|;)\s*(?:export\s+|local\s+)?([A-Z][A-Z0-9_]*)=", corpo, re.M))
    definidas |= set(re.findall(r"\blocal\s+([A-Z][A-Z0-9_]*)", corpo))
    definidas |= set(re.findall(r"\bread\s+(?:-r\s+)?([A-Z][A-Z0-9_]*)", corpo))
    definidas |= set(re.findall(r"for\s+([A-Z][A-Z0-9_]*)\s+in", corpo))
    usadas = set(re.findall(r"\$\{?([A-Z][A-Z0-9_]*)\b(?!:-|:=|\-)", corpo))
    # `${X:-padrão}` tem default — não morre com set -u
    com_default = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*):[-=]", corpo))
    return usadas - definidas - com_default - _AMBIENTE


def _chaves_do_env() -> set[str]:
    """Nomes (só nomes) do `.env` — scripts que o SOURCEIAM herdam essas variáveis de verdade."""
    env = RAIZ / ".env"
    if not env.exists():
        return set()
    return set(re.findall(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=", env.read_text(encoding="utf-8"), re.M))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_nenhuma_variavel_fantasma(script):
    if not script.exists():
        pytest.skip(f"{script.name} não existe neste ambiente")
    texto = script.read_text(encoding="utf-8")
    # SEM `set -u` a variável fantasma expande vazia — comportamento com seus próprios riscos, mas
    # não o desta catraca, que vigia a MORTE SILENCIOSA no meio do script.
    if not re.search(r"^\s*set -u", texto, re.M):
        pytest.skip(f"{script.name} não usa `set -u` — a morte silenciosa não se aplica")
    fantasmas = _fantasmas(texto)
    if re.search(r"^[^#\n]*\.\s+\S*\.env\b|^[^#\n]*source\s+\S*\.env\b", texto, re.M):
        fantasmas -= _chaves_do_env()
    assert not fantasmas, (
        f"{script.name} usa variável que ninguém define: {sorted(fantasmas)} — com `set -u` o "
        f"script MORRE ali, calado, e todo passo depois da linha deixa de rodar. Foi assim que "
        f"cpf, refichar, depurar, árvore e lex ficaram um dia e meio parados.")


def test_a_catraca_pega_o_caso_real():
    """Prova com o defeito exato que motivou o teste."""
    quebrado = 'set -u\nsay(){ echo "$*"; }\ntimeout 1200 bash "$REPO/tools/colher_vm2.sh"\n'
    assert "REPO" in _fantasmas(quebrado)
    consertado = "set -u\nREPO=/home/ubuntu/JFN\n" + quebrado.split("\n", 1)[1]
    assert "REPO" not in _fantasmas(consertado)
