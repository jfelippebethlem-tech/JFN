# -*- coding: utf-8 -*-
"""contingencia — o JFN não para de produzir quando o Claude da assinatura chega ao limite.

Pedido do dono (14/11/2026): "quando chegar perto de 100% do uso do limite claude, coloque tudo pros outros
modelos de ai continuarem, ok? a regra é nunca ficar sem produzir. o que for feito por eles depois tem
conferência sempre pelo claude opus".

O QUE ESTE MÓDULO GUARDA: o estado "assinatura em contingência até HH:MM", num arquivo ÚNICO
(`data/claude_contingencia.json`) que o motor e todos os consumidores leem — enquanto durar, ninguém chama o
CLI (não se martela uma conta que já disse "volte às 2:30").

TRÊS ORIGENS:
  · limite_assinatura — o CLI respondeu "You've hit your 5-hour limit · resets 2:30am (America/Sao_Paulo)"
    (medido em 13/11/2026 22:23: o motor classificava isso como erro "outro" e seguia tentando). A hora de
    volta é lida da própria mensagem (`hora_de_volta`); sem hora legível, pausa de `JFN_CLAUDE_PAUSA_LIMITE_S`;
  · teto_proprio — o orçamento diário do motor passou de 90% (chamadas ou segundos): o que resta fica
    RESERVADO ao Opus (verificação e conferência) e as tarefas de volume passam aos outros modelos até 00:00;
  · forcada — `JFN_CLAUDE_CONTINGENCIA=1` (ensaio/prova, ou decisão manual);
  · ritmo_semanal — o gasto da SEMANA passou da linha que faz a conta durar até a virada (`llm/ritmo_assinatura`,
    16/11/2026): ECONOMIA deixa só o Opus que confere; CONTIDO deixa só o canário.

O QUE NÃO FAZ: não decide nada. Quem produz em contingência é a cascata que a casa já usa
(`direcionamento_cerebro.gerar_sync`); tudo o que ela produzir vai para a fila `conferencia_opus` e NUNCA é
promovido a VERIFICADO sem o Opus da assinatura. Custo de API não passa por aqui.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]
FRACAO_PERTO = 0.90
# tarefas do Opus que usam a reserva dos últimos 10% do dia (é para elas que a reserva existe)
# Dono 20/11/2026 ("pode ligar o executor noturno da automelhoria. pode fazer tudo"): a MELHORIA também é reserva —
# juiz, automelhoria, consolidação do cérebro e o executor noturno passam no nível ECONOMIA do ritmo semanal (no
# CONTIDO, acima da linha, seguem barrados: os 10% finais da semana continuam do dono).
RESERVA_OPUS = ("canario", "verificacao_opus", "conferencia_opus",
                "juiz_qualidade", "autoaprimoramento", "cerebro_consolidacao", "automelhoria_executor")
MARGEM_VOLTA_S = 120          # a conta volta "às 2:30": tenta-se às 2:32
_MAX_PAUSA_S = 8 * 86400      # limite semanal é o maior que existe; além disso a leitura da hora está errada

_RE_LIMITE = re.compile(r"hit your [^.\n]{0,40}limit|usage limit|rate[ _-]?limit|limit reached|limite de uso|"
                        r"out of extra usage|too many requests|quota", re.I)
_RE_VOLTA = re.compile(
    r"resets?\s+(?:at\s+)?(?:(?P<mes>[A-Za-z]{3,9})\.?\s+(?P<dia>\d{1,2}),?\s+(?:at\s+)?)?"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?(?:\s*\((?P<tz>[A-Za-z_]+/[A-Za-z_/]+)\))?", re.I)
_MESES = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                          "nov", "dec"))}


def eh_limite(texto: str) -> bool:
    """O texto do erro é limite de uso da conta (429 / rate_limit / "hit your … limit")?"""
    t = texto or ""
    return bool(_RE_LIMITE.search(t)) or ("limit" in t.lower() and "usage" in t.lower())


def hora_de_volta(texto: str, agora: float | None = None) -> float | None:
    """Epoch em que a conta volta, lido de "resets 2:30am (America/Sao_Paulo)" / "resets 3pm" /
    "resets Nov 15, 3am". Sem hora legível → None (o chamador usa a pausa padrão; nunca se inventa hora)."""
    m = _RE_VOLTA.search(texto or "")
    if not m:
        return None
    agora = time.time() if agora is None else agora
    tz = None
    if m.group("tz"):
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(m.group("tz"))
        except (ImportError, KeyError, ValueError):
            tz = None
    base = datetime.fromtimestamp(agora, tz) if tz else datetime.fromtimestamp(agora).astimezone()
    h, mi, ap = int(m.group("h")), int(m.group("m") or 0), (m.group("ap") or "").lower()
    if ap:
        if not 1 <= h <= 12:
            return None
        h = (h % 12) + (12 if ap == "pm" else 0)
    if h > 23 or mi > 59:
        return None
    try:
        if m.group("mes"):
            mes = _MESES.get(m.group("mes")[:3].lower())
            if not mes:
                return None
            alvo = base.replace(month=mes, day=int(m.group("dia")), hour=h, minute=mi, second=0, microsecond=0)
            if alvo <= base:
                alvo = alvo.replace(year=alvo.year + 1)
        else:
            alvo = base.replace(hour=h, minute=mi, second=0, microsecond=0)
            if alvo <= base:
                alvo += timedelta(days=1)
    except ValueError:
        return None
    ate = alvo.timestamp() + MARGEM_VOLTA_S
    return ate if 0 < ate - agora <= _MAX_PAUSA_S else None


# ── arquivo único de estado ──────────────────────────────────────────────────────────────────────────
def _dados() -> Path:
    return Path(os.environ.get("JFN_CLAUDE_DADOS") or (_REPO / "data"))


def arquivo() -> Path:
    return _dados() / "claude_contingencia.json"


def _ler() -> dict:
    try:
        d = json.loads(arquivo().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _mutar(fn) -> dict:
    arq = arquivo()
    arq.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(arq.with_suffix(".json.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        d = _ler()
        fn(d)
        tmp = arq.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, arq)
        return d
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def forcada() -> bool:
    return os.environ.get("JFN_CLAUDE_CONTINGENCIA", "").strip().lower() in ("1", "true", "on", "sim")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def entrar(motivo: str, ate: float | None = None, *, origem: str = "limite_assinatura", avisar=None) -> dict:
    """Liga a contingência até `ate` (epoch). Sem `ate`: pausa de `JFN_CLAUDE_PAUSA_LIMITE_S` (1 h). Avisa o dono
    UMA vez por entrada (não a cada chamada barrada)."""
    agora = time.time()
    if ate is None or ate <= agora:
        try:
            pausa = int(os.environ.get("JFN_CLAUDE_PAUSA_LIMITE_S", "") or 3600)
        except ValueError:
            pausa = 3600
        ate = agora + pausa
    ja = {}

    def f(d):
        ja["ativa"] = isinstance(d.get("ate"), (int, float)) and d["ate"] > agora
        if not ja["ativa"]:
            d["desde"] = _iso(agora)
            d["entradas"] = (d.get("entradas") or [])[-19:] + [{"desde": _iso(agora), "ate": _iso(ate),
                                                              "origem": origem, "motivo": (motivo or "")[:160]}]
        d.update(ate=ate, ate_iso=_iso(ate), origem=origem, motivo=(motivo or "")[:200])
    d = _mutar(f)
    if not ja["ativa"]:
        logger.warning("contingência: assinatura Claude fora até %s (%s)", d["ate_iso"], origem)
        _avisar(f"🟡 <b>Claude da assinatura no limite</b> — volta às {datetime.fromtimestamp(ate):%H:%M de %d/%m}. "
                "O JFN segue produzindo com os outros modelos; tudo o que eles fizerem fica na fila de "
                "conferência do Opus e não vira VERIFICADO antes disso.", avisar)
    return d


def sair(motivo: str = "") -> None:
    """Encerra a contingência por limite (a assinatura respondeu, ou decisão manual)."""
    def f(d):
        if d.get("ate"):
            d.update(ate=None, ate_iso=None, encerrada_em=_iso(time.time()), encerrada_por=(motivo or "")[:120])
    _mutar(f)


def _avisar(texto: str, avisar=None) -> None:
    if avisar is None and os.environ.get("PYTEST_CURRENT_TEST"):
        return                              # teste nenhum manda mensagem de verdade ao dono
    try:
        if avisar is None:
            from compliance_agent.llm.claude_motor import _avisar_telegram as avisar
        avisar(texto)
    except (ImportError, OSError, RuntimeError, ValueError) as e:   # aviso é melhor-esforço; o estado já foi gravado
        logger.warning("contingência: aviso não enviado (%s)", type(e).__name__)


def _uso() -> dict:
    """Fração do orçamento diário do motor já usada, total e por tarefa. Motor ilegível → {} (INDISPONÍVEL)."""
    try:
        from compliance_agent.llm import claude_motor as M
        u = M.ler_uso()
        t = u["total"]
        fr = max(t["chamadas"] / max(1, M.teto_total()), t["segundos"] / max(1, M.teto_segundos()))
        perto = sorted(k for k, v in u["tarefas"].items()
                       if v["chamadas"] >= FRACAO_PERTO * M.teto_tarefa(k) and k not in RESERVA_OPUS)
        return {"fracao": round(fr, 3), "tarefas_perto_do_teto": perto}
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        return {}


def estado() -> dict:
    """Leitura única para motor, consumidores e painel. `ativa` ⇒ produzir com os outros modelos e enfileirar."""
    agora = time.time()
    d, u = _ler(), _uso()
    base = {"ativa": False, "origem": None, "ate": None, "ate_iso": None, "motivo": None,
            "uso_fracao": u.get("fracao"), "tarefas_perto_do_teto": u.get("tarefas_perto_do_teto", []),
            "ultima": (d.get("entradas") or [None])[-1]}
    if forcada():
        return dict(base, ativa=True, origem="forcada", motivo="contingência forçada (JFN_CLAUDE_CONTINGENCIA=1)")
    ate = d.get("ate")
    if isinstance(ate, (int, float)) and ate > agora:
        return dict(base, ativa=True, origem=d.get("origem") or "limite_assinatura", ate=ate, ate_iso=_iso(ate),
                    motivo=d.get("motivo"))
    r = _ritmo()
    if r.get("nivel") == "contido":
        return _ritmo_estado(base, r)
    if (u.get("fracao") or 0) >= FRACAO_PERTO:
        meia_noite = (datetime.fromtimestamp(agora) + timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                                                                microsecond=0).timestamp()
        return dict(base, ativa=True, origem="teto_proprio", ate=meia_noite, ate_iso=_iso(meia_noite),
                    motivo=f"{u['fracao']:.0%} do orçamento diário do motor — o resto fica para o Opus conferir")
    if r.get("nivel") == "economia":
        return _ritmo_estado(base, r)
    return base


def _ritmo() -> dict:
    """Ritmo SEMANAL da assinatura (16/11/2026: "a assinatura não pode acabar antes do sábado 19:00"). Só lê arquivo;
    ilegível ⇒ {} (sem restrição: os tetos diários seguem valendo)."""
    try:
        from compliance_agent.llm import ritmo_assinatura
        return ritmo_assinatura.nivel()
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        return {}


def _ritmo_estado(base: dict, r: dict) -> dict:
    ate = datetime.fromisoformat(r["reavaliar_em"]).timestamp()
    return dict(base, ativa=True, origem="ritmo_semanal", ate=ate, ate_iso=r["reavaliar_em"], motivo=r.get("motivo"),
                ritmo_nivel=r.get("nivel"), semana_pct=r.get("semana_pct"), linha_pct=r.get("linha_pct"))


def motivo_bloqueio(tarefa: str = "") -> str | None:
    """Por que o CLI NÃO deve ser chamado agora para esta tarefa (None = pode). As tarefas do Opus em
    `RESERVA_OPUS` atravessam a contingência por teto próprio (a reserva é delas), nunca a por limite da conta."""
    e = estado()
    if not e["ativa"]:
        return None
    if e["origem"] == "teto_proprio":
        if tarefa in RESERVA_OPUS or (e.get("uso_fracao") or 0) >= 1:   # a 100% quem fala é o teto duro do motor
            return None
        return f"contingência — {e['motivo']}"
    if e["origem"] == "forcada":
        return f"contingência — {e['motivo']}"
    if e["origem"] == "ritmo_semanal":
        if tarefa == "canario" or (e.get("ritmo_nivel") == "economia" and tarefa in RESERVA_OPUS):
            return None
        return f"ritmo semanal da assinatura — {e['motivo']}"
    return f"limite de uso da assinatura — pausa até {datetime.fromtimestamp(e['ate']):%H:%M}"


# ── produção em contingência para quem chama o motor direto (sem co-motor) ───────────────────────────
def cascata(tarefa: str, prompt: str, *, schema=None, sistema: str = "", motivo: str = "", item: str | None = None,
            valor: float | None = None, gerar=None, timeout: float = 120.0):
    """Roda a cascata da casa (a MESMA dos produtos, `direcionamento_cerebro.gerar_sync`) no lugar do Claude e
    põe o resultado na fila de conferência do Opus. Devolve `(dados_ou_texto, modelo_real)` ou None.

    Sob pytest sem `gerar` injetado devolve None: teste nenhum chama provedor de verdade."""
    from compliance_agent.llm import conferencia_opus
    if gerar is None:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return None
        from compliance_agent.llm.comotor import _gerar_sync_padrao as gerar
    entrada = prompt
    if schema is not None:
        entrada += ("\n\nResponda SOMENTE com um objeto JSON válido, sem texto fora dele, neste formato:\n"
                    + (schema if isinstance(schema, str) else json.dumps(schema, ensure_ascii=False)))
    try:
        txt = gerar(entrada, sistema, timeout, True)
    except (RuntimeError, OSError, ValueError, TypeError, KeyError) as e:   # cascata fora: o chamador fica PENDENTE
        logger.warning("contingência: cascata sem resposta para %s (%s)", tarefa, type(e).__name__)
        return None
    if not (txt or "").strip():
        return None
    dados = txt
    if schema is not None:
        from compliance_agent.llm.json_resposta import parse_json_llm
        dados = parse_json_llm(txt)
        exigidas = schema.get("required", []) if isinstance(schema, dict) else []
        if not isinstance(dados, dict) or any(k not in dados for k in exigidas):
            return None                     # leitura fora do formato é descartada, nunca "consertada"
    from compliance_agent.llm.comotor import _modelo_da_cascata
    modelo = _modelo_da_cascata()
    conferencia_opus.enfileirar(tarefa, item, entrada, sistema=sistema, motor=modelo, resposta=txt,
                                motivo=motivo or (estado().get("motivo") or "Claude indisponível"), valor=valor)
    return dados, modelo
