# -*- coding: utf-8 -*-
"""Coletor de PPPs/concessões da **CCPAR** (Companhia Carioca de Parcerias) — fonte E.

A CCPAR (`ccpar.rio`) conduz as PPPs do Município do Rio. Cada projeto tem uma
página server-rendered em ``/mapa/{slug}/`` com: fases do andamento, datas, valor
de investimento e **links diretos de documentos** (edital, contrato, anexos) no
CDN ``api.mziq.com/mzfilemanager/...`` — captáveis sem reverse-engineer de API.

Uso (CLI):
    python -m compliance_agent.pcrj.ppp_ccpar complexo-hospitalar-souza-aguiar

A parte de rede (``coletar_projeto``) é fina; o miolo (``parsear_projeto``) é puro
e testado. O cruzamento com o vencedor/contraprestação/processo (que vêm do D.O.,
não da CCPAR) é feito no dossiê (F4), não aqui — cada fonte guarda só o que sabe.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from . import db

BASE = "https://www.ccpar.rio"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# fases canônicas de uma PPP (ordem), usadas p/ inferir a fase corrente do texto
_FASES = [
    "Autorização de PMI / MIP", "Estudos", "Consulta Pública", "Audiência Pública",
    "Edital", "Leilão", "Assinatura do Contrato",
]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def parsear_projeto(html: str, slug: str) -> dict:
    """Extrai fatos de uma página de projeto da CCPAR. Puro (sem rede) → testável."""
    s = BeautifulSoup(html, "html.parser")
    titulo = s.find("title")
    nome = (titulo.get_text(strip=True).split(" - ")[0] if titulo else slug).strip()
    corpo = s.get_text(" ", strip=True)

    # documentos: links diretos do mzfilemanager, com rótulo do próprio link
    docs, vistos = [], set()
    for a in s.find_all("a", href=True):
        href = a["href"]
        if "mziq.com" not in href or href in vistos:
            continue
        vistos.add(href)
        lbl = a.get_text(" ", strip=True) or a.get("title") or a.get("aria-label") or ""
        docs.append({"titulo": lbl[:120], "url": href})

    # datas dd/mm/aaaa e valor de investimento
    datas = sorted(set(re.findall(r"\b\d{2}/\d{2}/20\d{2}\b", corpo)))
    m_inv = re.search(r"R\$\s?([\d\.,]+)\s?(bilh|bi|milh|mi)", corpo, re.I)
    investimento = None
    if m_inv:
        val = float(m_inv.group(1).replace(".", "").replace(",", "."))
        investimento = val * (1_000_000_000 if m_inv.group(2).lower().startswith("b") else 1_000_000)

    # fase corrente: última fase canônica mencionada como concluída/andamento
    fases_vistas = [f for f in _FASES if re.search(re.escape(f.split(" /")[0]), corpo, re.I)]
    concluido = bool(re.search(r"conclu[íi]do", corpo, re.I))
    fase_corrente = fases_vistas[-1] if fases_vistas else None

    return {
        "slug": slug, "nome": nome, "orgao_gestor": "CCPAR",
        "objeto": None, "modalidade": None,
        "fase": fase_corrente, "concluido": concluido,
        "valor_investimento": investimento,
        "datas": datas, "docs": docs,
    }


def coletar_projeto(slug: str, *, db_path=None,
                    client: Optional[httpx.Client] = None) -> dict:
    """Baixa e persiste um projeto de PPP da CCPAR em ``pcrj_ppp``. Idempotente (UPSERT por slug)."""
    own = client is None
    cli = client or httpx.Client(headers={"User-Agent": UA}, timeout=40, follow_redirects=True)
    try:
        r = cli.get(f"{BASE}/mapa/{slug}/")
        r.raise_for_status()
        info = parsear_projeto(r.text, slug)
    finally:
        if own:
            cli.close()

    db.inicializar(db_path)
    con = db.conectar(db_path)
    try:
        con.execute(
            """INSERT INTO pcrj_ppp
               (slug,nome,orgao_gestor,objeto,modalidade,fase,valor_investimento,
                contraprestacao,prazo_anos,vencedor,numero_processo,datas_json,docs_json,coletado_em)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(slug) DO UPDATE SET
                 nome=excluded.nome, fase=excluded.fase,
                 valor_investimento=excluded.valor_investimento,
                 datas_json=excluded.datas_json, docs_json=excluded.docs_json,
                 coletado_em=excluded.coletado_em""",
            (info["slug"], info["nome"], info["orgao_gestor"], info["objeto"],
             info["modalidade"], info["fase"], info["valor_investimento"],
             None, None, None, None,
             json.dumps(info["datas"], ensure_ascii=False),
             json.dumps(info["docs"], ensure_ascii=False), _now()),
        )
        con.commit()
    finally:
        con.close()
    info["n_docs"] = len(info["docs"])
    return info


def _texto_pdf(blob: bytes, max_paginas: int = 80) -> str:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(blob))
    return "\n".join((p.extract_text() or "") for p in r.pages[:max_paginas])


def _prioridade_pdf(nome: str) -> int:
    """Ordem de relevância jurídica: edital → minuta de contrato → caderno de encargos → resto."""
    ln = nome.lower()
    if "edital" in ln and "anexo" not in ln:
        return 0
    if "minuta" in ln and "contrato" in ln:
        return 1
    if "contrato" in ln:
        return 2
    if "encargos" in ln:
        return 3
    return 4


def _docs_de_zip(blob: bytes, max_docs: int = 6) -> list[tuple[str, str]]:
    """Extrai texto dos PDFs do ZIP, priorizando os juridicamente relevantes.

    A leitura completa importa: cláusulas como a garantia via Fundo Nacional de Saúde
    vivem na MINUTA DE CONTRATO, não no edital principal — ler só um PDF cega a análise.
    """
    z = zipfile.ZipFile(io.BytesIO(blob))
    pdfs = sorted((n for n in z.namelist() if n.lower().endswith(".pdf")), key=_prioridade_pdf)
    docs = []
    for nome in pdfs[:max_docs]:
        try:
            docs.append((nome.split("/")[-1], _texto_pdf(z.read(nome))))
        except Exception:  # noqa: BLE001 — um PDF ruim não derruba os outros
            continue
    return docs


def ingerir_edital(slug: str, *, db_path=None,
                   client: Optional[httpx.Client] = None) -> dict:
    """Baixa o doc 'EDITAL' do projeto (ZIP ou PDF), extrai o texto e guarda em ``pcrj_processo_doc``.

    É o que torna a triagem cláusula-a-cláusula durável: o dossiê passa a analisar as
    cláusulas de habilitação reais, não só o extrato de contrato do D.O.
    """
    db.inicializar(db_path)
    con = db.conectar(db_path)
    try:
        row = con.execute("SELECT docs_json FROM pcrj_ppp WHERE slug=?", (slug,)).fetchone()
        docs = json.loads(row["docs_json"]) if row and row["docs_json"] else []
    finally:
        con.close()
    edital = next((d for d in docs if "EDITAL" in (d.get("titulo") or "").upper()), None)
    if not edital:
        return {"slug": slug, "erro": "nenhum documento de edital em pcrj_ppp.docs_json"}

    own = client is None
    cli = client or httpx.Client(headers={"User-Agent": UA}, timeout=300, follow_redirects=True)
    try:
        r = cli.get(edital["url"])
        r.raise_for_status()
        blob, ctype = r.content, r.headers.get("content-type", "")
    finally:
        if own:
            cli.close()

    if "zip" in ctype or blob[:2] == b"PK":
        docs = _docs_de_zip(blob)
    else:
        docs = [((edital.get("titulo") or "edital.pdf"), _texto_pdf(blob))]
    docs = [(n, t) for n, t in docs if (t or "").strip()]
    if not docs:
        return {"slug": slug, "erro": "não extraí texto de nenhum PDF do documento"}

    con = db.conectar(db_path)
    try:
        for seq, (nome, texto) in enumerate(docs):
            con.execute(
                """INSERT INTO pcrj_processo_doc (numero_processo,seq,tipo,titulo,texto,url,coletado_em)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(numero_processo,seq) DO UPDATE SET
                     titulo=excluded.titulo, texto=excluded.texto, coletado_em=excluded.coletado_em""",
                (slug, seq, "edital_ccpar", nome, texto, edital["url"], _now()),
            )
        con.commit()
    finally:
        con.close()
    return {"slug": slug, "docs": [n for n, _ in docs], "n_docs": len(docs),
            "chars": sum(len(t) for _, t in docs), "url": edital["url"]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Coletor de PPP da CCPAR (ccpar.rio).")
    ap.add_argument("slug", help="slug do projeto, ex.: complexo-hospitalar-souza-aguiar")
    ap.add_argument("--ingerir-edital", action="store_true",
                    help="baixa o edital (ZIP/PDF) e guarda o texto em pcrj_processo_doc")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    if a.ingerir_edital:
        print(json.dumps(ingerir_edital(a.slug, db_path=a.db), ensure_ascii=False, indent=2))
        return
    info = coletar_projeto(a.slug, db_path=a.db)
    info["docs"] = f"{len(info['docs'])} documentos"  # resumo no print
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
