#!/usr/bin/env python3
"""
FICHA SEI — extrai do texto cru de um processo SEI APENAS o que é relevante p/ auditoria/compliance,
via LLM, devolvendo um JSON compacto. Resolve 2 coisas:
  (1) STORAGE: guardar a ficha (~500 chars) em vez do texto cru (12 mil chars) — ~20× menor.
  (2) RELEVÂNCIA: nem todo doc do SEI importa (capa/despacho/trâmite); a ficha marca `relevante`.

Modo COMPARA: roda a MESMA extração com um modelo BARATO (grátis-ish) e um MELHOR e compara
(campos preenchidos, tamanho, tempo, concordância) — para decidir qual usar no sweep.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.sei_ficha --comparar --n 10
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "data" / "sei_cache"

MODELO_BARATO = "gemini-2.5-flash-lite"   # grátis-ish (free tier generoso); proxy do "sem limite"
MODELO_MELHOR = "gemini-2.5-flash"        # melhor

_SIST = ("Você é analista de auditoria de contratação pública (controle externo, TCE-RJ). "
         "Extraia do texto de um processo SEI-RJ APENAS o que importa para auditoria. "
         "Seja conciso e factual; NUNCA invente. Responda SOMENTE com JSON válido, sem ```.")

_CAMPOS = ('{"objeto": "o que se contrata (1 frase)", "modalidade": "pregão/dispensa/inexigibilidade/... ou \\"\\"", '
           '"fundamento_legal": "artigo/lei citados ou \\"\\"", "valores": ["R$ ..."], "cnpjs": ["..."], '
           '"partes": ["órgãos/empresas"], "datas": ["..."], '
           '"red_flags": ["indícios a verificar, se houver"], '
           '"relevante": true, "resumo": "2-3 frases do que importa p/ auditoria"}')


def _carregar_env_completo():
    from compliance_agent.envfile import carregar_env
    carregar_env()
    h = Path.home() / ".hermes" / ".env"
    if h.exists():
        for ln in h.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in ln and ln.split("=", 1)[0].strip().startswith(("GEMINI", "GOOGLE")):
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _prompt(texto: str) -> list[dict]:
    p = (f"Texto do processo SEI (pode estar truncado):\n\n{(texto or '')[:8000]}\n\n"
         f"Extraia em JSON exatamente neste formato:\n{_CAMPOS}")
    return [{"role": "system", "content": _SIST}, {"role": "user", "content": p}]


def _nous_cred() -> tuple[str, str]:
    """(access_token, inference_base_url) do auth.json do hermes. Sem refresh (seguro)."""
    try:
        d = json.loads((Path.home() / ".hermes" / "auth.json").read_text(encoding="utf-8"))
        p = (d.get("providers") or {}).get("nous") or {}
        return p.get("access_token", ""), p.get("inference_base_url", "https://inference-api.nousresearch.com/v1")
    except Exception:
        return "", "https://inference-api.nousresearch.com/v1"


async def _chamar_nous(texto: str, model: str) -> str:
    """Chama o nous (OpenAI-compat) com o token atual do auth.json. 401 = expirado (re-auth hermes)."""
    import httpx
    tok, base = _nous_cred()
    if not tok:
        raise RuntimeError("sem access_token nous (auth.json)")
    async with httpx.AsyncClient(timeout=200) as c:  # nous é lento; "lento tá ok" se a qualidade segura
        r = await c.post(f"{base}/chat/completions",
                         headers={"Authorization": f"Bearer {tok}"},
                         json={"model": model, "messages": _prompt(texto), "temperature": 0.1})
        if r.status_code == 401:
            raise RuntimeError("401 token nous expirado (rode `hermes` p/ re-auth)")
        r.raise_for_status()
        return (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")


async def extrair_ficha(texto: str, model: str, provider: str = "gemini") -> dict:
    """Extrai a ficha compacta. provider: 'gemini' (gerar_gemini) ou 'nous' (OpenAI-compat). {'_erro'} em falha."""
    try:
        if provider == "nous":
            raw = await _chamar_nous(texto, model)
        else:
            from compliance_agent.direcionamento_cerebro import gerar_gemini
            raw = await gerar_gemini(_prompt(texto), model=model)
    except Exception as e:  # noqa: BLE001
        return {"_erro": f"{type(e).__name__}: {str(e)[:80]}"}
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return {"_erro": "sem JSON", "_raw": (raw or "")[:120]}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"_erro": "JSON inválido", "_raw": (raw or "")[:120]}


def conteudo_real(d: dict) -> str:
    """O conteúdo que IMPORTA = `conteudo_documentos` (texto real dos docs), NÃO `texto` (que é o
    MENU lateral do SEI). Concatena os documentos lidos. Inclui a árvore (cadeia) se houver."""
    partes = []
    for c in (d.get("conteudo_documentos") or []):
        t = c.get("conteudo") if isinstance(c, dict) else str(c)
        if t and len(t) > 40:
            partes.append(t)
    for rel in (d.get("cadeia") or []):  # docs dos relacionados (a árvore)
        if rel.get("texto") and len(rel["texto"]) > 40:
            partes.append("[RELACIONADO] " + rel["texto"])
    return "\n\n---\n\n".join(partes)


def _cached(n: int) -> list[tuple]:
    out = []
    for f in sorted(glob.glob(str(CACHE / "cdp_*.json"))):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
            cont = conteudo_real(d)
            if len(cont) > 150:  # só processos com CONTEÚDO real (não os que só têm menu)
                out.append((Path(f).stem.replace("cdp_", ""), cont))
        except Exception:
            pass
        if len(out) >= n:
            break
    return out


def _resumo_ficha(f: dict) -> str:
    if f.get("_erro"):
        return f"ERRO: {f['_erro']}"
    campos = sum(1 for k in ("objeto", "modalidade", "fundamento_legal", "resumo") if (f.get(k) or "").strip())
    return (f"campos={campos}/4 valores={len(f.get('valores') or [])} cnpjs={len(f.get('cnpjs') or [])} "
            f"flags={len(f.get('red_flags') or [])} relevante={f.get('relevante')} "
            f"tam={len(json.dumps(f, ensure_ascii=False))}ch")


# (tag, model, provider). nous *:free = 100% grátis/sem limite (catálogo nousresearch);
# gemini = a "melhor" de referência (free-tier com limites).
_MODELOS = [
    ("stepfun", "stepfun/step-3.7-flash:free", "nous"),     # nous 100% grátis/sem limite (lento ~40-60s)
    ("g-lite", MODELO_BARATO, "gemini"),                    # gemini free-tier (rápido, mas rate-limit 429)
    ("g-flash", MODELO_MELHOR, "gemini"),                   # gemini "melhor" de referência
]


async def comparar(n: int):
    _carregar_env_completo()
    procs = _cached(n)
    print(f"Comparando extração em {len(procs)} processos · " + " × ".join(f"{t}({m})" for t, m, _ in _MODELOS) + "\n")
    agg = {t: {"t": 0.0, "ok": 0, "ch": 0, "rel": 0} for t, _, _ in _MODELOS}
    for proc, texto in procs:
        print(f"== {proc}  (texto cru {len(texto)} ch) ==")
        for tag, model, prov in _MODELOS:
            t0 = time.time()
            f = await extrair_ficha(texto, model, provider=prov)
            dt = time.time() - t0
            agg[tag]["t"] += dt
            if not f.get("_erro"):
                agg[tag]["ok"] += 1
                agg[tag]["ch"] += len(json.dumps(f, ensure_ascii=False))
                if f.get("relevante"):
                    agg[tag]["rel"] += 1
            print(f"  [{tag:7}] {dt:.1f}s  {_resumo_ficha(f)}")
            if not f.get("_erro"):
                print(f"            objeto : {(f.get('objeto') or '')[:110]}")
                print(f"            resumo : {(f.get('resumo') or '')[:110]}")
                vc = (f.get('valores') or []) + (f.get('cnpjs') or [])
                if vc:
                    print(f"            val/cnpj: {', '.join(str(x) for x in vc[:5])}")
        print()
    print("=== AGREGADO ===")
    for tag, _, _ in _MODELOS:
        a = agg[tag]
        n_ok = a["ok"] or 1
        print(f"  {tag:7}: {a['ok']}/{len(procs)} ok · {a['t']:.0f}s total ({a['t']/max(len(procs),1):.1f}s/proc) · "
              f"{a['ch']//n_ok} ch/ficha · {a['rel']} relevantes")
    raw_total = sum(len(t) for _, t in procs)
    ref = next((agg[t] for t, _, _ in _MODELOS if agg[t]["ok"]), {"ch": 0, "ok": 1})
    ficha_ch = ref["ch"] // max(ref["ok"], 1)
    if procs and ficha_ch:
        print(f"\nSTORAGE: conteúdo real {raw_total // len(procs)} ch/proc; ficha ~{ficha_ch} ch/proc "
              f"→ ~{(raw_total // len(procs)) // max(ficha_ch, 1)}× menor guardando só a ficha.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comparar", action="store_true")
    ap.add_argument("--n", type=int, default=10)
    a = ap.parse_args()
    if a.comparar:
        asyncio.run(comparar(a.n))


if __name__ == "__main__":
    main()
