# -*- coding: utf-8 -*-
"""Leitor EXTERNO da bancada de OCR (26/11/2026) — roda DENTRO do ambiente isolado de cada motor candidato (sem o
código do JFN: só biblioteca padrão + a do motor) e escreve `leituras_<motor>_<lista>.jsonl` no MESMO formato da
`tools/ocr_bancada_o36.py` ({img_sha, motor, texto, linhas, s}), para a `medir` de lá comparar no controle nativo.

Motores:
  paddlevl  PaddleOCR-VL pelo pipeline `PaddleOCRVL` (reconhecimento num servidor vLLM local)
  (oxr REMOVIDO em 27/11/2026: inventava 21,37% dos números no controle nativo; leituras preservadas em
   /mnt/c/o36/leituras_oxr_controle.jsonl, reinstalação no it-campo:~/ocrbench/REMOVIDO-OXR-LEIAME.md)

Retoma: página já lida não é relida. Nada aqui toca PG, acervo ou compliance.db.
Uso: python ocr_bancada_externo.py --motor paddlevl --dir /mnt/c/o36 [--lista controle] [--url http://127.0.0.1:8118/v1]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

_TAG = re.compile(r"<[^>]+>")
MODELO_PADDLEVL = "PaddleOCR-VL-1.6-0.9B"


def leitor_paddlevl(url: str):
    from paddleocr import PaddleOCRVL
    from importlib.metadata import version
    kw = dict(vl_rec_backend="vllm-server", vl_rec_server_url=url, vl_rec_model_name=MODELO_PADDLEVL,
              vl_rec_api_model_name=MODELO_PADDLEVL)
    try:
        pipe, versao = PaddleOCRVL(pipeline_version="v1.6", **kw), "v1.6"
    except (ValueError, KeyError, TypeError) as exc:      # versão de pipeline que o pacote não conhece: padrão, DECLARADO
        print(f"pipeline_version v1.6 recusada ({exc}); uso o padrão", file=sys.stderr)
        pipe, versao = PaddleOCRVL(**kw), "padrão"

    def ler(png: Path) -> str:
        partes = []
        for res in pipe.predict(str(png)):
            md = getattr(res, "markdown", None) or {}
            partes.append(md.get("markdown_texts", "") if isinstance(md, dict) else str(md))
        return html.unescape(_TAG.sub(" ", "\n".join(partes)))
    return f"{MODELO_PADDLEVL} pipeline {versao} @paddleocr{version('paddleocr')} (vLLM, GPU it-campo) dpi200", ler


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--motor", required=True, choices=["paddlevl"])
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--lista", default="controle")
    ap.add_argument("--url", default=None)
    ap.add_argument("--limite", type=int, default=None)
    a = ap.parse_args(argv)
    nome, ler = leitor_paddlevl(a.url or "http://127.0.0.1:8118/v1")
    saida = a.dir / f"leituras_{a.motor}_{a.lista}.jsonl"
    feitos = set()
    if saida.exists():
        feitos = {json.loads(ln)["img_sha"] for ln in saida.read_text(encoding="utf-8").splitlines() if ln.strip()}
    renders = [json.loads(ln) for ln in (a.dir / f"render_{a.lista}.jsonl").read_text(encoding="utf-8").splitlines()
               if ln.strip()]
    fila = [r for r in renders if r.get("img_sha") and not r.get("erro") and r["img_sha"] not in feitos]
    if a.limite:
        fila = fila[:a.limite]
    ok = falhas = 0
    with saida.open("a", encoding="utf-8") as f:
        for r in fila:
            png = a.dir / "png" / r["png"]
            t0 = time.monotonic()
            try:
                texto = ler(png)
            except (OSError, ValueError, RuntimeError, KeyError) as exc:   # rede/HTTP (URLError ⊂ OSError), JSON, motor
                # a página falha, a bancada segue — e a falha é CONTADA no resumo (nunca some calada)
                falhas += 1
                print(f"falhou {r['img_sha'][:12]}: {type(exc).__name__}: {str(exc)[:160]}", file=sys.stderr)
                continue
            f.write(json.dumps({"img_sha": r["img_sha"], "motor": nome, "texto": texto, "linhas": [],
                                "s": round(time.monotonic() - t0, 3)}, ensure_ascii=False) + "\n")
            f.flush()
            ok += 1
    print(json.dumps({"motor": nome, "lidas": ok, "falhas": falhas, "ja_lidas": len(feitos), "saida": str(saida)},
                     ensure_ascii=False))
    return 0 if falhas == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
