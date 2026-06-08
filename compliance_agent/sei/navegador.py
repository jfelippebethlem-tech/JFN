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
    # processos relacionados (a CADEIA: licitação↔contrato↔empenho/pagamento) — base do índice
    import re as _re
    relacionados = []
    for r in integra.get("relacionados", []) or []:
        txt = (r.get("texto") or "") + " " + (r.get("titulo") or "")
        m = _re.search(r"(SEI[- ]?\S+|E-\d[\w./-]+|\d{2}[./]\d{3,}[\w./-]*)", txt)
        relacionados.append({"numero": m.group(1).strip() if m else (r.get("texto") or "").strip(),
                             "titulo": (r.get("titulo") or "").strip(), "url": r.get("url") or ""})
    # diagnóstico honesto quando 0 docs: distinguir RED FLAG (acesso restrito) de falha técnica (busca)
    texto = integra.get("texto", "") or ""
    url = integra.get("url", "") or ""
    low = texto.lower()
    # CADEADO (ícone — sinal mais confiável que o texto) OU marcadores textuais
    cadeado = bool(integra.get("cadeado"))
    acesso_restrito = cadeado or any(m in low for m in (
        "acesso restrito", "nivel de acesso", "nível de acesso", "documento restrito",
        "processo sigiloso", "credencial de acesso"))
    # "Nenhum resultado encontrado" = o processo NÃO foi localizado pela busca (nº ruidoso da OB,
    # processo fora do escopo de acesso da unidade itkava/ITERJ, ou inexistente) — NÃO é falha técnica.
    sem_resultado = any(m in low for m in ("nenhum resultado encontrado", "nenhum registro", "não encontrado"))
    motivo_zero = ""
    if not docs:
        if acesso_restrito:
            motivo_zero = "acesso_restrito"  # 🔴 red flag se já há OB paga (deveria ser público)
        elif sem_resultado:
            motivo_zero = "nenhum_resultado"  # processo não localizado/acessível pela unidade (ou nº ruidoso)
        elif "protocolo_pesquisar" in url or "iniciar processo" in low:
            motivo_zero = "busca_nao_resolveu"  # ficou na tela de pesquisa — falha técnica do reader
        else:
            motivo_zero = "arvore_vazia"
    return {"ok": True, "numero": numero, "url": url, "texto": texto,
            "docs": docs, "relacionados": relacionados,
            "acesso_restrito": acesso_restrito, "cadeado": cadeado,
            "n_docs_restritos": int(integra.get("n_docs_restritos") or 0), "motivo_zero": motivo_zero,
            "cnpjs": integra.get("cnpjs", []), "valores": integra.get("valores", [])}


def baixar(doc: DocSEI) -> str:
    """Conteúdo TEXTO do documento (o leitor já extrai o texto dos ~8 primeiros via sessão autenticada).
    Para os demais, retorna '' (o varredor prioriza os docs com preço, que estão entre os primeiros)."""
    return doc.conteudo or ""
