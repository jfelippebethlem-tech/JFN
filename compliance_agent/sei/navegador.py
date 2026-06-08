# -*- coding: utf-8 -*-
"""Navegação no SEI-RJ (Onda 5): abre um processo e lista a árvore de documentos com tipo/título.

Reusa o leitor JÁ VALIDADO (`collectors/sei_cdp.ler_processo_sei` → itkava/SIP, sem CAPTCHA; cacheia 24h),
que devolve `documentos=[{texto:título,url}]` + `conteudo_documentos=[{doc,conteudo}]`. Aqui só adaptamos
para a interface DocSEI que o extrator/varredor consomem. Honesto: erro/WAF → lista vazia + motivo.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class DocSEI:
    id: str
    titulo: str
    tipo_bruto: str
    url: str
    formato: str = "html"  # 'pdf' | 'html'
    conteudo: str = field(default="", repr=False)  # texto já extraído (1 os ~8 docs), se houver


def _run_coro(factory):
    """Roda uma corrotina mesmo se já houver loop (reusa o padrão do lex)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(lambda: asyncio.run(factory())).result()
    return asyncio.run(factory())


def _formato(url: str) -> str:
    return "pdf" if ".pdf" in (url or "").lower() else "html"


def abrir_processo(numero: str, usar_cache: bool = True) -> dict:
    """Abre o processo e devolve {ok, numero, url, erro, docs:[DocSEI]}.

    `ok=False` com `erro` quando o leitor falha (WAF/sem senha/sem texto) — nunca inventa árvore."""
    try:
        from compliance_agent.collectors import sei_cdp
        integra = _run_coro(lambda: sei_cdp.ler_processo_sei(numero, usar_cache=usar_cache)) or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "numero": numero, "erro": f"leitor: {str(e)[:120]}", "docs": []}
    if integra.get("erro"):
        return {"ok": False, "numero": numero, "erro": integra["erro"], "docs": []}

    # mapeia o texto já extraído por documento (1os ~8) para anexar à DocSEI correspondente
    conteudo_por_titulo = {}
    for cd in integra.get("conteudo_documentos", []) or []:
        conteudo_por_titulo[(cd.get("doc") or "").strip()[:80]] = cd.get("conteudo") or ""

    docs = []
    for i, d in enumerate(integra.get("documentos", []) or []):
        # Onda C: 'titulo' (tipo, do title/aria-label/nó pai) é a melhor pista; 'texto' costuma ser só o número
        numero = (d.get("texto") or "").strip()
        titulo = (d.get("titulo") or d.get("title_attr") or numero).strip()
        url = d.get("url") or ""
        docs.append(DocSEI(id=str(i), titulo=titulo, tipo_bruto=numero, url=url,
                           formato=_formato(url),
                           conteudo=conteudo_por_titulo.get(numero[:80], "") or conteudo_por_titulo.get(titulo[:80], "")))
    return {"ok": True, "numero": numero, "url": integra.get("url", ""),
            "texto": integra.get("texto", ""), "docs": docs,
            "cnpjs": integra.get("cnpjs", []), "valores": integra.get("valores", [])}


def baixar(doc: DocSEI) -> str:
    """Conteúdo TEXTO do documento (o leitor já extrai o texto dos ~8 primeiros via sessão autenticada).
    Para os demais, retorna '' (o varredor prioriza os docs com preço, que estão entre os primeiros)."""
    return doc.conteudo or ""
