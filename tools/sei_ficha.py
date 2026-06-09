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
         "REGRAS: (1) factual — NUNCA invente; campo sem dado no texto = \"\" ou []. "
         "(2) CONCISO — 'resumo' no MÁXIMO 2 frases; sem repetir. "
         "(3) Responda SOMENTE o objeto JSON (começa com { e termina com }), SEM texto antes/depois, SEM ```.")

_CAMPOS = ('{"objeto": "o que se contrata (1 frase)", "modalidade": "pregão/dispensa/inexigibilidade/adesão a ata/... ou \\"\\"", '
           '"fundamento_legal": "artigo/lei citados ou \\"\\"", "valores": ["R$ ..."], "cnpjs": ["..."], '
           '"partes": ["órgãos/empresas"], "datas": ["..."], '
           '"red_flags": ["indícios a verificar, se houver"], '
           '"relevante": true, "resumo": "1-2 frases do que importa p/ auditoria"}')

# FEW-SHOT: 1 exemplo input→ficha ideal "ensina" o modelo fraco (formato + profundidade esperada).
_EXEMPLO_TXT = ("Trata-se de adesão à ata de registro de preços do Pregão Eletrônico 045/2021 da Fundação Saúde "
                "do ERJ para aquisição de cateter venoso central, demanda da Diretoria-Geral de Saúde do CBMERJ, "
                "valor estimado R$ 17.156,00. Fornecedor: MEDLINE COMERCIAL LTDA, CNPJ 12.345.678/0001-90.")
_EXEMPLO_FICHA = ('{"objeto": "Aquisição de cateter venoso central (insumo de saúde) p/ a Diretoria-Geral de Saúde do CBMERJ", '
                  '"modalidade": "adesão a ata de registro de preços (Pregão 045/2021)", "fundamento_legal": "", '
                  '"valores": ["R$ 17.156,00"], "cnpjs": ["12.345.678/0001-90"], '
                  '"partes": ["CBMERJ", "Fundação Saúde do ERJ", "MEDLINE COMERCIAL LTDA"], "datas": [], '
                  '"red_flags": ["adesão a ata de outro órgão — verificar vantajosidade (art. 86 Lei 14.133)"], '
                  '"relevante": true, "resumo": "Adesão a ata de RP p/ cateter ao CBMERJ, R$ 17.156,00. Verificar vantajosidade da carona."}')


def _carregar_env_completo():
    from compliance_agent.envfile import carregar_env
    carregar_env()
    h = Path.home() / ".hermes" / ".env"
    if h.exists():
        for ln in h.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in ln and ln.split("=", 1)[0].strip().startswith(("GEMINI", "GOOGLE")):
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# Tamanho do trecho enviado ao LLM. Payloads grandes (>~5k) fazem o GATEWAY do nous cortar (502/503 =
# timeout upstream, NÃO o servidor caindo). 3500 cobre o essencial (objeto/valores/partes estão no começo).
_MAX_TXT = int(os.environ.get("SEI_FICHA_MAX_TXT", "3500"))


def _prompt(texto: str) -> list[dict]:
    # ENSINAR (few-shot): mostra 1 par TEXTO→FICHA ideal antes de pedir o real. Vira o jogo p/ modelo fraco.
    p = (f"Formato da FICHA (JSON):\n{_CAMPOS}\n\n"
         f"=== EXEMPLO ===\nTEXTO:\n{_EXEMPLO_TXT}\nFICHA:\n{_EXEMPLO_FICHA}\n\n"
         f"=== AGORA (mesmo formato) ===\nTEXTO:\n{(texto or '')[:_MAX_TXT]}\nFICHA:")
    return [{"role": "system", "content": _SIST}, {"role": "user", "content": p}]


_AUTH = Path.home() / ".hermes" / "auth.json"


def _refresh_nous_se_preciso() -> None:
    """Renova o token nous se expirado/perto (sweep roda 'aos poucos', token dura 15min). Rotaciona o
    refresh_token e PERSISTE atomicamente (senão reuse-detection revoga a sessão). Best-effort/silencioso."""
    try:
        import httpx
        d = json.loads(_AUTH.read_text(encoding="utf-8"))
        n = (d.get("providers") or {}).get("nous") or {}
        exp = n.get("expires_at")
        if exp:
            import datetime as _dt
            resta = (_dt.datetime.fromisoformat(exp) - _dt.datetime.now(_dt.timezone.utc)).total_seconds()
            if resta > 90:
                return  # ainda válido
        rt = n.get("refresh_token")
        if not rt:
            return
        r = httpx.post(f"{n.get('portal_base_url', 'https://portal.nousresearch.com')}/api/oauth/token",
                       data={"grant_type": "refresh_token", "client_id": n.get("client_id", "hermes-cli"),
                             "refresh_token": rt},
                       headers={"Accept": "application/json", "x-nous-refresh-token": rt}, timeout=30)
        if r.status_code != 200:
            return
        import datetime as _dt
        j = r.json()
        n["access_token"] = j.get("access_token", n.get("access_token"))
        if j.get("refresh_token"):
            n["refresh_token"] = j["refresh_token"]  # ROTACIONADO — persistir
        n["expires_at"] = (_dt.datetime.now(_dt.timezone.utc)
                           + _dt.timedelta(seconds=j.get("expires_in", 900))).isoformat()
        tmp = _AUTH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_AUTH)
    except Exception:
        pass


def _nous_cred() -> tuple[str, str]:
    """(access_token, inference_base_url) do auth.json — auto-renova se expirado (sweep autossuficiente)."""
    _refresh_nous_se_preciso()
    try:
        d = json.loads(_AUTH.read_text(encoding="utf-8"))
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
        # PARAMETRIZAR: stepfun/nemotron são modelos de RACIOCÍNIO — gastam tokens no campo `reasoning`
        # ANTES do `content`. max_tokens ALTO (4000) p/ caber raciocínio + JSON; cap baixo deixa content=null
        # (finish_reason 'length'). top_p conservador, temperatura baixa (extração factual).
        r = await c.post(f"{base}/chat/completions",
                         headers={"Authorization": f"Bearer {tok}"},
                         json={"model": model, "messages": _prompt(texto), "temperature": 0.1,
                               "max_tokens": 4000, "top_p": 0.9})
        if r.status_code == 401:
            raise RuntimeError("401 token nous expirado (rode `hermes` p/ re-auth)")
        r.raise_for_status()
        msg = (r.json().get("choices") or [{}])[0].get("message", {}) or {}
        # content é o normal; se vier vazio (modelo de raciocínio cortado), o JSON pode estar no reasoning.
        return msg.get("content") or msg.get("reasoning") or ""


async def extrair_ficha(texto: str, model: str, provider: str = "gemini") -> dict:
    """Extrai a ficha compacta. provider: 'gemini' (gerar_gemini) ou 'nous' (OpenAI-compat). {'_erro'} em falha.
    No nous, RETENTA erros transientes do servidor (502/503/timeout) — a infra deles oscila."""
    raw = None
    try:
        if provider == "nous":
            ult = None
            for _try in range(3):
                try:
                    raw = await _chamar_nous(texto, model)
                    break
                except Exception as e:  # noqa: BLE001
                    ult = e
                    if any(s in str(e) for s in ("502", "503", "Timeout", "ReadTimeout")):
                        await asyncio.sleep(3)  # transiente → retenta
                        continue
                    raise
            if raw is None:
                raise ult or RuntimeError("nous falhou")
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


STEPFUN = "stepfun/step-3.7-flash:free"


async def extrair_ficha_producao(texto: str, preferir_gratis: bool = True) -> tuple[dict, str]:
    """Extrator de PRODUÇÃO. preferir_gratis=True (diretriz do dono): usa o nous stepfun:free (100% grátis,
    sem limite, qualidade comprovada) — mesmo mais lento — e SÓ cai pro gemini-lite se o nous estiver fora
    (502/503 após retry). Retorna (ficha, modelo_usado)."""
    if preferir_gratis:
        f = await extrair_ficha(texto, STEPFUN, provider="nous")
        if not f.get("_erro"):
            return f, "stepfun:free"
        f = await extrair_ficha(texto, MODELO_BARATO, provider="gemini")
        return f, MODELO_BARATO + " (fallback)"
    f = await extrair_ficha(texto, MODELO_BARATO, provider="gemini")
    if not f.get("_erro"):
        return f, MODELO_BARATO
    f = await extrair_ficha(texto, STEPFUN, provider="nous")
    return f, "stepfun:free (fallback)"


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
    ("stepfun", "stepfun/step-3.7-flash:free", "nous"),     # nous 100% grátis/sem limite — ENSINADO+PARAMETRIZADO
    ("g-lite", MODELO_BARATO, "gemini"),                    # gemini free-tier de referência de qualidade
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
