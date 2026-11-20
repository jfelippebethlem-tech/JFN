# -*- coding: utf-8 -*-
"""comotor — o Claude como CO-MOTOR das camadas de juízo, ao lado da cascata atual.

Desenho pedido pelo dono (13/11/2026): "o claude vai ser o CO-MOTOR de tudo. os outros continuam também e
depois se cruzam pra ir treinando os outros modelos e ajustando comparativamente."

`juizo(tarefa)` devolve um `gerar(prompt, sistema="", timeout=45.0, json_saida=True)` com a MESMA assinatura de
`direcionamento_cerebro.gerar_sync` — os chamadores trocam uma linha. A cada chamada:

  1. o Claude (`claude_motor.pensar`, dentro do orçamento) e a cascata atual rodam EM PARALELO sobre a mesma
     entrada; sem cota do Claude, só a cascata — e o cruzamento registra que o Claude não estava;
  2. cada resposta é NORMALIZADA pela tarefa (⚪ 0 · 🟡 1 · 🔴 2) e os dois vereditos vão lado a lado para
     `data/cruzamento_motores.db` (`llm/cruzamento`), com o modelo de cada um;
  3. o texto devolvido ao chamador é o do Claude quando houver (o do outro fica no cruzamento, e em
     `ultima_chamada()`); a proveniência vai para `direcionamento_cerebro.ultimo_provedor/ultimo_modelo`,
     que os chamadores já gravam na coluna `modelo`;
  4. "treino" sem fine-tuning: metade das chamadas da cascata (sorteio, `JFN_COMOTOR_FEWSHOT_FRACAO`)
     recebe até 3 exemplos onde o Claude e a cascata divergiram, com o veredito do Claude como referência.
     A metade sem exemplos é o grupo de controle — o cruzamento mede o acordo nos dois braços, porque mudar
     prompt sem A/B já derrubou recall de 3/6 para 0/6 nesta casa;
  5. o placar por provedor (`cruzamento.preferido`) faz o co-motor chamar PRIMEIRO o provedor que mais
     concorda com o Claude naquela tarefa — só com amostra mínima e margem; senão, a cascata como sempre.
     A cascata central (`_gerar_default`, risco CRÍTICO no GitNexus: 688 dependentes) NÃO foi tocada.

Tarefa sem normalizador (texto livre, ex.: análise discursiva) não tem o que cruzar: aí a cascata só roda
quando o Claude não responde — gastar duas IAs para comparar prosa sem régua seria custo sem medição.
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from compliance_agent.llm import claude_api, claude_motor, contingencia, cruzamento
from compliance_agent.llm.cruzamento import Lado
from compliance_agent.llm.normalizadores import NORMALIZADORES

logger = logging.getLogger(__name__)

try:
    import httpx
    _HTTP: tuple = (httpx.HTTPError,)
except ImportError:  # sem httpx não há provedor HTTP a falhar
    _HTTP = ()
# o que um provedor/banco pode levantar: RespostaProvedorErro é RuntimeError; prazo do futuro é TimeoutError (OSError)
_FALHAS = (RuntimeError, OSError, ValueError, TypeError, KeyError, sqlite3.Error) + _HTTP

_ultima: dict = {}


def ultima_chamada() -> dict:
    """{"par", "exibido", "outro", "divergencia", "grave", "conferencia_pendente"} da última chamada do co-motor
    neste processo. `conferencia_pendente` = saiu sem o Claude da assinatura e está na fila do Opus."""
    return dict(_ultima)


# ── a cascata, com few-shot e preferência por placar ──────────────────────────────────────────────────
def _fracao_fewshot() -> float:
    try:
        return float(os.environ.get("JFN_COMOTOR_FEWSHOT_FRACAO", "0.5"))
    except ValueError:
        return 0.5


def _com_exemplos(prompt: str, exemplos: list[dict]) -> str:
    blocos = "\n\n".join(f"EXEMPLO {i + 1}\nENTRADA (resumo): {e['entrada']}\nVEREDITO DE REFERÊNCIA: {e['referencia']}"
                         for i, e in enumerate(exemplos))
    return ("Casos anteriores parecidos, com o veredito de um revisor mais experiente. Use-os como calibragem do "
            "critério, não como resposta: julgue o caso atual pelos fatos dele.\n\n" + blocos
            + "\n\n=== CASO ATUAL ===\n" + prompt)


def _chamar_provedor(provedor: str, prompt: str, sistema: str) -> str | None:
    """Chamada DIRETA ao provedor preferido pelo placar (sem passar pela ordem fixa da cascata)."""
    from compliance_agent.llm import free_llm as F
    if provedor == "groq" and F.groq_available():
        return F.groq_chat(prompt, system=sistema, smart=True)
    if provedor == "openrouter" and F.openrouter_available():
        return F.openrouter_chat(prompt, system=sistema, smart=True)
    if provedor in getattr(F, "_EXTRA", {}) and F.extra_available(provedor):
        return F.extra_chat(provedor, prompt, system=sistema)
    return None


def juizo(tarefa: str, *, modelo: str = claude_motor.MODELO_VOLUME, cascata: Callable | None = None,
          normalizar: Callable | None = None, pensar: Callable | None = None, sorteio: Callable | None = None,
          espera: float | None = None, timeout_claude: float = 180.0, conferencia: bool = True):
    """Fábrica do `gerar` co-motor de uma tarefa. `cascata`/`pensar`/`sorteio` são injetáveis para teste.

    `espera` = quanto aguardar a trava do único `claude` da VM (produto interativo: curto, ex. 15 s — passou
    disso, a resposta sai da cascata em vez de deixar o dono esperando). `timeout_claude` = prazo da chamada.

    `conferencia` (14/11/2026 — "nunca ficar sem produzir; o que for feito por eles tem conferência sempre pelo
    claude opus"): resposta devolvida SEM o Claude da assinatura (cascata, ou Claude barato `@api`) entra na fila
    `llm/conferencia_opus`; entrada que o Opus já conferiu volta com a resposta DELE, sem nova chamada. Desligue
    só em quem tem fila própria de Opus (triagem) ou descarta o veredito sem Claude (juiz de qualidade).
    """
    normalizar = normalizar or NORMALIZADORES.get(tarefa)
    _pensar = pensar or claude_motor.pensar

    def pensar(t, p, **kw):
        extra = {"timeout": timeout_claude} | ({"espera": espera} if espera is not None else {})
        return _pensar(t, p, **kw, **extra)
    sorteio = sorteio or random.random

    def _cascata(prompt, sistema, timeout, json_saida) -> tuple[str, str, bool]:
        fs = []
        if normalizar is not None and sorteio() < _fracao_fewshot():
            try:
                fs = cruzamento.exemplos(tarefa, k=3)
            except _FALHAS as e:  # sem exemplos a cascata segue igual
                logger.debug("comotor: exemplos indisponíveis (%s)", e)
        p = _com_exemplos(prompt, fs) if fs else prompt
        if cascata is None and normalizar is not None:
            try:
                pref = cruzamento.preferido(tarefa)
                if pref:
                    r = _chamar_provedor(pref, p, sistema)
                    if r and r.strip():
                        return r, pref, bool(fs)
            except _FALHAS as e:  # preferência é otimização; a cascata é o caminho garantido
                logger.debug("comotor: provedor preferido falhou (%s)", e)
        if cascata is not None:
            return cascata(p, sistema, timeout, json_saida), "cascata", bool(fs)
        return contingencia.gerar_cascata(p, sistema, timeout, json_saida), contingencia.modelo_da_cascata(), bool(fs)

    def gerar(prompt: str, sistema: str = "", timeout: float = 45.0, json_saida: bool = True, *,
              item: str | None = None) -> str:
        sufixo = "\n\nResponda APENAS com o JSON pedido, sem texto fora dele." if json_saida else ""
        item = item or hashlib.sha1((prompt or "").encode("utf-8", "replace")).hexdigest()[:16]
        if conferencia:
            try:
                from compliance_agent.llm import conferencia_opus
                ja = conferencia_opus.resposta_conferida(tarefa, prompt + sufixo, sistema)
            except _FALHAS + (ImportError,) as e:  # fila ilegível: segue o caminho normal
                logger.debug("comotor: fila de conferência indisponível (%s)", e)
                ja = None
            if ja:
                _ultima.clear()
                _ultima.update(par=None, divergencia=None, grave=None, exibido=f"claude:{ja[1]} (conferência)",
                               outro=None, conferencia_pendente=False)
                try:
                    from compliance_agent import direcionamento_cerebro as dc
                    dc.ultimo_provedor, dc.ultimo_modelo = "claude", ja[1]
                except ImportError:
                    logger.debug("comotor: direcionamento_cerebro indisponível — proveniência só em ultima_chamada()")
                return ja[0]
        t0 = time.monotonic()
        r_claude = r_casc = None
        erro_casc: Exception | None = None
        lat_c = lat_o = None
        if normalizar is None:
            r_claude = pensar(tarefa, prompt + sufixo, modelo=modelo, sistema=sistema)
            lat_c = int((time.monotonic() - t0) * 1000)
            if r_claude is None:
                t1 = time.monotonic()
                try:
                    r_casc = _cascata(prompt, sistema, timeout, json_saida)
                except _FALHAS as e:  # cascata fora: devolve-se o erro só se o Claude também faltar
                    erro_casc = e
                lat_o = int((time.monotonic() - t1) * 1000)
        else:
            fim: dict = {}

            def _medido(nome, fn, *a, **k):
                try:
                    return fn(*a, **k)
                finally:
                    fim[nome] = int((time.monotonic() - t0) * 1000)

            with ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"comotor-{tarefa}") as ex:
                fc = ex.submit(_medido, "c", pensar, tarefa, prompt + sufixo, modelo=modelo, sistema=sistema)
                fo = ex.submit(_medido, "o", _cascata, prompt, sistema, timeout, json_saida)
                try:
                    r_casc = fo.result()
                except _FALHAS as e:  # cascata fora: o Claude ainda pode responder
                    erro_casc = e
                r_claude = fc.result()
            lat_c, lat_o = fim.get("c"), fim.get("o")

        lado_c = lado_o = None
        if r_claude is not None:
            v, n, c = normalizar(r_claude.texto) if normalizar else (None, None, None)
            lado_c = Lado("claude", r_claude.modelo, v, n, c, lat_c)
        elif normalizar is not None:
            lado_c = Lado("claude", "indisponivel", f"sem_claude: {claude_motor.ultimo_motivo[:50]}", None)
        if r_casc is not None:
            txt, mod, fs = r_casc
            v, n, c = normalizar(txt) if normalizar else (None, None, None)
            lado_o = Lado("cascata", mod, v, n, c, lat_o, fs)
        try:
            cz = cruzamento.cruzar(tarefa, item, lado_c, lado_o, entrada_resumo=prompt[:600])
        except _FALHAS as e:  # registrar o cruzamento nunca derruba o juízo
            logger.warning("comotor: cruzamento não gravado (%s)", type(e).__name__)
            cz = {"par": None, "divergencia": None, "grave": None}

        _ultima.clear()
        _ultima.update(par=cz["par"], divergencia=cz["divergencia"], grave=cz["grave"],
                       exibido=(f"claude:{r_claude.modelo}" if r_claude else (r_casc[1] if r_casc else None)),
                       outro=(r_casc[1] if (r_claude and r_casc) else None), conferencia_pendente=False)
        # produzido sem o Claude da assinatura (cascata sozinha, ou Claude barato pela API) ⇒ o Opus confere depois
        sem_assinatura = (r_claude is None and r_casc is not None) or (
            r_claude is not None and claude_api.pela_api(r_claude.modelo))
        if conferencia and sem_assinatura:
            try:
                from compliance_agent.llm import conferencia_opus
                lado = lado_c if r_claude is not None else lado_o
                _ultima["conferencia_pendente"] = conferencia_opus.enfileirar(
                    tarefa, item, prompt + sufixo, sistema=sistema, motor=_ultima["exibido"],
                    resposta=(r_claude.texto if r_claude is not None else r_casc[0]),
                    veredito=lado.veredito, nivel=lado.nivel,
                    motivo=("Claude barato pela API (assinatura indisponível)" if r_claude is not None
                            else claude_motor.ultimo_motivo))
            except _FALHAS + (ImportError,) as e:  # a fila nunca derruba o juízo; sem marca, o item fica sem VERIFICADO
                logger.warning("comotor: resultado sem Claude não entrou na fila de conferência (%s)", type(e).__name__)
        try:
            from compliance_agent import direcionamento_cerebro as dc
            if r_claude is not None:
                dc.ultimo_provedor, dc.ultimo_modelo = "claude", r_claude.modelo
        except ImportError:
            logger.debug("comotor: direcionamento_cerebro indisponível — proveniência só em ultima_chamada()")
        if r_claude is not None:
            return r_claude.texto
        if r_casc is not None:
            return r_casc[0]
        raise RuntimeError(f"co-motor {tarefa}: Claude indisponível ({claude_motor.ultimo_motivo[:60]}) e cascata "
                           f"falhou ({type(erro_casc).__name__ if erro_casc else 'sem resposta'})")

    return gerar


def proveniencia(padrao: str = "desconhecido") -> str:
    """Rótulo para a coluna `modelo`: 'claude:<id> (+gemini:<m>)' quando os dois responderam."""
    u = _ultima
    if not u.get("exibido"):
        return padrao
    return u["exibido"] + (f" (+{u['outro']})" if u.get("outro") else "")
