# -*- coding: utf-8 -*-
"""Orquestrador do módulo PCRJ — roda o pipeline inteiro (ou etapas) em UM comando.

Etapas:
    1. camara      — coleta a relação de servidores da Câmara (todos os anos) + mapa de gabinetes.
    2. cruzamento  — consulta cada nome na remuneração da Prefeitura (LENTO ~1h; rate-limited).
    3. tse         — cruza os nomeados com candidaturas do TSE (estado do RJ, 92 municípios).
    4. relatorio   — gera o produto Kroll (pdf/xlsx/html).

Uso:
    python -m compliance_agent.pcrj.pipeline               # tudo
    python -m compliance_agent.pcrj.pipeline --etapas camara,tse,relatorio   # sem o sweep lento
    python -m compliance_agent.pcrj.pipeline --etapas relatorio              # só o relatório
"""
from __future__ import annotations

import argparse
import asyncio

from compliance_agent.pcrj import (
    camara_gabinetes,
    camara_servidores,
    cruzamento,
    relatorio,
    tse_candidatos,
)

_ETAPAS = ("camara", "cruzamento", "tse", "relatorio")


def rodar(etapas: list[str], workers: int = 2) -> dict:
    resultado: dict = {}
    if "camara" in etapas:
        print("[1/4] Câmara: servidores + gabinetes…", flush=True)
        resultado["servidores"] = camara_servidores.coletar()
        resultado["gabinetes"] = camara_gabinetes.coletar()
        print(f"      {resultado['servidores']} · {resultado['gabinetes']}", flush=True)
    if "cruzamento" in etapas:
        print("[2/4] Cruzamento Câmara→Prefeitura (lento)…", flush=True)
        resultado["cruzamento"] = cruzamento.cruzar(workers=workers)
        print(f"      {resultado['cruzamento']}", flush=True)
    if "tse" in etapas:
        print("[3/4] Cruzamento eleitoral TSE (estado do RJ)…", flush=True)
        resultado["tse"] = tse_candidatos.coletar()
        print(f"      {resultado['tse']}", flush=True)
    if "relatorio" in etapas:
        print("[4/4] Relatório Kroll (pdf/xlsx/html)…", flush=True)
        resultado["relatorio"] = asyncio.run(relatorio.gerar())
        print(f"      {resultado['relatorio']}", flush=True)
    return resultado


def main() -> None:
    ap = argparse.ArgumentParser(description="Pipeline do módulo PCRJ")
    ap.add_argument("--etapas", default=",".join(_ETAPAS),
                    help=f"lista separada por vírgula (default: todas). Opções: {','.join(_ETAPAS)}")
    ap.add_argument("--workers", type=int, default=2, help="workers do sweep da Prefeitura")
    args = ap.parse_args()
    etapas = [e.strip() for e in args.etapas.split(",") if e.strip() in _ETAPAS]
    if not etapas:
        ap.error(f"nenhuma etapa válida em '{args.etapas}'. Opções: {','.join(_ETAPAS)}")
    print(f"Pipeline PCRJ — etapas: {etapas}", flush=True)
    rodar(etapas, workers=args.workers)
    print("\n✓ Pipeline concluído.", flush=True)


if __name__ == "__main__":
    main()
