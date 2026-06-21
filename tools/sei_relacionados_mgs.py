#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enumera TODOS os processos relacionados dos âncoras MGS (contrato 762/2021 + pagamentos conhecidos)
para localizar os processos de pagamento de 2022-2023 (e suas NFs). Usa sei_reader.ler (cracked).
Salva data/sei_cache/relacionados_mgs.json. VM-guarded."""
import asyncio, json, sys, re
from pathlib import Path
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from tools.vm_guard import preflight, cleanup_orphans
from tools import sei_reader as SR

ANCORAS = [
    "330020/000762/2021",   # contrato/contratação (PAI)
    "330005/000007/2024",   # pagamento 2024
    "330005/000018/2025",   # pagamento 2025
]


async def main():
    achados = {}
    for proc in ANCORAS:
        try:
            res = await SR.ler(proc, usar_cache=False, tentativas_login=30)
        except Exception as e:  # noqa: BLE001
            achados[proc] = {"erro": str(e)[:120]}; continue
        rel = res.get("relacionados") or []
        # extrai nº de processo dos relacionados (url/titulo/texto)
        nums = set()
        blob = json.dumps(rel, ensure_ascii=False) + " " + (res.get("texto", "") or "")
        for m in re.findall(r"\b\d{6}/\d{6}/\d{4}\b", blob):
            nums.add(m)
        achados[proc] = {
            "n_relacionados": len(rel),
            "n_docs": len(res.get("documentos") or []),
            "via": res.get("via", ""),
            "rel_titulos": [(r.get("titulo") or r.get("texto") or "")[:80] for r in rel][:30],
            "nums_citados": sorted(nums),
        }
        print(f"{proc}: {len(rel)} relacionados, {len(nums)} nº citados", flush=True)
    out = REPO / "data/sei_cache/relacionados_mgs.json"
    out.write_text(json.dumps(achados, ensure_ascii=False, indent=1), encoding="utf-8")
    # consolida candidatos 2022-2023
    cand = sorted({n for a in achados.values() if isinstance(a, dict) for n in a.get("nums_citados", [])
                   if re.search(r"/202[23]$", n)})
    print("CANDIDATOS 2022-2023:", cand)
    print("arquivo:", out)


if __name__ == "__main__":
    ok, motivo = preflight()
    if not ok:
        print(json.dumps({"ok": False, "vm_guard": motivo})); sys.exit(1)
    cleanup_orphans()
    try:
        asyncio.run(main())
    finally:
        cleanup_orphans()
