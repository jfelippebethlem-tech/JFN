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
  · ORÇAMENTO diário total e por tarefa (chamadas e segundos, `llm/orcamento`) em `data/claude_motor_uso.json`,
    tetos por env (`JFN_CLAUDE_MAX_CHAMADAS_DIA`, `JFN_CLAUDE_MAX_SEGUNDOS_DIA`,
    `JFN_CLAUDE_MAX_<TAREFA>`); a chamada é RESERVADA antes de rodar (processo que morre no meio conta);
  · kill-switch: `JFN_CLAUDE_MOTOR=0` ou o arquivo `data/.pause_claude_motor`;
  · canário diário (`--canario`): falhou ⇒ motor desligado até o próximo canário OK, aviso no Telegram;
  · erro de limite de uso da conta ("You've hit your 5-hour limit · resets 2:30am") ⇒ CONTINGÊNCIA até a hora
    de volta lida da mensagem (`llm/contingencia`; sem hora legível, `JFN_CLAUDE_PAUSA_LIMITE_S`, padrão 1 h);
    a 90% do orçamento diário o resto fica reservado ao Opus. Em contingência os consumidores seguem com os
    outros modelos e o resultado vai para a fila `conferencia_opus`.

CONTRATO: `pensar()` nunca levanta. Sucesso ⇒ `Pensamento`; qualquer falha ⇒ `None`, com o motivo em
`ultimo_motivo` — o chamador cai na cascata atual. O registro de uso guarda tarefa, modelo, segundos e
desfecho; NUNCA o texto do prompt nem da resposta.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from compliance_agent.llm import arquivo_estado as arq
from compliance_agent.llm import claude_api, contingencia, orcamento
from compliance_agent.llm.orcamento import ler_uso, teto_segundos, teto_tarefa, teto_total
from compliance_agent.llm.claude_api import MODELO_JUIZO, MODELO_VOLUME
from compliance_agent.llm.json_resposta import chaves_faltando, instrucao_schema, parse_json_llm

logger = logging.getLogger(__name__)

# a sessão nunca usa chave de API: só a assinatura
# No `-p` a chave de API presente vence SEMPRE o login da assinatura, e as variáveis de nuvem desviam para Bedrock/
# Vertex/Foundry — as duas formas cobram (doc do Claude Code "Authentication", lida em 24/11/2026; decisões
# delegadas ~/vault/refatoracao/decisoes-delegadas-ia-20261124.md, D1). Nenhuma chega ao subprocesso.
VARIAVEIS_PROIBIDAS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "CLAUDE_CODE_USE_BEDROCK",
                       "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")

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
def _estado_arq() -> Path:
    return arq.dados() / "claude_motor_estado.json"


def _trava_arq() -> Path:
    return arq.dados() / "claude_motor.lock"


def vagas_claude() -> int:
    """Quantos `claude` do JFN ao mesmo tempo NESTA máquina (`JFN_CLAUDE_VAGAS`, que o supervisor do fluxo define pelo
    nó — fluxo/supervisor.VAGAS_CLAUDE). Ausente/ilegível = 1 (a trava de sempre)."""
    try:
        return max(1, int(os.environ.get("JFN_CLAUDE_VAGAS") or 1))
    except ValueError:
        return 1


def _pausa_arq() -> Path:
    return arq.dados() / ".pause_claude_motor"


def _log_arq() -> Path:
    return arq.dados() / "claude_motor.log"


def _pasta_trabalho() -> Path:
    return Path(os.environ.get("JFN_CLAUDE_CWD") or (Path.home() / ".local" / "state" / "jfn-claude-motor"))


def _bin() -> list[str]:
    """Caminho do `claude`. O cron e o serviço rodam com PATH mínimo: só o nome dava rc=127 em toda
    chamada (13/11/2026). Ordem: variável explícita → instalações do USUÁRIO (as que se atualizam) → PATH.
    14/11/2026: na VM-2 o PATH achava primeiro o /usr/bin/claude de sistema (2.1.296, parado) enquanto o do
    usuário em ~/.local/bin estava em 2.1.325 — o dono pediu "usar o claude code da vm2 atualizado"."""
    if os.environ.get("JFN_CLAUDE_BIN"):
        return [os.environ["JFN_CLAUDE_BIN"]]
    import shutil
    casa = Path(os.environ.get("HOME") or Path.home())
    achado = next((str(p) for p in (casa / ".npm-global" / "bin" / "claude", casa / ".local" / "bin" / "claude")
                   if p.is_file() and os.access(p, os.X_OK)), None) or shutil.which("claude")
    return [achado or "claude"]


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ler_estado() -> dict:
    return arq.ler_json(_estado_arq())


def _mutar_estado(**campos) -> None:
    arq.mutar_json(_estado_arq(), lambda d: d.update(campos), espera=10.0)


def _log(linha: str) -> None:
    try:
        _log_arq().parent.mkdir(parents=True, exist_ok=True)
        with open(_log_arq(), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {linha}\n")
    except OSError:
        logger.debug("claude_motor: log indisponível")


# ── portões ───────────────────────────────────────────────────────────────────────────────────────
def _motivo_kill_switch() -> str | None:
    """Kill-switch do dono: vale para a assinatura E para a API paga."""
    if (os.environ.get("JFN_CLAUDE_MOTOR", "1").strip().lower() in ("0", "false", "off", "no")):
        return "desligado (JFN_CLAUDE_MOTOR=0)"
    if _pausa_arq().exists():
        return f"pausado ({_pausa_arq().name})"
    return None


ENV_ESCOPO = "JFN_ASSINATURA_ESCOPO"
ESCOPO_ENSAIO = "ensaio_o85"
LIBERACAO_DONO = ".assinatura_liberada_dono.json"


def ritmo_liberado_pelo_dono() -> bool:
    """A trava de RITMO SEMANAL (só ela) cede à autorização do dono (`data/.assinatura_liberada_dono.json`, 25/11/2026:
    "pode fazer a passada ou o que precisar antes de sabado tambem") SOMENTE quando o processo declara o escopo do
    ensaio O8.5 (`JFN_ASSINATURA_ESCOPO=ensaio_o85`, exportado pelo filho de `tools/ensaio_o85.py`), o arquivo cobre
    esse escopo pela ASSINATURA e a semana medida está ABAIXO do `teto_semana_pct`. Sem medição, fora do escopo ou
    no teto: False (a trava de sempre). Kill switch, limite da conta, contingência forçada e tetos diários não cedem."""
    if os.environ.get(ENV_ESCOPO) != ESCOPO_ENSAIO:
        return False
    try:
        d = json.loads((arq.dados() / LIBERACAO_DONO).read_text(encoding="utf-8"))
        teto = float(d["teto_semana_pct"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    esc = str(d.get("escopo") or "")
    if "O8.5" not in esc or "ASSINATURA" not in esc:
        return False
    from compliance_agent.llm import ritmo_assinatura
    n = ritmo_assinatura.nivel()
    return bool(n.get("medido")) and n.get("semana_pct") is not None and float(n["semana_pct"]) < teto


def motivo_desligado(*, canario: bool = False, tarefa: str = "") -> str | None:
    """Por que o motor NÃO pode rodar agora (None = pode). O limite da conta mora SÓ na contingência."""
    m = _motivo_kill_switch()
    if not m:
        m = contingencia.motivo_bloqueio(tarefa)
        if m and contingencia.estado().get("origem") == "ritmo_semanal" and ritmo_liberado_pelo_dono():
            m = None                                   # só a trava de ritmo, só no escopo do ensaio (ver acima)
    if m:
        return m
    est = ler_estado()
    if not canario and est.get("canario_ok") is False:
        return f"desligado pelo canário de {est.get('canario_em', '?')}: {est.get('canario_motivo', '?')}"
    return None


# ── execução do CLI ───────────────────────────────────────────────────────────────────────────────
def montar_comando(modelo: str, sistema: str, ferramentas=()) -> list[str]:
    # nunca --bare: ele troca a assinatura por chave de API
    return ["nice", "-n", "10", *_bin(), "-p", "--model", modelo, "--output-format", "json",
            "--strict-mcp-config", "--setting-sources", "local", "--no-session-persistence",
            "--tools", ",".join(ferramentas), "--system-prompt", sistema]


def ambiente_limpo() -> dict:
    return {k: v for k, v in os.environ.items() if k not in VARIAVEIS_PROIBIDAS}


_PR_SET_PDEATHSIG = 1


def _morrer_com_o_chamador(pai: int):
    """preexec do CLI (Linux): SIGKILL quando o chamador morrer. Em sessão própria, o CLI escapava do SIGKILL que o
    governador/lease/parada/teto do `legado` dão no grupo do JOB e seguia órfão gastando a assinatura (O9.0, 26/11)."""
    def _pre():
        import ctypes
        ctypes.CDLL(None, use_errno=True).prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)
        if os.getppid() != pai:              # o chamador morreu antes do prctl: não nasce órfão
            os._exit(137)
    return _pre


def _executar_cli(cmd: list[str], entrada: str, env: dict, cwd: Path, timeout: float) -> tuple[int, str, str]:
    """Roda o CLI em grupo de processo próprio; no prazo estourado mata o GRUPO (por PID, nunca pkill). No Linux o CLI
    morre junto com o chamador (PR_SET_PDEATHSIG)."""
    pre = _morrer_com_o_chamador(os.getpid()) if os.uname().sysname == "Linux" else None
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env, cwd=cwd, start_new_session=True, preexec_fn=pre)
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


def classificar_erro(texto: str) -> str:
    """'limite' (cota da assinatura) | 'auth' (login) | 'outro'."""
    t = texto or ""
    if contingencia.eh_limite(t):     # inclui "You've hit your 5-hour limit" e 429/rate_limit (antes: "outro")
        return "limite"
    if re.search(r"api key|log ?in|authenticat|oauth|unauthorized|401", t, re.I):
        return "auth"
    return "outro"


def _falhar(tarefa: str, motivo: str, *, contar_erro: bool, segundos: float = 0.0, tipo: str = "") -> None:
    global ultimo_motivo
    ultimo_motivo = motivo

    def f(d):
        tt = orcamento.tarefa_de(d, tarefa)
        if contar_erro:
            d["total"]["erros"] += 1
            tt["erros"] += 1
            d["ultimo_erro"] = {"em": _agora(), "tarefa": tarefa, "motivo": motivo[:200], "tipo": tipo or "erro"}
        else:
            d["total"]["bloqueadas"] += 1
            tt["bloqueadas"] += 1
        d["total"]["segundos"] = round(d["total"]["segundos"] + segundos, 1)
        tt["segundos"] = round(tt["segundos"] + segundos, 1)
    orcamento.mutar_uso(f)
    if contar_erro:
        _log(f"tarefa={tarefa} erro {tipo or 'erro'}: {motivo[:160]}")


def pensar(tarefa: str, prompt: str, *, schema=None, modelo: str = MODELO_VOLUME, timeout: float = 180.0,
           ferramentas=(), sistema: str = "", espera: float | None = None, executar=None,
           backend: str = "auto", api_cliente=None, _canario: bool = False) -> Pensamento | None:
    """Claude pela ASSINATURA primeiro; sem ela (teto, limite de uso, canário fora, trava ocupada, erro), a API
    paga com teto em dólares (`claude_api`, Haiku por padrão, nunca Opus). `backend`: auto | cli | api.
    `None` ⇒ cair na cascata (motivo em `ultimo_motivo`). O modelo da API sai marcado `<id>@api` (`claude_api.pela_api`)."""
    global ultimo_motivo
    r = None
    if backend in ("auto", "cli"):
        r = _pensar_cli(tarefa, prompt, schema=schema, modelo=modelo, timeout=timeout, ferramentas=ferramentas,
                        sistema=sistema, espera=espera, executar=executar, _canario=_canario)
        if r is not None or backend == "cli" or _canario:
            return r
    # kill-switch (e teste sem dublê) barra a API também — decidido pelo estado, não pelo texto do motivo
    barrado = _motivo_kill_switch() or ("sob pytest sem executor dublê" if executar is None and arq.sob_pytest() else None)
    if barrado:
        if backend == "api":
            ultimo_motivo = barrado
        return None
    if ferramentas:                     # a API aqui é só texto: tarefa com ferramenta não migra
        return None
    motivo_cli = ultimo_motivo
    entrada = prompt + (instrucao_schema(schema) if schema is not None else "")
    ini = time.monotonic()
    res = claude_api.pensar_api(tarefa, entrada, sistema=sistema or SISTEMA_PADRAO, timeout=timeout,
                                cliente=api_cliente)
    if res is None:
        ultimo_motivo = " | ".join(m for m in (motivo_cli, claude_api.ultimo_motivo) if m)
        return None
    texto, quem, usd = res
    dados = None
    if schema is not None:
        dados = parse_json_llm(texto)
        if chaves_faltando(dados, schema) != []:
            ultimo_motivo = "API: resposta sem o JSON pedido"
            return None
    _log(f"tarefa={tarefa} ok modelo={quem}{claude_api.SUFIXO_API} {time.monotonic() - ini:.1f}s US$ {usd:.4f}")
    _mutar_estado(ultima_ok_iso=_agora())
    return Pensamento(texto=texto, modelo=f"{quem}{claude_api.SUFIXO_API}", segundos=round(time.monotonic() - ini, 1), tarefa=tarefa,
                      dados=dados, extras={"backend": "api", "usd": round(usd, 6)})


def _pensar_cli(tarefa: str, prompt: str, *, schema=None, modelo: str = MODELO_VOLUME, timeout: float = 180.0,
                ferramentas=(), sistema: str = "", espera: float | None = None, executar=None,
                _canario: bool = False) -> Pensamento | None:
    """Uma chamada ao Claude pela assinatura. `None` ⇒ cair na cascata (motivo em `ultimo_motivo`)."""
    global ultimo_motivo
    ultimo_motivo = ""
    if executar is None and arq.sob_pytest():
        # guarda dura: teste nenhum chama o claude de verdade (cota da assinatura) — só com executor dublê
        ultimo_motivo = "sob pytest sem executor dublê"
        return None
    executar = executar or _executar_cli
    espera = float(os.environ.get("JFN_CLAUDE_ESPERA_S", "90")) if espera is None else espera
    try:
        m = motivo_desligado(canario=_canario, tarefa=tarefa)
        if m:
            _falhar(tarefa, m, contar_erro=False)
            return None
        m = orcamento.motivo_teto(ler_uso(), tarefa)      # pré-checagem barata; a reserva confere de novo sob a trava
        if m:
            _falhar(tarefa, m, contar_erro=False)
            return None
        with arq.trava_vaga(_trava_arq(), vagas_claude(), espera) as pegou:
            if not pegou:
                _falhar(tarefa, f"ocupado: outro claude do JFN rodando há mais de {espera:.0f} s", contar_erro=False)
                return None
            reservado = {}

            def reservar(d):
                motivo = orcamento.motivo_teto(d, tarefa)
                reservado["motivo"] = motivo
                if not motivo:
                    d["total"]["chamadas"] += 1
                    orcamento.tarefa_de(d, tarefa)["chamadas"] += 1
            orcamento.mutar_uso(reservar)
            if reservado["motivo"]:
                _falhar(tarefa, reservado["motivo"], contar_erro=False)
                return None
            pasta = _pasta_trabalho()
            pasta.mkdir(mode=0o700, parents=True, exist_ok=True)
            entrada = prompt + (instrucao_schema(schema) if schema is not None else "")
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
        _tratar_tipo(tipo, motivo, (err or "") + " " + (out or ""))
        _falhar(tarefa, motivo, contar_erro=True, segundos=seg, tipo=tipo)
        return None
    resultado = corpo.get("result")
    if corpo.get("is_error") or rc != 0 or not isinstance(resultado, str) or not resultado.strip():
        bruto = str(resultado or corpo.get("subtype") or "resultado vazio")
        tipo = classificar_erro(bruto + " " + (err or ""))
        motivo = _sem_eco(f"o claude respondeu com erro ({tipo}): {bruto[:160]}", prompt)
        _tratar_tipo(tipo, motivo, bruto + " " + (err or ""))
        _falhar(tarefa, motivo, contar_erro=True, segundos=seg, tipo=tipo)
        return None
    dados = None
    if schema is not None:
        dados = parse_json_llm(resultado)
        faltam = chaves_faltando(dados, schema)
        if faltam != []:
            motivo = "resposta sem o JSON pedido" + (f" (faltam {', '.join(faltam[:5])})" if faltam else "")
            _falhar(tarefa, motivo, contar_erro=True, segundos=seg, tipo="schema")
            return None

    def f(d):
        tt = orcamento.tarefa_de(d, tarefa)
        d["total"]["ok"] += 1
        tt["ok"] += 1
        d["total"]["segundos"] = round(d["total"]["segundos"] + seg, 1)
        tt["segundos"] = round(tt["segundos"] + seg, 1)
        d["ultima_ok"] = {"em": _agora(), "tarefa": tarefa, "modelo": modelo, "segundos": round(seg, 1)}
    orcamento.mutar_uso(f)
    _mutar_estado(ultima_ok_iso=_agora())      # persiste à virada do dia: é o "efeito" do motor no AO VIVO
    _log(f"tarefa={tarefa} ok modelo={modelo} {seg:.1f}s{_tokens_do_corpo(corpo)}")
    return Pensamento(texto=resultado, modelo=modelo, segundos=round(seg, 1), tarefa=tarefa, dados=dados,
                      extras={k: corpo.get(k) for k in ("num_turns", "duration_ms") if k in corpo})


def _tokens_do_corpo(corpo: dict) -> str:
    """Tokens da chamada, do `usage` que o CLI devolve no JSON — só para MEDIR o custo por tarefa (22/11/2026: o
    log tinha só segundos, e a parte do motor na cota semanal saía de regressão). Sem `usage` legível: vazio."""
    u = corpo.get("usage")
    if not isinstance(u, dict):
        return ""
    try:
        v = [int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                                           "output_tokens")]
    except (TypeError, ValueError):
        return ""
    return " tok in={} cw={} cr={} out={}".format(*v)


def _tratar_tipo(tipo: str, motivo: str, bruto: str = "") -> None:
    if tipo == "limite":
        # arquivo único: o motor e os consumidores leem dele; sem hora legível, a pausa padrão é da contingência
        d = contingencia.entrar(motivo, contingencia.hora_de_volta(bruto or motivo))
        _log(f"limite de uso da assinatura: contingência até {datetime.fromtimestamp(d['ate']):%d/%m %H:%M}")


# ── canário diário ────────────────────────────────────────────────────────────────────────────────
def avisar_dono(texto: str) -> bool:
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
    avisar = avisar or avisar_dono
    em_limite = contingencia.motivo_bloqueio("canario")
    if em_limite:
        # conta no limite não é assinatura quebrada: o canário NÃO reprova (reprovar desligava o motor até o
        # canário do dia seguinte, mesmo com a conta de volta em 2 h) — fica para depois da hora de volta
        _log(f"canário adiado: {em_limite}")
        return {"ok": None, "motivo": em_limite, "segundos": None}
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
        "contingencia": _contingencia_painel(),
    }


def _contingencia_painel() -> dict | None:
    try:
        e = contingencia.estado()
        return {k: e.get(k) for k in ("ativa", "origem", "ate_iso", "motivo")}
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        return None


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Motor Claude do JFN (assinatura, com teto de cota)")
    ap.add_argument("--canario", action="store_true", help="chamada mínima que prova a assinatura")
    ap.add_argument("--status", action="store_true", help="uso de hoje (JSON)")
    a = ap.parse_args(argv)
    if a.canario:
        r = canario()
        print(json.dumps(r, ensure_ascii=False))
        return 1 if r["ok"] is False else 0
    print(json.dumps(painel(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
