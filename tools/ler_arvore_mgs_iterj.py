#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lê FRESH (sem cache) a árvore SEI dos processos de pagamento MGS-ITERJ via itkava (sei_reader).
Segue relacionados, extrai NF/competência/medição. Salva tudo em data/sei_cache/arvore_mgs_iterj.json."""
import asyncio, json, re, sys
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/JFN")
from tools.sei_reader import ler

# Processos de pagamento por ano (tenta variantes de unidade 330005/330020)
ALVOS = [
    ["SEI-330005/000018/2025", "SEI-330020/000018/2025"],   # 2025 — par idêntico 10/2025
    ["SEI-330005/000007/2024", "SEI-330020/000007/2024"],   # 2024
    ["SEI-330005/000030/2026", "SEI-330020/000030/2026"],   # 2026
]
MESES = r"(janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|0[1-9]/20\d\d|1[0-2]/20\d\d)"


def achados(texto):
    t = texto or ""
    return {
        "nf": sorted(set(re.findall(r"(?:nota fiscal|NF[-\s.:nº]*)\s*[:nº]*\s*(\d{2,8})", t, re.I)))[:30],
        "competencia": sorted(set(re.findall(r"(?:compet[êe]ncia|m[êe]s de refer[êe]ncia|per[íi]odo)[^\n]{0,40}?" + MESES, t, re.I)))[:30],
        "medicao": sorted(set(re.findall(r"(?:boletim de medi[çc][ãa]o|medi[çc][ãa]o)[^\n]{0,30}", t, re.I)))[:20],
    }


async def main():
    out = {"lido_em": "2026-06-19", "processos": []}
    for variantes in ALVOS:
        rec = None
        for num in variantes:
            print(f"[ler] {num} (fresh)…", flush=True)
            try:
                r = await ler(num, usar_cache=False)
            except Exception as e:
                r = {"numero": num, "erro": f"{type(e).__name__}: {str(e)[:120]}"}
            if not r.get("erro") and (r.get("texto") or r.get("documentos")):
                rec = r
                print(f"  ✓ {num}: {len(r.get('texto',''))} chars, {len(r.get('documentos',[]))} docs, {len(r.get('conteudo_documentos',[]))} lidos", flush=True)
                break
            print(f"  ✗ {num}: {str(r.get('erro'))[:100]}", flush=True)
            rec = rec or r
        if rec and not rec.get("erro"):
            txt_all = (rec.get("texto", "") or "") + "\n".join(
                (d.get("texto") or d.get("conteudo") or "") for d in (rec.get("conteudo_documentos") or []))
            rec["_achados"] = achados(txt_all)
            rec["_relacionados"] = rec.get("relacionados") or rec.get("processos_relacionados") or []
            out["processos"].append({k: rec.get(k) for k in ("numero", "url", "cnpjs", "valores", "_achados", "_relacionados")}
                                    | {"n_docs": len(rec.get("documentos", [])), "n_lidos": len(rec.get("conteudo_documentos", []))})
            print(f"  achados: {rec['_achados']}", flush=True)
            print(f"  relacionados: {rec['_relacionados']}", flush=True)
        else:
            out["processos"].append({"numero": variantes[0], "erro": (rec or {}).get("erro", "INDISPONÍVEL")})
    Path("data/sei_cache/arvore_mgs_iterj.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nSALVO em data/sei_cache/arvore_mgs_iterj.json")


asyncio.run(main())
