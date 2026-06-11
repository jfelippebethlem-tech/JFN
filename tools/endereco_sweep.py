# -*- coding: utf-8 -*-
"""Sweep de VERIFICAÇÃO DE ENDEREÇO sobre os suspeitos de fachada/laranja de um órgão.

Compõe com o sweep estrutural (`tools/dd_sweep_orgao`): lê os candidatos 🔴/🟡 já marcados (checkpoint
`data/dd_sweep/dd_sweep_<ug>.jsonl`), busca o endereço cadastral (registry, cacheado) e roda
`verificacao_endereco.analisar_endereco` — geocode-match (bate o município?) + edificação/baldio (Overpass).

POR QUE só os suspeitos: o Nominatim público é limitado a ≤1 req/s e o Overpass tem cota — varrer milhares
de endereços seria abuso e arriscaria bloqueio do IP da VM. A triagem estrutural barata já filtrou; aqui
gastamos a verificação cara de rede onde ela importa. Resumível (checkpoint), educado (pausa configurável),
honesto (cobertura OSM incompleta → ausência ≠ prova; INDISPONÍVEL ≠ baldio).

Uso:  python -m tools.endereco_sweep 036100 [--todos] [--limite N] [--pausa S]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from compliance_agent.investigacao_orgao_dd import _moeda, top_fornecedores_pj
from compliance_agent.verificacao_endereco import analisar_endereco, em_backoff

_DIR = Path("data") / "dd_sweep"
_ORDEM = {"INDICIO": 0, "INDISPONIVEL": 1, "AFASTADO": 2}


def _candidatos_do_dd(ug: str) -> list[dict]:
    """Fornecedores 🔴/🟡 do checkpoint do sweep estrutural (onde o endereço importa)."""
    ck = _DIR / f"dd_sweep_{ug}.jsonl"
    if not ck.exists():
        return []
    out = []
    for ln in ck.read_text("utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if r.get("grau") in ("🔴", "🟡"):
            out.append({"cnpj": r["cnpj"], "nome": r.get("nome", ""), "total_pago": r.get("total_pago", 0.0),
                        "grau": r.get("grau"), "codigos": r.get("codigos", [])})
    return out


def _endereco_cadastral(cnpj: str) -> dict:
    """Endereço da sede via registry (cacheado). {endereco, municipio, uf, cep} ou {} se INDISPONÍVEL."""
    try:
        from compliance_agent.providers import lookup
        r = lookup("registry", cnpj=cnpj)
        if not (r.ok and isinstance(r.dados, dict)):
            return {}
        d = r.dados
        endereco = ", ".join(str(d.get(k) or "").strip() for k in ("logradouro", "numero", "bairro")
                             if str(d.get(k) or "").strip())
        return {"endereco": endereco, "municipio": d.get("municipio") or "",
                "uf": d.get("uf") or "", "cep": d.get("cep") or "",
                "complemento": d.get("complemento") or ""}
    except Exception:
        return {}


def _escreve_relatorio(rel: Path, ug: str, resultados: list[dict], total: int) -> None:
    rank = sorted(resultados, key=lambda r: (_ORDEM.get(r["status"], 9), -r.get("peso", 0)))
    flag = [r for r in rank if r["status"] == "INDICIO"]
    L = [f"# Sweep de endereço — suspeitos da UG {ug}", "",
         f"{len(resultados)}/{total} suspeito(s) verificado(s) · **{len(flag)} com indício de endereço "
         "(baldio / município divergente / não resolvido / residencial)**.", "",
         "*Geocode (Nominatim) + edificação (Overpass/OSM). Cobertura OSM no BR é incompleta → ausência de "
         "edificação ≠ prova de baldio; confirmar por imagem/in loco. INDISPONÍVEL ≠ baldio; indício ≠ acusação.*",
         "", "| Status | Nível | Fornecedor | Total pago | Constatação |", "|:--:|:--:|---|--:|---|"]
    for r in rank:
        if r["status"] == "AFASTADO":
            continue
        L.append(f"| {r['status']} | {r.get('nivel', '—')} | {r['nome'][:38]} | {_moeda(r['total_pago'])} "
                 f"| {r.get('evidencia', '')[:150]} |")
    if not flag:
        L.append("| — | — | *(nenhum indício de endereço entre os suspeitos verificados)* | — | — |")
    rel.write_text("\n".join(L), "utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Sweep de verificação de endereço (suspeitos de fachada)")
    ap.add_argument("ug", help="código da UG (ex.: 036100)")
    ap.add_argument("--todos", action="store_true",
                    help="varre TODOS os fornecedores PJ (NÃO recomendado — abusa do OSM/Nominatim)")
    ap.add_argument("--limite", type=int, default=0, help="máximo de alvos (0=todos os suspeitos)")
    ap.add_argument("--pausa", type=float, default=0.5, help="pausa extra entre alvos (s)")
    a = ap.parse_args()
    load_dotenv(".env")

    _DIR.mkdir(parents=True, exist_ok=True)
    if a.todos:
        forns = [{"cnpj": f["cnpj"], "nome": f["nome"], "total_pago": f["total_pago"],
                  "grau": "?", "codigos": []} for f in top_fornecedores_pj(a.ug, top_n=None, ordem="asc")]
        print(f"[end_sweep {a.ug}] ⚠ modo --todos: {len(forns)} fornecedores (cuidado com a cota OSM)", flush=True)
    else:
        forns = _candidatos_do_dd(a.ug)
        print(f"[end_sweep {a.ug}] {len(forns)} suspeito(s) 🔴/🟡 do sweep estrutural", flush=True)
    if a.limite > 0:
        forns = forns[:a.limite]
    total = len(forns)
    if not total:
        print(f"[end_sweep {a.ug}] nenhum alvo (rode tools.dd_sweep_orgao {a.ug} antes).", flush=True)
        return 0

    ckpt = _DIR / f"endereco_sweep_{a.ug}.jsonl"
    rel = _DIR / f"endereco_sweep_{a.ug}.md"
    feitos: dict[str, dict] = {}
    if ckpt.exists():
        for ln in ckpt.read_text("utf-8").splitlines():
            try:
                r = json.loads(ln)
                feitos[r["cnpj"]] = r
            except Exception:
                continue
    resultados = list(feitos.values())

    t0 = time.time()
    with ckpt.open("a", encoding="utf-8") as fck:
        for i, f in enumerate(forns, 1):
            if f["cnpj"] in feitos:
                continue
            espera = em_backoff()  # fontes OSM pediram trégua (429/5xx) → respeitar antes de seguir
            if espera > 0:
                print(f"  ⏸ back-off {espera:.0f}s (respeitando a fonte OSM)", flush=True)
                time.sleep(espera + 1)
            cad = _endereco_cadastral(f["cnpj"])
            if not cad.get("endereco"):
                res = {"status": "INDISPONIVEL", "nivel": "—", "peso": 0,
                       "evidencia": "Endereço cadastral não disponível (registry INDISPONÍVEL)."}
            else:
                try:
                    res = analisar_endereco(cad["endereco"], cad["municipio"], cad["uf"], cad["cep"],
                                            usar_overpass=True)
                except Exception as e:  # noqa: BLE001
                    res = {"status": "INDISPONIVEL", "nivel": "—", "peso": 0,
                           "evidencia": f"erro: {str(e)[:60]}"}
            rec = {"cnpj": f["cnpj"], "nome": f["nome"], "total_pago": f["total_pago"],
                   "grau_dd": f.get("grau"), "codigos_dd": f.get("codigos", []),
                   "endereco": cad.get("endereco", ""), "municipio": cad.get("municipio", ""),
                   "status": res["status"], "nivel": res.get("nivel", "—"),
                   "peso": res.get("peso", 0), "evidencia": res.get("evidencia", "")}
            fck.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fck.flush()
            feitos[f["cnpj"]] = rec
            resultados.append(rec)
            if res["status"] == "INDICIO":
                print(f"  → {res.get('nivel')} {f['nome'][:40]} :: {res['evidencia'][:90]}", flush=True)
            if i % 10 == 0 or res["status"] == "INDICIO":
                _escreve_relatorio(rel, a.ug, resultados, total)
                if i % 10 == 0:
                    print(f"  ...{len(feitos)}/{total} ({100 * len(feitos) // total}%)", flush=True)
            time.sleep(a.pausa)

    _escreve_relatorio(rel, a.ug, resultados, total)
    flag = [r for r in resultados if r["status"] == "INDICIO"]
    print(f"[end_sweep {a.ug}] CONCLUÍDO {len(feitos)}/{total} · {len(flag)} com indício de endereço · "
          f"relatório: {rel} · {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
