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

RESERVA (18/11/2026, `tools/sei_ocr_reserva.py`): quando a GPU para, a VM-2 lê com RapidOCR (PP-OCRv5 em ONNX) e entrega
`NNN.ocr_reserva.txt` (+ `.ocr_reserva.json`). PRECEDÊNCIA por motor — só entra texto de motor MAIS FORTE que o atual:
  nativo (nunca tocado)  >  Surya/GPU (3)  >  reserva (2)  >  Tesseract (1)  >  sem texto (0)
Reserva substitui Tesseract e preenche sem-texto; Surya substitui reserva quando chegar (o texto da reserva fica em
`.reserva.txt`, o do Tesseract segue em `.tesseract.txt`); reserva que chega DEPOIS do Surya não entra (`mantido_superior`).
O registro anota o motor (`surya` | `reserva`).

    python -m tools.sei_ocr_gpu_integrar            # aplica o que chegou
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
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


# sufixo da entrega → (motor, posto). Surya antes da reserva na mesma rodada: a reserva que chegar junto não entra.
FONTES = ((".ocr_gpu", "surya", 3), (".ocr_reserva", "reserva", 2))
MOTOR_PADRAO = {"surya": "surya-ocr-2.5", "reserva": "reserva:rapidocr"}


def _posto(d: dict) -> int:
    """Força do texto ATUAL do documento: 4 nativo · 3 Surya · 2 reserva · 1 Tesseract · 0 sem texto."""
    if _chars(d) >= MIN_CHARS and not d.get("ocr"):    # nativo: o texto do próprio PDF é a verdade
        return 4
    if _chars(d) < MIN_CHARS or not d.get("texto"):
        return 0
    motor = str(d.get("ocr_motor") or "")
    return 3 if motor.startswith("surya") else 2 if motor.startswith("reserva") else 1


def integrar() -> dict:
    res = {"preenchidos": 0, "substituidos": 0, "nativos_mantidos": 0, "sem_manifesto": 0, "fora_do_manifesto": 0,
           "processos": 0}
    corrompidos = mantidos = 0
    feitos = _aplicados()
    novos: list[dict] = []
    for pasta in sorted(CACHE.glob("integra_*")):
        entregas = [(g, suf, motor, posto) for suf, motor, posto in FONTES
                    for g in sorted(pasta.glob(f"*{suf}.txt")) if str(g) not in feitos]
        if not entregas:
            continue
        entregas.sort(key=lambda e: (int(e[0].name.split(".")[0]), -e[3]))   # por documento, o motor mais forte primeiro
        tag = pasta.name[len("integra_"):]
        mpath = ARQUIVO / tag / "manifest.json"
        if not mpath.exists():
            res["sem_manifesto"] += len(entregas)
            continue
        man = json.loads(mpath.read_text(encoding="utf-8"))
        por_i = {int(d["i"]): d for d in man.get("docs") or [] if str(d.get("i", "")).isdigit()}
        mudou = False
        for g, suf, motor, posto in entregas:
            i = int(g.name.split(".")[0])
            gmeta = g.with_name(g.name[:-len(".txt")] + ".json")
            meta = json.loads(gmeta.read_text()) if gmeta.exists() else {}
            texto = _corpo(g.read_text(encoding="utf-8"))
            d = por_i.get(i)
            reg = {"arq": str(g), "tag": tag, "i": i, "motor": motor, "em": time.strftime("%F %T")}
            if d is None:
                res["fora_do_manifesto"] += 1
                novos.append({**reg, "acao": "fora_do_manifesto"})
                continue
            atual = _posto(d)
            if atual == 4:
                res["nativos_mantidos"] += 1
                novos.append({**reg, "acao": "nativo_mantido"})
                continue
            if "\ufffd" in texto or len(texto) < MIN_CHARS:  # acento cortado (U+FFFD) ou motor sem texto: não entra
                corrompidos += int("\ufffd" in texto)   # apaga a entrega e NÃO registra: a releitura pode chegar depois
                g.unlink(missing_ok=True)
                gmeta.unlink(missing_ok=True)
                continue
            if atual >= posto:                          # já tem texto de motor igual ou mais forte (Surya > reserva)
                mantidos += 1
                novos.append({**reg, "acao": "mantido_superior", "motor_atual": str(d.get("ocr_motor") or "")})
                continue
            cab = f"[{d.get('titulo', '')}] (fase: {d.get('fase', '')} · tipo: {d.get('tipo', '')})\n\n"
            if atual > 0:                               # Tesseract ou reserva → guarda o antigo e substitui
                antigo = ARQUIVO / tag / d["texto"]
                guarda = antigo.with_suffix(".tesseract.txt" if atual == 1 else ".reserva.txt")
                if antigo.exists() and not guarda.exists():
                    guarda.write_text(antigo.read_text(encoding="utf-8"), encoding="utf-8")
                d["ocr_anterior"] = str(guarda.relative_to(ARQUIVO / tag))
                destino = antigo
                res["substituidos"] += 1
                acao = "substituido"
            else:                                                      # sem texto → preenche
                destino = ARQUIVO / tag / "texto" / f"{i:03d}_{_slug(d.get('titulo', ''))}.txt"
                d["texto"] = str(destino.relative_to(ARQUIVO / tag))
                d[f"texto_recuperado_ocr_{'gpu' if motor == 'surya' else 'reserva'}"] = True
                res["preenchidos"] += 1
                acao = "preenchido"
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(cab + texto, encoding="utf-8")
            d.update(chars=len(texto), ocr=True, ocr_motor=str(meta.get("motor") or MOTOR_PADRAO[motor]),
                     ocr_paginas=meta.get("paginas"), ocr_cortado=bool(meta.get("cortado")))
            mudou = True
            novos.append({**reg, "acao": acao})
        if mudou:
            tmp = mpath.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, mpath)
            res["processos"] += 1
    if corrompidos:
        res["texto_corrompido"] = corrompidos
    if mantidos:
        res["mantido_superior"] = mantidos
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
                                  f"OCR por IA (GPU/reserva): {res['preenchidos']} documento(s) preenchido(s) e "
                                  f"{res['substituidos']} relido(s) em {res['processos']} processo(s)")
            finally:
                pc.close()
        except (ImportError, OSError, ValueError, KeyError, sqlite3.Error) as e:   # aviso é acessório; o texto já está no arquivo
            print(f"propagação não avisada: {type(e).__name__}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
