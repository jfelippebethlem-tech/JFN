"""
Coletor de Dados Abertos do Estado do RJ — via API CKAN (sem Chrome, sem CAPTCHA).

POR QUE ESTE MÓDULO EXISTE
──────────────────────────
SIAFE2/DOERJ/SEI exigem Chrome (CDP) e, no SEI, CAPTCHA. Mas o Estado do RJ
também publica MUITO dado estruturado em portais CKAN e de transparência que
respondem por HTTP simples — sem navegador, sem CAPTCHA, sem rate-limit agressivo:

  • https://dadosabertos.rj.gov.br        — portal CKAN do Estado (datasets gerais)
  • https://www.transparencia.rj.gov.br   — despesas, fornecedores, contratos
  • https://portal.fazenda.rj.gov.br/transparencia/dados-abertos/ — fonte SIAFE

CKAN expõe uma API REST padronizada:
  GET /api/3/action/package_search?q=<termo>        → busca datasets
  GET /api/3/action/package_show?id=<id>            → detalhe + recursos (CSV/JSON)
  GET /api/3/action/datastore_search?resource_id=…  → linhas tabulares (se houver datastore)

Este coletor é COMPLEMENTAR ao scraping: dá ao agente uma fonte de dados
limpa para cruzar com o que vem do SIAFE2/DOERJ, e funciona mesmo quando o
Chrome não está disponível.

Uso (standalone):
    python -m compliance_agent.collectors.dados_abertos_rj "despesa"
    python -m compliance_agent.collectors.dados_abertos_rj "doerj"
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

CKAN_BASE = "https://dadosabertos.rj.gov.br"
_TIMEOUT = 30

# Header sem acentos: httpx codifica headers em latin-1/ascii e quebra com 'ú'.
_HEADERS = {
    "User-Agent": "JFN-Compliance-Agent/1.0 (auditoria publica RJ)",
    "Accept": "application/json",
}


CDP_URL = "http://127.0.0.1:9222"


def _monta_url(base: str, action: str, params: dict) -> str:
    from urllib.parse import urlencode
    qs = urlencode(params)
    return f"{base}/api/3/action/{action}" + (f"?{qs}" if qs else "")


async def _fetch_via_chrome(url: str) -> dict:
    """
    Fallback: faz fetch() de uma URL JSON DENTRO do Chrome 9222 já aberto.
    Como é um navegador real (com cookies/JS), passa pelo WAF que bloqueia
    clientes HTTP simples — mesmo princípio do coletor do DOERJ.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        return {"erro": f"playwright indisponível: {e}"}

    p = None
    try:
        p = await async_playwright().start()
        browser = await p.chromium.connect_over_cdp(CDP_URL, timeout=15000)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        # Executa fetch no contexto da página (real browser → passa WAF)
        js = """
            async (u) => {
                try {
                    const r = await fetch(u, {headers: {'Accept': 'application/json'}});
                    const t = await r.text();
                    return {status: r.status, body: t};
                } catch (e) { return {status: 0, body: String(e)}; }
            }
        """
        res = await page.evaluate(js, url)
        status = res.get("status", 0)
        body = res.get("body", "")
        if status != 200:
            return {"erro": f"HTTP {status} via Chrome"}
        import json as _json
        try:
            return {"ok": True, "json": _json.loads(body)}
        except Exception:
            return {"erro": "resposta não-JSON via Chrome"}
    except Exception as e:
        return {"erro": f"CDP indisponível: {type(e).__name__}: {e}"}
    finally:
        if p:
            try:
                await p.stop()
            except Exception:
                pass


async def _ckan_get(action: str, params: dict, base: str = CKAN_BASE) -> dict:
    """
    Chama uma action da API CKAN e devolve o campo 'result'.
    Tenta HTTP direto; se o WAF bloquear (403), cai para fetch via Chrome 9222.
    """
    url = f"{base}/api/3/action/{action}"
    # 1) HTTP direto
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS,
                                     follow_redirects=True) as c:
            r = await c.get(url, params=params)
            if r.status_code == 200:
                data = r.json()
                if data.get("success"):
                    return {"ok": True, "result": data.get("result")}
                return {"erro": f"CKAN success=false em {action}"}
            # 403/429/etc → tenta o navegador
            http_erro = f"HTTP {r.status_code} em {action}"
    except Exception as e:
        http_erro = f"{type(e).__name__}: {e}"

    # 2) Fallback stealth via Scrapling (rapido, passa WAF SEM Chrome)
    try:
        from compliance_agent.collectors._scrapling_fetch import get_json
        data = get_json(_monta_url(base, action, params))
        if isinstance(data, dict) and data.get("success"):
            return {"ok": True, "result": data.get("result"), "_via": "scrapling"}
    except Exception:
        pass

    # 3) Fallback via Chrome (ultimo recurso, passa WAF)
    via = await _fetch_via_chrome(_monta_url(base, action, params))
    if via.get("ok"):
        data = via["json"]
        if data.get("success"):
            return {"ok": True, "result": data.get("result"), "_via": "chrome"}
        return {"erro": f"CKAN success=false em {action} (via Chrome)"}
    return {"erro": f"{http_erro}; fallback Chrome: {via.get('erro')}"}


async def buscar_datasets(termo: str, limite: int = 10,
                          base: str = CKAN_BASE) -> dict:
    """
    Busca datasets por termo (ex.: 'despesa', 'doerj', 'contrato', 'servidor').
    Retorna lista de datasets com título, nome, organização e recursos (CSV/JSON).
    """
    res = await _ckan_get("package_search",
                          {"q": termo, "rows": limite}, base=base)
    if res.get("erro"):
        return res
    result = res["result"] or {}
    datasets = []
    for pkg in result.get("results", []):
        recursos = [{
            "nome": r.get("name") or r.get("description") or "",
            "formato": (r.get("format") or "").upper(),
            "url": r.get("url", ""),
            "resource_id": r.get("id", ""),
            "datastore_active": bool(r.get("datastore_active")),
        } for r in pkg.get("resources", [])]
        datasets.append({
            "titulo": pkg.get("title", ""),
            "nome": pkg.get("name", ""),
            "organizacao": (pkg.get("organization") or {}).get("title", ""),
            "notas": (pkg.get("notes") or "")[:300],
            "n_recursos": len(recursos),
            "recursos": recursos,
        })
    return {
        "ok": True,
        "total": result.get("count", len(datasets)),
        "retornados": len(datasets),
        "datasets": datasets,
    }


async def listar_recursos(dataset_id: str, base: str = CKAN_BASE) -> dict:
    """Detalhe de um dataset: lista seus recursos (arquivos) com URLs."""
    res = await _ckan_get("package_show", {"id": dataset_id}, base=base)
    if res.get("erro"):
        return res
    pkg = res["result"] or {}
    recursos = [{
        "nome": r.get("name") or r.get("description") or "",
        "formato": (r.get("format") or "").upper(),
        "url": r.get("url", ""),
        "resource_id": r.get("id", ""),
        "datastore_active": bool(r.get("datastore_active")),
    } for r in pkg.get("resources", [])]
    return {
        "ok": True,
        "titulo": pkg.get("title", ""),
        "organizacao": (pkg.get("organization") or {}).get("title", ""),
        "recursos": recursos,
    }


async def consultar_datastore(resource_id: str, termo: str = "",
                              limite: int = 50, base: str = CKAN_BASE) -> dict:
    """
    Consulta linhas tabulares de um recurso com datastore ativo.
    'termo' faz busca full-text nas linhas (opcional).
    """
    params: dict = {"resource_id": resource_id, "limit": limite}
    if termo:
        params["q"] = termo
    res = await _ckan_get("datastore_search", params, base=base)
    if res.get("erro"):
        return res
    result = res["result"] or {}
    campos = [f.get("id") for f in result.get("fields", [])]
    registros = result.get("records", [])
    return {
        "ok": True,
        "total": result.get("total", len(registros)),
        "campos": campos,
        "registros": registros[:limite],
    }


async def baixar_recurso_csv(url: str, max_linhas: int = 500) -> dict:
    """
    Baixa um recurso CSV/JSON e devolve as primeiras linhas como texto bruto.
    Útil quando o recurso NÃO tem datastore ativo (só o arquivo).
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS,
                                     follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            texto = r.text
        linhas = texto.splitlines()
        return {
            "ok": True,
            "n_linhas": len(linhas),
            "cabecalho": linhas[0] if linhas else "",
            "amostra": linhas[:max_linhas],
        }
    except Exception as e:
        return {"erro": f"{type(e).__name__}: {e}"}


# ── Atalho de alto nível para o agente ────────────────────────────────────────

async def pesquisar(termo: str, limite: int = 8) -> dict:
    """
    Pesquisa de alto nível: busca datasets e, se o primeiro tiver datastore
    ativo, já traz uma amostra das linhas. É a função que o agente usa.
    """
    busca = await buscar_datasets(termo, limite=limite)
    if busca.get("erro"):
        return busca

    amostra = None
    for ds in busca.get("datasets", []):
        for rec in ds.get("recursos", []):
            if rec.get("datastore_active") and rec.get("resource_id"):
                amostra = await consultar_datastore(rec["resource_id"], limite=10)
                amostra["_dataset"] = ds["titulo"]
                amostra["_recurso"] = rec["nome"]
                break
        if amostra:
            break

    return {
        "ok": True,
        "termo": termo,
        "total_datasets": busca.get("total", 0),
        "datasets": [
            {"titulo": d["titulo"], "org": d["organizacao"],
             "n_recursos": d["n_recursos"],
             "formatos": sorted({r["formato"] for r in d["recursos"] if r["formato"]})}
            for d in busca.get("datasets", [])
        ],
        "amostra_linhas": amostra,
    }


if __name__ == "__main__":
    import json
    import sys
    termo = sys.argv[1] if len(sys.argv) > 1 else "despesa"
    out = asyncio.run(pesquisar(termo))
    print(json.dumps(out, ensure_ascii=False, indent=2)[:4000])
