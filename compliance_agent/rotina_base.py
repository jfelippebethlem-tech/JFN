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
import sqlite3
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
    feito = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
        os.chmod(tmp, 0o644)          # mkstemp cria 0600; o painel lê com o mesmo usuário, mas sem surpresa
        os.replace(tmp, destino)
        feito = True
    finally:                          # falhou no meio: o temporário não fica para trás (o erro sobe igual)
        if not feito:
            with contextlib.suppress(OSError):
                os.unlink(tmp)


def ler_json(caminho: Path) -> Any:
    """JSON anterior (para histórico e para preservar curadoria). Ausente ou ilegível → None."""
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def agora_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# exceções ESPECÍFICAS (catraca de captura genérica): o que o motor e as rotinas levantam de verdade
_FALHAS_DA_ROTINA = (sqlite3.Error, OSError, ValueError, TypeError, KeyError, RuntimeError, ImportError, AttributeError)

ULTIMO_MODELO: str | None = None      # modelo que respondeu a última chamada (proveniência da camada subjetiva)
ULTIMA_EM_CONTINGENCIA: bool = False  # a última resposta saiu SEM o Claude da assinatura (fila de conferência do Opus)


PROMPT_VERSION = "rotina_base.pensar.v1-20261124"   # rastreabilidade no trace do gateway (o prompt é da rotina)


def _sufixo_api(resp) -> str | None:
    m = resp.modelo or resp.provedor
    if resp.provedor == "api_anthropic":
        from compliance_agent.llm.claude_api import SUFIXO_API
        return f"{m}{SUFIXO_API}"
    return m


def pensar(tarefa: str, prompt: str, *, schema: dict | None = None, **kw) -> tuple[Any, str | None]:
    """O motor Claude PELO GATEWAY (`adaptadores/llm/gateway.chamar`) e devolve `(resultado, motivo)`.

    resultado None = sem juízo (motivo diz por quê: gateway ausente, recusa da política, sem cota, teto, erro, ou
    `ABSTEVE` do modelo com o motivo dele). Antes de 24/11/2026 chamava `claude_motor.pensar(backend="auto")`, que caía
    na API paga sem teto mensal (risco R3 do mapa ~/vault/refatoracao/gateway-llm-pontos-de-chamada.md). Agora:
    camadas 2 (assinatura) → 3 (API, teto US$ 100/mês e corte a 85%), classe de dado declarada pela política da
    tarefa (`gateway.classe_da_tarefa`), máscara de CPF/conta, circuit breaker e trace. Chaves aceitas em `kw`:
    `modelo` (só o da assinatura; a API usa `claude_api.modelo_para`, como antes), `sistema`, `timeout`, `espera`,
    `contingencia` e `backends` (dublês do gateway, só teste).

    Contingência (dono, 14/11/2026: "nunca ficar sem produzir"): sem o Claude, a cascata da casa responde no lugar
    (`llm/contingencia.cascata`, pela camada 4 do gateway), `ULTIMO_MODELO` leva o modelo REAL,
    `ULTIMA_EM_CONTINGENCIA` fica True e o resultado entra na fila de conferência do Opus. A camada 4 tem política de
    dados desconhecida: só recebe classe `publico` — para `interno` a contingência é RECUSADA e o motivo volta.
    `contingencia=False` no chamador desliga (fica PENDENTE)."""
    global ULTIMO_MODELO, ULTIMA_EM_CONTINGENCIA
    ULTIMA_EM_CONTINGENCIA = False
    usar_contingencia = kw.pop("contingencia", True)
    backends = kw.pop("backends", None)
    sistema = kw.get("sistema", "") or ""
    try:
        from compliance_agent.adaptadores.llm import gateway as G
    except ImportError as exc:
        return None, f"gateway LLM ausente nesta base ({exc})"
    msgs = ([{"role": "system", "content": sistema}] if sistema else []) + [{"role": "user", "content": prompt}]
    comum = {"prompt_version": PROMPT_VERSION, "schema": schema, "timeout": kw.get("timeout", 180.0)}
    try:
        classe = G.classe_da_tarefa(tarefa)
        r = G.chamar(tarefa, msgs, classe_dado=classe, so_camadas=(2, 3), modelo_por_camada={2: kw.get("modelo"), 3: None},
                     espera=kw.get("espera"), backends=backends, **comum)
    except G.GatewayErro as exc:   # recusa/sem provedor: nunca derruba a rotina; o motivo explícito volta
        motivo = f"motor Claude sem resposta pelo gateway: {exc}"
        if not usar_contingencia:
            return None, motivo
        visto: dict = {}

        def _contingencia(*, tarefa, sistema, prompt, schema, **_):
            from compliance_agent.llm import contingencia
            alt = contingencia.cascata(tarefa, prompt, schema=schema, sistema=sistema, motivo=motivo[:300])
            if alt is None:
                return None
            visto["modelo"] = alt[1]
            txt = alt[0] if isinstance(alt[0], str) else json.dumps(alt[0], ensure_ascii=False)
            return G.Retorno(texto=txt, modelo=alt[1], dados=alt[0] if schema is not None else None)
        try:
            alt = G.chamar(tarefa, msgs, classe_dado=classe, so_camadas=(4,),
                           backends={**(backends or {}), "cascata_dc": _contingencia}, **comum)
        except G.ClasseDadoRecusada as e2:
            return None, f"{motivo} | contingência RECUSADA pela política: {e2}"
        except G.GatewayErro as e2:
            return None, f"{motivo} | contingência falhou: {e2}"
        if alt.estado != G.RESPONDIDO:
            return None, f"{motivo} | contingência: {alt.estado}"
        ULTIMO_MODELO, ULTIMA_EM_CONTINGENCIA = visto.get("modelo") or alt.modelo, True
        return (alt.dados if schema is not None else alt.texto), None
    if r.estado == G.ABSTEVE:
        return None, f"motor Claude absteve-se: {getattr(r.saida, 'motivo', '') or 'sem motivo'}"
    if r.estado != G.RESPONDIDO:
        return None, f"motor Claude: {r.estado}"
    ULTIMO_MODELO = _sufixo_api(r)
    if r.provedor == "api_anthropic":                     # Claude barato pela API: também vai ao Opus
        try:
            from compliance_agent.llm import conferencia_opus
            ULTIMA_EM_CONTINGENCIA = conferencia_opus.enfileirar(
                tarefa, None, prompt, sistema=sistema, motor=f"claude:{ULTIMO_MODELO}",
                resposta=r.texto, motivo="Claude barato pela API (assinatura indisponível)")
        except (ImportError, sqlite3.Error, OSError, ValueError) as exc:
            logging.getLogger(__name__).warning("rotina_base: sem fila de conferência (%s)", type(exc).__name__)
    return (r.dados if schema is not None else r.texto), None


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
    except _FALHAS_DA_ROTINA:          # o resto sobe com traceback para o log do cron
        log.exception("falhou após %.1f s", time.time() - t0)
        return 1
    log.info("fim em %.1f s (rc=%s)", time.time() - t0, rc)
    return rc
