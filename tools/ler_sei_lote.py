#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Leitura em LOTE de processos SEI — para rodar no **GitHub Actions** (IPs Azure passam pelo WAF do SEI-RJ,
como já acontece no SIAFE) ou no **desktop** (rede gov). Loga no SEI interno como `itkava` e popula o cache
`data/sei_cache/cdp_*.json`, que o Lex/JFN passam a usar automaticamente (24h).

Da VM (IP GCP) o WAF DROPA a conexão — por isso este lote é pensado para o Actions/desktop.

Uso:
    python tools/ler_sei_lote.py SEI-070002/008633/2022 E-12/345/2026     # processos explícitos
    python tools/ler_sei_lote.py --pendentes 30                            # 30 processos correlacionados sem cache
    python tools/ler_sei_lote.py --pendentes 50 --headful                  # janela visível (debug local)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
except Exception:
    pass

_DB = os.environ.get("JFN_DB", str(REPO / "data" / "compliance.db"))
CACHE_DIR = REPO / "data" / "sei_cache"


def _ja_em_cache(numero: str) -> bool:
    import re
    n = re.sub(r"\s+", "", numero.strip().upper()).replace("/", "_")
    return (CACHE_DIR / f"cdp_{n}.json").exists()


def _pendentes(limite: int) -> list[str]:
    """Processos SEI correlacionados (SIAFE/contratos TCE-RJ) que ainda NÃO têm cache lido."""
    con = sqlite3.connect(_DB)
    nums: list[str] = []
    for sql in (
        "SELECT DISTINCT processo FROM ob_orcamentaria_siafe WHERE processo IS NOT NULL AND processo!=''",
        "SELECT DISTINCT processo FROM contratos_tcerj WHERE processo IS NOT NULL AND processo!=''",
        "SELECT DISTINCT numero_sei FROM ordens_bancarias WHERE numero_sei IS NOT NULL AND numero_sei!=''",
    ):
        try:
            for (p,) in con.execute(sql):
                p = (p or "").strip().lstrip("*").strip()
                if p and not _ja_em_cache(p) and p not in nums:
                    nums.append(p)
                    if len(nums) >= limite:
                        con.close()
                        return nums
        except sqlite3.OperationalError:
            continue
    con.close()
    return nums


async def _rodar(numeros: list[str], headless: bool) -> dict:
    from compliance_agent.collectors import sei_cdp
    lido = erro = 0
    for i, n in enumerate(numeros, 1):
        r = await sei_cdp.ler_processo_sei_launch(n, usar_cache=True, headless=headless)
        if r.get("erro") and not (r.get("texto") or r.get("conteudo_documentos")):
            erro += 1
            print(f"[{i}/{len(numeros)}] ✗ {n}: {str(r.get('erro'))[:90]}")
        else:
            lido += 1
            nd = len(r.get("conteudo_documentos", []) or [])
            print(f"[{i}/{len(numeros)}] ✓ {n}: {len(r.get('texto',''))} chars, {nd} doc(s) lidos")
    return {"total": len(numeros), "lido": lido, "erro": erro}


def main():
    ap = argparse.ArgumentParser(description="Leitura em lote de processos SEI (Actions/desktop).")
    ap.add_argument("processos", nargs="*", help="números de processo SEI a ler")
    ap.add_argument("--pendentes", type=int, metavar="N", help="ler N processos correlacionados ainda sem cache")
    ap.add_argument("--headful", action="store_true", help="janela visível (debug local)")
    ap.add_argument("--diagnostico", action="store_true",
                    help="só testa se o egress (proxy) chega ao SEI — não lê processo nem loga")
    a = ap.parse_args()

    if a.diagnostico:
        from compliance_agent.collectors.sei_cdp import testar_acesso
        r = asyncio.run(testar_acesso(headless=not a.headful))
        rotulo = {"OK_LOGIN": "✅ egress ACEITO — chegou na tela de login",
                  "WAF_BLOCK": "🔴 WAF bloqueou (página de bloqueio)",
                  "TIMEOUT_DROP": "🔴 conexão dropada/timeout (WAF blackhole ou proxy morto)",
                  "CAPTCHA": "🟡 caiu em CAPTCHA (pesquisa pública, não no login interno)",
                  "DESCONHECIDO": "🟡 respondeu, mas sem tela de login reconhecível",
                  "ERRO": "⚠ erro inesperado"}.get(r["estado"], r["estado"])
        print(f"Proxy: {r['proxy'] or '(nenhum — egress direto da máquina)'}")
        print(f"HTTP: {r['http_status']} | Estado: {rotulo}")
        if r.get("_amostra"):
            print(f"Amostra: {r['_amostra'][:160]}")
        print("\n→ Se 'WAF_BLOCK'/'TIMEOUT' SEM proxy e 'OK_LOGIN' COM proxy, o proxy resolve o gargalo.")
        return

    numeros = list(a.processos)
    if a.pendentes:
        numeros += _pendentes(a.pendentes)
    if not numeros:
        print("Nada a ler. Passe números ou use --pendentes N."); return

    if not os.environ.get("SEI_PASS"):
        print("⚠ SEI_PASS não definido (.env ou secret). Sem login interno o WAF/CAPTCHA barra a leitura.")
    _proxy = os.environ.get("SEI_PROXY_URL") or os.environ.get("PROXY_URL")
    if _proxy:
        from urllib.parse import urlparse
        _h = urlparse(_proxy).hostname or "?"
        print(f"🌐 Proxy ativo p/ o SEI (via {_h}) — rota residencial BR p/ contornar o WAF da VM.")
    else:
        print("ℹ Sem PROXY_URL/SEI_PROXY_URL: da VM (IP GCP) o WAF do SEI dropa a conexão. "
              "Defina PROXY_URL=http://user:pass@host:porta no .env p/ rotear por IP residencial.")

    res = asyncio.run(_rodar(numeros, headless=not a.headful))
    print(f"\nResumo: {res['lido']} lido(s), {res['erro']} erro(s) de {res['total']}. "
          f"Cache em {CACHE_DIR}")


if __name__ == "__main__":
    main()
