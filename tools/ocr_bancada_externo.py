# -*- coding: utf-8 -*-
"""Leitor EXTERNO da bancada de OCR (26/11/2026) — roda DENTRO do ambiente isolado de cada motor candidato (sem o
código do JFN: só biblioteca padrão + a do motor) e escreve `leituras_<motor>_<lista>.jsonl` no MESMO formato da
`tools/ocr_bancada_o36.py` ({img_sha, motor, texto, linhas, s}), para a `medir` de lá comparar no controle nativo.

Motores:
  oxr       OXR-1.0 (SoMark) pela API de documentos local (`/v1/parse/sync`, porta 8000; vLLM + layout atrás)
  paddlevl  PaddleOCR-VL pelo pipeline `PaddleOCRVL` (reconhecimento num servidor vLLM local)

Retoma: página já lida não é relida. Nada aqui toca PG, acervo ou compliance.db.
Uso: python ocr_bancada_externo.py --motor oxr --dir /mnt/c/o36 [--lista controle] [--url http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.request
import uuid
from pathlib import Path

_TAG = re.compile(r"<[^>]+>")
MODELO_PADDLEVL = "PaddleOCR-VL-1.6-0.9B"


def _texto_de(obj) -> str:
    """O markdown da resposta (procura a chave em qualquer nível); HTML de tabela vira texto (as células ficam)."""
    achados: list[str] = []

    def andar(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, str) and k.lower() in ("markdown", "md", "markdown_texts", "content"):
                    achados.append(v)
                else:
                    andar(v)
        elif isinstance(x, list):
            for v in x:
                andar(v)
    andar(obj)
    t = "\n".join(achados)
    return html.unescape(_TAG.sub(" ", t))


def _multipart(campos: list[tuple[str, str]], arquivo: Path) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    partes = []
    for k, v in campos:
        partes.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    partes.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{arquivo.name}"\r\n'
                  f"Content-Type: image/png\r\n\r\n".encode() + arquivo.read_bytes() + b"\r\n")
    partes.append(f"--{b}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={b}"


def leitor_oxr(url: str):
    def ler(png: Path) -> str:
        corpo, tipo = _multipart([("api_key", "dummy"), ("output_formats", "markdown")], png)
        req = urllib.request.Request(f"{url.rstrip('/')}/v1/parse/sync", data=corpo, headers={"Content-Type": tipo})
        with urllib.request.urlopen(req, timeout=600) as r:
            return _texto_de(json.loads(r.read().decode("utf-8")))
    return "oxr@1.0 (SoMark; vLLM+layout, GPU it-campo) dpi200", ler


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
    ap.add_argument("--motor", required=True, choices=["oxr", "paddlevl"])
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--lista", default="controle")
    ap.add_argument("--url", default=None)
    ap.add_argument("--limite", type=int, default=None)
    a = ap.parse_args(argv)
    url = a.url or {"oxr": "http://127.0.0.1:8000", "paddlevl": "http://127.0.0.1:8118/v1"}[a.motor]
    nome, ler = (leitor_oxr if a.motor == "oxr" else leitor_paddlevl)(url)
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
