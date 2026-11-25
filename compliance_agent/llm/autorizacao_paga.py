# -*- coding: utf-8 -*-
"""autorizacao_paga — crédito de API PAGA só com autorização EXPLÍCITA do dono, por chamada ou por lote.

Regra do dono (24/11/2026): "créditos de API só quando eu autorizar". Vale para TODA camada paga (API da Anthropic,
OpenRouter pago, Gemini pago, …), inclusive piloto pequeno. O teto mensal (US$ 100 do gateway) e os tetos de cada
porta continuam valendo, mas NÃO autorizam gasto sozinhos: sem autorização válida a porta paga recusa com o motivo
`RECUSA` e o item fica NÃO JULGADO — pendente para a assinatura.

COMO O DONO AUTORIZA. Uma entrada no livro `config/llm_autorizacoes_pagas.yaml` (`JFN_LLM_AUTORIZACOES` desvia o
arquivo nos testes) — só o dono acrescenta; o commit que a acrescenta cita a mensagem dele — e o lote que vai gastar
roda com `JFN_LLM_AUTORIZACAO_PAGA=<id>` (ou o chamador do gateway passa `autorizacao_paga=<id>`). A entrada precisa
de TODOS os campos:

    - id: AUT-20261201-01            # único no livro
      quem: dono                     # quem autorizou
      quando: 2026-12-01T21:00:00-03:00   # quando autorizou (com fuso) — antes de agora
      ate: 2026-12-02T21:00:00-03:00      # validade (com fuso) — depois de agora
      registro: "chat do Claude Code, 01/12/2026 21h"   # onde está a autorização (mensagem, ata)
      tarefas: [leitura_integral]    # tarefas cobertas (lista explícita; nada de curinga)
      provedores: [api_anthropic]    # portas pagas cobertas
      teto_usd: 2.00                 # teto DESTA autorização (o gateway soma o gasto do trace por id)
      motivo: "piloto li-2 com 20 processos"

Livro ausente, ilegível, id inexistente/repetido, campo faltando, fora da validade, tarefa ou provedor fora da lista
⇒ recusa (falha FECHADA), com o motivo dito. Nada aqui lê ou grava chave/senha.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

RECUSA = "API paga não autorizada pelo dono"
ENV_ID = "JFN_LLM_AUTORIZACAO_PAGA"
ENV_ARQ = "JFN_LLM_AUTORIZACOES"
CAMPOS = ("id", "quem", "quando", "ate", "registro", "tarefas", "provedores", "teto_usd", "motivo")
_REPO = Path(__file__).resolve().parents[2]


def caminho() -> Path:
    return Path(os.environ.get(ENV_ARQ) or (_REPO / "config" / "llm_autorizacoes_pagas.yaml"))


def id_do_ambiente() -> str | None:
    v = (os.environ.get(ENV_ID) or "").strip()
    return v or None


def _instante(v) -> datetime | None:
    if isinstance(v, datetime):
        d = v
    else:
        try:
            d = datetime.fromisoformat(str(v).strip())
        except ValueError:
            return None
    return d if d.tzinfo is not None else None          # sem fuso não vale (ambíguo)


def carregar() -> tuple[list[dict], str | None]:
    """(entradas, motivo_de_erro). Livro ausente = nenhuma autorização (não é erro: é o padrão)."""
    p = caminho()
    if not p.exists():
        return [], None
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        return [], f"livro de autorizações ilegível ({type(e).__name__})"
    lst = d.get("autorizacoes") if isinstance(d, dict) else None
    if lst is None:
        return [], None
    if not isinstance(lst, list) or not all(isinstance(x, dict) for x in lst):
        return [], "livro de autorizações fora do formato (autorizacoes: lista de mapas)"
    return lst, None


def verificar(aut_id: str | None, *, tarefa: str, provedor: str,
              agora: datetime | None = None) -> tuple[dict | None, str | None]:
    """(entrada, None) se `aut_id` autoriza `tarefa` em `provedor` agora; senão (None, motivo). Sem id ⇒ recusa."""
    if not aut_id:
        return None, "nenhuma autorização informada (JFN_LLM_AUTORIZACAO_PAGA / autorizacao_paga)"
    entradas, erro = carregar()
    if erro:
        return None, erro
    achadas = [e for e in entradas if str(e.get("id") or "") == aut_id]
    if not achadas:
        return None, f"autorização '{aut_id}' não está no livro {caminho().name}"
    if len(achadas) > 1:
        return None, f"autorização '{aut_id}' repetida no livro (ambígua)"
    e = achadas[0]
    faltam = [c for c in CAMPOS if e.get(c) in (None, "", [])]
    if faltam:
        return None, f"autorização '{aut_id}' incompleta (faltam: {', '.join(faltam)})"
    quando, ate = _instante(e["quando"]), _instante(e["ate"])
    if quando is None or ate is None:
        return None, f"autorização '{aut_id}': 'quando'/'ate' precisam de data ISO com fuso"
    agora = agora or datetime.now(timezone.utc)
    if not quando <= agora <= ate:
        return None, f"autorização '{aut_id}' fora da validade ({quando.isoformat()} → {ate.isoformat()})"
    if not isinstance(e["tarefas"], list) or tarefa not in [str(t) for t in e["tarefas"]]:
        return None, f"autorização '{aut_id}' não cobre a tarefa '{tarefa}'"
    if not isinstance(e["provedores"], list) or provedor not in [str(p) for p in e["provedores"]]:
        return None, f"autorização '{aut_id}' não cobre o provedor '{provedor}'"
    try:
        teto = float(e["teto_usd"])
    except (TypeError, ValueError):
        return None, f"autorização '{aut_id}': teto_usd ilegível"
    if teto <= 0:
        return None, f"autorização '{aut_id}': teto_usd precisa ser > 0"
    return {**e, "teto_usd": teto, "quando": quando.isoformat(), "ate": ate.isoformat()}, None


def motivo_recusa(aut_id: str | None, *, tarefa: str, provedor: str) -> str | None:
    """None = autorizado; senão a recusa honesta com o porquê (para portas sem teto por autorização)."""
    _, m = verificar(aut_id, tarefa=tarefa, provedor=provedor)
    return None if m is None else f"{RECUSA} — {m}"
