# -*- coding: utf-8 -*-
"""claude_api — o SEGUNDO backend do motor Claude: a API da Anthropic, paga, com teto DURO em dólares.

Recurso liberado pelo dono em 13/11/2026: "pode usar até 100 USD de API pra acelerar isso" — e, no mesmo dia,
"use os modelos mais baratos na api [...] opus fica muito caro", "veja como fazer render os 100 dólares" e
"não pode ter margem pra erro em nada. esse é um projeto de governo". Daí as regras deste módulo:

  · a ASSINATURA (`claude_motor`, CLI) é a primeira opção; a API entra quando a assinatura está sem cota, quando
    a trava do único `claude` da VM está ocupada, ou para LOTE (Batch API, metade do preço — o padrão sempre
    que ninguém espera a resposta);
  · Haiku 5.5 é o modelo da API; Sonnet 5.5 só nas tarefas em que uma amostra provou erro do Haiku
    (`JFN_API_SONNET_TAREFAS`); Opus NUNCA pela API (fica na assinatura);
  · o modelo barato NUNCA decide sozinho: ele extrai, tria e SUGERE. O que vira fato no painel passa pela
    dupla leitura e pela verificação (ver `verificacao.py` e os consumidores);
  · parte fixa do prompt (instruções, exemplos) vai no `system` com `cache_control` (leitura a 0,1×); o item
    variável vai no fim. A leitura de cache é contada no livro-caixa para provar que o cache pega;
  · saída enxuta: JSON estruturado (`output_config.format`), `max_tokens` justo, `effort` baixo em
    classificação; resultado idêntico não se paga duas vezes (memória por hash da entrada).

A CHAVE: lida em tempo de execução de `~/.config/jfn/anthropic.env` (`ANTHROPIC_API_KEY_JFN`, arquivo 600,
FORA do repositório). Nunca vai para log, `.env` do JFN, commit, mensagem ou exceção (o motivo de falha leva só
o TIPO da exceção). Sem o arquivo, o backend some em silêncio — nunca quebra. Regra §4.1: API paga cobra.

O TETO (nunca reinicia sozinho): custo de CADA resposta = `usage` (entrada, saída, leitura e escrita de cache)
× preço, acumulado em `data/claude_api_gasto.json` sob trava de arquivo. Antes da chamada a entrada é CONTADA
(`count_tokens`) e a saída estimada pelo `max_tokens` inteiro; a estimativa fica RESERVADA enquanto a chamada
roda (paralelismo não fura teto). Recusa se passar do teto total − US$ 5 OU do teto do BALDE da tarefa
(orçamento do dono: triagem 10 · normalização de itens 10 · extração do SEI 35 · revisão cética 20 ·
calibração 10 · reserva 15, esta só com `JFN_API_RESERVA_LIBERADA=1`). Tarefa pausada por queda de
qualidade também é recusada até alguém despausar.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MODELO_JUIZO = "claude-opus-5-5"
MODELO_VOLUME = "claude-sonnet-5-5"
MODELO_BARATO = "claude-haiku-5-5"
MODELO_API_PADRAO = MODELO_BARATO

# US$ por 1M tokens (entrada, saída) — tabela do dono de 13/11/2026 (= skill claude-api, cache 2026-11-03).
# Haiku: até 100K tokens de prompt; acima disso 0,50/2,50 — aplicado quando a entrada passa de 100K.
PRECOS = {
    MODELO_JUIZO: (4.00, 20.00),
    MODELO_VOLUME: (2.00, 10.00),
    MODELO_BARATO: (0.10, 0.50),
}
_HAIKU_LONGO = (0.50, 2.50)
_LEITURA_CACHE = 0.10       # × preço de entrada
_ESCRITA_CACHE = 1.25       # × preço de entrada (TTL 5 min)
DESCONTO_LOTE = 0.50
MARGEM_USD = 5.0
_BETA_FALLBACK = "server-side-fallback-2026-07-01"
_COM_FALLBACK = {MODELO_VOLUME}     # Opus não passa pela API; o Haiku não tem fallback do servidor

# Orçamento do dono por BALDE (US$). Tarefas de juízo que caem da assinatura para a API pagam da revisão.
BALDES_USD = {"triagem_alertas": 10.0, "normalizacao_itens": 10.0, "extracao_sei": 35.0,
              "revisao_cetica": 20.0, "calibracao": 10.0, "reserva": 15.0}
BALDE_DA_TAREFA = {
    "triagem_alertas": "triagem_alertas",
    "normalizacao_itens": "normalizacao_itens",
    "extracao_sei": "extracao_sei",
    "pericia_execucao": "revisao_cetica", "pericia_fornecedor": "revisao_cetica",
    "parecer_juridico": "revisao_cetica", "camada_subjetiva": "revisao_cetica",
    "investigacao_risco": "revisao_cetica", "revisao_cetica": "revisao_cetica",
    "calibracao": "calibracao", "fumaca": "calibracao",
}

ultimo_motivo: str = ""


def balde(tarefa: str) -> str:
    return BALDE_DA_TAREFA.get(tarefa, "reserva")


def modelo_para(tarefa: str) -> str:
    """Haiku, ou Sonnet se a tarefa está em `JFN_API_SONNET_TAREFAS` (amostra provou erro do Haiku)."""
    sonnet = {t.strip() for t in os.environ.get("JFN_API_SONNET_TAREFAS", "").split(",") if t.strip()}
    return MODELO_VOLUME if tarefa in sonnet else MODELO_API_PADRAO


def _sem_opus(modelo: str) -> str:
    if modelo == MODELO_JUIZO:
        logger.info("claude_api: Opus pedido pela API — rebaixado para %s (decisão do dono)", MODELO_API_PADRAO)
        return MODELO_API_PADRAO
    return modelo


# ── chave e teto (lidos do arquivo a cada uso; nunca guardados em atributo que vá parar em repr/log) ──────
def _arquivo_env() -> Path:
    return Path(os.environ.get("JFN_ANTHROPIC_ENV") or (Path.home() / ".config" / "jfn" / "anthropic.env"))


def _ler_env() -> dict:
    try:
        linhas = _arquivo_env().read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    d = {}
    for ln in linhas:
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            d[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return d


def _chave() -> str | None:
    return _ler_env().get("ANTHROPIC_API_KEY_JFN") or None


def teto_usd() -> float:
    bruto = os.environ.get("JFN_API_TETO_USD") or _ler_env().get("JFN_API_TETO_USD") or "100"
    try:
        return float(bruto)
    except ValueError:
        return 100.0


def limite_efetivo() -> float:
    return max(0.0, teto_usd() - MARGEM_USD)


def disponivel() -> bool:
    if os.environ.get("JFN_CLAUDE_API", "1").strip().lower() in ("0", "false", "off", "no"):
        return False
    return _chave() is not None


# ── livro-caixa ───────────────────────────────────────────────────────────────────────────────────────
def _dados() -> Path:
    from compliance_agent.llm.claude_motor import _dados as d
    return d()


def _gasto_arq() -> Path:
    return _dados() / "claude_api_gasto.json"


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _vazio() -> dict:
    return {"total_usd": 0.0, "reservado_usd": 0.0, "chamadas": 0, "recusadas_teto": 0, "por_tarefa": {},
            "por_balde": {}, "por_modelo": {}, "lotes": {}, "pausadas": {}, "ultima": None, "ultimo_erro": None,
            "desde": _agora()}


def ler_gasto() -> dict:
    from compliance_agent.llm.claude_motor import _ler_json
    d = _ler_json(_gasto_arq())
    return {**_vazio(), **d} if d else _vazio()


def _mutar(fn):
    from compliance_agent.llm.claude_motor import _flock, _gravar_json
    with _flock(_gasto_arq().with_suffix(".json.lock"), 15.0):
        d = ler_gasto()
        r = fn(d)
        _gravar_json(_gasto_arq(), d)
        return r


def _b(d: dict, nome: str) -> dict:
    return d["por_balde"].setdefault(nome, {"usd": 0.0, "reservado": 0.0, "itens": 0, "restantes": None})


def _precos(modelo: str, tokens_entrada: int = 0) -> tuple[float, float]:
    if modelo == MODELO_BARATO and tokens_entrada > 100_000:
        return _HAIKU_LONGO
    return PRECOS.get(modelo, max(PRECOS.values()))     # desconhecido = o mais caro: nunca subestimar


def _uso(usage, k: str) -> int:
    v = usage.get(k) if isinstance(usage, dict) else getattr(usage, k, None)
    return int(v or 0)


def custo(modelo: str, usage, *, lote: bool = False) -> float:
    """US$ de uma resposta, de `response.usage` (objeto do SDK ou dict)."""
    ent, sai = _uso(usage, "input_tokens"), _uso(usage, "output_tokens")
    lido, escrito = _uso(usage, "cache_read_input_tokens"), _uso(usage, "cache_creation_input_tokens")
    pin, pout = _precos(modelo, ent + lido + escrito)
    usd = (ent * pin + sai * pout + lido * pin * _LEITURA_CACHE + escrito * pin * _ESCRITA_CACHE) / 1e6
    return usd * (DESCONTO_LOTE if lote else 1.0)


def estimativa(modelo: str, tokens_entrada: int, max_tokens: int, *, lote: bool = False) -> float:
    pin, pout = _precos(modelo, tokens_entrada)
    # entrada estimada como escrita de cache (1,25×): o pior caso da primeira chamada
    return (tokens_entrada * pin * _ESCRITA_CACHE + max_tokens * pout) / 1e6 * (DESCONTO_LOTE if lote else 1.0)


def _reservar(tarefa: str, est: float) -> str | None:
    """Reserva `est` no total e no balde, sob trava. Devolve o motivo da recusa, ou None se reservou."""
    nome = balde(tarefa)

    def f(d):
        b = _b(d, nome)
        if nome in d["pausadas"]:
            return f"API: tarefa {nome} PAUSADA ({d['pausadas'][nome].get('motivo', '?')})"
        if nome == "reserva" and os.environ.get("JFN_API_RESERVA_LIBERADA") != "1":
            return f"API: '{tarefa}' cairia na reserva, que só se usa com liberação (JFN_API_RESERVA_LIBERADA=1)"
        if d["total_usd"] + d["reservado_usd"] + est > limite_efetivo():
            d["recusadas_teto"] += 1
            return (f"API: teto total — US$ {d['total_usd']:.2f} gastos + US$ {d['reservado_usd']:.2f} em curso + "
                    f"US$ {est:.4f} passam de US$ {limite_efetivo():.2f} (teto {teto_usd():.0f} − margem)")
        if b["usd"] + b["reservado"] + est > BALDES_USD.get(nome, 0.0):
            d["recusadas_teto"] += 1
            return f"API: teto do balde {nome} (US$ {BALDES_USD.get(nome, 0):.2f}) — gasto US$ {b['usd']:.2f}"
        d["reservado_usd"] = round(d["reservado_usd"] + est, 6)
        b["reservado"] = round(b["reservado"] + est, 6)
        return None
    return _mutar(f)


def _liquidar(tarefa: str, modelo: str, est: float, usd: float, usage=None, *, erro: str = "", itens: int = 0) -> None:
    nome = balde(tarefa)

    def f(d):
        b = _b(d, nome)
        d["reservado_usd"] = round(max(0.0, d["reservado_usd"] - est), 6)
        b["reservado"] = round(max(0.0, b["reservado"] - est), 6)
        d["total_usd"] = round(d["total_usd"] + usd, 6)
        b["usd"] = round(b["usd"] + usd, 6)
        b["itens"] += itens
        t = d["por_tarefa"].setdefault(tarefa, {"usd": 0.0, "chamadas": 0, "erros": 0})
        m = d["por_modelo"].setdefault(modelo, {"usd": 0.0, "chamadas": 0, "entrada": 0, "saida": 0, "cache_lido": 0})
        t["usd"] = round(t["usd"] + usd, 6)
        m["usd"] = round(m["usd"] + usd, 6)
        if erro:
            t["erros"] += 1
            d["ultimo_erro"] = {"em": _agora(), "tarefa": tarefa, "motivo": erro[:200]}
            return
        d["chamadas"] += 1
        t["chamadas"] += 1
        m["chamadas"] += 1
        if usage is not None:
            m["entrada"] += _uso(usage, "input_tokens") + _uso(usage, "cache_creation_input_tokens")
            m["cache_lido"] += _uso(usage, "cache_read_input_tokens")
            m["saida"] += _uso(usage, "output_tokens")
        d["ultima"] = {"em": _agora(), "tarefa": tarefa, "modelo": modelo, "usd": round(usd, 6)}
    _mutar(f)


def pausar(tarefa: str, motivo: str) -> None:
    _mutar(lambda d: d["pausadas"].__setitem__(balde(tarefa), {"em": _agora(), "motivo": motivo[:200]}))


def despausar(tarefa: str) -> None:
    _mutar(lambda d: d["pausadas"].pop(balde(tarefa), None))


def registrar_restantes(tarefa: str, restantes: int) -> None:
    """Itens que faltam na tarefa — alimenta a PROJEÇÃO do painel (custo real por item × restantes)."""
    _mutar(lambda d: _b(d, balde(tarefa)).__setitem__("restantes", int(restantes)))


# ── memória: mesma entrada não se paga duas vezes ──────────────────────────────────────────────────────
def _memo_con() -> sqlite3.Connection:
    con = sqlite3.connect(_dados() / "claude_api_memo.db", timeout=15)
    con.execute("CREATE TABLE IF NOT EXISTS memo(chave TEXT PRIMARY KEY, modelo TEXT, texto TEXT, em TEXT)")
    return con


def chave_memo(modelo: str, sistema: str, prompt: str, formato=None) -> str:
    bruto = json.dumps([modelo, sistema, prompt, formato], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def _memo_ler(chave: str) -> str | None:
    try:
        con = _memo_con()
        try:
            r = con.execute("SELECT texto FROM memo WHERE chave=?", (chave,)).fetchone()
        finally:
            con.close()
        return r[0] if r else None
    except sqlite3.Error:
        return None


def _memo_gravar(chave: str, modelo: str, texto: str) -> None:
    try:
        con = _memo_con()
        try:
            con.execute("INSERT OR REPLACE INTO memo VALUES(?,?,?,?)", (chave, modelo, texto, _agora()))
            con.commit()
        finally:
            con.close()
    except sqlite3.Error as e:
        logger.debug("claude_api: memória não gravada (%s)", type(e).__name__)


# ── cliente e parâmetros ──────────────────────────────────────────────────────────────────────────────
def _cliente(timeout: float):
    import anthropic
    return anthropic.Anthropic(api_key=_chave(), max_retries=2, timeout=timeout)


def _texto(resp) -> str:
    return "".join(getattr(b, "text", "") or "" for b in (resp.content or []) if getattr(b, "type", "") == "text")


def parametros(modelo: str, sistema: str, prompt: str, max_tokens: int, effort: str, formato: dict | None = None) -> dict:
    """Parte FIXA (sistema) com marca de cache; item variável no fim; JSON estruturado quando há `formato`."""
    oc = {"effort": effort}
    if formato:
        oc["format"] = {"type": "json_schema", "schema": formato}
    p = {"model": modelo, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}],
         "output_config": oc}
    if sistema:
        p["system"] = [{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}]
    return p


def _falhas():
    try:
        import anthropic
        return (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, anthropic.APIError)
    except ImportError:
        return (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError)


def pensar_api(tarefa: str, prompt: str, *, sistema: str = "", modelo: str | None = None, max_tokens: int = 4000,
               effort: str = "medium", formato: dict | None = None, timeout: float = 180.0, cliente=None):
    """Chamada SÍNCRONA (alguém espera a resposta), dentro do teto. `(texto, modelo, usd)` ou `None` com motivo
    em `ultimo_motivo`. Nunca levanta. Para volume, use `enviar_lote`."""
    global ultimo_motivo
    ultimo_motivo = ""
    modelo = _sem_opus(modelo or modelo_para(tarefa))
    if cliente is None and os.environ.get("PYTEST_CURRENT_TEST"):
        ultimo_motivo = "API: sob pytest sem cliente dublê"
        return None
    if cliente is None and not disponivel():
        ultimo_motivo = "API: sem chave (ou JFN_CLAUDE_API=0)"
        return None
    memo = chave_memo(modelo, sistema, prompt, formato)
    if (ja := _memo_ler(memo)) is not None:
        return ja, modelo, 0.0
    falhas = _falhas()
    est, reservou = 0.0, False
    try:
        cli = cliente or _cliente(timeout)
        params = parametros(modelo, sistema, prompt, max_tokens, effort, formato)
        contagem = cli.messages.count_tokens(**{k: v for k, v in params.items() if k != "max_tokens"})
        est = estimativa(modelo, int(contagem.input_tokens), max_tokens)
        recusa = _reservar(tarefa, est)
        if recusa:
            ultimo_motivo = recusa
            return None
        reservou = True
        if modelo in _COM_FALLBACK:
            resp = cli.beta.messages.create(**params, betas=[_BETA_FALLBACK], fallbacks="default")
        else:
            resp = cli.messages.create(**params)
        quem = getattr(resp, "model", None) or modelo
        usd = max(custo(modelo, resp.usage), custo(quem, resp.usage))  # fallback do servidor: o mais caro
        if resp.stop_reason == "refusal":
            cat = getattr(getattr(resp, "stop_details", None), "category", None)
            _liquidar(tarefa, modelo, est, usd, erro=f"recusa ({cat or 'sem categoria'})")
            ultimo_motivo = f"API: recusa do modelo ({cat or 'sem categoria'})"
            return None
        texto = _texto(resp)
        if resp.stop_reason == "max_tokens" or not texto.strip():
            _liquidar(tarefa, modelo, est, usd, erro=f"resposta inválida ({resp.stop_reason})")
            ultimo_motivo = f"API: resposta {'cortada no max_tokens' if resp.stop_reason == 'max_tokens' else 'vazia'}"
            return None
        _liquidar(tarefa, quem, est, usd, resp.usage, itens=1)
        _memo_gravar(memo, quem, texto)
        return texto, quem, usd
    except falhas as e:
        if reservou:
            _liquidar(tarefa, modelo, est, 0.0, erro=type(e).__name__)
        ultimo_motivo = f"API: falhou ({type(e).__name__})"     # nunca a mensagem: pode ecoar cabeçalho/chave
        logger.warning("claude_api: %s", ultimo_motivo)
        return None


# ── Batch API (50%) — o padrão para volume ───────────────────────────────────────────────────────────
def _tokens_aprox(texto: str) -> int:
    # CONSERVADOR sem gastar count_tokens por item: ~2,5 caracteres/token (português fica perto de 3,5–4)
    return math.ceil(len(texto or "") / 2.5) + 50


def enviar_lote(tarefa: str, itens: list[tuple[str, str]], *, sistema: str = "", modelo: str | None = None,
                max_tokens: int = 2000, effort: str = "low", formato: dict | None = None, n_decisoes: int | None = None,
                cliente=None) -> str | None:
    """Envia `itens` [(custom_id, prompt)] como UM lote (cada prompt pode carregar várias decisões; informe o
    total em `n_decisoes` para a projeção). Reserva o custo estimado do lote todo. Devolve o id ou None."""
    global ultimo_motivo
    ultimo_motivo = ""
    modelo = _sem_opus(modelo or modelo_para(tarefa))
    if not itens:
        return None
    if cliente is None and (os.environ.get("PYTEST_CURRENT_TEST") or not disponivel()):
        ultimo_motivo = "API: indisponível para lote"
        return None
    est = sum(estimativa(modelo, _tokens_aprox(sistema) + _tokens_aprox(p), max_tokens, lote=True) for _, p in itens)
    recusa = _reservar(tarefa, est)
    if recusa:
        ultimo_motivo = recusa
        return None
    try:
        cli = cliente or _cliente(300.0)
        lote = cli.messages.batches.create(requests=[
            {"custom_id": cid, "params": parametros(modelo, sistema, p, max_tokens, effort, formato)} for cid, p in itens])
    except _falhas() as e:
        _liquidar(tarefa, modelo, est, 0.0, erro=f"lote não enviado ({type(e).__name__})")
        ultimo_motivo = f"API: lote não enviado ({type(e).__name__})"
        return None
    _mutar(lambda d: d["lotes"].__setitem__(lote.id, {
        "tarefa": tarefa, "modelo": modelo, "reservado": est, "n": len(itens),
        "decisoes": n_decisoes or len(itens), "em": _agora()}))
    return lote.id


def colher_lote(lote_id: str, *, cliente=None) -> dict | None:
    """Lote terminado: {custom_id: texto|None} (recusa, corte e erro = None), custo real lançado, reserva
    liberada. Em curso ou desconhecido: None."""
    info = ler_gasto()["lotes"].get(lote_id)
    if not info:
        return None
    cli = cliente or _cliente(300.0)
    if cli.messages.batches.retrieve(lote_id).processing_status != "ended":
        return None
    saida, usd = {}, 0.0
    soma = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    for r in cli.messages.batches.results(lote_id):
        if r.result.type != "succeeded":
            saida[r.custom_id] = None
            continue
        msg = r.result.message
        usd += custo(info["modelo"], msg.usage, lote=True)
        for k in soma:
            soma[k] += _uso(msg.usage, k)
        texto = _texto(msg)
        saida[r.custom_id] = texto if (msg.stop_reason not in ("refusal", "max_tokens") and texto.strip()) else None
    _liquidar(info["tarefa"], info["modelo"], info["reservado"], usd, soma, itens=int(info.get("decisoes") or 0))
    _mutar(lambda d: d["lotes"].pop(lote_id, None))
    return saida


def lotes_em_curso() -> dict:
    return dict(ler_gasto()["lotes"])


# ── painel ────────────────────────────────────────────────────────────────────────────────────────────
def painel() -> dict:
    """Gasto acumulado, o que resta, por balde com projeção (custo real por item × itens restantes)."""
    d = ler_gasto()
    baldes = {}
    for nome, teto in BALDES_USD.items():
        b = d["por_balde"].get(nome) or {"usd": 0.0, "reservado": 0.0, "itens": 0, "restantes": None}
        por_item = (b["usd"] / b["itens"]) if b.get("itens") else None
        proj = round(b["usd"] + por_item * b["restantes"], 2) if (por_item is not None and b.get("restantes") is not None) else None
        baldes[nome] = {"teto_usd": teto, "gasto_usd": round(b["usd"], 4), "reservado_usd": round(b["reservado"], 4),
                        "itens": b.get("itens", 0), "usd_por_item": round(por_item, 6) if por_item is not None else None,
                        "restantes": b.get("restantes"), "projecao_total_usd": proj,
                        "projecao_cabe": (proj <= teto) if proj is not None else None,
                        "pausada": d["pausadas"].get(nome)}
    cache = {m: {"cache_lido": v.get("cache_lido", 0), "entrada": v.get("entrada", 0)} for m, v in d["por_modelo"].items()}
    return {"disponivel": disponivel(), "teto_usd": teto_usd(), "limite_efetivo_usd": limite_efetivo(),
            "gasto_usd": round(d["total_usd"], 4), "reservado_usd": round(d["reservado_usd"], 4),
            "resta_usd": round(max(0.0, limite_efetivo() - d["total_usd"] - d["reservado_usd"]), 4),
            "chamadas": d["chamadas"], "recusadas_teto": d["recusadas_teto"], "baldes": baldes,
            "por_tarefa": d["por_tarefa"], "por_modelo": d["por_modelo"], "cache": cache,
            "lotes_em_curso": len(d["lotes"]), "ultima": d["ultima"], "ultimo_erro": d["ultimo_erro"],
            "desde": d.get("desde"), "atualizado": time.strftime("%Y-%m-%dT%H:%M:%S")}
