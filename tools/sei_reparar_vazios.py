#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repara documentos do arquivo SEI que ficaram SEM TEXTO, usando o PDF já guardado no cache.

Achado que originou a ferramenta (2026-07-24): 2.950 dos 14.613 documentos capturados (20%) têm apenas o
cabeçalho e nenhum conteúdo. Investigando a origem de cada um:

  • a maioria é **vazia de verdade** — "Despacho de Encaminhamento de Processo" não tem corpo, é carimbo
    de tramitação (300+ casos), ou o PDF em cache também está vazio (1 KB — resíduo do bug antigo do
    `insert_textbox`, já corrigido na captura, mas os arquivos velhos ficaram);
  • uma parte tem **PDF substancial no cache e texto zerado no arquivo** — aí houve falha de EXTRAÇÃO, e
    o conteúdo pode ser recuperado sem tocar no SEI. Medido: um "parecer" de 33 KB devolveu 5.858
    caracteres; um anexo de 153 KB devolveu 29.629.

Reparar é de graça (o PDF já está em disco), não depende de login e não gasta o SEI — enquanto recapturar
exige browser, sessão e horas. Por isso esta ferramenta roda primeiro.

O casamento é posicional: `data/sei_cache/integra_<processo>/<i:03d}.pdf` corresponde ao documento de
índice `i` do manifesto — verificado no acervo.

Uso:
    python -m tools.sei_reparar_vazios                 # relatório (não escreve nada)
    python -m tools.sei_reparar_vazios --aplicar       # grava o texto recuperado e atualiza o manifesto
    python -m tools.sei_reparar_vazios --min-kb 20     # só PDFs acima de N KB (default 20)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compliance_agent.sei import acervo_texto  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "data" / "sei_arquivo"
CACHE = RAIZ / "data" / "sei_cache"
MIN_CHARS = 80          # abaixo disso o arquivo só tem o cabeçalho gerado, não conteúdo


def candidatos(min_kb: int = 20) -> list[dict]:
    """Documentos sem texto cujo PDF em cache é substancial — os que valem reprocessar."""
    achados: list[dict] = []
    for pdir in sorted(ARQUIVO.iterdir()):
        man = pdir / "manifest.json"
        if not pdir.is_dir() or not man.exists():
            continue
        cdir = CACHE / f"integra_{pdir.name}"
        if not cdir.is_dir():
            continue
        try:
            j = json.loads(man.read_text())
        except (ValueError, OSError):
            continue
        for d in j.get("docs") or []:
            rel = d.get("texto")
            if not rel:
                continue
            falq = pdir / rel
            if not falq.exists():
                continue
            # A ETIQUETA CONTAVA COMO CONTEÚDO. `len(arquivo)` inclui a linha
            # `[título] (fase: … · tipo: …)` que nós mesmos prependemos, e ela sozinha passa dos
            # 80 caracteres — de modo que TODO arquivo só-rótulo era lido como "já tem texto" e a
            # ferramenta relatava "nada a reparar" com 7.682 documentos vazios no acervo. É a
            # família 12 do catálogo (metadado dentro do dado) sobrevivendo aqui, e a casa já tem
            # a porta única que resolve: `acervo_texto.tem_conteudo` mede o teor SEM a etiqueta.
            if acervo_texto.tem_conteudo(falq, minimo=MIN_CHARS):
                continue
            try:
                pdf = cdir / f"{int(d.get('i')):03d}.pdf"
            except (TypeError, ValueError):
                continue
            if pdf.exists() and pdf.stat().st_size > min_kb * 1024:
                achados.append({"processo": pdir.name, "i": d.get("i"), "tipo": d.get("tipo"),
                                "titulo": d.get("titulo"), "pdf": pdf, "txt": falq,
                                "manifest": man, "kb": pdf.stat().st_size / 1024})
    return achados


_RE_ID_TITULO = re.compile(r"(\d{6,})")
"""O identificador SEI é o ÚLTIMO grupo de 6+ dígitos do título — com ou sem parênteses.
Exigir parênteses deixava indeterminado o que era conferível: "Despacho de Encaminhamento de
Processo 83371025" traz o id solto, e o SEI o imprime igualmente no cabeçalho da peça."""


def pertence(titulo: str, texto: str) -> bool | None:
    """O texto extraído é DESTE documento? True / False / None (indeterminado).

    O casamento `integra_<proc>/<i:03d}.pdf` ↔ documento `i` do manifesto **não vale**. Medido em
    2026-08-04, entre os 24 candidatos ao reparo, 7 permitiam conferência e **6 traziam o PDF
    ERRADO**: "Nota de Autorização de Despesa - NAD 3378" devolvia o texto de um "Despacho de
    Encaminhamento", "Anexo 2024PD26195 - IRRF" devolvia um e-mail, e o mesmo arquivo de 18 MB
    aparecia em dois processos sob índices e títulos diferentes (md5 idêntico). Escrever isso
    colaria o teor de um documento no TÍTULO de outro — a mesma armadilha que a reconciliação de
    órfãos já documentou, e pior que deixar o documento vazio: vazio é lacuna declarada, trocado
    é prova falsa.

    A prova aceita é o identificador SEI que o próprio título carrega entre parênteses aparecendo
    no texto extraído (o SEI o imprime no cabeçalho de cada peça). Sem id no título, ou sem texto
    para conferir, o resultado é **indeterminado** — e indeterminado não se grava.
    """
    ids = _RE_ID_TITULO.findall(str(titulo or ""))
    if not ids or not (texto or "").strip():
        return None
    return ids[-1] in texto


def reparar(alvos: list[dict], aplicar: bool = False) -> dict:
    """Extrai o texto do PDF (nativo ou OCR, via `ocr_documento`) e grava. Honesto: se a extração vier
    vazia, NÃO escreve nada e conta como irrecuperável — o documento continua declarado sem texto."""
    from compliance_agent.sei.ocr_docs import ocr_documento
    recuperados = irrecuperaveis = nao_conferidos = 0
    chars_total = 0
    por_manifest: dict[Path, dict] = {}
    for a in alvos:
        try:
            texto = (ocr_documento(a["pdf"].read_bytes(), tipo="pdf") or "").strip()
        except Exception as e:  # noqa: BLE001 — PDF corrompido/lib ausente: conta como irrecuperável
            print(f"  ! {a['processo']} i={a['i']}: falha ao extrair ({str(e)[:60]})")
            irrecuperaveis += 1
            continue
        if len(texto) < MIN_CHARS:
            irrecuperaveis += 1
            continue
        # PROVA DE PERTENCIMENTO antes de escrever (ver `pertence`)
        veredito = pertence(a.get("titulo"), texto)
        if veredito is not True:
            nao_conferidos += 1
            print(f"  ✗ {a['processo']} i={a['i']:>3} {str(a['titulo'])[:44]:44s} — "
                  + ("PDF é de OUTRO documento" if veredito is False
                     else "não dá para conferir a que documento pertence")
                  + "; NÃO gravado")
            continue
        recuperados += 1
        chars_total += len(texto)
        print(f"  ✓ {a['processo']} i={a['i']:>3} {str(a['tipo'])[:12]:12s} {a['kb']:7.0f}KB → {len(texto):,} chars")
        if not aplicar:
            continue
        cabecalho = a["txt"].read_text(errors="replace").strip()
        a["txt"].write_text(f"{cabecalho}\n\n{texto}" if cabecalho else texto, encoding="utf-8")
        # o manifesto guarda `chars`/`ocr`: mantê-los coerentes com o arquivo é o que faz o resto do
        # sistema parar de tratar o documento como vazio.
        m = por_manifest.setdefault(a["manifest"], json.loads(a["manifest"].read_text()))
        for d in m.get("docs") or []:
            if str(d.get("i")) == str(a["i"]):
                d["chars"] = str(len(texto))
                d["ocr"] = "True"
                d["reparado_em"] = "2026-07-24"
    for man, m in por_manifest.items():
        man.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return {"alvos": len(alvos), "recuperados": recuperados, "irrecuperaveis": irrecuperaveis,
            "nao_conferidos": nao_conferidos,
            "chars_recuperados": chars_total, "aplicado": aplicar,
            "manifests_atualizados": len(por_manifest)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true", help="grava o texto recuperado (default: só relata)")
    ap.add_argument("--min-kb", type=int, default=20, help="tamanho mínimo do PDF em cache (default 20)")
    a = ap.parse_args(argv)
    alvos = candidatos(a.min_kb)
    print(f"documentos sem texto com PDF ≥ {a.min_kb}KB no cache: {len(alvos)}")
    if not alvos:
        print("nada a reparar — os vazios restantes não têm PDF utilizável em disco (exigem recaptura).")
        return 0
    r = reparar(alvos, aplicar=a.aplicar)
    print(f"\nrecuperados: {r['recuperados']} · irrecuperáveis: {r['irrecuperaveis']} · "
          f"não conferidos (PDF de outro documento ou sem prova): {r['nao_conferidos']} · "
          f"{r['chars_recuperados']:,} caracteres" + ("" if a.aplicar else "  (SIMULAÇÃO — use --aplicar)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
