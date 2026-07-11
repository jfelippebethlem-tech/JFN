#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Segue TODOS os relacionados 'Financeiro: Pagamento' do processo de pagamento MGS e extrai, de cada um,
o nº SEI + as Notas Fiscais (competência/valor) — para achar os pagamentos de 2022-2023 e suas NFs.
Usa sei_reader.ler_com_cadeia (abre cada relacionado na MESMA sessão). VM-guarded.
Uso: sei_cadeia_pagamentos_mgs.py [330005/000007/2024]"""
import asyncio
import json
import sys
import re
from pathlib import Path
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from tools.vm_guard import preflight, cleanup_orphans
from tools import sei_reader as SR

ALVO = sys.argv[1] if len(sys.argv) > 1 else "330005/000007/2024"
NF = re.compile(r"(?i)nota fiscal\s+(\d{1,5})")
COMP = re.compile(r"\b(0[1-9]|1[0-2])/(202[1-6])\b")
MONEY = re.compile(r"\b(\d{1,3}(?:\.\d{3})*,\d{2})\b")


async def main():
    res = await SR.ler_com_cadeia(ALVO, max_rel=12, tentativas_login=30)
    cadeia = res.get("cadeia") or res.get("relacionados_lidos") or []
    saida = []
    for m in cadeia:
        txt = m.get("texto", "") or ""
        nums = sorted(set(re.findall(r"\b\d{6}/\d{6}/\d{4}\b", txt)))
        comps = sorted(set("/".join(c) for c in COMP.findall(txt)))
        nfs = NF.findall(txt)
        saida.append({
            "id": m.get("id_procedimento"), "titulo": m.get("titulo_rel", "")[:60],
            "n_docs": m.get("n_docs"), "nums_sei": nums[:6],
            "competencias": comps, "nfs": nfs[:12], "n_texto": m.get("n_texto"),
        })
        print(f"  id={m.get('id_procedimento')} docs={m.get('n_docs')} nums={nums[:3]} comps={comps}", flush=True)
    out = REPO / "data/sei_cache/cadeia_pagamentos_mgs.json"
    out.write_text(json.dumps({"alvo": ALVO, "n_cadeia": len(cadeia), "membros": saida},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    # consolida: quais cobrem 2022/2023?
    alvo23 = [s for s in saida if any(c.endswith(("/2022", "/2023")) for c in s["competencias"])]
    print("\nMEMBROS COM COMPETÊNCIAS 2022/2023:")
    for s in alvo23:
        print(f"  nums={s['nums_sei']} comps={s['competencias']} nfs={s['nfs']}")
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
