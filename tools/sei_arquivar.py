#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Íntegra SEI → ARQUIVO COMPACTO consultável (texto + fotos de medição).

    .venv/bin/python tools/sei_arquivar.py "330020/000762/2021" [--apagar-pdf]
    .venv/bin/python tools/sei_arquivar.py --dir data/sei_cache/integra_TAG

Entrada:  data/sei_cache/integra_<TAG>/NNN.pdf (+ manifest.json com os títulos,
          gravado pelo tools/sei_integra_completa.py).
Saída:    data/sei_arquivo/<TAG>/
            manifest.json   fase e tipo de CADA documento (compliance_agent/
                            sei/fases.py), linha do tempo, lacunas, modalidade
            texto/NNN_<tipo>.txt   todo o texto (PDF nativo; OCR se scan)
            fotos/NNN_pPP.jpg      páginas fotográficas PRESERVADAS (relatório
                                   fotográfico/medição — prova de execução)

Um PDF de íntegra de 20-50MB vira ~1-3MB de texto + fotos JPEG. O original por
documento pode ser apagado com --apagar-pdf (o merged INTEGRA_*.pdf fica).
Consulta canônica depois: tools/sei_consultar.py (NÃO reinventar parsing).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz

from compliance_agent.sei.fases import FASES, classificar, lacunas

RAIZ = Path(__file__).resolve().parents[1]
CACHE = RAIZ / "data" / "sei_cache"
ARQUIVO = RAIZ / "data" / "sei_arquivo"

# docs destas categorias têm as páginas preservadas como imagem (prova visual)
_TIPOS_FOTO = {"relatorio_fotografico", "medicao", "fiscalizacao"}
_MAX_FOTOS_DOC = 60
_MIN_CHARS_PAG = 200          # abaixo disso a página é candidata a scan/foto


def _texto_pdf(doc: fitz.Document) -> tuple[str, list[int]]:
    """Texto nativo por página + índices das páginas 'pobres' (scan/foto)."""
    partes, pobres = [], []
    for i, pg in enumerate(doc):
        t = pg.get_text("text").strip()
        partes.append(t)
        if len(t) < _MIN_CHARS_PAG:
            pobres.append(i)
    return "\n\n".join(p for p in partes if p), pobres


def _ocr_pdf(pdf_bytes: bytes) -> str:
    """OCR do PDF inteiro via módulo da casa (fail-open: sem OCR → '')."""
    try:
        from compliance_agent.sei.ocr_docs import ocr_documento
        return (ocr_documento(pdf_bytes, tipo="pdf") or "").strip()
    except Exception:
        return ""


def _pagina_com_imagem_grande(pg: fitz.Page) -> bool:
    try:
        area_pg = abs(pg.rect)
        for img in pg.get_image_info():
            bb = fitz.Rect(img["bbox"])
            if abs(bb) >= 0.35 * area_pg:
                return True
    except Exception:
        pass
    return False


def _salvar_foto(pg: fitz.Page, destino: Path) -> bool:
    try:
        pix = pg.get_pixmap(dpi=110, colorspace=fitz.csRGB)
        destino.write_bytes(pix.tobytes("jpeg", jpg_quality=72))
        return True
    except Exception:
        try:
            destino.with_suffix(".png").write_bytes(pix.tobytes("png"))
            return True
        except Exception:
            return False


def _slug(t: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", (t or "").lower())[:40].strip("_") or "doc"


def _modalidade(tipos: set[str]) -> str:
    if "contratacao_direta" in tipos:
        return "dispensa/inexigibilidade"
    if {"edital", "julgamento", "homologacao"} & tipos:
        return "licitacao"
    return ""


def arquivar(origem: Path, destino: Path, processo: str = "",
             apagar_pdf: bool = False, ocr: bool = True) -> dict:
    """Converte o diretório de íntegra em arquivo compacto. Idempotente."""
    origem, destino = Path(origem), Path(destino)
    (destino / "texto").mkdir(parents=True, exist_ok=True)
    (destino / "fotos").mkdir(parents=True, exist_ok=True)

    titulos = {}
    captura_completa = None   # None = manifesto antigo (não declara); True/False = novo
    total_arvore = None
    mpath = origem / "manifest.json"
    if mpath.exists():
        bruto = json.loads(mpath.read_text(encoding="utf-8"))
        # formato NOVO (grava incremental): {"docs": [...], "completo": bool, ...}
        # formato ANTIGO (lista pura) segue lido igual — 355 processos já arquivados
        if isinstance(bruto, dict):
            captura_completa = bool(bruto.get("completo"))
            total_arvore = bruto.get("total_arvore")
            bruto = bruto.get("docs") or []
        for e in bruto:
            titulos[int(e["i"])] = e.get("titulo") or e.get("contexto") or ""

    docs_saida, tipos_vistos = [], set()
    for pdf in sorted(origem.glob("[0-9][0-9][0-9]*.pdf")):
        i = int(pdf.name[:3])
        titulo = titulos.get(i, "")
        fase, tipo = classificar(titulo)
        tipos_vistos.add(tipo)
        entrada = {"i": i, "titulo": titulo, "fase": fase, "tipo": tipo,
                   "texto": "", "chars": 0, "ocr": False, "fotos": []}
        try:
            doc = fitz.open(str(pdf))
        except Exception:
            entrada["erro"] = "pdf ilegível"
            docs_saida.append(entrada)
            continue

        texto, pobres = _texto_pdf(doc)
        if ocr and len(texto) < _MIN_CHARS_PAG and doc.page_count:
            t2 = _ocr_pdf(pdf.read_bytes())
            if len(t2) > len(texto):
                texto, entrada["ocr"] = t2, True

        # PDF sem texto E sem imagem: o documento NÃO tem teor gravado. Marca neutra de
        # propósito — a causa se apurou depois (nosso insert_textbox falhava calado, ver
        # compliance_agent/sei/pdf_texto.py), e o dado não deve carregar diagnóstico.
        # Serve para REPROCESSAR: 11.901 documentos assim em 2026-07-23.
        if not texto and not any(doc[p].get_images() for p in range(doc.page_count)):
            entrada["sem_conteudo"] = True

        txt_rel = f"texto/{i:03d}_{_slug(titulo)}.txt"
        (destino / txt_rel).write_text(
            f"[{titulo}] (fase: {fase} · tipo: {tipo})\n\n{texto}",
            encoding="utf-8")
        entrada["texto"], entrada["chars"] = txt_rel, len(texto)

        # fotos: docs fotográficos inteiros; nos demais, só páginas com
        # imagem grande e pouco texto (anexo com foto de entrega, por ex.)
        paginas_foto = (range(doc.page_count) if tipo in _TIPOS_FOTO
                        else [p for p in pobres
                              if _pagina_com_imagem_grande(doc[p])])
        for p in list(paginas_foto)[:_MAX_FOTOS_DOC]:
            frel = f"fotos/{i:03d}_p{p + 1:02d}.jpg"
            if (destino / frel).exists() or _salvar_foto(doc[p], destino / frel):
                entrada["fotos"].append(frel)
        doc.close()
        docs_saida.append(entrada)
        if apagar_pdf:
            pdf.unlink(missing_ok=True)

    # INDISPONÍVEL ≠ 0 no ARQUIVO: docs que existem na árvore mas NÃO foram capturados
    # (formato raro — ZIP de PDFs, .odt, etc.) entram MARCADOS, com o título, para o
    # auditor saber que existem e buscar à mão. Sem isso sumiam sem rastro do arquivo.
    capturados = {d["i"] for d in docs_saida}
    for i, titulo in sorted(titulos.items()):
        if i in capturados:
            continue
        fase_nc, tipo_nc = classificar(titulo)
        docs_saida.append({"i": i, "titulo": titulo, "fase": fase_nc, "tipo": tipo_nc,
                           "texto": "", "chars": 0, "ocr": False, "fotos": [],
                           "nao_capturado": True})
    docs_saida.sort(key=lambda d: d["i"])

    # fases/lacunas SÓ pelos capturados: um doc não-capturado não tem conteúdo, então
    # NÃO pode fazer a fase dele parecer coberta (senão lacunas() mentiria).
    fases_presentes = {d["fase"] for d in docs_saida
                       if not d.get("nao_capturado")} - {"indefinida"}
    tem_pagamento = any(d["fase"] == "despesa" and not d.get("nao_capturado")
                        for d in docs_saida)
    # INDISPONÍVEL ≠ 0: com ZERO documento capturado não se afirma o que falta NOS AUTOS.
    # Sem esta guarda o manifesto acusava "🔴 falta Seleção (edital/julgamento)" em processo
    # que talvez tenha tudo — nós é que não baixamos nada (94 casos em 2026-07-23).
    vazio = not any(not d.get("nao_capturado") for d in docs_saida)  # sem NENHUM capturado
    # NUNCA REGREDIR: uma captura MENOR (rerun sem nada, ou cache zerado/parcial) não pode
    # apagar um arquivo que já tinha MAIS docs capturados. Cobre o caso vazio (33 órfãos em
    # 2026-07-06) E o cache zerado regredindo um parcial maior (215→menos). Re-captura
    # cresce por resume; só regride se o cache foi perdido — aí preservamos o melhor.
    cap_novos = sum(1 for d in docs_saida if not d.get("nao_capturado"))
    mdest_ant = destino / "manifest.json"
    if mdest_ant.exists():
        try:
            anterior = json.loads(mdest_ant.read_text(encoding="utf-8"))
            cap_ant = sum(1 for d in (anterior.get("docs") or [])
                          if isinstance(d, dict) and not d.get("nao_capturado"))
            if cap_ant > cap_novos:
                print(f"  preservado: {destino.name} já tinha {cap_ant} docs capturados "
                      f"(> {cap_novos} agora) — não regrido", flush=True)
                return anterior
        except (ValueError, OSError) as exc:
            print(f"  {destino.name}: manifesto anterior ilegível ({str(exc)[:40]}) "
                  "— sigo e regravo", flush=True)
    manifest = {
        "processo": processo,
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origem": str(origem),
        "modalidade": _modalidade(tipos_vistos),
        "docs": docs_saida,
        "linha_do_tempo": {f: sum(1 for d in docs_saida
                                  if d["fase"] == f and not d.get("nao_capturado"))
                           for f in FASES},
        "lacunas": [] if vazio else lacunas(fases_presentes, _modalidade(tipos_vistos),
                                            com_pagamento=tem_pagamento),
        "captura_vazia": vazio,
        # quantos documentos ficaram SEM TEOR gravado (candidatos a reprocessar)
        "sem_conteudo": sum(1 for d in docs_saida if d.get("sem_conteudo")),
        # docs da árvore não capturados (formato raro) — registrados p/ o auditor achar
        "nao_capturados": sum(1 for d in docs_saida if d.get("nao_capturado")),
        "captura_completa": captura_completa,   # None = manifesto antigo, não declarava
        "total_arvore": total_arvore,
        "fotos_total": sum(len(d["fotos"]) for d in docs_saida),
    }
    if vazio:
        manifest["aviso"] = ("Nada foi capturado desta íntegra (falha/pendência de coleta). "
                             "NÃO interpretar como processo sem documentos — reprocessar.")
    elif captura_completa is False:
        # morreu no meio: o que veio vale, mas o que FALTA nos autos ainda não se sabe
        manifest["lacunas"] = []
        manifest["aviso"] = (
            f"Captura PARCIAL ({len(docs_saida)} de {total_arvore or '?'} documentos da árvore) — "
            "download interrompido. Lacunas não afirmadas: retomar antes de concluir.")
    (destino / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def arquivar_pendentes(ocr: bool = True, apagar_pdf: bool = False) -> int:
    """Arquiva toda íntegra em data/sei_cache/integra_* ainda sem arquivo
    (ou re-baixada depois do arquivamento). Para o supervisor do sweep."""
    feitos = 0
    for origem in sorted(CACHE.glob("integra_*")):
        if not origem.is_dir() or not any(origem.glob("[0-9][0-9][0-9]*.pdf")):
            continue
        tag = origem.name.replace("integra_", "")
        destino = ARQUIVO / tag
        mdest = destino / "manifest.json"
        if mdest.exists() and mdest.stat().st_mtime >= max(
                p.stat().st_mtime for p in origem.iterdir()):
            continue
        proc = ""
        partes = tag.split("_")
        if len(partes) == 3 and all(p.isdigit() for p in partes):
            proc = f"{partes[0]}/{partes[1]}/{partes[2]}"
        m = arquivar(origem, destino, processo=proc, ocr=ocr,
                     apagar_pdf=apagar_pdf)
        feitos += 1
        print(f"arquivado {tag}: {len(m['docs'])} docs, {m['fotos_total']} fotos,"
              f" {len(m['lacunas'])} lacunas", flush=True)
    print(f"pendentes arquivadas: {feitos}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("processo", nargs="?", default="",
                    help='ex.: "330020/000762/2021"')
    ap.add_argument("--dir", default="", help="diretório integra_<TAG> direto")
    ap.add_argument("--pendentes", action="store_true",
                    help="arquiva todas as íntegras ainda não arquivadas")
    ap.add_argument("--apagar-pdf", action="store_true",
                    help="remove os NNN.pdf após converter (economia de disco)")
    ap.add_argument("--sem-ocr", action="store_true")
    args = ap.parse_args()

    if args.pendentes:
        return arquivar_pendentes(ocr=not args.sem_ocr,
                                  apagar_pdf=args.apagar_pdf)

    if args.dir:
        origem = Path(args.dir)
        tag = origem.name.replace("integra_", "")
        proc = args.processo
    else:
        if not args.processo:
            ap.error("informe o processo ou --dir")
        tag = re.sub(r"[^0-9]", "_", args.processo)
        origem = CACHE / f"integra_{tag}"
        proc = args.processo
    if not origem.is_dir():
        print(f"íntegra não encontrada: {origem} — rode antes: "
              f".venv/bin/python tools/sei_integra_completa.py \"{proc}\"")
        return 1

    m = arquivar(origem, ARQUIVO / tag, processo=proc,
                 apagar_pdf=args.apagar_pdf, ocr=not args.sem_ocr)
    print(json.dumps({"processo": m["processo"], "docs": len(m["docs"]),
                      "fotos": m["fotos_total"],
                      "modalidade": m["modalidade"] or "?",
                      "linha_do_tempo": {k: v for k, v in
                                         m["linha_do_tempo"].items() if v},
                      "lacunas": m["lacunas"],
                      "saida": str(ARQUIVO / tag)},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
