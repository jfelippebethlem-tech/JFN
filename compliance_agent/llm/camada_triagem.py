# -*- coding: utf-8 -*-
"""camada_triagem — a IA que roda 24/7 sobre o que a camada determinística marcou.

Responde ao pedido *"queremos que as outras ias sejam usadas no fallback pra rodar e identificar
irregularidades 24/7, mas nao sei como te pedir isso e montar"*. A forma concreta é esta.

ARQUITETURA EM TRÊS CAMADAS — e o ponto central é que a IA é a MENOR delas:

  1. **Determinística** (`varredura_orgaos`, os 31 detectores). Regra e limiar em código, sem
     cota e sem custo. É onde o volume tem de morrer.
  2. **Triagem — este módulo.** Só o que a camada 1 marcou como avaliável-mas-subjetivo chega
     aqui, e só em RUBRICA FECHADA: o modelo escolhe entre 3-4 níveis nomeados e cita o trecho.
     Nunca produz número, nunca produz grau final. Usa exclusivamente a cadeia GRÁTIS.
  3. **Parecer** (Gemini/Cerebras, já existente). Só o topo confirmado pelas camadas 1 e 2.

POR QUE RUBRICA FECHADA. `avaliar_rubrica` (spec §1.3) descarta resposta sem citação literal e
recusa nível fora da escala. Então o pior caso de um modelo fraco não é erro — é `nao_avaliavel`,
que o framework já trata. Isso é o que torna seguro usar IA grátis em volume.

GUARD-RAILS (regra do dono: *"preferir guard-rail real (kill-switch + cap) a cota do free tier"*):

  · **kill-switch em arquivo** — `data/.pause_llm_triagem` existe ⇒ para na hora, sem deploy;
  · **teto diário de chamadas** — `JFN_TRIAGEM_MAX_DIA` (padrão 2.000), contado em disco e
    reiniciado por data. Estourou, devolve vazio e o detector degrada honesto;
  · **só cadeia grátis** — `best_free_chat` percorre Ollama/Groq/OpenRouter/Cerebras/Gemini/
    Cloudflare com cooldown por provedor. Nada aqui usa chave paga por padrão;
  · **uso registrado** — `data/triagem_uso.json` guarda contagem por dia e por desfecho, para a
    conta ser auditável em vez de estimada.

Falha SEMPRE degrada para string vazia: o detector responde `nao_avaliavel`, que é a resposta
honesta, e a varredura continua.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
from datetime import date
from typing import Callable

logger = logging.getLogger(__name__)

PAUSE = pathlib.Path(os.environ.get("JFN_TRIAGEM_PAUSE", "data/.pause_llm_triagem"))
USO = pathlib.Path(os.environ.get("JFN_TRIAGEM_USO", "data/triagem_uso.json"))
MAX_DIA = int(os.environ.get("JFN_TRIAGEM_MAX_DIA", "2000"))


def _hoje() -> str:
    return date.today().isoformat()


def ler_uso() -> dict:
    """Contadores do dia corrente. Vira a página sozinho na virada da data."""
    try:
        dados = json.loads(USO.read_text())
    except (OSError, json.JSONDecodeError):
        dados = {}
    if dados.get("data") != _hoje():
        dados = {"data": _hoje(), "chamadas": 0, "ok": 0, "vazias": 0, "erros": 0,
                 "bloqueadas_teto": 0, "bloqueadas_pause": 0}
    return dados


def _gravar_uso(dados: dict) -> None:
    try:
        USO.parent.mkdir(parents=True, exist_ok=True)
        USO.write_text(json.dumps(dados, ensure_ascii=False))
    except OSError as e:  # noqa: BLE001 — registro de uso não pode derrubar a varredura
        logger.warning("triagem: não consegui gravar o uso (%s)", e)


def pausado() -> bool:
    """Kill-switch de arquivo: criar `data/.pause_llm_triagem` para a camada 2 na hora."""
    return PAUSE.exists()


def orcamento_restante() -> int:
    return max(0, MAX_DIA - int(ler_uso().get("chamadas", 0)))


def _com_moldura(sistema: str) -> str:
    """Prefixa a moldura jurídica brasileira ao `system` que o detector passou.

    Sem isto, a camada 2 do 24/7 julgava licitação brasileira com o que quer que o modelo
    tivesse aprendido na internet: errava o dispositivo, citava súmula inexistente e tratava a
    Lei 8.666/1993 como vigente para contratação nova. O ponto único é aqui porque TODO detector
    passa por `gerar(prompt, sistema)` — corrigir em cada card seria esquecer metade.

    Usa a moldura COMPACTA (sem o catálogo dos 42 vícios): a rubrica já vem fechada pelo
    detector, que dita os níveis válidos. O que o modelo precisa é do regime vigente e dos
    deveres de honestidade — cerca de 1.100 tokens em vez de 3.200, o que importa quando a
    chamada é curta e o modelo é pequeno.
    """
    try:
        from compliance_agent.knowledge.moldura_juridica import moldura
        return f"{moldura(com_catalogo=False)}\n\n{sistema}" if sistema else moldura(
            com_catalogo=False)
    except Exception as e:  # noqa: BLE001 — sem a moldura a triagem piora, mas não pode parar
        logger.warning("moldura jurídica indisponível (%s) — triagem segue sem ela", str(e)[:80])
        return sistema


def gerar_triagem(*, max_dia: int | None = None) -> Callable[[str, str], str]:
    """Devolve o callable `gerar(prompt, sistema) -> str` que os detectores esperam.

    Uso:
        from compliance_agent.llm.camada_triagem import gerar_triagem
        varrer_todas(con, gerar=gerar_triagem(), con_achados=achados)

    Sem chamadas disponíveis (pausa ou teto), devolve "" — e o detector marca `nao_avaliavel`
    com o motivo, em vez de fingir juízo.
    """
    teto = MAX_DIA if max_dia is None else max_dia

    def gerar(prompt: str, sistema: str = "") -> str:
        dados = ler_uso()
        sistema = _com_moldura(sistema)

        if pausado():
            dados["bloqueadas_pause"] = dados.get("bloqueadas_pause", 0) + 1
            _gravar_uso(dados)
            return ""
        if dados.get("chamadas", 0) >= teto:
            dados["bloqueadas_teto"] = dados.get("bloqueadas_teto", 0) + 1
            _gravar_uso(dados)
            logger.warning("triagem: teto diário de %s chamadas atingido — degradando para "
                           "nao_avaliavel até a virada do dia", teto)
            return ""

        dados["chamadas"] = dados.get("chamadas", 0) + 1
        try:
            from compliance_agent.llm.free_llm import best_free_chat
            # `smart=False`: rubrica fechada não precisa do modelo grande — e o pequeno é o que
            # é ilimitado. Qualidade aqui vem da RUBRICA, não do tamanho do modelo.
            resp = best_free_chat(prompt, system=sistema, smart=False, fallback="")
        except Exception as e:  # noqa: BLE001 — cadeia inteira fora do ar: degrada honesto
            dados["erros"] = dados.get("erros", 0) + 1
            _gravar_uso(dados)
            logger.warning("triagem: cadeia grátis indisponível (%s)", str(e)[:80])
            return ""

        if (resp or "").strip():
            dados["ok"] = dados.get("ok", 0) + 1
        else:
            dados["vazias"] = dados.get("vazias", 0) + 1
        _gravar_uso(dados)
        return resp or ""

    return gerar


def status() -> dict:
    """Panorama para o operador: quanto já se gastou hoje e o que está bloqueando."""
    dados = ler_uso()
    return {
        "data": dados.get("data"),
        "chamadas_hoje": dados.get("chamadas", 0),
        "teto_dia": MAX_DIA,
        "restante": orcamento_restante(),
        "ok": dados.get("ok", 0),
        "vazias": dados.get("vazias", 0),
        "erros": dados.get("erros", 0),
        "bloqueadas_teto": dados.get("bloqueadas_teto", 0),
        "bloqueadas_pause": dados.get("bloqueadas_pause", 0),
        "pausado": pausado(),
        "arquivo_pause": str(PAUSE),
    }
