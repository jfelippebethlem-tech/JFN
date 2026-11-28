# -*- coding: utf-8 -*-
"""arquivo_estado — onde mora e como se grava o estado local do Claude (motor, API, contingência, ritmo).

Uma pasta (`JFN_CLAUDE_DADOS`, senão `<repo>/data`), arquivos JSON pequenos gravados de forma atômica sob trava de
ARQUIVO (`fcntl.flock`, aparece em /proc/locks — nunca trava por nome de processo), e a regra "teste nenhum chama
provedor, manda mensagem ao dono ou suja dado real" num lugar só. Este módulo não importa nada do pacote.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]


def dados() -> Path:
    """Pasta do estado (lida a cada uso: o teste desvia por env)."""
    return Path(os.environ.get("JFN_CLAUDE_DADOS") or (_REPO / "data"))


def sob_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


@contextmanager
def trava(caminho: Path, espera: float | None):
    """Trava de ARQUIVO. Rende True se pegou dentro de `espera` s; `espera=None` bloqueia até pegar."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(caminho, os.O_RDWR | os.O_CREAT, 0o600)
    pegou = False
    try:
        if espera is None:
            fcntl.flock(fd, fcntl.LOCK_EX)
            pegou = True
        else:
            limite = time.monotonic() + max(0.0, espera)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    pegou = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= limite:
                        break
                    time.sleep(0.5)
        yield pegou
    finally:
        if pegou:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def trava_vaga(caminho: Path, vagas: int, espera: float | None):
    """Trava de ARQUIVO com `vagas` lugares (`caminho`, `caminho.1`, …): rende True se pegou UM dentro de `espera` s.
    27/11/2026: o `claude` por vez valia nas VMs de 2 vCPU e prendia o it-campo (24 fios) a 1 leitura. vagas=1 é a
    trava de sempre (o mesmo arquivo)."""
    vagas = max(1, int(vagas or 1))
    caminho.parent.mkdir(parents=True, exist_ok=True)
    arqs = [caminho] + [caminho.with_name(f"{caminho.name}.{i}") for i in range(1, vagas)]
    fds = [os.open(a, os.O_RDWR | os.O_CREAT, 0o600) for a in arqs]
    preso = None
    try:
        limite = None if espera is None else time.monotonic() + max(0.0, espera)
        while preso is None:
            for fd in fds:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    preso = fd
                    break
                except BlockingIOError:
                    continue
            if preso is None:
                if limite is not None and time.monotonic() >= limite:
                    break
                time.sleep(0.5)
        yield preso is not None
    finally:
        if preso is not None:
            fcntl.flock(preso, fcntl.LOCK_UN)
        for fd in fds:
            os.close(fd)


def ler_json(caminho: Path) -> dict:
    """O objeto do arquivo; ausente, ilegível ou não-objeto ⇒ {}."""
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def gravar_json(caminho: Path, conteudo: dict) -> None:
    """Escrita atômica (tmp + replace). Falha de disco é registrada e engolida: registro não derruba o juízo."""
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = caminho.with_suffix(caminho.suffix + ".tmp")
        tmp.write_text(json.dumps(conteudo, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, caminho)
    except OSError as e:
        logger.warning("arquivo_estado: não gravei %s (%s)", caminho.name, e)


def mutar_json(caminho: Path, fn, *, espera: float | None, ler=ler_json):
    """Lê → `fn(d)` → grava, sob a trava `<arquivo>.lock`. Devolve o que `fn` devolver.

    Com `espera` (s) e a trava não vindo no prazo, grava assim mesmo: é o contador de uso/estado do motor, e um
    contador um pouco torto vale mais que o juízo parado por causa dele. `espera=None` bloqueia até pegar."""
    with trava(caminho.with_suffix(caminho.suffix + ".lock"), espera):
        d = ler(caminho)
        r = fn(d)
        gravar_json(caminho, d)
        return r
