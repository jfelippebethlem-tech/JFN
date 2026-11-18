"""Aplica o OCR por IA da GPU do it-campo (Surya 2.5) ao ARQUIVO canônico do SEI (`data/sei_arquivo/<tag>`).

POR QUE (18/11/2026, medido com gabarito — 79 páginas nativas 'sujadas' como escaneado): o Tesseract de produção
acerta 78,0% dos valores em R$, 89,8% das datas e 92,5% dos CNPJ; o Surya na GPU, 99,7% / 100% / 95,7%. 219.125
documentos do acervo (60%) foram lidos pelo Tesseract. O trabalhador do it-campo (`ocr_gpu_worker.py`) entrega
`data/sei_cache/integra_<tag>/NNN.ocr_gpu.txt` (+ `.ocr_gpu.json`); este integrador:

  · documento SEM texto (< 40 chars)        → preenche (texto/NNN_<slug>.txt com o cabeçalho da casa);
  · documento lido pelo TESSERACT (ocr=True) → substitui; o texto antigo fica em `ocr_anterior` (nada se perde);
  · documento NATIVO (texto do próprio PDF)  → NUNCA toca (texto nativo é a verdade; OCR só piora);
  · texto da GPU vazio                       → não aplica.
Idempotente (registro em `data/sei_ocr_gpu_aplicado.jsonl`). Depois avisa a propagação (`sei_arquivado`).

    python -m tools.sei_ocr_gpu_integrar            # aplica o que chegou
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
DATA = _REPO / "data"
ARQUIVO, CACHE = DATA / "sei_arquivo", DATA / "sei_cache"
LEDGER = DATA / "sei_ocr_gpu_aplicado.jsonl"
MIN_CHARS = 40


def _slug(t: str) -> str:            # mesmo slug do sei_arquivar
    return re.sub(r"[^0-9a-z]+", "_", (t or "").lower())[:40].strip("_") or "doc"


def _chars(d: dict) -> int:
    try:
        return int(d.get("chars") or 0)
    except (TypeError, ValueError):
        return 0


def _corpo(t: str) -> str:
    return re.sub(r"\[página \d+\]", "", t or "").strip()


def _aplicados() -> set[str]:
    if not LEDGER.exists():
        return set()
    return {json.loads(ln)["arq"] for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()}


def integrar() -> dict:
    res = {"preenchidos": 0, "substituidos": 0, "nativos_mantidos": 0, "sem_manifesto": 0, "fora_do_manifesto": 0,
           "processos": 0}
    feitos = _aplicados()
    novos: list[dict] = []
    for pasta in sorted(CACHE.glob("integra_*")):
        gpus = sorted(p for p in pasta.glob("*.ocr_gpu.txt") if str(p) not in feitos)
        if not gpus:
            continue
        tag = pasta.name[len("integra_"):]
        mpath = ARQUIVO / tag / "manifest.json"
        if not mpath.exists():
            res["sem_manifesto"] += len(gpus)
            continue
        man = json.loads(mpath.read_text(encoding="utf-8"))
        por_i = {int(d["i"]): d for d in man.get("docs") or [] if str(d.get("i", "")).isdigit()}
        mudou = False
        for g in gpus:
            i = int(g.name.split(".")[0])
            meta = json.loads(g.with_suffix("").with_suffix(".ocr_gpu.json").read_text()) \
                if g.with_suffix("").with_suffix(".ocr_gpu.json").exists() else {}
            texto = _corpo(g.read_text(encoding="utf-8"))
            d = por_i.get(i)
            reg = {"arq": str(g), "tag": tag, "i": i, "em": time.strftime("%F %T")}
            if d is None:
                res["fora_do_manifesto"] += 1
                novos.append({**reg, "acao": "fora_do_manifesto"})
                continue
            nativo = _chars(d) >= MIN_CHARS and not d.get("ocr")
            if nativo or len(texto) < MIN_CHARS:
                res["nativos_mantidos"] += int(nativo)
                novos.append({**reg, "acao": "nativo_mantido" if nativo else "gpu_vazio"})
                continue
            cab = f"[{d.get('titulo', '')}] (fase: {d.get('fase', '')} · tipo: {d.get('tipo', '')})\n\n"
            if _chars(d) >= MIN_CHARS and d.get("texto"):           # Tesseract → guarda o antigo e substitui
                antigo = ARQUIVO / tag / d["texto"]
                guarda = antigo.with_suffix(".tesseract.txt")
                if antigo.exists() and not guarda.exists():
                    guarda.write_text(antigo.read_text(encoding="utf-8"), encoding="utf-8")
                d["ocr_anterior"] = str(guarda.relative_to(ARQUIVO / tag))
                destino = antigo
                res["substituidos"] += 1
                acao = "substituido"
            else:                                                      # sem texto → preenche
                destino = ARQUIVO / tag / "texto" / f"{i:03d}_{_slug(d.get('titulo', ''))}.txt"
                d["texto"] = str(destino.relative_to(ARQUIVO / tag))
                d["texto_recuperado_ocr_gpu"] = True
                res["preenchidos"] += 1
                acao = "preenchido"
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(cab + texto, encoding="utf-8")
            d.update(chars=len(texto), ocr=True, ocr_motor=str(meta.get("motor") or "surya-ocr-2.5"),
                     ocr_paginas=meta.get("paginas"), ocr_cortado=bool(meta.get("cortado")))
            mudou = True
            novos.append({**reg, "acao": acao})
        if mudou:
            tmp = mpath.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, mpath)
            res["processos"] += 1
    if novos:
        with LEDGER.open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(n, ensure_ascii=False) + "\n" for n in novos)
    return res


def main() -> int:
    res = integrar()
    print(json.dumps(res, ensure_ascii=False))
    if res["preenchidos"] or res["substituidos"]:
        try:
            from compliance_agent import propagacao
            pc = propagacao.conectar()
            try:
                propagacao.emitir(pc, propagacao.carregar(), "sei_arquivado",
                                  f"OCR por IA (GPU): {res['preenchidos']} documento(s) preenchido(s) e "
                                  f"{res['substituidos']} relido(s) em {res['processos']} processo(s)")
            finally:
                pc.close()
        except Exception as e:  # noqa: BLE001 — aviso de propagação é acessório; o texto já está no arquivo
            print(f"propagação não avisada: {type(e).__name__}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
