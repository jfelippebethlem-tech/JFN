# -*- coding: utf-8 -*-
"""Processo-filho que roda UM estágio (handler ou conferência de efeito) — o supervisor nunca roda handler no
próprio processo (§3.3: o laço só escolhe; lição do "lane contínuo while true" na VM-1).

Entrada e saída por arquivo JSON (o stdout do handler fica livre para log):
    python -m compliance_agent.fluxo.executar rodar    <entrada.json> <saida.json>
    python -m compliance_agent.fluxo.executar conferir <entrada.json> <saida.json>
`entrada` = {tipo, chave, ficha, no, tentativa, correlation_id, payload[, resultado]}.
Saída de `rodar` = {efeito, eventos}; de `conferir` = {conferido, conferencia} (`conferencia` = o que o efeito
mediu — o motivo da reprovação vai ao `erro_resumo`). Códigos: 0 ok · 3 ErroPermanente (quarentena) · 4 `fila.Adiado`
(espera conhecida: {adiado, reabre_em}, volta sem gastar tentativa) · outro = falha transitória (traceback no stderr,
que o supervisor resume no `erro_resumo`). `expandir:<estágio>` (um evento → N jobs) roda aqui: fluxo/expandir.py.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, estagio_de
from compliance_agent.fluxo.fila import Adiado, Resultado

SAIDA_PERMANENTE = 3
SAIDA_ADIADO = 4


def main(argv: list[str] | None = None) -> int:
    modo, entrada, saida = (argv if argv is not None else sys.argv[1:])[:3]
    e = json.loads(Path(entrada).read_text(encoding="utf-8"))
    if e["tipo"].startswith("expandir:"):
        from compliance_agent.fluxo import expandir
        estagio = expandir.ESTAGIO
    else:
        estagio = estagio_de(e["tipo"])
    if estagio is None:
        Path(saida).write_text(json.dumps({"erro": f"estágio desconhecido: {e['tipo']}"}), encoding="utf-8")
        return SAIDA_PERMANENTE
    ctx = Contexto(no=e["no"], tipo=e["tipo"], chave=e["chave"], ficha=e["ficha"], tentativa=e["tentativa"],
                   correlation_id=e.get("correlation_id"))
    # O8.5 (leitura única): com JFN_LEITURAS_REGISTRAR=1 o filho anota o que leu (fluxo/leituras) e grava no esquema
    # do fluxo ao sair; desligado (padrão até a O9.0), nada muda.
    from compliance_agent.fluxo import leituras
    reg = leituras.iniciar(ctx, modo, estagio) if leituras.ligado() else None
    try:
        return _rodar(modo, e, estagio, ctx, saida)
    finally:
        if reg is not None:
            leituras.encerrar(reg)


def _rodar(modo: str, e: dict, estagio, ctx: Contexto, saida: str) -> int:
    try:
        if modo == "rodar":
            r = estagio.handler(e.get("payload") or {}, ctx)
            out = {"efeito": r.efeito, "eventos": r.eventos}
        else:
            res = e.get("resultado") or {}
            r = Resultado(efeito=res.get("efeito") or {}, eventos=res.get("eventos") or [])
            out = {"conferido": bool(estagio.efeito(e.get("payload") or {}, ctx, r)),
                   "conferencia": r.efeito.get("conferencia")}
    except ErroPermanente as exc:
        Path(saida).write_text(json.dumps({"erro": str(exc)}, ensure_ascii=False), encoding="utf-8")
        return SAIDA_PERMANENTE
    except psycopg.OperationalError as exc:
        # regra 3 do motor: interrupção da INFRAESTRUTURA não gasta tentativa. 27/11/2026: a conexão it-campo → PG da
        # VM-2 caiu e um job do E6 queimou as 5 tentativas na quarentena. Só conexão PERDIDA vira espera; erro real do
        # banco (ex.: QueryCanceled por tempo, também OperationalError) segue gastando tentativa — não esconder defeito.
        if not _conexao_caiu(exc):
            raise
        exc = Adiado(f"infra: conexão com o PostgreSQL caiu ({str(exc).splitlines()[0][:160]})",
                     reabre_em=datetime.now(timezone.utc) + timedelta(minutes=2))
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        Path(saida).write_text(json.dumps({"adiado": f"{type(exc).__name__}: {exc}", "reabre_em": exc.reabre_em.isoformat()},
                                          ensure_ascii=False, default=str), encoding="utf-8")
        return SAIDA_ADIADO
    except Adiado as exc:
        # o nome da classe vai ao stderr (SemCota dos estágios de LLM: o relatório do ensaio o reconhece)
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        reabre = exc.reabre_em.isoformat() if hasattr(exc.reabre_em, "isoformat") else exc.reabre_em
        Path(saida).write_text(json.dumps({"adiado": f"{type(exc).__name__}: {exc}", "reabre_em": reabre},
                                          ensure_ascii=False, default=str), encoding="utf-8")
        return SAIDA_ADIADO
    Path(saida).write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


_CONEXAO_PERDIDA = ("server closed the connection", "connection failed", "consuming input failed",
                    "could not receive data", "could not send data", "connection to server", "terminating connection")


def _conexao_caiu(exc: Exception) -> bool:
    if isinstance(exc, psycopg.errors.QueryCanceled):
        return False
    m = str(exc).lower()
    return any(k in m for k in _CONEXAO_PERDIDA)


if __name__ == "__main__":
    sys.exit(main())
