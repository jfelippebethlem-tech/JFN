#!/usr/bin/env python3
"""Coleta SEI dos contratos do FUNESBOM (CBMERJ) 2024+, na ORDEM DE SUSPEITA (score de triagem).
Reusa 100% o pipeline canônico (tools.sei_sweep.run): browser_lock_async, login itkava único, retry,
_ficha_e_storage, checkpoint resumível. Só TROCA a fonte da fila (contratos_tcerj, não ordens_bancarias),
porque as OBs dos bombeiros não trazem nº SEI. Bounded + resumível: relançar drena em ordem de prioridade.

Uso:  PYTHONPATH=. .venv/bin/python -m tools.sei_bombeiros_sweep --max 12
Sem Gemini (GEMINI_DISABLED=1 global; ficha usa stepfun:free/nous). Honestidade: indício != acusação."""
import asyncio
import argparse
import json
import pathlib
import tools.sei_sweep as S

FILA = pathlib.Path("data/bombeiros_sei_fila.json")

def _carregar_fila():
    itens = json.loads(FILA.read_text(encoding="utf-8"))
    # (proc, nob, tot) — nob fica 1 (só p/ log); tot=valor do contrato (ordena o log, prioridade já no arquivo)
    return [(x["sei"], 1, float(x.get("valor") or 0)) for x in itens]

def main():
    ap = argparse.ArgumentParser(description="SEI sweep priorizado dos contratos do FUNESBOM")
    ap.add_argument("--max", type=int, default=12)
    a = ap.parse_args()
    fila_bombeiros = _carregar_fila()
    # pausa INDEPENDENTE: não obedece o .pause_sei_sweep do sweep principal (controle próprio).
    S.PAUSE = pathlib.Path("data/.pause_bombeiros")
    # injeta a fila dos bombeiros no run() canônico (ignora o LIMIT do SQL original; run() filtra _pular
    # e fatia [:max_n], então devolvemos a lista inteira já priorizada e a coleta drena em prioridade).
    S._fila = lambda ug, limite, cnpj=None: fila_bombeiros
    S._log(f"[bombeiros] fila priorizada: {len(fila_bombeiros)} contratos; lote --max {a.max} (árvore prof.=6)")
    # segue a árvore de relacionados mais fundo: a licitação/contrato costuma estar no processo-pai,
    # não no nº de pagamento/registro (achado do teste paralelo Link Card).
    asyncio.run(S.run(max_n=a.max, ug=None, diario=False, max_rel_arvore=6))

if __name__ == "__main__":
    main()
