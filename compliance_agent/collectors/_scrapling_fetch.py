"""Fetch stealth reutilizavel (Scrapling) — melhora os sweeps.

POR QUE: os sweeps caem pro Chrome 9222 (browser real, lento e que desconecta/quebra)
quando o WAF bloqueia o httpx simples. O Scrapling impersona um browser no nivel
TLS/HTTP e passa o WAF SEM navegador — mais rapido (~0.2s medido) e sem a fragilidade
do Chrome CDP. Este helper e um drop-in: Scrapling -> (se indisponivel) httpx.

Uso nos collectors:
    from compliance_agent.collectors._scrapling_fetch import get_json, get_text
    dados = get_json(url)          # dict
    status, html = get_text(url)   # (int, str)
"""
from __future__ import annotations

import json as _json


def get_text(url: str, timeout: int = 30) -> tuple[int, str]:
    """Retorna (status, texto). Tenta Scrapling stealth; cai pra httpx se falhar."""
    # 1) Scrapling (rapido + stealth, passa WAF sem Chrome)
    try:
        from scrapling.fetchers import Fetcher
        r = Fetcher.get(url, timeout=timeout)
        b = getattr(r, "body", b"")
        txt = b.decode("utf-8", "ignore") if isinstance(b, (bytes, bytearray)) else str(b)
        st = int(getattr(r, "status", 0) or 0)
        if st and txt:
            return (st, txt)
    except Exception:
        pass
    # 2) fallback httpx (jeito antigo)
    import httpx
    r = httpx.get(url, timeout=timeout, follow_redirects=True,
                  headers={"User-Agent": "Mozilla/5.0 (JFN auditoria)", "Accept": "application/json, */*"})
    return (r.status_code, r.text)


def get_json(url: str, timeout: int = 30) -> dict:
    """Busca e faz parse JSON. Retorna dict (com _status/_raw se nao for JSON)."""
    st, txt = get_text(url, timeout)
    try:
        return _json.loads(txt)
    except Exception:
        return {"_status": st, "_raw": txt[:500], "_erro": "resposta nao-JSON"}


if __name__ == "__main__":
    import sys, time
    u = sys.argv[1] if len(sys.argv) > 1 else "https://dadosabertos.rj.gov.br/api/3/action/package_search?q=despesa&rows=2"
    t = time.time()
    st, txt = get_text(u)
    print(f"status={st} tempo={time.time()-t:.2f}s len={len(txt)} json_ok={'success' in txt or 'result' in txt}")
