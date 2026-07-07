# -*- coding: utf-8 -*-
"""Guarda de recurso da VM — NUNCA crashar por CPU (diretriz do dono).

A VM tem 2 cores. Dois jobs de BROWSER ao mesmo tempo (sweep SIAFE + reader SEI via Playwright) já
derrubaram a sessão (load ~4,4). Este módulo dá o "supervisor consciente de recurso" do jeito certo,
sem substituir o supervisor do SIAFE:

  - `load_ok(max_load)` — guarda de carga (load average por core).
  - `browser_lock()` — lock EXCLUSIVO de browser (filelock): só UM job de browser por vez. SIAFE e SEI
    se serializam em vez de competir pelos 2 cores.
  - `aguardar_recurso(...)` — espera (com timeout) load baixar + adquirir o lock.

Aditivo: jobs que NÃO usam browser (PNCP/HTTP, TFE, providers) não precisam do lock — rodam livres.
Storage-safe: o lock é um arquivo pequeno em data/ com PID+timestamp; locks órfãos (processo morto OU
velhos demais) são quebrados automaticamente.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
_LOCK = _REPO / "data" / "browser.lock"


def n_cores() -> int:
    return os.cpu_count() or 2


def load_atual() -> float:
    """Load average de 1 min (absoluto)."""
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return 0.0


def load_ok(max_por_core: float = 1.5) -> bool:
    """True se o load de 1 min está abaixo de `max_por_core` × núcleos (folga p/ tarefa pesada)."""
    return load_atual() <= max_por_core * n_cores()


def _pid_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _boot_time() -> float:
    """Epoch do último boot (via /proc/stat btime). 0.0 se indisponível.

    Usado p/ invalidar locks de antes do reboot: após um boot os PIDs são reusados, então um lock órfão
    pode coincidir com um PID novo e PARECER vivo — travando o sweep até a idade_max (bug que derrubou o
    SEI sweep após um restart da VM). Qualquer lock criado antes do boot é, por definição, de dono morto."""
    try:
        for linha in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
            if linha.startswith("btime "):
                return float(linha.split()[1])
    except (OSError, ValueError, IndexError) as exc:
        logger.debug("btime ilegível em /proc/stat: %s", exc)
    return 0.0


def _lock_obsoleto(idade_max: float) -> bool:
    """Lock é obsoleto se foi criado ANTES do último boot, OU o dono morreu, OU é mais velho que idade_max."""
    try:
        txt = _LOCK.read_text(encoding="utf-8").strip().split(":")
        pid, ts = int(txt[0]), float(txt[1])
    except (OSError, ValueError, IndexError):
        return True
    bt = _boot_time()
    if bt and ts < bt:            # lock de uma sessão anterior ao boot — PID reusado parece vivo (reboot-safe)
        return True
    if not _pid_vivo(pid):
        return True
    return (time.time() - ts) > idade_max


def _tentar_adquirir(idade_max: float) -> bool:
    _LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()}:{time.time()}".encode())
        os.close(fd)
        return True
    except FileExistsError:
        if _lock_obsoleto(idade_max):
            try:
                _LOCK.unlink()
            except OSError as exc:
                logger.debug("lock obsoleto não removido: %s", exc)
            return _tentar_adquirir(idade_max)
        return False


def _liberar() -> None:
    try:
        txt = _LOCK.read_text(encoding="utf-8").strip().split(":")
        if int(txt[0]) == os.getpid():  # só o dono remove
            _LOCK.unlink()
    except (OSError, ValueError, IndexError) as exc:
        logger.debug("liberação do browser_lock falhou: %s", exc)


@contextmanager
def browser_lock(*, espera_max: float = 600.0, idade_max: float = 1800.0, intervalo: float = 5.0):
    """Lock EXCLUSIVO de browser (SÍNCRONO). Bloqueia até adquirir (ou `espera_max` s). Libera no fim.
    `idade_max`: locks mais velhos que isso (ou de PID morto) são órfãos e são quebrados.
    Uso:  with browser_lock(): ... lança Chromium ..."""
    fim = time.monotonic() + espera_max
    while not _tentar_adquirir(idade_max):
        if time.monotonic() >= fim:
            raise TimeoutError(f"browser_lock: não adquiriu em {espera_max}s (outro browser ativo)")
        time.sleep(intervalo)
    try:
        yield
    finally:
        _liberar()


@asynccontextmanager
async def browser_lock_async(*, espera_max: float = 600.0, idade_max: float = 1800.0, intervalo: float = 5.0):
    """Versão ASSÍNCRONA (não bloqueia o event loop) — p/ o reader SEI, que roda no server async."""
    fim = time.monotonic() + espera_max
    while not _tentar_adquirir(idade_max):
        if time.monotonic() >= fim:
            raise TimeoutError(f"browser_lock_async: não adquiriu em {espera_max}s (outro browser ativo)")
        await asyncio.sleep(intervalo)
    try:
        yield
    finally:
        _liberar()


def aguardar_load(max_por_core: float = 1.5, espera_max: float = 300.0, intervalo: float = 5.0) -> bool:
    """Espera o load cair abaixo do limite (ou timeout). Retorna True se ok, False se estourou o tempo."""
    fim = time.monotonic() + espera_max
    while not load_ok(max_por_core):
        if time.monotonic() >= fim:
            return False
        time.sleep(intervalo)
    return True


async def aguardar_load_async(max_por_core: float = 1.5, espera_max: float = 300.0,
                              intervalo: float = 5.0) -> bool:
    """Versão ASSÍNCRONA — não bloqueia o event loop (p/ uso no server async)."""
    fim = time.monotonic() + espera_max
    while not load_ok(max_por_core):
        if time.monotonic() >= fim:
            return False
        await asyncio.sleep(intervalo)
    return True
