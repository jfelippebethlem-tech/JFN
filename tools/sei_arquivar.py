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
    # Inicializado AQUI, fora do `if mpath.exists()`. Antes só era definido lá dentro, e um
    # diretório de íntegra SEM `manifest.json` — o que sobra quando a captura é interrompida
    # antes de gravá-lo — estourava `UnboundLocalError` na varredura dos PDFs mais abaixo.
    # Latente no acervo de 2026-08-23 (83 diretórios com PDF, todos com manifesto), mas
    # capturas SÃO interrompidas: descoberto por um teste que montou o caso sem manifesto.
    alheios_i: set[int] = set()
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
        # DOCUMENTO DE OUTRO PROCESSO NÃO ENTRA. A íntegra do SEI às vezes traz peças alheias
        # junto: medido em 2026-07-29, `080001/000744/2024` (R$ 51,6 mi, repasse do Fundo
        # Estadual de Saúde) recebeu 24 documentos de 22 outros processos — despacho da
        # Educação sobre frequência de colégio, correspondências de RH, assinaturas de
        # merendeira e de PM —, e o dossiê atribuiu tudo àquele processo, RESPONSÁVEIS
        # inclusive. O manifest já sabia de quem era cada um, no campo `contexto`.
        # Documento SEM número no contexto FICA: ausência de dado não prova que é alheio, e
        # descartá-lo trocaria contaminação por perda silenciosa.
        if processo:
            from compliance_agent.sei.documentos_alheios import separar_alheios
            sep = separar_alheios(bruto, processo)
            if sep["alheios"]:
                de_quem = ", ".join(f"{k} ({v})" for k, v in
                                    sorted(sep["por_processo_alheio"].items(), key=lambda kv: -kv[1])[:3])
                print(f"  {destino.name}: {len(sep['alheios'])} documento(s) de OUTRO processo "
                      f"fora do arquivo — {de_quem}")
                alheios_i = {int(e["i"]) for e in sep["alheios"] if str(e.get("i", "")).isdigit()}
            else:
                alheios_i = set()
            bruto = sep["proprios"]
        else:
            alheios_i = set()
        for e in bruto:
            titulos[int(e["i"])] = e.get("titulo") or e.get("contexto") or ""

    docs_saida, tipos_vistos = [], set()
    for pdf in sorted(origem.glob("[0-9][0-9][0-9]*.pdf")):
        i = int(pdf.name[:3])
        if i in alheios_i:      # peça de outro processo: não vira texto nem entra no manifest
            continue
        titulo = titulos.get(i, "")
        fase, tipo = classificar(titulo)
        tipos_vistos.add(tipo)
        entrada = {"i": i, "titulo": titulo, "fase": fase, "tipo": tipo,
                   "texto": "", "chars": 0, "ocr": False, "fotos": []}

        # RETOMADA INCREMENTAL — sem isto, processo grande NUNCA completa.
        # Medido em 2026-08-23 no `080002/019206/2025` (40 PDFs): o disparo refazia do `000.pdf`
        # a cada vez e o `timeout 1500` do lane cortava por volta do 13º. Os txt de 000-012
        # apareciam reescritos com hora nova a cada disparo — trabalho refeito e jogado fora, e
        # NADA no log denunciava: cada disparo parecia progresso. Reaproveitar o texto já extraído
        # torna o trabalho monotônico; o disparo seguinte continua de onde o anterior parou.
        # O OCR é o custo (minutos por PDF de imagem); ler o txt de volta custa microssegundos.
        pronto = next(destino.glob(f"texto/{i:03d}_*.txt"), None)
        if pronto is not None and pronto.stat().st_mtime >= pdf.stat().st_mtime:
            try:
                bruto_txt = pronto.read_text("utf-8", errors="ignore")
                # o arquivo guarda `[titulo] (fase: X · tipo: Y)\n\n<texto>`; o corpo é o que
                # vem depois do cabeçalho — é ele que conta para `chars`.
                corpo = bruto_txt.split("\n\n", 1)[1] if "\n\n" in bruto_txt else ""
                entrada["texto"] = f"texto/{pronto.name}"
                entrada["chars"] = len(corpo)
                entrada["reaproveitado"] = True
                entrada["fotos"] = sorted(
                    f"fotos/{f.name}" for f in destino.glob(f"fotos/{i:03d}_p*.jpg"))
                docs_saida.append(entrada)
                continue
            except OSError:
                pass    # txt ilegível: cai no caminho normal e reextrai

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
                # TOCAR O MTIME AO PRESERVAR. Manter o antigo é a decisão certa, mas ela não
                # mexia no manifesto — e `arquivar_pendentes` monta a fila por "cache mais novo
                # que o manifesto". Resultado medido em 2026-08-23: o `030001_087722_2024`
                # reaparecia em TODO disparo do lane, e o OCR dos 319 PDFs rodava ANTES da
                # decisão de preservar. Com `timeout 1500`, os dois primeiros processos comiam
                # os 25 min e o lane terminava em 124 sem NUNCA alcançar o resto da fila — o
                # `080002/019206/2025` ficou 3 disparos sem ser tocado por isso.
                # Mesmo bug, mesmo conserto que `sei_arquivar_do_cache` já aplicara em
                # 2026-08-15: o irmão foi corrigido, este não. O conteúdo não muda.
                try:
                    mdest_ant.touch()
                except OSError:
                    pass
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
    # ORDEM POR CUSTO, NÃO ALFABÉTICA. Medido em 2026-08-23: a fila tinha 10 processos e o
    # primeiro em ordem alfabética (`070002_005897_2024`) traz 741 PDFs / 548 MB — sozinho ele
    # estoura o `timeout 1500` do lane, e o `080002/019206/2025` (3º, 40 PDFs) nunca era
    # alcançado. Alfabético não é prioridade: é sorteio pelo nome. Menor primeiro faz a fila
    # ANDAR — os grandes passam quando sobrarem sozinhos, e nenhum fica preso atrás deles.
    def _peso(d: Path) -> tuple:
        try:
            return (sum(p.stat().st_size for p in d.glob("[0-9][0-9][0-9]*.pdf")), d.name)
        except OSError:
            return (0, d.name)

    for origem in sorted((d for d in CACHE.glob("integra_*") if d.is_dir()), key=_peso):
        if not any(origem.glob("[0-9][0-9][0-9]*.pdf")):
            continue
        tag = origem.name.replace("integra_", "")
        # TAG MALFORMADA: resíduo do bug do prefixo `SEI-` (`integra_____080002_...`), corrigido
        # em `sei_integra_completa.py` mas com diretórios antigos ainda no cache. Sem esta guarda
        # o lane tentaria arquivá-los em TODO disparo e criaria `sei_arquivo/____080002_...` —
        # lixo novo a partir de lixo velho. Os processos reais já estão arquivados sob o slug
        # correto; o cache órfão fica onde está (apagar dado não é chamada de quem repara).
        if not (len(tag.split("_")) == 3 and all(x.isdigit() for x in tag.split("_"))):
            print(f"  ignorado (slug malformado, resíduo do prefixo SEI-): {origem.name}", flush=True)
            continue
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
