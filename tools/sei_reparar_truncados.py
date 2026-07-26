# -*- coding: utf-8 -*-
"""Devolve à fila os processos SEI cujo cache foi gravado TRUNCADO.

Defeito reparado (2026-07-23): o `timeout` do orquestrador matava o Chromium
junto com o Python (faltava `--foreground`). A árvore já extraída era gravada com
`conteudo_documentos: []` e o checkpoint marcava `n_docs>0` — pelo `_pular` do
sweep, esses processos NUNCA mais voltavam à fila. O SEI serviu; nós jogamos fora.

Este reparo é idempotente e NÃO apaga nada: move o cache suspeito para
`data/sei_cache/_truncados/` (auditoria) e zera a entrada no progress, para o
sweep relê-los normalmente. A guarda que impede novos casos vive em
`tools/sei_reader.leitura_truncada`.

    python -m tools.sei_reparar_truncados            # relatório (não escreve)
    python -m tools.sei_reparar_truncados --aplicar  # quarentena + volta à fila
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "data" / "sei_cache"
PROGRESS = CACHE / "sei_sweep_progress.json"
QUARENTENA = CACHE / "_truncados"


def _numero_do_cache(caminho: Path) -> str | None:
    """cdp_SEI_270131_000140_2023.json → SEI-270131/000140/2023."""
    m = re.match(r"cdp_SEI_(\d+)_(\d+)_(\d+)\.json$", caminho.name)
    return f"SEI-{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else None


def encontrar_truncados() -> list[tuple[Path, str | None, int]]:
    """Caches com árvore extraída mas ZERO conteúdo → leitura interrompida."""
    achados = []
    for f in sorted(CACHE.glob("cdp_SEI_*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        n_docs = len(d.get("documentos") or [])
        if n_docs > 0 and not (d.get("conteudo_documentos") or []):
            achados.append((f, _numero_do_cache(f), n_docs))
    return achados


def reparar(aplicar: bool = False) -> dict:
    achados = encontrar_truncados()
    prog = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {"feitos": {}}
    feitos = prog.setdefault("feitos", {})
    bloqueados = [n for _, n, _ in achados if n and (feitos.get(n, {}).get("n_docs") or 0) > 0]

    if aplicar and achados:
        QUARENTENA.mkdir(parents=True, exist_ok=True)
        for f, numero, _ in achados:
            shutil.move(str(f), str(QUARENTENA / f.name))
            if numero and numero in feitos:
                # zera para o sweep reler; preserva o histórico do que houve
                feitos[numero] = {"n_docs": 0, "tentativas": 0,
                                  "em": datetime.now().isoformat(),
                                  "reparado_truncado_em": datetime.now().isoformat()}
        tmp = PROGRESS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prog, ensure_ascii=False))
        tmp.replace(PROGRESS)

    return {"encontrados": len(achados), "bloqueando_a_fila": len(bloqueados),
            "aplicado": aplicar, "quarentena": str(QUARENTENA)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aplicar", action="store_true",
                    help="move os caches truncados p/ quarentena e devolve à fila")
    args = ap.parse_args()
    r = reparar(aplicar=args.aplicar)
    print(f"caches truncados encontrados : {r['encontrados']}")
    print(f"  ...que travavam a fila     : {r['bloqueando_a_fila']}")
    if not args.aplicar:
        print("\n(relatório apenas — rode com --aplicar para reparar)")
    else:
        print(f"movidos para                 : {r['quarentena']}")
        print("progress zerado — os processos voltam à fila no próximo sweep.")


if __name__ == "__main__":
    main()
