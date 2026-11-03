# -*- coding: utf-8 -*-
"""
Os CASOS do vault (`~/vault/casos/*.md`) para o painel — os dossiês que passaram por leitura humana.

POR QUE EXISTE. O painel mostrava achado de detector (achados.db: muitos "confirmados" com score 0,3 e a
própria explicação dizendo "falso positivo a descartar") e nenhuma tela mostrava os casos que de fato foram
conferidos à mão e viraram dossiê. Pedido do dono em 03/11/2026: "uma aba dos casos confirmados".

O frontmatter das notas é heterogêneo (a gravidade aparece como `severidade`, `grau`, `gravidade` ou `risco`):
o nível sai do PRIMEIRO emoji de semáforo em qualquer um deles. Nota sem semáforo fica "sem grau" — nunca
vira verde por omissão. Cada número de processo SEI citado na nota é cruzado com o parecer do Processo 360
(`processo_avaliacao`), para o caso mostrar o que o motor diz hoje dos mesmos autos.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

VAULT_CASOS = Path(os.environ.get("JFN_VAULT_CASOS") or Path.home() / "vault" / "casos")
_DB = Path(__file__).resolve().parents[1] / "data" / "compliance.db"
_NIVEL = (("🔴", 4, "alto"), ("🟠", 3, "médio-alto"), ("🟡", 2, "médio"), ("🟢", 1, "baixo"))
_CAMPOS_GRAU = ("severidade", "grau", "gravidade", "risco")
_SEI = re.compile(r"SEI-\d{6}/\d{6}/\d{4}")
_CNPJ = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
_SLUG = re.compile(r"^[\w.\-]+$")


def _frontmatter(texto: str) -> tuple[dict, str]:
    if not texto.startswith("---"):
        return {}, texto
    fim = texto.find("\n---", 3)
    if fim < 0:
        return {}, texto
    meta = {}
    for linha in texto[3:fim].splitlines():
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", linha)
        if m:
            meta[m.group(1).lower()] = m.group(2).strip().strip('"')
    return meta, texto[fim + 4:].lstrip("\n")


def _nivel(meta: dict) -> tuple[int, str, str]:
    """(ordem, rótulo, texto do grau). Sem semáforo = 0 — "sem grau", não verde."""
    for campo in _CAMPOS_GRAU:
        v = meta.get(campo) or ""
        for emoji, ordem, rot in _NIVEL:
            if emoji in v:
                return ordem, rot, v
    return 0, "sem grau", next((meta[c] for c in _CAMPOS_GRAU if meta.get(c)), "")


def _situacao(status: str) -> str:
    s = status.lower()
    if re.search(r"conclu|encerrad|arquivad", s):
        return "concluído"
    if re.search(r"afastad|descartad|improced", s):
        return "afastado"
    if "contexto" in s:
        return "contexto"
    return "aberto"


def _resumo(meta: dict, corpo: str) -> str:
    if meta.get("resumo"):
        return meta["resumo"]
    for bloco in re.split(r"\n\s*\n", corpo):
        b = bloco.strip()
        if b and not b.startswith(("#", ">", "|", "<!--", "---", "-", "*")) and not re.match(r"[*_\s]*(relacionad|ver |veja|links?)", b, re.I):
            b = re.sub(r"\[\[(?:[^\]|]*/)?([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), b)
            return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", b))[:400]
    return ""


def _titulo(corpo: str, slug: str) -> str:
    m = re.search(r"^#\s+(.+)$", corpo, re.M)
    return m.group(1).strip() if m else slug.replace("-", " ")


def _pareceres(numeros: set[str]) -> dict[str, dict]:
    if not numeros or not _DB.exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=10)
        try:
            q = ",".join("?" * len(numeros))
            return {r[0]: {"grau": r[1], "score100": r[2], "avaliado_em": r[3]} for r in con.execute(
                f"SELECT numero_sei, grau, score100, avaliado_em FROM processo_avaliacao "  # noqa: S608
                f"WHERE numero_sei IN ({q})", sorted(numeros))}
        finally:
            con.close()
    except sqlite3.Error:
        return {}                                    # 360 indisponível: o caso aparece sem o cruzamento


def listar() -> dict:
    if not VAULT_CASOS.is_dir():
        return {"ok": False, "erro": f"pasta de casos indisponível: {VAULT_CASOS}"}
    casos, todos_sei = [], set()
    for p in sorted(VAULT_CASOS.glob("*.md")):
        try:
            texto = p.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, corpo = _frontmatter(texto)
        ordem, rot, grau_txt = _nivel(meta)
        seis = sorted(set(_SEI.findall(texto)))
        todos_sei.update(seis)
        casos.append({
            "slug": p.stem, "titulo": _titulo(corpo, p.stem), "resumo": _resumo(meta, corpo),
            "nivel": ordem, "nivel_rotulo": rot, "grau": grau_txt,
            "status": meta.get("status", ""), "situacao": _situacao(meta.get("status", "")),
            "entidade": meta.get("entidade") or meta.get("fornecedor") or meta.get("orgao") or "",
            "esfera": meta.get("esfera", ""),
            "atualizado": meta.get("atualizado") or meta.get("criado") or meta.get("aberto_em")
            or meta.get("detectado_em") or "",
            "tags": [t.strip() for t in meta.get("tags", "").strip("[]").split(",") if t.strip()],
            "fonte": meta.get("fonte", ""), "sei": seis, "cnpjs": sorted(set(_CNPJ.findall(texto)))[:12],
            "piso_siafe": "<!-- piso-siafe -->" in texto,
        })
    par = _pareceres(todos_sei)
    for c in casos:
        c["pareceres"] = [{"numero": n, **par[n]} for n in c["sei"] if n in par]
    casos.sort(key=lambda c: (-c["nivel"], c["situacao"] != "aberto", -int(re.sub(r"\D", "", c["atualizado"])[:8] or 0)))
    cont = {}
    for c in casos:
        cont[c["nivel_rotulo"]] = cont.get(c["nivel_rotulo"], 0) + 1
    return {"ok": True, "total": len(casos), "por_nivel": cont,
            "abertos": sum(c["situacao"] == "aberto" for c in casos),
            "com_parecer_360": sum(bool(c["pareceres"]) for c in casos), "casos": casos}


def nota(slug: str) -> dict:
    if not _SLUG.match(slug or ""):
        return {"ok": False, "erro": "identificador de caso inválido"}
    p = VAULT_CASOS / f"{slug}.md"
    if not p.is_file():
        return {"ok": False, "erro": "caso não encontrado"}
    meta, corpo = _frontmatter(p.read_text(encoding="utf-8"))
    return {"ok": True, "slug": slug, "meta": meta, "markdown": corpo}
