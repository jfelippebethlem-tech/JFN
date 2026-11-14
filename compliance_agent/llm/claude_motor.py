# -*- coding: utf-8 -*-
"""claude_motor — o Claude (Claude Code CLI, pela ASSINATURA do dono) como motor de raciocínio do JFN.

Pedido do dono (13/11/2026): "quero tudo rodando, periciando, cruzando informação, com o Claude como motor
de tudo" — depois ajustado para CO-MOTOR: o Claude roda AO LADO da cascata atual (ver `llm/comotor.py`),
os vereditos se cruzam e a cascata aprende com a divergência. Este módulo é só o motor: UMA função,
`pensar()`, que chama o CLI com as travas de cota.

COMO CHAMA (copiado do que já funciona na Atena, `~/atena/atena/visao.py`):
  `nice claude -p --model M --output-format json --strict-mcp-config --setting-sources local
   --no-session-persistence --tools "" --system-prompt <regras>`, prompt pela ENTRADA PADRÃO (argumento
  fica visível na lista de processos), cwd numa pasta vazia FORA do repositório (senão o CLI sobe a
  árvore e carrega o CLAUDE.md do JFN), e o ambiente SEM `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`.
  NUNCA `--bare`: ele troca a assinatura por chave de API (doc do Claude Code, lida em 09/11/2026 —
  memória `claude-p-bare-deixa-de-usar-assinatura`). Chave paga cobra; a regra §4.1 manda não supor.

TRAVAS (nenhuma depende de nome de processo):
  · um `claude` por vez na VM de 2 vCPU — `fcntl.flock` em `data/claude_motor.lock` (aparece em
    /proc/locks, e o AO VIVO mostra "rodando" enquanto a trava está presa);
  · ORÇAMENTO diário total e por tarefa (chamadas e segundos) em `data/claude_motor_uso.json`,
    tetos por env (`JFN_CLAUDE_MAX_CHAMADAS_DIA`, `JFN_CLAUDE_MAX_SEGUNDOS_DIA`,
    `JFN_CLAUDE_MAX_<TAREFA>`); a chamada é RESERVADA antes de rodar (processo que morre no meio conta);
  · kill-switch: `JFN_CLAUDE_MOTOR=0` ou o arquivo `data/.pause_claude_motor`;
  · canário diário (`--canario`): falhou ⇒ motor desligado até o próximo canário OK, aviso no Telegram;
  · erro de limite de uso ⇒ motor em pausa por `JFN_CLAUDE_PAUSA_LIMITE_S` (padrão 1 h).

CONTRATO: `pensar()` nunca levanta. Sucesso ⇒ `Pensamento`; qualquer falha ⇒ `None`, com o motivo em
`ultimo_motivo` — o chamador cai na cascata atual. O registro de uso guarda tarefa, modelo, segundos e
desfecho; NUNCA o texto do prompt nem da resposta.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import re
import signal
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]

# ids conferidos no binário instalado (Claude Code 2.1.323, 13/11/2026) sem gastar chamada
MODELO_VOLUME = "claude-sonnet-5-5"
MODELO_JUIZO = "claude-opus-5-5"

# a sessão nunca usa chave de API: só a assinatura
VARIAVEIS_PROIBIDAS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

TETO_CHAMADAS_DIA = 120
TETO_SEGUNDOS_DIA = 7200
TETO_TAREFA_PADRAO = 10
# Por tarefa (chamadas/dia). Soma > total de propósito: o total é quem trava; a tarefa só impede que uma
# fila sozinha coma o dia. Ver o relatório de 13/11/2026 para a conta.
TETOS_TAREFA = {
    "canario": 3,
    "pericia_execucao": 30,
    "pericia_fornecedor": 15,
    "parecer_juridico": 10,
    "triagem_alertas": 40,
    "camada_subjetiva": 20,
    "investigacao_risco": 10,
    "verificacao_opus": 30,      # todo 🔴/🟡 da triagem relido pelo Opus (diretriz "sem margem pra erro")
    "juiz_qualidade": 12,        # juiz subjetivo das regras de qualidade (só assinatura; amostra por valor/risco)
}

SISTEMA_PADRAO = (
    "Você é auditor de controle externo (TCE-RJ) do sistema JFN. Responda em português do Brasil. "
    "Indício não é acusação; ausência de documento é INDISPONÍVEL, não irregularidade; presunção de "
    "legitimidade; nunca invente fato, valor, documento ou citação que não esteja na entrada."
)

ultimo_motivo: str = ""


@dataclass
class Pensamento:
    texto: str
    modelo: str
    segundos: float
    tarefa: str
    dados: object = None
    extras: dict = field(default_factory=dict)


# ── caminhos (lidos a cada uso: o teste desvia por env) ─────────────────────────────────────────────
def _dados() -> Path:
    return Path(os.environ.get("JFN_CLAUDE_DADOS") or (_REPO / "data"))


def _uso_arq() -> Path:
    return _dados() / "claude_motor_uso.json"


def _estado_arq() -> Path:
    return _dados() / "claude_motor_estado.json"


def _trava_arq() -> Path:
    return _dados() / "claude_motor.lock"


def _pausa_arq() -> Path:
    return _dados() / ".pause_claude_motor"


def _log_arq() -> Path:
    return _dados() / "claude_motor.log"


def _pasta_trabalho() -> Path:
    return Path(os.environ.get("JFN_CLAUDE_CWD") or (Path.home() / ".local" / "state" / "jfn-claude-motor"))


def _bin() -> list[str]:
    return [os.environ.get("JFN_CLAUDE_BIN") or "claude"]


def _int_env(nome: str, padrao: int) -> int:
    try:
        return int(os.environ.get(nome, "") or padrao)
    except ValueError:
        return padrao


def teto_total() -> int:
    return _int_env("JFN_CLAUDE_MAX_CHAMADAS_DIA", TETO_CHAMADAS_DIA)


def teto_segundos() -> int:
    return _int_env("JFN_CLAUDE_MAX_SEGUNDOS_DIA", TETO_SEGUNDOS_DIA)


def teto_tarefa(tarefa: str) -> int:
    return _int_env(f"JFN_CLAUDE_MAX_{tarefa.upper()}", TETOS_TAREFA.get(tarefa, TETO_TAREFA_PADRAO))


# ── arquivos JSON com escrita atômica e trava curta própria ─────────────────────────────────────────
@contextmanager
def _flock(caminho: Path, espera: float):
    """Trava de ARQUIVO (não de nome de processo). Rende True se pegou dentro de `espera` s."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(caminho, os.O_RDWR | os.O_CREAT, 0o600)
    pegou = False
    try:
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


def _ler_json(caminho: Path) -> dict:
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_json(caminho: Path, dados: dict) -> None:
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = caminho.with_suffix(caminho.suffix + ".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, caminho)
    except OSError as e:  # registro não pode derrubar o juízo
        logger.warning("claude_motor: não gravei %s (%s)", caminho.name, e)


def _hoje() -> str:
    return date.today().isoformat()


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _uso_vazio() -> dict:
    return {"data": _hoje(), "total": {"chamadas": 0, "segundos": 0.0, "ok": 0, "erros": 0, "bloqueadas": 0},
            "tarefas": {}, "ultimo_erro": None, "ultima_ok": None}


def ler_uso() -> dict:
    d = _ler_json(_uso_arq())
    if d.get("data") != _hoje():
        anterior = d.get("ultimo_erro")
        d = _uso_vazio()
        d["ultimo_erro"] = anterior      # o último erro sobrevive à virada do dia (o painel precisa dele)
    return d


def _mutar_uso(fn) -> dict:
    with _flock(_uso_arq().with_suffix(".json.lock"), 10.0):
        d = ler_uso()
        fn(d)
        _gravar_json(_uso_arq(), d)
        return d


def _tarefa_de(d: dict, tarefa: str) -> dict:
    return d["tarefas"].setdefault(tarefa, {"chamadas": 0, "segundos": 0.0, "ok": 0, "erros": 0, "bloqueadas": 0})


def ler_estado() -> dict:
    return _ler_json(_estado_arq())


def _mutar_estado(**campos) -> None:
    with _flock(_estado_arq().with_suffix(".json.lock"), 10.0):
        d = ler_estado()
        d.update(campos)
        _gravar_json(_estado_arq(), d)


def _log(linha: str) -> None:
    try:
        _log_arq().parent.mkdir(parents=True, exist_ok=True)
        with open(_log_arq(), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {linha}\n")
    except OSError:
        logger.debug("claude_motor: log indisponível")


# ── portões ───────────────────────────────────────────────────────────────────────────────────────
def motivo_desligado(*, canario: bool = False) -> str | None:
    """Por que o motor NÃO pode rodar agora (None = pode)."""
    if (os.environ.get("JFN_CLAUDE_MOTOR", "1").strip().lower() in ("0", "false", "off", "no")):
        return "desligado (JFN_CLAUDE_MOTOR=0)"
    if _pausa_arq().exists():
        return f"pausado ({_pausa_arq().name})"
    est = ler_estado()
    ate = est.get("bloqueado_ate")
    if isinstance(ate, (int, float)) and ate > time.time():
        return f"limite de uso da assinatura — pausa até {datetime.fromtimestamp(ate):%H:%M}"
    if not canario and est.get("canario_ok") is False:
        return f"desligado pelo canário de {est.get('canario_em', '?')}: {est.get('canario_motivo', '?')}"
    return None


def _motivo_teto(d: dict, tarefa: str) -> str | None:
    t = d["total"]
    if t["chamadas"] >= teto_total():
        return f"teto diário total ({teto_total()} chamadas)"
    if t["segundos"] >= teto_segundos():
        return f"teto diário de tempo ({teto_segundos()} s)"
    if _tarefa_de(d, tarefa)["chamadas"] >= teto_tarefa(tarefa):
        return f"teto diário da tarefa {tarefa} ({teto_tarefa(tarefa)} chamadas)"
    return None


# ── execução do CLI ───────────────────────────────────────────────────────────────────────────────
def montar_comando(modelo: str, sistema: str, ferramentas=()) -> list[str]:
    # nunca --bare: ele troca a assinatura por chave de API
    return ["nice", "-n", "10", *_bin(), "-p", "--model", modelo, "--output-format", "json",
            "--strict-mcp-config", "--setting-sources", "local", "--no-session-persistence",
            "--tools", ",".join(ferramentas), "--system-prompt", sistema]


def ambiente_limpo() -> dict:
    return {k: v for k, v in os.environ.items() if k not in VARIAVEIS_PROIBIDAS}


def _executar_cli(cmd: list[str], entrada: str, env: dict, cwd: Path, timeout: float) -> tuple[int, str, str]:
    """Roda o CLI em grupo de processo próprio; no prazo estourado mata o GRUPO (por PID, nunca pkill)."""
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env, cwd=cwd, start_new_session=True)
    try:
        out, err = proc.communicate(entrada, timeout=timeout)
        return proc.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            logger.debug("claude_motor: grupo %s já tinha saído no prazo estourado", proc.pid)
        proc.communicate()
        raise


_RE_LIMITE = re.compile(r"usage limit|rate limit|limit reached|limite de uso|out of extra usage|quota", re.I)


def classificar_erro(texto: str) -> str:
    """'limite' (cota da assinatura) | 'auth' (login) | 'outro'."""
    t = texto or ""
    if _RE_LIMITE.search(t) or ("limit" in t.lower() and "usage" in t.lower()):
        return "limite"
    if re.search(r"api key|log ?in|authenticat|oauth|unauthorized|401", t, re.I):
        return "auth"
    return "outro"


def _instrucao_schema(schema) -> str:
    return ("\n\nResponda SOMENTE com um objeto JSON válido, sem texto fora dele, neste formato:\n"
            + (schema if isinstance(schema, str) else json.dumps(schema, ensure_ascii=False)))


def _chaves_exigidas(schema) -> list[str]:
    if isinstance(schema, dict):
        if isinstance(schema.get("required"), list):
            return [str(k) for k in schema["required"]]
        if "properties" not in schema and "type" not in schema:
            return list(schema.keys())      # schema dado como exemplo do objeto
    return []


def _falhar(tarefa: str, motivo: str, *, contar_erro: bool, segundos: float = 0.0, tipo: str = "") -> None:
    global ultimo_motivo
    ultimo_motivo = motivo

    def f(d):
        tt = _tarefa_de(d, tarefa)
        if contar_erro:
            d["total"]["erros"] += 1
            tt["erros"] += 1
            d["ultimo_erro"] = {"em": _agora(), "tarefa": tarefa, "motivo": motivo[:200], "tipo": tipo or "erro"}
        else:
            d["total"]["bloqueadas"] += 1
            tt["bloqueadas"] += 1
        d["total"]["segundos"] = round(d["total"]["segundos"] + segundos, 1)
        tt["segundos"] = round(tt["segundos"] + segundos, 1)
    _mutar_uso(f)
    if contar_erro:
        _log(f"tarefa={tarefa} erro {tipo or 'erro'}: {motivo[:160]}")


_SEM_API = ("desligado (JFN_CLAUDE_MOTOR", "pausado", "sob pytest")   # kill-switch vale para os dois backends


def pensar(tarefa: str, prompt: str, *, schema=None, modelo: str = MODELO_VOLUME, timeout: float = 180.0,
           ferramentas=(), sistema: str = "", espera: float | None = None, executar=None,
           backend: str = "auto", api_cliente=None, _canario: bool = False) -> Pensamento | None:
    """Claude pela ASSINATURA primeiro; sem ela (teto, limite de uso, canário fora, trava ocupada, erro), a API
    paga com teto em dólares (`claude_api`, Haiku por padrão, nunca Opus). `backend`: auto | cli | api.
    `None` ⇒ cair na cascata (motivo em `ultimo_motivo`). O modelo da API sai marcado `<id>@api`."""
    global ultimo_motivo
    r = None
    if backend in ("auto", "cli"):
        r = _pensar_cli(tarefa, prompt, schema=schema, modelo=modelo, timeout=timeout, ferramentas=ferramentas,
                        sistema=sistema, espera=espera, executar=executar, _canario=_canario)
        if r is not None or backend == "cli" or _canario or ultimo_motivo.startswith(_SEM_API):
            return r
    if ferramentas:                     # a API aqui é só texto: tarefa com ferramenta não migra
        return None
    motivo_cli = ultimo_motivo
    from compliance_agent.llm import claude_api
    entrada = prompt + (_instrucao_schema(schema) if schema is not None else "")
    ini = time.monotonic()
    res = claude_api.pensar_api(tarefa, entrada, sistema=sistema or SISTEMA_PADRAO, timeout=timeout,
                                cliente=api_cliente)
    if res is None:
        ultimo_motivo = " | ".join(m for m in (motivo_cli, claude_api.ultimo_motivo) if m)
        return None
    texto, quem, usd = res
    dados = None
    if schema is not None:
        from compliance_agent.llm.json_resposta import parse_json_llm
        dados = parse_json_llm(texto)
        if dados is None or [k for k in _chaves_exigidas(schema) if not (isinstance(dados, dict) and k in dados)]:
            ultimo_motivo = "API: resposta sem o JSON pedido"
            return None
    _log(f"tarefa={tarefa} ok modelo={quem}@api {time.monotonic() - ini:.1f}s US$ {usd:.4f}")
    _mutar_estado(ultima_ok_iso=_agora())
    return Pensamento(texto=texto, modelo=f"{quem}@api", segundos=round(time.monotonic() - ini, 1), tarefa=tarefa,
                      dados=dados, extras={"backend": "api", "usd": round(usd, 6)})


def _pensar_cli(tarefa: str, prompt: str, *, schema=None, modelo: str = MODELO_VOLUME, timeout: float = 180.0,
                ferramentas=(), sistema: str = "", espera: float | None = None, executar=None,
                _canario: bool = False) -> Pensamento | None:
    """Uma chamada ao Claude pela assinatura. `None` ⇒ cair na cascata (motivo em `ultimo_motivo`)."""
    global ultimo_motivo
    ultimo_motivo = ""
    if executar is None and os.environ.get("PYTEST_CURRENT_TEST"):
        # guarda dura: teste nenhum chama o claude de verdade (cota da assinatura) — só com executor dublê
        ultimo_motivo = "sob pytest sem executor dublê"
        return None
    executar = executar or _executar_cli
    espera = float(os.environ.get("JFN_CLAUDE_ESPERA_S", "90")) if espera is None else espera
    try:
        m = motivo_desligado(canario=_canario)
        if m:
            _falhar(tarefa, m, contar_erro=False)
            return None
        if _motivo_teto(ler_uso(), tarefa):
            _falhar(tarefa, _motivo_teto(ler_uso(), tarefa), contar_erro=False)
            return None
        with _flock(_trava_arq(), espera) as pegou:
            if not pegou:
                _falhar(tarefa, f"ocupado: outro claude do JFN rodando há mais de {espera:.0f} s", contar_erro=False)
                return None
            reservado = {}

            def reservar(d):
                motivo = _motivo_teto(d, tarefa)
                reservado["motivo"] = motivo
                if not motivo:
                    d["total"]["chamadas"] += 1
                    _tarefa_de(d, tarefa)["chamadas"] += 1
            _mutar_uso(reservar)
            if reservado["motivo"]:
                _falhar(tarefa, reservado["motivo"], contar_erro=False)
                return None
            pasta = _pasta_trabalho()
            pasta.mkdir(mode=0o700, parents=True, exist_ok=True)
            entrada = prompt + (_instrucao_schema(schema) if schema is not None else "")
            ini = time.monotonic()
            try:
                rc, out, err = executar(montar_comando(modelo, sistema or SISTEMA_PADRAO, ferramentas),
                                        entrada, ambiente_limpo(), pasta, timeout)
            except subprocess.TimeoutExpired:
                _falhar(tarefa, f"passou do prazo de {timeout:.0f} s", contar_erro=True,
                        segundos=time.monotonic() - ini, tipo="prazo")
                return None
            except OSError as e:
                _falhar(tarefa, f"CLI não executou ({type(e).__name__})", contar_erro=True, tipo="cli")
                return None
            seg = time.monotonic() - ini
        return _interpretar(tarefa, modelo, rc, out, err, seg, schema, prompt)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
        # contrato: pensar() nunca derruba o chamador (arquivo de uso, JSON, executor torto)
        ultimo_motivo = f"falha interna do motor ({type(e).__name__})"
        logger.warning("claude_motor: %s", ultimo_motivo)
        return None


def _sem_eco(motivo: str, prompt: str) -> str:
    p = (prompt or "").strip()
    return motivo.replace(p, "…") if len(p) >= 8 else motivo


def _interpretar(tarefa, modelo, rc, out, err, seg, schema, prompt) -> Pensamento | None:
    try:
        corpo = json.loads(out)
    except (TypeError, ValueError):
        corpo = None
    if not isinstance(corpo, dict):
        motivo = _sem_eco(f"saída sem JSON (rc={rc}) {(err or out or '')[:160]}", prompt)
        tipo = classificar_erro(err + " " + (out or ""))
        _tratar_tipo(tipo, motivo)
        _falhar(tarefa, motivo, contar_erro=True, segundos=seg, tipo=tipo)
        return None
    resultado = corpo.get("result")
    if corpo.get("is_error") or rc != 0 or not isinstance(resultado, str) or not resultado.strip():
        bruto = str(resultado or corpo.get("subtype") or "resultado vazio")
        tipo = classificar_erro(bruto + " " + (err or ""))
        motivo = _sem_eco(f"o claude respondeu com erro ({tipo}): {bruto[:160]}", prompt)
        _tratar_tipo(tipo, motivo)
        _falhar(tarefa, motivo, contar_erro=True, segundos=seg, tipo=tipo)
        return None
    dados = None
    if schema is not None:
        from compliance_agent.llm.json_resposta import parse_json_llm
        dados = parse_json_llm(resultado)
        faltam = [k for k in _chaves_exigidas(schema) if not (isinstance(dados, dict) and k in dados)]
        if dados is None or faltam:
            motivo = "resposta sem o JSON pedido" + (f" (faltam {', '.join(faltam[:5])})" if dados is not None else "")
            _falhar(tarefa, motivo, contar_erro=True, segundos=seg, tipo="schema")
            return None

    def f(d):
        tt = _tarefa_de(d, tarefa)
        d["total"]["ok"] += 1
        tt["ok"] += 1
        d["total"]["segundos"] = round(d["total"]["segundos"] + seg, 1)
        tt["segundos"] = round(tt["segundos"] + seg, 1)
        d["ultima_ok"] = {"em": _agora(), "tarefa": tarefa, "modelo": modelo, "segundos": round(seg, 1)}
    _mutar_uso(f)
    _mutar_estado(ultima_ok_iso=_agora())      # persiste à virada do dia: é o "efeito" do motor no AO VIVO
    _log(f"tarefa={tarefa} ok modelo={modelo} {seg:.1f}s")
    return Pensamento(texto=resultado, modelo=modelo, segundos=round(seg, 1), tarefa=tarefa, dados=dados,
                      extras={k: corpo.get(k) for k in ("num_turns", "duration_ms") if k in corpo})


def _tratar_tipo(tipo: str, motivo: str) -> None:
    if tipo == "limite":
        pausa = _int_env("JFN_CLAUDE_PAUSA_LIMITE_S", 3600)
        _mutar_estado(bloqueado_ate=time.time() + pausa, bloqueio_motivo=motivo[:200])
        _log(f"limite de uso: motor em pausa por {pausa} s")


# ── canário diário ────────────────────────────────────────────────────────────────────────────────
def _avisar_telegram(texto: str) -> bool:
    try:
        import asyncio
        from compliance_agent.notifications.telegram import enviar_mensagem
        r = asyncio.run(enviar_mensagem(texto, parse_mode="HTML"))
        return bool(isinstance(r, dict) and r.get("ok"))
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        # aviso é melhor-esforço (enviar_mensagem já devolve {"ok": False} em erro de rede); o estado já foi gravado
        logger.warning("canário: aviso ao Telegram falhou (%s)", type(e).__name__)
        return False


def canario(*, executar=None, avisar=None) -> dict:
    """Prova mínima de que o `claude -p` responde PELA ASSINATURA (ambiente sem chave, sem --bare).

    Falha ⇒ `canario_ok=False` (o motor fica desligado) + aviso ao dono. Volta a funcionar ⇒ religa e avisa.
    """
    avisar = avisar or _avisar_telegram
    antes = ler_estado().get("canario_ok")
    chave_no_ambiente = [k for k in VARIAVEIS_PROIBIDAS if k in ambiente_limpo()]
    if chave_no_ambiente:            # impossível pelo código — mas é exatamente o que o canário existe para pegar
        r, motivo = None, "chave de API no ambiente do motor"
    else:
        r = pensar("canario", "Responda apenas com a palavra OK.", modelo=MODELO_VOLUME, timeout=90.0,
                   espera=300.0, executar=executar, _canario=True)
        motivo = "" if r else (ultimo_motivo or "sem resposta")
        if r and "OK" not in r.texto.upper():
            r, motivo = None, "resposta inesperada do canário"
    ok = r is not None
    _mutar_estado(canario_ok=ok, canario_em=_agora(), canario_motivo=motivo[:200],
                  canario_segundos=(r.segundos if r else None))
    _log(f"canário {'OK' if ok else 'FALHOU'}" + ("" if ok else f": {motivo[:160]}"))
    if not ok:
        avisar("🔴 <b>Motor Claude do JFN desligado</b> — o canário diário falhou: "
               f"{motivo[:180]}. As camadas de juízo seguem só com a cascata gratuita até o próximo canário OK.")
    elif antes is False:
        avisar("🟢 <b>Motor Claude do JFN religado</b> — canário OK pela assinatura.")
    return {"ok": ok, "motivo": motivo, "segundos": r.segundos if r else None}


# ── painel ────────────────────────────────────────────────────────────────────────────────────────
def painel() -> dict:
    """Resumo para o AO VIVO: chamadas hoje, por tarefa, tetos, último erro, canário. Sem conteúdo."""
    u, e = ler_uso(), ler_estado()
    return {
        "ligado": motivo_desligado() is None,
        "motivo_desligado": motivo_desligado(),
        "hoje": u["total"]["chamadas"], "teto": teto_total(),
        "segundos": u["total"]["segundos"], "teto_segundos": teto_segundos(),
        "ok": u["total"]["ok"], "erros": u["total"]["erros"], "bloqueadas": u["total"]["bloqueadas"],
        "por_tarefa": {t: {"chamadas": v["chamadas"], "teto": teto_tarefa(t), "ok": v["ok"], "erros": v["erros"]}
                       for t, v in sorted(u["tarefas"].items())},
        "ultimo_erro": u.get("ultimo_erro"), "ultima_ok": u.get("ultima_ok"),
        "canario": {"ok": e.get("canario_ok"), "em": e.get("canario_em"), "motivo": e.get("canario_motivo")},
        "modelos": {"volume": MODELO_VOLUME, "juizo": MODELO_JUIZO},
    }


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Motor Claude do JFN (assinatura, com teto de cota)")
    ap.add_argument("--canario", action="store_true", help="chamada mínima que prova a assinatura")
    ap.add_argument("--status", action="store_true", help="uso de hoje (JSON)")
    a = ap.parse_args(argv)
    if a.canario:
        r = canario()
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r["ok"] else 1
    print(json.dumps(painel(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
