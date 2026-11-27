# -*- coding: utf-8 -*-
"""orcamento — o orçamento DIÁRIO do Claude da assinatura (chamadas e segundos, total e por tarefa).

Decisão do dono, não detalhe do CLI: os tetos mudam quando o dono libera ou aperta a cota; o motor (`claude_motor`)
reserva e conta, a contingência (`contingencia`) lê a fração gasta para reservar os 10% finais ao Opus, e o painel
mostra. Arquivo `data/claude_motor_uso.json` (zera na virada do dia; o último erro sobrevive). Tetos por env
(`JFN_CLAUDE_MAX_CHAMADAS_DIA`, `JFN_CLAUDE_MAX_SEGUNDOS_DIA`, `JFN_CLAUDE_MAX_<TAREFA>`).
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from compliance_agent.llm import arquivo_estado as arq

TETO_CHAMADAS_DIA = 600       # 15/11/2026: dono "pode rodar o claude nas perícias de dia também" (era 320; 120 antes de 14/11)
TETO_SEGUNDOS_DIA = 28800     # era 7200 → 14400; 21/11/2026 dono "a todo vapor, principalmente as perícias" (o ritmo SEMANAL segue sendo quem segura a conta)
TETO_TAREFA_PADRAO = 10
# Por tarefa (chamadas/dia). Soma > total de propósito: o total é quem trava; a tarefa só impede que uma
# fila sozinha coma o dia. Ver o relatório de 13/11/2026 para a conta.
TETOS_TAREFA = {
    "canario": 3,
    "pericia_execucao": 100,     # 30→100 em 15/11/2026: dono "pode rodar o claude nas perícias de dia também"
    "pericia_fornecedor": 15,
    "parecer_juridico": 10,
    "triagem_alertas": 40,
    "camada_subjetiva": 20,
    "investigacao_risco": 10,
    "verificacao_opus": 200,     # todo 🔴/🟡 da triagem relido pelo Opus; 30→200 em 14/11/2026 a pedido do dono
    "juiz_qualidade": 12,        # juiz subjetivo das regras de qualidade (só assinatura; amostra por valor/risco)
    "conferencia_opus": 240,     # 60→240 em 21/11/2026 (4.747 na fila, entram ~590/dia); Opus relê o que os outros modelos produziram em contingência (llm/conferencia_opus)
    "pericia_integral": 200,     # 15/11/2026: perícia integral por processo (Opus, todos os eixos numa chamada)
    "conferencia_e12": 60,       # 27/11/2026: E12 nativo (Opus) caía no padrão de 10/dia por nó; 60 = a capacidade medida
                                 # da conferência (plano §17: entrada ≤ ~60/dia) — o ritmo semanal segura o total
    "leitura_integral": 400,     # 27/11/2026: E8 (fatos, Haiku) caía no padrão de 10/dia por nó e a etapa 2 da religação
                                 # travou em SemCota (VM-2 e it-campo); dono: «pode usar tudo aê preciso» — o ritmo
                                 # SEMANAL segue sendo quem segura a conta
}


def arquivo() -> Path:
    return arq.dados() / "claude_motor_uso.json"


def int_env(nome: str, padrao: int) -> int:
    try:
        return int(os.environ.get(nome, "") or padrao)
    except ValueError:
        return padrao


def teto_total() -> int:
    return int_env("JFN_CLAUDE_MAX_CHAMADAS_DIA", TETO_CHAMADAS_DIA)


def teto_segundos() -> int:
    return int_env("JFN_CLAUDE_MAX_SEGUNDOS_DIA", TETO_SEGUNDOS_DIA)


def teto_tarefa(tarefa: str) -> int:
    return int_env(f"JFN_CLAUDE_MAX_{tarefa.upper()}", TETOS_TAREFA.get(tarefa, TETO_TAREFA_PADRAO))


def _hoje() -> str:
    return date.today().isoformat()


def _uso_vazio() -> dict:
    return {"data": _hoje(), "total": {"chamadas": 0, "segundos": 0.0, "ok": 0, "erros": 0, "bloqueadas": 0},
            "tarefas": {}, "ultimo_erro": None, "ultima_ok": None}


def ler_uso() -> dict:
    d = arq.ler_json(arquivo())
    if d.get("data") != _hoje():
        anterior = d.get("ultimo_erro")
        d = _uso_vazio()
        d["ultimo_erro"] = anterior      # o último erro sobrevive à virada do dia (o painel precisa dele)
    return d


def mutar_uso(fn) -> None:
    arq.mutar_json(arquivo(), fn, espera=10.0, ler=lambda _c: ler_uso())


def tarefa_de(d: dict, tarefa: str) -> dict:
    return d["tarefas"].setdefault(tarefa, {"chamadas": 0, "segundos": 0.0, "ok": 0, "erros": 0, "bloqueadas": 0})


def motivo_teto(d: dict, tarefa: str) -> str | None:
    t = d["total"]
    if t["chamadas"] >= teto_total():
        return f"teto diário total ({teto_total()} chamadas)"
    if t["segundos"] >= teto_segundos():
        return f"teto diário de tempo ({teto_segundos()} s)"
    if tarefa_de(d, tarefa)["chamadas"] >= teto_tarefa(tarefa):
        return f"teto diário da tarefa {tarefa} ({teto_tarefa(tarefa)} chamadas)"
    return None
