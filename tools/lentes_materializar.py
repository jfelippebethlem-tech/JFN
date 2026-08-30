#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Materializa as lentes de detecção num JSON para o painel ler — sem cálculo na rota.

**Por que materializar.** As lentes varrem a `ob_orcamentaria_siafe` inteira: 2 a 15 s cada,
~26 s somadas. Rota que calcula na hora trava o painel sob carga, e a casa já tem o padrão
(`digest_estado.json`, `pipelines_slo_estado.json`): cron grava, rota lê.

**Por que existir.** As sete lentes construídas em 08/2026 eram CLI-only — nenhuma tinha caller.
É o padrão "construído, testado, nunca rodado" (7º caso da casa). Este arquivo é o caller.

Cada bloco carrega a ressalva da própria lente; nenhuma delas acusa — todas ORDENAM fila.

Uso:
    .venv/bin/python tools/lentes_materializar.py            # grava data/lentes_estado.json
    .venv/bin/python tools/lentes_materializar.py --limite 5 # amostra, para conferência
"""
from __future__ import annotations

import argparse
import datetime
import json
import sqlite3
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tools"))

DB = RAIZ / "data" / "compliance.db"
SAIDA = RAIZ / "data" / "lentes_estado.json"


def _seguro(nome: str, fn, *a, **kw) -> dict:
    """Roda uma lente. Falha vira INDISPONÍVEL declarado — nunca lista vazia silenciosa."""
    t0 = time.time()
    try:
        return {"ok": True, "itens": fn(*a, **kw), "segundos": round(time.time() - t0, 1)}
    # Enumeradas, e não a captura genérica: uma lente quebrada não pode derrubar as outras, mas a
    # catraca `test_catraca_excepts` está certa — captura genérica engole erro de programação
    # (NameError num campo renomeado) e o transforma em "INDISPONÍVEL", que parece dado.
    # Estas são as falhas REAIS das lentes: tabela/coluna ausente, banco travado ou corrompido,
    # arquivo sumido, chave que mudou de nome no dicionário, tipo inesperado vindo do SQLite.
    except (sqlite3.Error, OSError, KeyError, IndexError, ValueError, TypeError) as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}", "itens": None,
                "segundos": round(time.time() - t0, 1)}


def materializar(limite: int = 50) -> dict:
    from contrato_acima_do_porte import acima_do_porte
    from convergencia import convergir
    from dependencia_mutua import dependencia
    from pago_a_sancionado import pagos_durante_sancao
    from pago_sem_contrato import sem_contrato
    from pericia_tripla import periciar
    from porte_declarado_certame import declaracoes_incompativeis
    from porte_incompativel import incompativeis
    from troca_de_controle import trocas

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    lentes = {
        "convergencia": _seguro("convergencia", convergir, con),
        "dependencia_mutua": _seguro("dependencia_mutua", dependencia, con),
        "pago_a_sancionado": _seguro("pago_a_sancionado", pagos_durante_sancao, con),
        "porte_incompativel": _seguro("porte_incompativel", incompativeis, con),
        # corte ESTRITO por padrão: só certame publicado DEPOIS de a empresa já ter estourado o
        # teto no ano. O amplo triplica o número e inclui quem podia não saber ainda.
        "porte_declarado_certame": _seguro("porte_declarado_certame", declaracoes_incompativeis,
                                           con, estrito=True),
        # corte FORTE: o fraco marca 21,6% do universo e não ordena fila nenhuma.
        "troca_de_controle": _seguro("troca_de_controle", trocas, con, forte=True),
        # critério LEGAL na forma literal: contrato CELEBRADO acima do teto do porte.
        "contrato_acima_do_porte": _seguro("contrato_acima_do_porte", acima_do_porte, con),
        # LÊ A INTERPRETAÇÃO DA IA, não uma tabela — única lente que vem do texto dos autos.
        "pago_sem_contrato": _seguro("pago_sem_contrato", sem_contrato, con),
        # ordena PROCESSOS por lacuna probatória, não fornecedores por sinal.
        "pericia_tripla": _seguro("pericia_tripla", periciar, con),
    }
    con.close()

    for nome, bloco in lentes.items():
        itens = bloco.pop("itens")
        bloco["n"] = len(itens) if itens is not None else None  # None = INDISPONÍVEL, não zero
        bloco["topo"] = itens[:limite] if itens else []
    return {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "limite": limite, "lentes": lentes,
            # bloco NOVO e aditivo: quem já lê `lentes` não muda de comportamento
            "pcrj": _materializar_pcrj(limite),
            "aviso": "Indícios para apuração interna — cada lente ORDENA fila, nenhuma acusa."}


def _materializar_pcrj(limite: int) -> dict:
    """Lentes sobre a despesa do MUNICÍPIO do Rio (`tools/lentes_pcrj`).

    Contrato diferente do das lentes estaduais: cada uma devolve um dicionário com `universo`,
    `prevalencia` e `massa`, não uma lista. A prevalência viaja junto porque é o que decide se o
    sinal discrimina — publicar contagem sem denominador é o erro que a casa já catalogou."""
    from lentes_pcrj import LENTES as L_FORNECEDOR
    from lentes_pcrj_contrato import CONTROLES as C_CONTRATO
    from lentes_pcrj_contrato import LENTES as L_CONTRATO
    from lentes_pcrj_execucao import CONTROLES as C_EXECUCAO
    from lentes_pcrj_execucao import LENTES as L_EXECUCAO

    # os CONTROLES entram junto: não procuram irregularidade, procuram defeito no dado — e um
    # acervo que falha neles não sustenta nenhuma das outras lentes
    saida = {}
    for fn in L_FORNECEDOR + L_EXECUCAO + L_CONTRATO + C_EXECUCAO + C_CONTRATO:
        b = _seguro(fn.__name__, fn)
        r = b.pop("itens", None)
        if not b["ok"] or r is None:
            saida[fn.__name__] = {**b, "n": None, "topo": []}
            continue
        saida[fn.__name__] = {
            "ok": True, "segundos": b["segundos"],
            "titulo": r["lente"],
            "n": r["n"], "universo": r["universo"],
            "prevalencia": r["prevalencia"],      # None = INDISPONÍVEL, jamais 0%
            "massa": r["massa"],
            "topo": (r["achados"] or [])[:limite],
            # o que foi RESSALVADO fica contado e visível: sumir com ele esconderia o dia em que
            # a concessionária cobrar demais
            "n_ressalvados": len(r.get("ressalvados") or []),
            "n_inconclusivos": len(r.get("inconclusivos") or []),
            "indisponivel": r.get("_indisponivel"),
            "nota": r.get("_nota"),
        }
    return {"universo_contratual": _universo_pcrj(), "lentes": saida}


def _universo_pcrj() -> dict:
    """O denominador declarado: quanto do bruto entra no exame contratual, e o que saiu."""
    from compliance_agent.pcrj.universo import resumo
    try:
        return resumo(str(DB))
    except (sqlite3.Error, OSError, KeyError) as e:
        return {"indisponivel": f"{type(e).__name__}: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limite", type=int, default=50, help="itens gravados por lente")
    a = ap.parse_args()
    estado = materializar(a.limite)
    # as lentes de sanção devolvem `datetime.date` (vigência); vira ISO aqui, no serializador,
    # para não mexer no formato de retorno de código já testado e usado pelo CLI.
    SAIDA.write_text(json.dumps(estado, ensure_ascii=False, indent=1,
                                default=lambda o: o.isoformat()
                                if isinstance(o, (datetime.date, datetime.datetime)) else str(o)),
                     encoding="utf-8")
    for nome, b in estado["lentes"].items():
        n = b["n"] if b["n"] is not None else "INDISPONÍVEL"
        print(f"  {nome:22s} {str(n):>12}  {b['segundos']:5.1f}s"
              f"{'' if b['ok'] else '  ← ' + b['erro'][:60]}")
    u = estado["pcrj"].get("universo_contratual", {})
    if "contratual" in u:
        from compliance_agent.reporting.intel_base import moeda
        print(f"\n  PCRJ · universo contratual: R$ {moeda(u['contratual']['pago'])} "
              f"({u['fracao_do_bruto']*100:.1f}% do bruto)")
    for nome, b in estado["pcrj"]["lentes"].items():
        n = b["n"] if b["n"] is not None else "INDISPONÍVEL"
        pv = f"{b['prevalencia']*100:.2f}%" if b.get("prevalencia") is not None else "INDISP."
        print(f"  pcrj.{nome:24s} {str(n):>8} {pv:>9}  {b['segundos']:5.1f}s"
              f"{'' if b['ok'] else '  ← ' + str(b.get('erro'))[:50]}")
    print(f"\n{SAIDA.relative_to(RAIZ)} ({SAIDA.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
