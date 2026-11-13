# -*- coding: utf-8 -*-
"""Esqueleto comum das rotinas automáticas que alimentam o painel (perícia contábil, regras da gestão Couto,
confronto CGE × JFN).

Pedido do dono (13/11/2026): "quero tudo rodando, periciando, cruzando informação, com o Claude como motor de tudo".
Cada rotina é UM comando idempotente (`python -m ...`) que o cron chama com `nice` e `timeout`. Este módulo dá as
três coisas que todas precisam e que já falharam na casa quando cada uma fez a sua:

  · trava por ARQUIVO (`fcntl.flock`), nunca por nome de processo (`guarda-por-nome-de-processo-nao-e-mutex`).
    A trava presa aparece em /proc/locks — é por ela que o AO VIVO sabe que a rotina está rodando agora;
  · log com data e hora em CADA linha;
  · gravação ATÔMICA do JSON que o painel lê (tmp + rename): a aba nunca lê meio arquivo;
  · `pensar()` — o motor Claude com import tardio. Sem o motor (módulo ausente, sem cota, erro), devolve
    `(None, motivo)` e a rotina marca a camada subjetiva como PENDENTE; a determinística segue.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("JFN_DATA_DIR") or RAIZ / "data")


def logger_rotina(nome: str, arquivo: Path | None = None) -> logging.Logger:
    """Logger com data em cada linha, no arquivo `data/<nome>.log` e na saída padrão (o cron redireciona)."""
    lg = logging.getLogger(f"rotina.{nome}")
    if lg.handlers:
        return lg
    lg.setLevel(logging.INFO)
    lg.propagate = False
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    destino = arquivo or DATA / f"{nome}.log"
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(destino, encoding="utf-8")
        fh.setFormatter(fmt)
        lg.addHandler(fh)
    except OSError as exc:            # sem disco para o log não é motivo para não rodar
        print(f"[rotina {nome}] log em arquivo indisponível: {exc}", file=sys.stderr)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    lg.addHandler(sh)
    return lg


class TravaOcupada(RuntimeError):
    """Outra execução da mesma rotina segura a trava."""


@contextlib.contextmanager
def trava(caminho: Path):
    """Trava exclusiva NÃO bloqueante por arquivo. Ocupada → `TravaOcupada` (a rotina sai sem fazer nada)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(caminho, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TravaOcupada(str(caminho)) from exc
        os.write(fd, f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}\n".encode())
        yield
    finally:
        os.close(fd)                  # fechar solta o flock


def gravar_json(destino: Path, obj: Any) -> None:
    """Grava atômico: escreve num temporário do MESMO diretório e renomeia por cima."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{destino.name}.", dir=destino.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
        os.chmod(tmp, 0o644)          # mkstemp cria 0600; o painel lê com o mesmo usuário, mas sem surpresa
        os.replace(tmp, destino)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def ler_json(caminho: Path) -> Any:
    """JSON anterior (para histórico e para preservar curadoria). Ausente ou ilegível → None."""
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def agora_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


ULTIMO_MODELO: str | None = None      # modelo que respondeu a última chamada (proveniência da camada subjetiva)


def pensar(tarefa: str, prompt: str, *, schema: dict | None = None, **kw) -> tuple[Any, str | None]:
    """Chama o motor Claude (`compliance_agent.llm.claude_motor.pensar`) e devolve `(resultado, motivo)`.

    resultado None = sem juízo (motivo diz por quê: motor ausente, sem cota, erro). A interface do motor devolve
    o texto/JSON ou None; algumas versões devolvem `(resultado, motivo)` — as duas formas são aceitas."""
    try:
        from compliance_agent.llm import claude_motor  # import tardio: o motor é de outra frente
    except ImportError as exc:
        return None, f"motor Claude ausente nesta base ({exc})"
    fn = getattr(claude_motor, "pensar", None)
    if fn is None:
        return None, "motor Claude sem a função pensar()"
    try:
        r = fn(tarefa, prompt, schema=schema, **kw)
    except Exception as exc:  # noqa: BLE001 — qualquer falha do motor vira "pendente", nunca derruba a rotina
        return None, f"motor Claude falhou: {type(exc).__name__}: {exc}"
    global ULTIMO_MODELO
    motivo = None
    if isinstance(r, tuple) and len(r) == 2:
        r, motivo = r
    if r is None:
        return None, (motivo or getattr(claude_motor, "ultimo_motivo", None) or getattr(claude_motor, "ULTIMO_MOTIVO", None)
                      or "motor Claude sem resposta (cota?)")
    if hasattr(r, "texto"):           # `Pensamento` do motor: dados (JSON já validado) ou o texto cru
        ULTIMO_MODELO = getattr(r, "modelo", None)
        r = r.dados if (schema is not None and getattr(r, "dados", None) is not None) else r.texto
    if schema is not None and isinstance(r, str):
        try:
            r = json.loads(r)
        except ValueError:
            return None, "motor Claude devolveu JSON inválido"
    return r, None


def executar(nome: str, fn, *, trava_arquivo: Path | None = None) -> int:
    """Roda `fn(log)` sob a trava da rotina. Trava ocupada → 0 (não é erro: a outra execução está trabalhando)."""
    log = logger_rotina(nome)
    t0 = time.time()
    try:
        with trava(trava_arquivo or DATA / f"{nome}.lock"):
            log.info("início (pid %s)", os.getpid())
            rc = fn(log) or 0
    except TravaOcupada as exc:
        log.info("outra execução segura a trava %s — saindo sem fazer nada", exc)
        return 0
    except Exception:
        log.exception("falhou após %.1f s", time.time() - t0)
        return 1
    log.info("fim em %.1f s (rc=%s)", time.time() - t0, rc)
    return rc
