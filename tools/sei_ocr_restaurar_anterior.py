# -*- coding: utf-8 -*-
"""Desfaz as substituições de texto por OCR (Surya/reserva) feitas até 20/11/2026: o texto ANTERIOR volta a ser o
canônico e o do OCR novo fica AO LADO (`.gpu.txt` / `.reserva.txt`). Nada é apagado.

Por quê (20/11/2026, dono: "100% acurado"): conferência à mão do 1º lote do arquivo frio achou blocos inteiros
perdidos pelo Surya (razão social, CNPJ e discriminação de uma NFS-e de R$ 100.033,95) e números errados; medido nas
7.985 substituições conferíveis do registro: 77 (1,0%) perderam CNPJ válido que o Tesseract tinha e 1.844 (23,1%)
deixaram de ter algum valor em R$ do texto anterior. Desde então o integrador nunca substitui
(`tools/sei_ocr_gpu_integrar.py`); isto alinha o passado à mesma regra.

    python -m tools.sei_ocr_restaurar_anterior --ensaio     # só conta
    python -m tools.sei_ocr_restaurar_anterior              # aplica, sob a trava de cada manifesto
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from compliance_agent.sei.acervo_texto import mutar_manifesto

ARQUIVO = Path("data/sei_arquivo")
LEDGER = Path("data/sei_ocr_gpu_aplicado.jsonl")
_CHAVES_OCR = ("ocr_motor", "ocr_paginas", "ocr_cortado")


def _restaurar_doc(pasta: Path, d: dict) -> str | None:
    """Devolve a ação feita no doc (ou None se não havia o que restaurar)."""
    ant = d.get("ocr_anterior")
    motor = str(d.get("ocr_motor") or "")
    if not ant or not d.get("texto") or not (motor.startswith("surya") or motor.startswith("reserva")):
        return None
    atual, anterior = pasta / d["texto"], pasta / ant
    if not anterior.exists() or not atual.exists():
        return "sem_arquivo"
    nome = "gpu" if motor.startswith("surya") else "reserva"
    ao_lado = atual.with_suffix(f".{nome}.txt")
    if not ao_lado.exists():
        ao_lado.write_text(atual.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    texto_ant = anterior.read_text(encoding="utf-8", errors="replace")
    atual.write_text(texto_ant, encoding="utf-8")
    d[f"ocr_{nome}_ao_lado"] = str(ao_lado.relative_to(pasta))
    d["chars"] = len(texto_ant)
    d["ocr_restaurado_em"] = time.strftime("%F %T")
    for k in _CHAVES_OCR:
        d.pop(k, None)
    return "restaurado"


def rodar(ensaio: bool) -> dict:
    tags = sorted({json.loads(ln)["tag"] for ln in LEDGER.open(encoding="utf-8")
                   if '"substituido"' in ln})
    res = {"pastas": 0, "restaurados": 0, "sem_arquivo": 0, "travadas": 0}
    for tag in tags:
        pasta = ARQUIVO / tag
        if not (pasta / "manifest.json").exists():
            continue
        if ensaio:
            man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
            n = sum(1 for d in man.get("docs", []) if isinstance(d, dict) and d.get("ocr_anterior")
                    and str(d.get("ocr_motor") or "").startswith(("surya", "reserva")))
            res["restaurados"] += n
            res["pastas"] += bool(n)
            continue
        feitos: list[str] = []

        def fn(man, pasta=pasta, feitos=feitos):
            for d in man.get("docs", []):
                if isinstance(d, dict):
                    a = _restaurar_doc(pasta, d)
                    if a:
                        feitos.append(a)
            return bool(feitos)
        if mutar_manifesto(pasta, fn, espera=60) is None and not feitos:
            res["travadas"] += 1
            continue
        res["pastas"] += bool(feitos)
        res["restaurados"] += feitos.count("restaurado")
        res["sem_arquivo"] += feitos.count("sem_arquivo")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ensaio", action="store_true", help="só conta, não grava")
    a = ap.parse_args(argv)
    print(json.dumps(rodar(a.ensaio), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
