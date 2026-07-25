#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arquiva processos SEI a partir do TEXTO QUE JÁ ESTÁ NO CACHE — sem browser, sem login, sem SEI.

Achado que originou a ferramenta (2026-07-24): o sweep lê o processo e guarda o texto em
`data/sei_cache/cdp_*.json` (campo `conteudo_documentos`), mas o ARQUIVO consultável
(`data/sei_arquivo/<proc>/`) só era montado pela fila de íntegras, que precisa de browser e sessão. O
resultado medido:

    5.401 processos no cache
      346 arquivados
    4.655 COM TEXTO no cache e NÃO arquivados — 107.951.833 caracteres parados

Ou seja: o SEI já serviu 108 milhões de caracteres, e o motor de análise (execução, parecer da PGE,
fracionamento, direcionamento) não enxergava nada disso, porque todos leem o ARQUIVO. Converter é de
graça e instantâneo — é só transpor o formato.

Honesto: o arquivo gerado declara `origem: cache CDP` e `via` de cada documento (leitura direta ou OCR),
para nunca se confundir com a captura completa da íntegra (que traz também fotos e anexos binários).
Idempotente: pula o que já está arquivado com texto; nunca sobrescreve captura boa.

Uso:
    python -m tools.sei_arquivar_do_cache                 # relatório (não escreve)
    python -m tools.sei_arquivar_do_cache --aplicar       # arquiva tudo o que dá
    python -m tools.sei_arquivar_do_cache --aplicar --max 500
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "data" / "sei_cache"
ARQUIVO = RAIZ / "data" / "sei_arquivo"
MIN_CHARS = 500          # cache com menos que isso não vale arquivar (é cabeçalho/erro)

# ── VERIFICAÇÃO DE INTEGRIDADE (2026-07-24, depois de o dono perguntar "estão íntegros?") ──
# Comparando, nos 47 processos que têm AS DUAS fontes, o texto do cache com o PDF da íntegra capturada
# por browser, apareceu o corte: `cache 400 vs pdf 7.926 chars`, `400 vs 8.317`, repetidamente. Parte dos
# caches guarda só uma AMOSTRA de ~400 caracteres por documento — e o número de documentos também não
# bate (cache 2-7 docs contra 7-137 PDFs).
# Arquivar isso seria pior que não arquivar: o processo PARECERIA capturado e o motor daria veredito
# sobre migalhas. Medido no acervo: 1.831 caches completos (110 M chars) contra 3.219 amostras.
_CORTE_MIN, _CORTE_MAX = 390, 410      # a faixa exata onde o corte do sweep para
_FRACAO_AMOSTRA = 0.8                  # ≥80% dos docs no corte ⇒ é amostra, não conteúdo


def qualidade_cache(conteudo_documentos: list) -> str:
    """'completo' | 'amostra' | 'misto' — só 'completo' pode virar arquivo consultável."""
    tam = [len(str(x.get("conteudo") or x.get("texto") or "")) for x in (conteudo_documentos or [])]
    if not tam:
        return "amostra"
    frac = sum(1 for t in tam if _CORTE_MIN <= t <= _CORTE_MAX) / len(tam)
    if frac >= _FRACAO_AMOSTRA:
        return "amostra"
    return "completo" if frac <= 0.2 else "misto"


def _slug_processo(numero: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in (numero or "").replace("SEI-", "")).strip("_")


def _slug_arquivo(titulo: str, i: int) -> str:
    t = unicodedata.normalize("NFD", (titulo or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:60] or "documento"
    return f"{i:03d}_{t}.txt"


def _ja_arquivado(numero: str) -> bool:
    d = ARQUIVO / _slug_processo(numero)
    if not (d / "manifest.json").exists():
        return False
    td = d / "texto"
    return td.is_dir() and any(f.stat().st_size > 200 for f in td.glob("*.txt"))


def candidatos(min_chars: int = MIN_CHARS) -> list[dict]:
    """Caches com texto suficiente e ainda não arquivados, do maior conteúdo para o menor."""
    out = []
    for f in CACHE.glob("cdp_*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        numero = (d.get("numero") or "").strip()
        cd = d.get("conteudo_documentos") or []
        if not numero or not cd or _ja_arquivado(numero):
            continue
        chars = sum(len(str(x.get("conteudo") or x.get("texto") or "")) for x in cd)
        q = qualidade_cache(cd)
        if q != "completo":
            continue          # amostra truncada NÃO vira arquivo (veredito sobre migalha é pior que nada)
        if chars >= min_chars:
            out.append({"numero": numero, "cache": f, "dados": d, "n_docs": len(cd), "chars": chars,
                        "qualidade": q})
    out.sort(key=lambda e: -e["chars"])
    return out


def arquivar(item: dict, aplicar: bool = False) -> dict:
    """Monta `data/sei_arquivo/<proc>/` (manifest.json + texto/) no MESMO formato da captura de íntegra,
    para que todo o motor de análise leia sem saber a diferença."""
    from compliance_agent.sei.classificador_doc import classificar_doc
    from compliance_agent.sei.fases import linha_do_tempo

    numero = item["numero"]
    destino = ARQUIVO / _slug_processo(numero)
    docs_manifest, titulos, escritos = [], [], 0
    for i, doc in enumerate(item["dados"].get("conteudo_documentos") or []):
        titulo = str(doc.get("doc") or doc.get("titulo") or f"documento {i}").strip()
        conteudo = str(doc.get("conteudo") or doc.get("texto") or "").strip()
        via = str(doc.get("via") or "").strip()
        rel = f"texto/{_slug_arquivo(titulo, i)}"
        titulos.append(titulo)
        docs_manifest.append({
            "i": str(i), "titulo": titulo,
            "fase": "", "tipo": classificar_doc(titulo, conteudo[:1500]),
            "texto": rel, "chars": str(len(conteudo)),
            "ocr": "True" if via == "ocr" else "False", "fotos": "[]", "via_cache": via or "leitura",
        })
        if aplicar:
            f = destino / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            cabecalho = f"[{titulo}] (tipo: {docs_manifest[-1]['tipo']})\n\n"
            f.write_text(cabecalho + conteudo, encoding="utf-8")
            escritos += 1
    manifest = {
        "processo": numero.replace("SEI-", ""),
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # deixa explícito que veio do cache: não tem fotos nem anexos binários, ao contrário da íntegra
        "origem": f"cache CDP ({item['cache'].name}) — texto já lido pelo sweep, arquivado sem browser",
        "modalidade": "", "docs": docs_manifest,
        "linha_do_tempo": linha_do_tempo(titulos), "lacunas": [],
        "fotos_total": 0,
        "aviso": ("arquivo montado a partir do CACHE do sweep: contém o TEXTO dos documentos, não os "
                  "anexos binários nem as fotos de medição — para esses, capturar a íntegra"),
        "qualidade_cache": item.get("qualidade", "completo"),
        "verificacao": ("integridade conferida: caches com corte fixo de ~400 chars/doc (amostra) são "
                        "recusados; este veio de cache com texto completo"),
    }
    if aplicar:
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        (destino / "fotos").mkdir(exist_ok=True)
    return {"numero": numero, "docs": len(docs_manifest), "chars": item["chars"], "escritos": escritos}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--max", type=int, default=0, help="limita quantos processos arquivar (0 = todos)")
    ap.add_argument("--min-chars", type=int, default=MIN_CHARS)
    a = ap.parse_args(argv)
    alvos = candidatos(a.min_chars)
    if a.max:
        alvos = alvos[:a.max]
    total_chars = sum(x["chars"] for x in alvos)
    print(f"processos no cache com texto e sem arquivo: {len(alvos):,} — {total_chars:,} caracteres")
    if not alvos:
        return 0
    feitos = 0
    for x in alvos:
        r = arquivar(x, aplicar=a.aplicar)
        feitos += 1
        if feitos <= 5 or feitos % 500 == 0:
            print(f"  {feitos:5d}. {r['numero']:28s} {r['docs']:3d} docs  {r['chars']:>9,} chars")
    print(f"\n{'arquivados' if a.aplicar else 'arquivaria'}: {feitos:,} processos · "
          f"{total_chars:,} caracteres" + ("" if a.aplicar else "  (SIMULAÇÃO — use --aplicar)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
