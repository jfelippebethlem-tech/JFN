# -*- coding: utf-8 -*-
"""Processo-filho que roda UM estágio (handler ou conferência de efeito) — o supervisor nunca roda handler no
próprio processo (§3.3: o laço só escolhe; lição do "lane contínuo while true" na VM-1).

Entrada e saída por arquivo JSON (o stdout do handler fica livre para log):
    python -m compliance_agent.fluxo.executar rodar    <entrada.json> <saida.json>
    python -m compliance_agent.fluxo.executar conferir <entrada.json> <saida.json>
`entrada` = {tipo, chave, ficha, no, tentativa, correlation_id, payload[, resultado]}.
Saída de `rodar` = {efeito, eventos}; de `conferir` = {conferido}. Códigos: 0 ok · 3 ErroPermanente (quarentena) ·
outro = falha transitória (traceback no stderr, que o supervisor resume no `erro_resumo`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, estagio_de
from compliance_agent.fluxo.fila import Resultado

SAIDA_PERMANENTE = 3


def main(argv: list[str] | None = None) -> int:
    modo, entrada, saida = (argv if argv is not None else sys.argv[1:])[:3]
    e = json.loads(Path(entrada).read_text(encoding="utf-8"))
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
            out = {"conferido": bool(estagio.efeito(e.get("payload") or {}, ctx,
                                                    Resultado(efeito=res.get("efeito") or {},
                                                              eventos=res.get("eventos") or [])))}
    except ErroPermanente as exc:
        Path(saida).write_text(json.dumps({"erro": str(exc)}, ensure_ascii=False), encoding="utf-8")
        return SAIDA_PERMANENTE
    Path(saida).write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
