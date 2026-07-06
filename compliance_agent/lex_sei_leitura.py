# -*- coding: utf-8 -*-
"""Lex — leitura da ÍNTEGRA dos processos SEI (browser/portal) + saneamento do texto.

Extraído de lex.py (split 2026-07-06); comportamento idêntico (snapshot-tested).
"""
from __future__ import annotations

from pathlib import Path

# ── Leitura da ÍNTEGRA dos processos SEI ──────────────────────────────────────

def _run_coro(factory):
    """Roda uma corrotina com segurança, mesmo dentro de um event loop (FastAPI)."""
    import asyncio
    import concurrent.futures
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            return ex.submit(lambda: asyncio.run(factory())).result()
    return asyncio.run(factory())


def _dossie_sei(numero: str) -> dict | None:
    """DOSSIÊ consolidado do processo (`data/sei_trees/` via tabela `sei_arvore`) — o que o sweep já
    destilou (ficha+cadeia+pagamentos OB). Barato, sem WAF e MENOS TOKEN que a íntegra crua → preferido.
    None se ainda não houver dossiê (cai p/ leitura ao vivo)."""
    try:
        import sqlite3
        from compliance_agent.correlacao_sei import _DB
        if not _DB.exists():
            return None
        con = sqlite3.connect(_DB)
        con.execute("PRAGMA busy_timeout=10000")
        try:
            row = con.execute(
                "SELECT txt_path, nivel_risco FROM sei_arvore "
                "WHERE numero_sei = ? OR numero_sei LIKE '%'||?||'%' "
                "ORDER BY length(numero_sei) LIMIT 1",
                (numero.strip(), numero.strip())).fetchone()
        finally:
            con.close()
        if not row or not row[0]:
            return None
        p = Path(row[0])
        if not p.exists():
            return None
        return {"numero": numero, "texto": p.read_text(encoding="utf-8"),
                "conteudo_documentos": [], "_fonte": "dossie_sei", "nivel_risco": row[1] or ""}
    except Exception:  # noqa: BLE001
        return None


def _ler_integra_sei(numero: str) -> dict:
    """Íntegra de UM processo SEI. PREFERE o dossiê consolidado (sweep já destilou — barato/sem WAF/menos
    token); só lê AO VIVO (Chrome 9222 + OCR; fallback portal) se ainda não houver dossiê. Cacheia 24h."""
    _d = _dossie_sei(numero)
    if _d:
        return _d
    res = {}
    try:
        from compliance_agent.collectors import sei_cdp
        # porta ÚNICA → reader itkava/ITERJ (sem captcha). Ver sei_cdp.ler_processo_sei.
        res = _run_coro(lambda: sei_cdp.ler_processo_sei(numero, usar_cache=True)) or {}
        if not res.get("erro") and (res.get("texto") or res.get("conteudo_documentos")):
            return res
    except Exception as exc:  # noqa: BLE001
        res = {"numero": numero, "erro": f"cdp: {str(exc)[:120]}"}
    # fallback: portal público httpx (metadados + documentos)
    try:
        from compliance_agent.collectors import sei_portal
        meta = _run_coro(lambda: sei_portal.buscar_processo(numero, usar_cache=True)) or {}
        if not meta.get("erro"):
            meta.setdefault("texto", "")
            meta.setdefault("conteudo_documentos", [])
            return meta
    except Exception:
        pass
    return res or {"numero": numero, "erro": "indisponível"}


_WAF_MARCADORES = ("web page blocked", "url you requested has been blocked", "attack id",
                   "página não encontrada", "pagina nao encontrada", "acesso negado")


def _bloqueio_rede(integra: dict) -> str:
    """Detecta página de WAF/erro (o IP da VM é barrado no SEI-RJ). Retorna motivo ou ''."""
    amostra = ((integra.get("texto", "") or "") + " " + (integra.get("title", "") or "")).lower()
    if any(m in amostra for m in _WAF_MARCADORES):
        return ("bloqueio de rede (WAF) — o IP de saída da VM (GCP) não é autorizado pelo SEI-RJ; "
                "ler de um IP permitido/proxy ou preencher o cache externamente")
    return ""


_INTERFACE_SEI = ("controle de prazos", "processos recebidos", "processos gerados", "acompanhamento especial",
                  "base de conhecimento", "blocos de assinatura", "registros - 1 a", "menu principal",
                  "controle de processos", "iniciar processo", "retorno programado")


def _eh_interface_sei(integra: dict) -> str:
    """Detecta a TELA/MENU do SEI (desktop após login) — NÃO é o inteiro teor de um processo. Foi a falha
    flagrada no Loop 1: a leitura trazia o menu ('Controle de Prazos', 'Processos recebidos (N registros)')
    e o parecer 'analisava' o menu. Conservador: ≥2 marcadores de UI co-ocorrendo."""
    amostra = ((integra.get("texto", "") or "") + " " + (integra.get("title", "") or "")).lower()
    if sum(1 for m in _INTERFACE_SEI if m in amostra) >= 2:
        return "tela/menu do SEI (não é o inteiro teor do processo) — a leitura não chegou ao documento"
    return ""


def _texto_integra(integra: dict) -> str:
    if _bloqueio_rede(integra):
        return ""  # página de bloqueio (WAF) não é conteúdo de processo
    if _eh_interface_sei(integra):
        return ""  # tela/menu do SEI não é conteúdo de processo (não vira achado/análise)
    txt = integra.get("texto", "") or ""
    for d in integra.get("conteudo_documentos", []) or []:
        txt += "\n" + (d.get("conteudo", "") or "")
    return txt


