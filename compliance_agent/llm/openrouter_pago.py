# -*- coding: utf-8 -*-
"""openrouter_pago — a ÚNICA porta de chamada PAGA ao OpenRouter (22/11/2026).

Pedido do dono (22/11/2026): "Tem o OpenRouter da conta iterjremoto com US$ 45,11. Pode usar até ele ficar com US$ 10
de saldo; depois disso apenas os modelos gratuitos." Objetivo: velocidade e poupar o Haiku.

SEPARAÇÃO DO GRÁTIS (regra §4.1 — nunca assumir free tier):
  · chave PRÓPRIA (`OPENROUTER_PAGO_API_KEY`), lida do arquivo 600 `~/.config/jfn/openrouter_pago.env` NA HORA de cada
    chamada — nunca do `.env` da casa, nunca guardada em variável global, nunca logada. Os outros usos do OpenRouter
    (free_llm, Yoda…) não a conhecem: não há como o caminho pago vazar para eles;
  · a guarda `:free` do `free_llm._requisicao` fica INTACTA (este módulo não a usa nem a altera); e esta porta RECUSA
    modelo `:free` — grátis vai pela porta grátis, pago por esta, sem mistura.

GUARD-RAIL REAL (não "cota do free tier"):
  · kill-switch `JFN_FICHA_OR_PAGO=0`;
  · TETO DIÁRIO em US$ (`JFN_FICHA_OR_PAGO_TETO_DIA_USD`, padrão `TETO_DIA_PADRAO`), somado do custo REAL devolvido pelo
    OpenRouter (`usage.cost`) num livro local (`data/openrouter_pago_gasto.json`); livro ilegível/não gravável → não
    chama (falha FECHADA);
  · antes de cada lote `liberar(estimativa)`: GET /credits — se `total_credits − total_usage − estimativa` <
    `OPENROUTER_PAGO_PISO_CONTA_USD` (10) → não chama; GET /key — se `limit_remaining` < estimativa → não chama
    (a chave tem Credit limit no SERVIDOR: segunda trava, independente desta); erro de rede/HTTP → não chama;
  · cada resposta vai ao trace da casa (`free_llm._trace`, provedor `openrouter_pago`, modelo, tokens, usd)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

BASE = "https://openrouter.ai/api/v1"
REPO = Path(__file__).resolve().parents[2]
ENV_PADRAO = Path.home() / ".config" / "jfn" / "openrouter_pago.env"
GASTO_PADRAO = REPO / "data" / "openrouter_pago_gasto.json"
PISO_PADRAO = 10.0
# US$ 5/dia: a US$ 0,0047/processo (deepseek-v4.1-flash, bancada de 22/11) dá ~1.050 chamadas/dia — o que a etapa
# paga da ficha consome num dia (só o que o consenso grátis não fechou, ~30% da fila; cron de hora em hora, lote 400,
# teto de tempo do ciclo) — e um defeito (laço, prompt gigante) não queima mais que 1/7 dos ~US$ 34 utilizáveis num
# dia. O dono sobe pelo env (`JFN_FICHA_OR_PAGO_TETO_DIA_USD`) se quiser ir mais rápido.
TETO_DIA_PADRAO = 5.0
TAREFA = "ficha_acervo"     # a única tarefa que usa esta porta (tools/sei_ficha_acervo) — chave da autorização
TIMEOUT_S = 180


def _arq_env() -> Path:
    return Path(os.environ.get("JFN_OR_PAGO_ENV") or ENV_PADRAO)


def _arq_gasto() -> Path:
    return Path(os.environ.get("JFN_OR_PAGO_GASTO") or GASTO_PADRAO)


def _cfg() -> dict:
    """Lê o arquivo da chave na hora (nada fica em memória entre chamadas). Sem arquivo → {}."""
    try:
        linhas = _arq_env().read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    return {k.strip(): v.strip() for k, _, v in (l.partition("=") for l in linhas)
            if k.strip() and not k.lstrip().startswith("#") and v.strip()}


def piso_conta() -> float:
    try:
        return float(_cfg().get("OPENROUTER_PAGO_PISO_CONTA_USD") or PISO_PADRAO)
    except ValueError:
        return PISO_PADRAO


def teto_dia() -> float:
    try:
        return float(os.environ.get("JFN_FICHA_OR_PAGO_TETO_DIA_USD") or TETO_DIA_PADRAO)
    except ValueError:
        return TETO_DIA_PADRAO


def ligado() -> tuple[bool, str]:
    if os.environ.get("JFN_FICHA_OR_PAGO", "1").strip().lower() in ("0", "off", "nao", "não", "false", ""):
        return False, "desligado (JFN_FICHA_OR_PAGO=0)"
    if not _cfg().get("OPENROUTER_PAGO_API_KEY"):
        return False, "sem chave paga"
    # regra do dono (24/11/2026): "créditos de API só quando eu autorizar" — a autorização de 22/11 só volta a valer
    # se o dono a registrar no livro (`llm/autorizacao_paga`, id em JFN_LLM_AUTORIZACAO_PAGA)
    from compliance_agent.llm import autorizacao_paga as AP
    recusa = AP.motivo_recusa(AP.id_do_ambiente(), tarefa=TAREFA, provedor="openrouter_pago")
    if recusa:
        return False, recusa
    return True, ""


def _livro() -> dict:
    """{dia: {usd, chamadas, por_modelo}}. Arquivo ausente = nada gasto; ilegível → ValueError (falha fechada)."""
    p = _arq_gasto()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def gasto_hoje() -> float:
    return float((_livro().get(datetime.now().strftime("%F")) or {}).get("usd", 0.0))


def _anotar(modelo: str, usd: float) -> None:
    d = _livro()
    hoje = datetime.now().strftime("%F")
    dia = d.setdefault(hoje, {"usd": 0.0, "chamadas": 0, "por_modelo": {}})
    dia["usd"] = round(dia["usd"] + usd, 6)
    dia["chamadas"] += 1
    dia["por_modelo"][modelo] = round(dia["por_modelo"].get(modelo, 0.0) + usd, 6)
    p = _arq_gasto()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _cab() -> dict:
    return {"Authorization": "Bearer " + _cfg().get("OPENROUTER_PAGO_API_KEY", ""), "Content-Type": "application/json"}


def saldo() -> dict:
    """{conta_usd: créditos − uso da CONTA, chave_restante_usd: limit_remaining da chave (None = sem limite)}.
    Erro de rede/HTTP/JSON propaga (quem decide gastar trata como NÃO)."""
    import httpx
    c = httpx.get(f"{BASE}/credits", headers=_cab(), timeout=30)
    c.raise_for_status()
    cd = c.json()["data"]
    k = httpx.get(f"{BASE}/key", headers=_cab(), timeout=30)
    k.raise_for_status()
    kd = k.json()["data"]
    rest = kd.get("limit_remaining")
    return {"conta_usd": round(float(cd["total_credits"]) - float(cd["total_usage"]), 4),
            "chave_restante_usd": None if rest is None else round(float(rest), 4)}


def liberar(estimativa_usd: float) -> tuple[bool, str]:
    """Pode gastar `estimativa_usd` agora? (False, motivo) em qualquer dúvida."""
    ok, motivo = ligado()
    if not ok:
        return False, motivo
    try:
        hoje = gasto_hoje()
    except (OSError, ValueError) as exc:
        return False, f"livro de gasto ilegível ({type(exc).__name__}) — não gasta"
    if hoje + estimativa_usd > teto_dia():
        return False, f"teto do dia: US$ {hoje:.4f} gastos + US$ {estimativa_usd:.4f} > US$ {teto_dia():.2f}"
    import httpx
    try:
        s = saldo()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:     # rede/HTTP/JSON: não gasta (falha fechada)
        return False, f"saldo indisponível ({type(exc).__name__}) — não gasta"
    if s["conta_usd"] - estimativa_usd < piso_conta():
        return False, (f"piso da conta: US$ {s['conta_usd']:.2f} − US$ {estimativa_usd:.2f} < "
                       f"US$ {piso_conta():.2f} — daqui em diante só grátis")
    if s["chave_restante_usd"] is not None and s["chave_restante_usd"] < estimativa_usd:
        return False, f"limite da chave: restam US$ {s['chave_restante_usd']:.2f} < US$ {estimativa_usd:.2f}"
    return True, ""


def chamar(modelo: str, sistema: str, prompt: str, max_tokens: int = 16_000) -> str:
    """Texto da resposta ("" = não respondeu). Só modelo PAGO; o teto do dia é reconferido a cada chamada (local).
    Quem chama tem de ter passado por `liberar` antes do lote."""
    import httpx
    from compliance_agent.llm.free_llm import _trace
    if modelo.endswith(":free") or modelo.startswith("openrouter/"):
        raise ValueError("porta paga recusa modelo grátis/roteador — grátis vai pelo free_llm")
    ok, motivo = ligado()
    if not ok:
        return ""
    if gasto_hoje() >= teto_dia():
        return ""
    carga = {"model": modelo, "max_tokens": max_tokens, "temperature": 0.1, "reasoning": {"enabled": False},
             "usage": {"include": True},
             "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": prompt}]}
    ini, saida, erro, usd, tin, tout = time.monotonic(), "", "", None, None, None
    try:
        r = httpx.post(f"{BASE}/chat/completions", headers=_cab(), json=carga, timeout=TIMEOUT_S)
        if r.status_code != 200:
            erro = f"HTTP {r.status_code}"
        else:
            j = r.json()
            u = j.get("usage") or {}
            usd = float(u["cost"]) if u.get("cost") is not None else None
            tin, tout = u.get("prompt_tokens"), u.get("completion_tokens")
            esc = (j.get("choices") or [{}])[0]
            if esc.get("finish_reason") == "length":
                erro = "cortada (length)"                  # resposta cortada não é resposta — mas foi cobrada
            else:
                saida = (esc.get("message") or {}).get("content") or ""
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        erro = type(exc).__name__
    if usd is None and (tin or tout):           # custo não informado: anota por cima (US$ 1/4 por M, >10× o medido)
        usd = round(((tin or 0) * 1.0 + (tout or 0) * 4.0) / 1e6, 6)
        erro = (erro + " · custo estimado").strip(" ·")
    if usd is not None:
        _anotar(modelo, usd)
    _trace("openrouter_pago", bool(saida), int((time.monotonic() - ini) * 1000), erro, modelo=modelo,
           tokens_in=tin, tokens_out=tout, usd=usd)
    return saida


def estado() -> dict:
    """Para o `--estado` dos consumidores: ligado, saldo da conta/chave (GET), gasto e teto do dia, piso."""
    ok, motivo = ligado()
    out = {"ligado": ok, "motivo": motivo, "teto_dia_usd": teto_dia(), "piso_conta_usd": piso_conta()}
    try:
        out["gasto_hoje_usd"] = round(gasto_hoje(), 4)
    except (OSError, ValueError) as exc:
        out["gasto_hoje_usd"] = f"ilegível ({type(exc).__name__})"
    if ok:
        import httpx
        try:
            out.update(saldo())
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            out["saldo"] = f"indisponível ({type(exc).__name__})"
    return out
