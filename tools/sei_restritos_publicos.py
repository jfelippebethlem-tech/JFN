# -*- coding: utf-8 -*-
"""Mede, processo a processo, quantos dos RESTRITO (`data/sei_restritos.json`) a PESQUISA PÚBLICA do SEI-RJ abre
(achado de 27/11/2026, n=20: ~50% com árvore + documentos; 30% só árvore; 20% não aparecem). Só HTTP, só leitura:
grava `data/sei_restritos_publico.json` ({processo: {classe, docs, com_link, em}}, gitignored), retomável (pula o já
medido), com pausa entre consultas. Não captura nada: é o universo medido para a via pública do E2/E3.
    python -m tools.sei_restritos_publicos [--limite N] [--pausa 0.6]
Rodar na VM-1 ou no it-campo (a VM-2 não completa TLS com sei.rj.gov.br).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ENTRADA = Path("data/sei_restritos.json")
SAIDA = Path("data/sei_restritos_publico.json")


def _gravar(d: dict) -> None:
    tmp = SAIDA.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SAIDA)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--pausa", type=float, default=0.6)
    a = ap.parse_args(argv)
    import httpx

    from compliance_agent.sei import pesquisa_publica as PP
    from tools.sei_rj_catalogo import Sessao
    rest = sorted(k for k, v in json.loads(ENTRADA.read_text(encoding="utf-8")).items()
                  if isinstance(v, dict) and v.get("status") == "RESTRITO")
    feito = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.is_file() else {}
    alvo = [k for k in rest if k not in feito][: a.limite or None]
    print(f"sei_restritos_publicos: {len(rest)} restritos; {len(feito)} já medidos; {len(alvo)} nesta rodada", flush=True)
    s = Sessao()
    s.abrir()
    for i, k in enumerate(alvo, 1):
        try:
            classe, arv = PP.consultar(s, k)
            feito[k] = {"classe": classe, "docs": len(arv.documentos) if arv else 0,
                        "com_link": len(arv.com_link) if arv else 0,
                        "em": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        except (httpx.HTTPError, ValueError, OSError, RuntimeError) as e:   # rede/sessão/resposta: reabre e segue
            feito[k] = {"classe": "ERRO", "erro": f"{type(e).__name__}: {str(e)[:160]}",
                        "em": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            try:
                s = Sessao()
                s.abrir()
            except (httpx.HTTPError, OSError, RuntimeError):
                time.sleep(30)
        if i % 25 == 0:
            _gravar(feito)
            print(f"  {i}/{len(alvo)} {dict(Counter(v['classe'] for v in feito.values()))}", flush=True)
        time.sleep(a.pausa)
    _gravar(feito)
    c = Counter(v["classe"] for v in feito.values())
    print(f"sei_restritos_publicos: {dict(c)} · documentos com link: {sum(v.get('com_link', 0) for v in feito.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
