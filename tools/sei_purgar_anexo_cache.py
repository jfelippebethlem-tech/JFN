"""sei_purgar_anexo_cache — tira o binário serializado dos caches do SEI.

O `_conteudo_doc` devolve `anexo_bytes` (o PDF original) para quem arquiva na MESMA execução.
Até 2026-08-02 esse campo ia junto para o `cdp_*.json` e o `default=str` o transformava na repr
`b'%PDF-1.4…'` — texto inútil (não volta a ser bytes) que inflava o cache ~400×: um processo
com 302 KB de texto ocupava 127 MB. A gravação já não inclui mais o campo (`sei_reader.
_grava_cache_atomico`); esta ferramenta limpa o passivo que ficou no disco.

Seguro por construção: reescreve o JSON SEM `anexo_bytes` e mantém todo o resto (o texto, que é
o que o motor lê); grava em `.tmp` e faz rename atômico; pula o que já está limpo; nunca apaga
arquivo. Processa do maior para o menor, UM POR VEZ (parse de JSON grande custa RAM — a VM tem
2 vCPU e sweeps vivos).

    .venv/bin/python -m tools.sei_purgar_anexo_cache              # relatório (não escreve)
    .venv/bin/python -m tools.sei_purgar_anexo_cache --aplicar --max 20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "data" / "sei_cache"
LIMITE_MB_PADRAO = 12.0


def candidatos(limite_mb: float = LIMITE_MB_PADRAO) -> list[tuple[Path, float]]:
    """Caches acima do limite, do maior para o menor (só `.json`; `.zst` é gerado depois)."""
    itens = []
    for p in CACHE.glob("cdp_*.json"):
        try:
            mb = p.stat().st_size / 1e6
        except OSError:
            continue
        if mb > limite_mb:
            itens.append((p, mb))
    itens.sort(key=lambda t: -t[1])
    return itens


def purgar_dict(d: dict) -> tuple[dict, int]:
    """Remove `anexo_bytes` de cada documento. Devolve (dict limpo, nº de campos removidos)."""
    docs = d.get("conteudo_documentos")
    if not isinstance(docs, list):
        return d, 0
    n = 0
    novos = []
    for x in docs:
        if isinstance(x, dict) and "anexo_bytes" in x:
            n += 1
            novos.append({k: v for k, v in x.items() if k != "anexo_bytes"})
        else:
            novos.append(x)
    if n:
        d = dict(d)
        d["conteudo_documentos"] = novos
    return d, n


def purgar_arquivo(p: Path, aplicar: bool) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"arquivo": p.name, "erro": str(e)[:80], "removidos": 0, "mb_antes": 0, "mb_depois": 0}
    antes = p.stat().st_size / 1e6
    limpo, n = purgar_dict(d)
    if not n:
        return {"arquivo": p.name, "removidos": 0, "mb_antes": round(antes, 1), "mb_depois": round(antes, 1)}
    if not aplicar:
        return {"arquivo": p.name, "removidos": n, "mb_antes": round(antes, 1), "mb_depois": None}
    tmp = p.with_suffix(".json.purga")
    tmp.write_text(json.dumps(limpo, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)
    return {"arquivo": p.name, "removidos": n, "mb_antes": round(antes, 1),
            "mb_depois": round(p.stat().st_size / 1e6, 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--max", type=int, default=0, help="quantos arquivos por rodada (0 = todos)")
    ap.add_argument("--limite-mb", type=float, default=LIMITE_MB_PADRAO)
    a = ap.parse_args(argv)

    alvos = candidatos(a.limite_mb)
    if a.max:
        alvos = alvos[:a.max]
    if not alvos:
        print("nenhum cache acima do limite — nada a purgar")
        return 0
    print(f"caches acima de {a.limite_mb:g} MB: {len(alvos)} · "
          f"{sum(mb for _, mb in alvos):,.0f} MB no total")
    ganho = 0.0
    for p, _mb in alvos:
        r = purgar_arquivo(p, a.aplicar)
        if r.get("erro"):
            print(f"  ! {r['arquivo']}: {r['erro']}")
            continue
        if r["removidos"]:
            dep = r["mb_depois"]
            if dep is not None:
                ganho += r["mb_antes"] - dep
            print(f"  {r['arquivo']}: {r['removidos']} anexo(s) · "
                  f"{r['mb_antes']} MB → {dep if dep is not None else '(simulação)'}")
    print(f"\n{'liberado' if a.aplicar else 'liberaria'}: {ganho:,.0f} MB"
          + ("" if a.aplicar else "  (SIMULAÇÃO — use --aplicar)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
