# -*- coding: utf-8 -*-
"""Estágio `legado:<rotina>` — roda o comando que rodava antes da parada, com contrato de estágio (§3.2, O2.1).

É a ponte da religação: cada rotina do config/fluxo.yaml (cron, timer ou derivado da propagação) passa pelo motor
com recursos, teto de tempo, trava e EFEITO CONFERIDO, sem reescrever o script. O estágio de verdade (E1–E18)
substitui a rotina quando for portado (O3–O8); até lá ela fica marcada com o estágio de destino.

handler(payload, ctx):
  · `payload.rotina` (ou o sufixo do tipo `legado:<rotina>`) escolhe a rotina; `payload.args` soma argumentos do
    horário (ex.: a data do DOERJ);
  · rotina inativa ⇒ ErroPermanente (quarentena, com o `bloqueio` do yaml); nó fora de `nos` ⇒ falha transitória;
  · `condicao.dia_semana_iso` falsa hoje ⇒ "pulado" declarado (o `[ "$(date +%u)" = 7 ] &&` do cron antigo);
  · trava por rotina (flock não bloqueante, o MESMO arquivo que o cron/despachante usavam) ocupada ⇒ transitória;
  · cada passo roda em grupo de processos próprio, saída anexada a data/logs/fluxo/<rotina>.log, teto `timeout_s`;
  · qualquer rc ≠ 0 ou teto estourado ⇒ falha transitória (o motor faz backoff e, esgotado, quarentena).
efeito(payload, ctx, resultado) — roda em OUTRO processo e relê o mundo: rc==0 de todos os passos E o trecho do log
desta execução sem `log_sem` (padrão: traceback) e com `log_contem`, E `arquivo` regravado depois do início.
Os placeholders do argv são só `{py}` (o python deste processo), `{raiz}`, `{hoje}` e `{ontem}` (Brasília).
"""
from __future__ import annotations

import contextlib
import fcntl
import importlib.util
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.fluxo import grafo as G
from compliance_agent.fluxo.fila import Resultado

RAIZ = G.RAIZ
PASTA_LOG = Path("data") / "logs" / "fluxo"
FUSO = ZoneInfo("America/Sao_Paulo")
ENV_GRAFO = "JFN_FLUXO_GRAFO"                   # teste aponta para um yaml próprio
_RX_ENV = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


class FalhaTransitoria(RuntimeError):
    """Tentar de novo pode dar certo (trava ocupada, rc ≠ 0, teto de tempo)."""


def _grafo() -> G.Grafo:
    return G.carregar_cache(os.environ.get(ENV_GRAFO) or None)


def _rotina_id(payload: dict, ctx: Contexto) -> str:
    rid = payload.get("rotina") or (ctx.tipo.split(":", 1)[1] if ctx.tipo.startswith(G.PREFIXO_LEGADO) else "")
    if not rid:
        raise ErroPermanente(f"job {ctx.chave} sem rotina")
    return rid


def _agora() -> datetime:
    return datetime.now(FUSO)


def expandir(arg: str, agora: datetime | None = None) -> str:
    agora = agora or _agora()
    return (arg.replace("{py}", sys.executable).replace("{raiz}", str(RAIZ))
            .replace("{hoje}", agora.strftime("%Y-%m-%d"))
            .replace("{ontem}", (agora - timedelta(days=1)).strftime("%Y-%m-%d")))


def _alvo_existe(argv: list[str]) -> bool:
    """O script/módulo que o argv chama existe? (não existir é permanente: tentar de novo não cria o arquivo)."""
    if "-m" in argv[1:3] and argv.index("-m") + 1 < len(argv):
        mod = argv[argv.index("-m") + 1]
        base = RAIZ.joinpath(*mod.split("."))
        if base.with_suffix(".py").is_file() or (base / "__init__.py").is_file():
            return True
        try:                                             # módulo instalado no venv (fora do repo)
            return importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError):
            return False
    for a in argv[:3]:
        if a.endswith((".py", ".sh")):
            return (RAIZ / a).exists() or Path(a).exists()
    return True


def _ler_env_arquivo(caminho: Path) -> dict[str, str]:
    """KEY=VAL do .env (o `set -a; . ./.env` dos crons). Valores nunca vão a log."""
    out: dict[str, str] = {}
    with contextlib.suppress(OSError):
        for ln in caminho.read_text(encoding="utf-8").splitlines():
            if ln.lstrip().startswith("#"):
                continue
            m = _RX_ENV.match(ln)
            if m:
                v = m.group(2)
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1]
                out[m.group(1)] = v
    return out


def montar_env(r: G.Rotina) -> dict[str, str]:
    env = dict(os.environ)
    if r.carregar_env:
        env.update(_ler_env_arquivo(RAIZ / ".env"))
    env.update({"PYTHONPATH": str(RAIZ), "HOME": os.path.expanduser("~")})
    if r.path_extra:
        env["PATH"] = os.pathsep.join([os.path.expanduser(p) for p in r.path_extra] + [env.get("PATH", "")])
    env.update(r.env)
    return env


def caminho_trava(rid: str, r: G.Rotina) -> Path:
    return RAIZ / (r.trava or f"data/locks/{rid}.lock")


def _rodar_passo(argv: list[str], env: dict, log, teto_s: float) -> int:
    p = subprocess.Popen(argv, cwd=RAIZ, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        return p.wait(timeout=max(1.0, teto_s))
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            p.wait(timeout=20)
        if p.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(p.pid, signal.SIGKILL)
            p.wait()
        return 124


def handler(payload: dict, ctx: Contexto) -> Resultado:
    rid = _rotina_id(payload, ctx)
    g = _grafo()
    r = g.rotinas.get(rid)
    if r is None:
        raise ErroPermanente(f"rotina '{rid}' não está no config/fluxo.yaml")
    if not r.ativa:
        raise ErroPermanente(f"rotina '{rid}' inativa: {r.bloqueio}")
    nos = r.nos or g.estagios[r.estagio].nos
    if nos and ctx.no not in nos:
        raise FalhaTransitoria(f"rotina '{rid}' roda em {nos}, não em {ctx.no}")
    agora = _agora()
    if r.condicao and agora.isoweekday() != r.condicao.dia_semana_iso:
        return Resultado(efeito={"rotina": rid, "pulado": "condicao", "dia_semana_iso": agora.isoweekday()})
    argvs = [[expandir(a, agora) for a in argv] for argv in r.argvs()]
    extra = [expandir(a, agora) for a in (payload.get("args") or [])]
    argvs[-1] = argvs[-1] + extra                        # args do horário vão no último passo (o único, quase sempre)
    for argv in argvs:
        if not _alvo_existe(argv):
            raise ErroPermanente(f"rotina '{rid}': alvo do comando não existe: {argv[:4]}")
    teto = float(r.timeout_s or g.estagios[r.estagio].timeout_s)
    trava_p = caminho_trava(rid, r)
    trava_p.parent.mkdir(parents=True, exist_ok=True)
    log_rel = PASTA_LOG / f"{rid}.log"
    (RAIZ / log_rel).parent.mkdir(parents=True, exist_ok=True)
    with trava_p.open("a") as trava:
        try:
            fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FalhaTransitoria(f"trava {trava_p.name} ocupada (a rotina já roda fora deste job)") from None
        env = montar_env(r)
        inicio = time.time()
        rcs: list[int] = []
        with (RAIZ / log_rel).open("ab") as log:
            log.write(f"\n== {agora:%Y-%m-%d %H:%M:%S} job {ctx.chave} ficha {ctx.ficha} no {ctx.no}\n".encode())
            log.flush()
            de = log.tell()
            for argv in argvs:
                restante = teto - (time.time() - inicio)
                log.write(f"-- {' '.join(argv)}\n".encode())
                log.flush()
                rc = _rodar_passo(argv, env, log, restante) if restante > 0 else 124
                rcs.append(rc)
                if rc != 0 and (r.parar_no_erro or rc == 124):
                    break
            log.flush()
            ate = log.tell()
        fim = time.time()
    ruins = [rc for rc in rcs if rc != 0]
    if ruins:
        motivo = f"estourou o teto de {teto:.0f} s" if 124 in ruins else f"rc={ruins}"
        raise FalhaTransitoria(f"rotina '{rid}': {motivo} (ver {log_rel})")
    return Resultado(efeito={"rotina": rid, "rc": 0, "rcs": rcs, "inicio": inicio, "fim": fim, "log": str(log_rel),
                             "log_de": de, "log_ate": ate},
                     eventos=[{"fonte": rid, "tipo": "concluido"}])


def efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    """Conferência independente (outro processo): relê log e arquivo de efeito; não aceita a palavra do handler."""
    ef = resultado.efeito or {}
    rid = _rotina_id(payload, ctx)
    r = _grafo().rotinas.get(rid)
    if r is None or ef.get("rotina") != rid:
        return False
    if ef.get("pulado") == "condicao":
        return bool(r.condicao) and _agora().isoweekday() != r.condicao.dia_semana_iso
    if ef.get("rc") != 0 or any(rc != 0 for rc in ef.get("rcs") or [1]):
        return False
    log = RAIZ / str(ef.get("log") or "")
    de, ate = int(ef.get("log_de", -1)), int(ef.get("log_ate", -1))
    if not log.is_file() or de < 0 or ate < de or log.stat().st_size < ate:
        return False
    with log.open("rb") as fh:
        fh.seek(de)
        trecho = fh.read(ate - de).decode("utf-8", "replace")
    if r.efeito.log_sem and re.search(r.efeito.log_sem, trecho):
        return False
    if r.efeito.log_contem and not re.search(r.efeito.log_contem, trecho):
        return False
    if r.efeito.arquivo:
        try:
            mtime = (RAIZ / r.efeito.arquivo).stat().st_mtime
        except OSError:
            return False
        if mtime < float(ef.get("inicio", 0)) - 2 or mtime > time.time() + 60:
            return False
    return True


ESTAGIO = Estagio(handler=handler, efeito=efeito, recursos=["cpu_leve"], prioridade=100)
