# -*- coding: utf-8 -*-
"""
Os REQUERIMENTOS SUGERIDOS do vault (`~/vault/requerimentos/*.md`) para o painel — só leitura.

POR QUE EXISTE. Os pedidos de informação que as investigações recomendam ("requisitar à SECID a íntegra do
matriz", "pedir via requerimento a lista de TACs") ficavam espalhados nos "próximos passos" das notas de caso.
Pedido do dono em 09/11/2026: uma aba que os reúna, por situação. Mesmo desenho da aba Casos
(`casos_vault.py`): um Markdown por item, lido em tempo de execução — nada do vault entra no repositório.

Frontmatter: `id, titulo, destinatario, caso, status, data_sugestao, prioridade, pedidos (lista), fundamento,
pendencias (lista), minuta, origem`. Nota torta (sem frontmatter, status fora da lista, arquivo ilegível) NÃO
some nem derruba a rota: entra com `status: indefinido` e o defeito descrito em `problemas` — nunca vira
"sugerido" por omissão.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

VAULT_REQ = Path(os.environ.get("JFN_VAULT_REQUERIMENTOS") or Path.home() / "vault" / "requerimentos")
STATUS = ("sugerido", "minuta", "protocolado", "respondido")
_PRIORIDADE = ("alta", "média", "baixa")
_LISTAS = ("pedidos", "pendencias")
_SLUG = re.compile(r"^[\w.\-]+$")
_CASO = re.compile(r"(?:casos/)?([\w.\-]+?)(?:\.md)?(?:\|[^\]]*)?(?:\]\])?$")


def _frontmatter(texto: str) -> tuple[dict, str, list[str]]:
    """(meta, corpo, problemas). `chave: valor` por linha; `  - item` entra na lista da chave anterior."""
    if not texto.startswith("---"):
        return {}, texto, ["sem frontmatter"]
    fim = texto.find("\n---", 3)
    if fim < 0:
        return {}, texto, ["frontmatter não fechado"]
    meta, chave = {}, None
    for linha in texto[3:fim].splitlines():
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", linha)
        if m:
            chave = m.group(1).lower()
            v = m.group(2).strip().strip('"')
            meta[chave] = v if v else []
            continue
        m = re.match(r"^\s*-\s+(.*)$", linha)
        if m and chave and isinstance(meta.get(chave), list):
            meta[chave].append(m.group(1).strip().strip('"'))
    return meta, texto[fim + 4:].lstrip("\n"), []


def _item(p: Path) -> dict:
    try:
        meta, _, problemas = _frontmatter(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        meta, problemas = {}, ["arquivo ilegível"]
    for campo in _LISTAS:
        v = meta.get(campo)
        meta[campo] = v if isinstance(v, list) else ([v] if v else [])
    txt = lambda k: meta.get(k) if isinstance(meta.get(k), str) else ""  # noqa: E731
    status = txt("status").lower()
    if status not in STATUS:
        if not problemas:
            problemas = [f"status fora da lista ({', '.join(STATUS)}): “{txt('status')}”"]
        status = "indefinido"
    m = _CASO.search(txt("caso").replace("[[", ""))
    return {
        "slug": p.stem, "id": txt("id") or p.stem, "titulo": txt("titulo") or p.stem.replace("-", " "),
        "destinatario": txt("destinatario"), "caso": m.group(1) if m else "", "status": status,
        "data_sugestao": txt("data_sugestao"), "prioridade": txt("prioridade").lower(),
        "pedidos": meta["pedidos"], "fundamento": txt("fundamento"), "pendencias": meta["pendencias"],
        "minuta": txt("minuta"), "origem": txt("origem"), "problemas": problemas,
    }


def listar() -> dict:
    if not VAULT_REQ.is_dir():
        return {"ok": False, "erro": f"pasta de requerimentos indisponível: {VAULT_REQ}"}
    itens = [_item(p) for p in sorted(VAULT_REQ.glob("*.md"))]
    ordem = lambda seq, v: seq.index(v) if v in seq else len(seq)  # noqa: E731
    itens.sort(key=lambda i: (ordem(STATUS, i["status"]), ordem(_PRIORIDADE, i["prioridade"]), i["id"]))
    cont = {}
    for i in itens:
        cont[i["status"]] = cont.get(i["status"], 0) + 1
    return {"ok": True, "total": len(itens), "por_status": cont, "itens": itens}


def minuta(slug: str) -> dict:
    """O Markdown da minuta citada no requerimento — só `.md` DENTRO do vault (caminho relativo à raiz dele)."""
    if not _SLUG.match(slug or ""):
        return {"ok": False, "erro": "identificador de requerimento inválido"}
    p = VAULT_REQ / f"{slug}.md"
    if not p.is_file():
        return {"ok": False, "erro": "requerimento não encontrado"}
    rel = _item(p)["minuta"]
    raiz = VAULT_REQ.parent.resolve()
    alvo = (raiz / rel).resolve() if rel.endswith(".md") else None
    if not alvo or not alvo.is_relative_to(raiz) or not alvo.is_file():
        return {"ok": False, "erro": "minuta não disponível no vault"}
    from compliance_agent.casos_vault import _frontmatter as _fm_caso
    return {"ok": True, "slug": slug, "caminho": rel, "markdown": _fm_caso(alvo.read_text(encoding="utf-8"))[1]}
