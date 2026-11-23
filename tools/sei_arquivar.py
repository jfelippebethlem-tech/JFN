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

import logging
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz

from compliance_agent.sei.fases import FASES, classificar, lacunas

logger = logging.getLogger(__name__)

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


def _ocr_pdf(pdf_bytes: bytes, completar_mistas: bool = False) -> str:
    """OCR do PDF inteiro via módulo da casa (fail-open: sem OCR → '')."""
    try:
        from compliance_agent.sei.ocr_docs import ocr_documento
        return (ocr_documento(pdf_bytes, tipo="pdf", completar_mistas=completar_mistas) or "").strip()
    except Exception:
        return ""


def _ocr_da_captura(pdf: Path) -> str:
    """OCR que a CAPTURA já fez deste mesmo PDF (`NNN.ocr.txt`, gravado por `sei_integra_completa`).

    O anexo escaneado passava pelo OCR duas vezes: na captura (para saber se havia teor) e aqui, do zero, sobre
    os mesmos bytes — medido no it-campo em 14/11/2026: 25–32 s de arquivamento em processos de 19–40 documentos
    com 2–5 escaneados, contra 0,3 s num processo sem nenhum. Só vale o texto gravado DEPOIS do PDF; sem ele
    (captura antiga, texto cortado no teto de caracteres), '' e o OCR roda como sempre."""
    lado = pdf.with_suffix(".ocr.txt")
    try:
        if lado.stat().st_mtime >= pdf.stat().st_mtime:
            return lado.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
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


def _fotos_do_doc(destino: Path, i: int) -> list[Path]:
    """Páginas fotográficas do doc `i` já em `fotos/`: o .jpg do arquivador ou o .webp que `sei_compactar` pôs no lugar."""
    return [f for f in destino.glob(f"fotos/{i:03d}_p*.*") if f.suffix.lower() in (".jpg", ".webp")]


def _slug(t: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", (t or "").lower())[:40].strip("_") or "doc"


def _etiqueta_e_de(txt: Path, titulo: str) -> bool:
    """O `.txt` do acervo é do documento `titulo`? Lê só a 1ª linha (`[título] (fase: … · tipo: …)`)."""
    try:
        with txt.open(encoding="utf-8", errors="ignore") as f:
            linha = f.readline()
    except OSError:
        return False
    return linha.startswith(f"[{titulo}] (fase:")


def _modalidade(tipos: set[str]) -> str:
    if "contratacao_direta" in tipos:
        return "dispensa/inexigibilidade"
    if {"edital", "julgamento", "homologacao"} & tipos:
        return "licitacao"
    return ""


def arquivar(origem: Path, destino: Path, processo: str = "",
             apagar_pdf: bool = False, ocr: bool = True, textos_soltos: bool = False) -> dict:
    """Converte o diretório de íntegra em arquivo compacto. Idempotente.

    `textos_soltos=True` (reparo dirigido): documento SEM PDF na origem entra pelo texto que ficou ao lado —
    `NNN.txt` (nativo depurado, `tools/sei_depurar_pdfs.py`) ou `NNN.ocr.txt` (OCR da captura). É o que permite
    rearquivar pasta depurada; sem a opção, a pasta depurada mantém o arquivo existente."""
    origem, destino = Path(origem), Path(destino)
    # PASTA DEPURADA (tools/sei_depurar_pdfs.py, 15/11/2026): os PDFs nativos viraram NNN.txt e saíram. Rearquivar
    # varreria só os PDFs que sobraram e gravaria um manifesto SEM os documentos nativos — perda silenciosa.
    if not textos_soltos and (origem / "depurados.json").exists() and (destino / "manifest.json").exists():
        print(f"  {origem.name}: depurada — arquivo existente mantido (não rearquivo)", flush=True)
        return json.loads((destino / "manifest.json").read_text(encoding="utf-8"))
    (destino / "texto").mkdir(parents=True, exist_ok=True)
    (destino / "fotos").mkdir(parents=True, exist_ok=True)

    titulos = {}
    # Inicializado AQUI, fora do `if mpath.exists()`. Antes só era definido lá dentro, e um
    # diretório de íntegra SEM `manifest.json` — o que sobra quando a captura é interrompida
    # antes de gravá-lo — estourava `UnboundLocalError` na varredura dos PDFs mais abaixo.
    # Latente no acervo de 2026-08-23 (83 diretórios com PDF, todos com manifesto), mas
    # capturas SÃO interrompidas: descoberto por um teste que montou o caso sem manifesto.
    alheios_i: set[int] = set()
    ids_doc: dict[int, str] = {}
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
            # o IDENTIFICADOR do documento na árvore (gravado pela captura; nos manifestos antigos, na url do nó)
            m_id = re.search(r"id_documento=(\d+)", str(e.get("url") or ""))
            ids_doc[int(e["i"])] = str(e.get("id_documento") or (m_id.group(1) if m_id else ""))

    docs_saida, tipos_vistos = [], set()
    for pdf in sorted(origem.glob("[0-9][0-9][0-9]*.pdf")):
        # O ÍNDICE É O NÚMERO INTEIRO DO NOME, não os 3 primeiros dígitos: a captura grava `{i:03d}.pdf`, que
        # passa de 999 para `1000.pdf`. Com `name[:3]`, 1000–1009 viravam o documento 100 — medido em 18/11/2026:
        # 15 processos com árvore > 1.000 (o `210108/000169/2023` com 2.770) e 7.554 documentos colapsados.
        i = int(re.match(r"\d+", pdf.name).group())
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
        # O TEXTO REAPROVEITADO TEM DE SER DESTE DOCUMENTO, não da posição: a captura pode reordenar a árvore entre
        # rodadas (`sei_integra_completa.preparar_retomada`), e `texto/{i:03d}_*.txt` podia ser de OUTRO título que
        # ocupou o índice i antes — colava o teor de um documento no título de outro (20/11/2026). Vale o .txt cuja
        # etiqueta traz este título.
        pronto = next((t for t in destino.glob(f"texto/{i:03d}_*.txt")
                       if _etiqueta_e_de(t, titulo)), None)
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
                    f"fotos/{f.name}" for f in _fotos_do_doc(destino, i))
                docs_saida.append(entrada)
                continue
            except OSError as e:
                logger.debug("reaproveitamento do texto existente falhou: %s", e)    # txt ilegível: cai no caminho normal e reextrai

        try:
            doc = fitz.open(str(pdf))
        except Exception:
            entrada["erro"] = "pdf ilegível"
            docs_saida.append(entrada)
            continue

        texto, pobres = _texto_pdf(doc)
        if ocr and len(texto) < _MIN_CHARS_PAG and doc.page_count:
            t2 = _ocr_da_captura(pdf) or _ocr_pdf(pdf.read_bytes())
            if len(t2) > len(texto):
                texto, entrada["ocr"] = t2, True
        elif ocr and any(_pagina_com_imagem_grande(doc[p]) for p in pobres):
            # documento MISTO: tem texto, mas também página escaneada que o OCR do documento inteiro nunca via.
            # Só as escaneadas vão ao OCR; o texto nativo segue inteiro (ocr_docs._completar_paginas_escaneadas).
            t2 = _ocr_pdf(pdf.read_bytes(), completar_mistas=True)
            if len(t2) > len(texto):
                texto, entrada["ocr"], entrada["ocr_paginas"] = t2, True, "mistas"

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
            if not (destino / frel).exists() and (destino / frel).with_suffix(".webp").exists():
                frel = frel[:-4] + ".webp"     # página já compactada (sei_compactar): não reextrai o JPG
            if (destino / frel).exists() or _salvar_foto(doc[p], destino / frel):
                entrada["fotos"].append(frel)
        doc.close()
        docs_saida.append(entrada)
        if apagar_pdf:
            pdf.unlink(missing_ok=True)

    if textos_soltos:
        tem = {d["i"] for d in docs_saida}
        for i, titulo in sorted(titulos.items()):
            if i in tem or i in alheios_i:
                continue
            for lado, por_ocr in ((origem / f"{i:03d}.txt", False), (origem / f"{i:03d}.ocr.txt", True)):
                if not lado.is_file():
                    continue
                texto = lado.read_text(encoding="utf-8", errors="replace").strip()
                fase, tipo = classificar(titulo)
                tipos_vistos.add(tipo)
                txt_rel = f"texto/{i:03d}_{_slug(titulo)}.txt"
                (destino / txt_rel).write_text(f"[{titulo}] (fase: {fase} · tipo: {tipo})\n\n{texto}",
                                               encoding="utf-8")
                docs_saida.append({"i": i, "titulo": titulo, "fase": fase, "tipo": tipo, "texto": txt_rel,
                                   "chars": len(texto), "ocr": por_ocr, "via_texto_solto": lado.name,
                                   "fotos": sorted(f"fotos/{f.name}" for f in _fotos_do_doc(destino, i))})
                break

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
    for d in docs_saida:
        if ids_doc.get(d["i"]):
            d["id_documento"] = ids_doc[d["i"]]

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
            # DOCUMENTOS DISTINTOS, não entradas: o manifesto feito com o índice de 3 dígitos (até 18/11/2026) repetia o
            # mesmo `i` até 11 vezes (`210108/000169/2023`: 2.770 entradas capturadas, 1.000 índices). Contando entradas,
            # a guarda preservava justamente o arquivo errado contra a captura corrigida.
            cap_ant = len({str(d.get("i")) for d in (anterior.get("docs") or [])
                           if isinstance(d, dict) and not d.get("nao_capturado")})
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
                except OSError as e:
                    logger.debug("mtime do manifesto anterior não tocado: %s", e)
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
    if alheios_i:
        manifest["alheios_fora"] = len(alheios_i)   # peças de outro processo: saem do tamanho da árvore
    # CONFERÊNCIA DOCUMENTO A DOCUMENTO (régua única `manifesto_norm.conferir_documentos`): `captura_completa` passa a
    # dizer "todo documento da árvore veio" — só com a árvore medida; o "download chegou ao fim" da captura fica em
    # `download_completo`. Cada um que não veio vai em `docs_faltantes` com id/nº/título/motivo.
    _registrar_conferencia(destino, manifest, captura_completa)
    destino.mkdir(parents=True, exist_ok=True)
    from compliance_agent.llm.arquivo_estado import trava
    alvo = destino / "manifest.json"
    with trava(alvo.with_name(alvo.name + ".lock"), 120):   # mesma trava de quem relê-mescla (`mutar_manifesto`)
        tmp = alvo.with_name(alvo.name + ".tmp")
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(alvo)
    return manifest


def _registrar_conferencia(destino: Path, manifest: dict, download_completo) -> None:
    from compliance_agent.sei import manifesto_norm
    conf = manifesto_norm.conferir_documentos(destino, manifest)
    manifest["download_completo"] = download_completo
    if conf["medido"]:
        manifest["captura_completa"] = conf["captura_completa"]
    manifest["docs_faltantes"] = conf["docs_faltantes"]
    manifest["conferencia_documentos"] = {
        "em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "medido": conf["medido"],
        "total_arvore": conf["total_arvore"], "n_docs": conf["n_docs"], "vieram": conf["vieram"],
        "com_texto": conf["com_texto"], "faltantes": len(conf["docs_faltantes"]),
        "faltam_sem_identificacao": conf["faltam_sem_identificacao"]}


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


def _ids_da_captura(pasta: Path) -> dict[tuple[int, str], str]:
    """{(i, título): id_documento} do manifesto da íntegra no cache — só vale onde o TÍTULO também casa."""
    try:
        c = json.loads((CACHE / f"integra_{pasta.name}" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for e in (c.get("docs") if isinstance(c, dict) else c) or []:
        if not isinstance(e, dict):
            continue
        m_id = re.search(r"id_documento=(\d+)", str(e.get("url") or ""))
        ident = str(e.get("id_documento") or (m_id.group(1) if m_id else ""))
        try:
            if ident:
                out[(int(e.get("i")), str(e.get("titulo") or ""))] = ident
        except (TypeError, ValueError):
            continue
    return out


def conferir_acervo(gravar: bool = False, idade_min_h: float = 2.0) -> dict:
    """Conferência DOCUMENTO A DOCUMENTO de todo o acervo (`manifesto_norm.conferir_documentos`).

    Ensaio por padrão (não grava). Com `gravar`, só onde a árvore foi MEDIDA, por `acervo_texto.mutar_manifesto`
    (reler-mesclar-gravar sob trava), e nunca em pasta mexida há menos de `idade_min_h` horas (worker vivo).
    Grava `captura_completa` (todo documento veio), `docs_faltantes` [{i, id_documento, numero_sei, titulo, motivo}],
    `conferencia_documentos` (números) e preserva o "download chegou ao fim" antigo em `download_completo`."""
    import time as _t
    from collections import Counter
    from compliance_agent.sei import acervo_texto, manifesto_norm
    c: Counter = Counter()
    motivos: Counter = Counter()
    agora = _t.time()
    for pasta in sorted(p for p in ARQUIVO.iterdir() if p.is_dir()):
        man = acervo_texto.manifesto(pasta)
        if man is None:
            c["sem_manifest"] += 1
            continue
        c["manifests"] += 1
        c["antes_captura_completa_true"] += man.get("captura_completa") is True
        conf = manifesto_norm.conferir_documentos(pasta, man)
        if not conf["medido"]:
            c["arvore_nao_medida"] += 1
            continue
        c["arvore_medida"] += 1
        c["completos"] += conf["captura_completa"]
        c["incompletos"] += not conf["captura_completa"]
        c["docs"] += conf["n_docs"]
        c["docs_vieram"] += conf["vieram"]
        c["docs_faltantes"] += len(conf["docs_faltantes"])
        c["faltam_sem_identificacao"] += conf["faltam_sem_identificacao"]
        motivos.update(f["motivo"] for f in conf["docs_faltantes"])
        if not gravar:
            continue
        try:
            recente = max(f.stat().st_mtime for f in [pasta / "manifest.json", *pasta.glob("texto")])
        except (OSError, ValueError):
            recente = agora
        if agora - recente < idade_min_h * 3600:
            c["pulado_pasta_recente"] += 1
            continue
        ids = _ids_da_captura(pasta)

        def _aplica(m, pasta=pasta, ids=ids):
            cf = manifesto_norm.conferir_documentos(pasta, m)      # sobre o manifesto RELIDO
            if not cf["medido"]:
                return False
            for f in cf["docs_faltantes"]:
                try:
                    f["id_documento"] = f["id_documento"] or ids.get((int(f["i"]), f["titulo"]), "")
                except (TypeError, ValueError):
                    pass
            if "download_completo" not in m:
                m["download_completo"] = m.get("captura_completa")
            m["captura_completa"] = cf["captura_completa"]
            m["docs_faltantes"] = cf["docs_faltantes"]
            m["conferencia_documentos"] = {
                "em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "medido": True,
                "total_arvore": cf["total_arvore"], "n_docs": cf["n_docs"], "vieram": cf["vieram"],
                "com_texto": cf["com_texto"], "faltantes": len(cf["docs_faltantes"]),
                "faltam_sem_identificacao": cf["faltam_sem_identificacao"]}
            return True
        if acervo_texto.mutar_manifesto(pasta, _aplica):
            c["gravados"] += 1
    return {"contagem": dict(c), "motivos": dict(motivos.most_common()), "gravado": gravar}


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
    ap.add_argument("--conferir-acervo", action="store_true",
                    help="confere CADA documento da árvore em todo o acervo (ensaio; grava só com --gravar)")
    ap.add_argument("--gravar", action="store_true", help="com --conferir-acervo: grava no manifest (sob trava)")
    args = ap.parse_args()

    if args.conferir_acervo:
        print(json.dumps(conferir_acervo(gravar=args.gravar), ensure_ascii=False, indent=1))
        return 0

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
