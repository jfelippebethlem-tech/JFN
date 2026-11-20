"""Aplica o OCR por IA da GPU do it-campo (Surya 2.5) ao ARQUIVO canônico do SEI (`data/sei_arquivo/<tag>`).

POR QUE (18/11/2026, medido com gabarito — 79 páginas nativas 'sujadas' como escaneado): o Tesseract de produção
acerta 78,0% dos valores em R$, 89,8% das datas e 92,5% dos CNPJ; o Surya na GPU, 99,7% / 100% / 95,7%. 219.125
documentos do acervo (60%) foram lidos pelo Tesseract. O trabalhador do it-campo (`ocr_gpu_worker.py`) entrega
`data/sei_cache/integra_<tag>/NNN.ocr_gpu.txt` (+ `.ocr_gpu.json`); este integrador:

  · documento SEM texto (< 40 chars)        → preenche (texto/NNN_<slug>.txt com o cabeçalho da casa);
  · documento que JÁ TEM texto (Tesseract/reserva) → NUNCA substitui; o novo fica ao lado (`.gpu.txt` Surya, `.reserva.txt` RapidOCR);
  · documento NATIVO (texto do próprio PDF)  → NUNCA toca (texto nativo é a verdade; OCR só piora);
  · texto da GPU vazio                       → não aplica.
Idempotente (registro em `data/sei_ocr_gpu_aplicado.jsonl`). Depois avisa a propagação (`sei_arquivado`).

RESERVA (18/11/2026, `tools/sei_ocr_reserva.py`): quando a GPU para, a VM-2 lê com RapidOCR (PP-OCRv5 em ONNX) e entrega
`NNN.ocr_reserva.txt` (+ `.ocr_reserva.json`). PRECEDÊNCIA por motor — só entra texto de motor MAIS FORTE que o atual:
  nativo (nunca tocado)  >  Surya/GPU (3)  >  reserva (2)  >  Tesseract (1)  >  sem texto (0)
Reserva substitui Tesseract e preenche sem-texto; Surya substitui reserva quando chegar (o texto da reserva fica em
`.reserva.txt`, o do Tesseract segue em `.tesseract.txt`); reserva que chega DEPOIS do Surya não entra (`mantido_superior`).
O registro anota o motor (`surya` | `reserva`).

CNPJ NÃO SE PERDE (20/11/2026, lote real de 20 documentos do frio conferido à mão): o Surya devolve bloco VAZIO em parte
das páginas tortas ou com brasão/código de barras — numa NFS-e de R$ 100.033,95 o texto novo perdeu razão social,
CNPJ do prestador e discriminação que o Tesseract tinha; em 15 substituições, 4 de 28 CNPJ com DV válido sumiram (3
documentos). Perda de bloco não se mede só por CNPJ, e o dono pediu 100% de acurácia: desde então o texto existente NUNCA é
substituído (`mantido_existente_gpu_ao_lado`); a GPU só PREENCHE documento sem texto. Tokens do modelo (`<|NN|>`) saem.

    python -m tools.sei_ocr_gpu_integrar            # aplica o que chegou
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from compliance_agent.cpf_cnpj import cnpj_valido
from compliance_agent.sei.acervo_texto import foi_ocr, mutar_manifesto

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


_RE_CNPJ = re.compile(r"(?<!\d)\d{2}[.,]?\d{3}[.,]?\d{3}\s?/\s?\d{4}[-.,]?\d{2}(?!\d)")


def cnpjs(texto: str) -> set[str]:
    """CNPJ com DV válido no texto (14 dígitos). DV válido por acaso em leitura errada é raro: serve de marcador de
    'esse bloco foi lido' para comparar dois OCR do mesmo documento."""
    return {d for d in (re.sub(r"\D", "", m.group()) for m in _RE_CNPJ.finditer(texto or "")) if cnpj_valido(d)}


def _aplicados() -> set[str]:
    if not LEDGER.exists():
        return set()
    return {json.loads(ln)["arq"] for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()}


# sufixo da entrega → (motor, posto). Surya antes da reserva na mesma rodada: a reserva que chegar junto não entra.
FONTES = ((".ocr_gpu", "surya", 3), (".ocr_reserva", "reserva", 2))
MOTOR_PADRAO = {"surya": "surya-ocr-2.5", "reserva": "reserva:rapidocr"}


def _posto(d: dict) -> int:
    """Força do texto ATUAL do documento: 4 nativo · 3 Surya · 2 reserva · 1 Tesseract · 0 sem texto."""
    if _chars(d) >= MIN_CHARS and not foi_ocr(d):    # nativo: o texto do próprio PDF é a verdade
        return 4
    if _chars(d) < MIN_CHARS or not d.get("texto"):
        return 0
    motor = str(d.get("ocr_motor") or "")
    return 3 if motor.startswith("surya") else 2 if motor.startswith("reserva") else 1


_RX_TOKEN_MODELO = re.compile(r"<\|\d+\|>")


def integrar() -> dict:
    res = {"preenchidos": 0, "substituidos": 0, "nativos_mantidos": 0, "sem_manifesto": 0, "fora_do_manifesto": 0,
           "processos": 0}
    corrompidos = mantidos = perderia = 0
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
        parcial = {k: 0 for k in res} | {"corrompidos": 0, "mantidos": 0, "perderia_cnpj": 0}
        da_pasta: list[dict] = []

        def aplicar(man: dict) -> bool:
            # 20/11/2026: sob a trava do manifesto (reler → mudar → gravar, `acervo_texto.mutar_manifesto`): o
            # integrador lia o manifesto e regravava o objeto inteiro — o que a captura/arquivamento gravasse no meio
            # sumia. Contagens e registro só valem se a gravação aconteceu (zerados a cada tentativa).
            parcial.update({k: 0 for k in parcial})
            da_pasta.clear()
            por_i = {int(d["i"]): d for d in man.get("docs") or [] if str(d.get("i", "")).isdigit()}
            mudou = False
            for g, suf, motor, posto in entregas:
                i = int(g.name.split(".")[0])
                gmeta = g.with_name(g.name[:-len(".txt")] + ".json")
                meta = json.loads(gmeta.read_text()) if gmeta.exists() else {}
                texto = _RX_TOKEN_MODELO.sub("", _corpo(g.read_text(encoding="utf-8")))
                d = por_i.get(i)
                reg = {"arq": str(g), "tag": tag, "i": i, "motor": motor, "em": time.strftime("%F %T")}
                if d is None:
                    parcial["fora_do_manifesto"] += 1
                    da_pasta.append({**reg, "acao": "fora_do_manifesto"})
                    continue
                atual = _posto(d)
                if atual == 4:
                    parcial["nativos_mantidos"] += 1
                    da_pasta.append({**reg, "acao": "nativo_mantido"})
                    continue
                if "\ufffd" in texto or len(texto) < MIN_CHARS:  # acento cortado (U+FFFD) ou motor sem texto: não entra
                    parcial["corrompidos"] += int("\ufffd" in texto)   # apaga a entrega e NÃO registra: a releitura pode chegar
                    g.unlink(missing_ok=True)
                    gmeta.unlink(missing_ok=True)
                    continue
                if atual >= posto:                          # já tem texto de motor igual ou mais forte (Surya > reserva)
                    parcial["mantidos"] += 1
                    da_pasta.append({**reg, "acao": "mantido_superior", "motor_atual": str(d.get("ocr_motor") or "")})
                    continue
                cab = f"[{d.get('titulo', '')}] (fase: {d.get('fase', '')} · tipo: {d.get('tipo', '')})\n\n"
                if atual > 0:
                    # 20/11/2026, dono: "100% acurado". Conferência à mão do 1º lote do frio: o Surya devolveu
                    # BLOCOS VAZIOS onde o Tesseract tinha razão social, CNPJ e discriminação (NFS-e de
                    # R$ 100.033,95; emitente de um DANFE) e errou 4 números de uma planilha. Perda de bloco não
                    # se mede só por CNPJ — então o texto existente NUNCA é substituído: o da GPU fica AO LADO
                    # (`.gpu.txt`), como complemento para quem lê, e o canônico não muda.
                    antigo = ARQUIVO / tag / d["texto"]
                    nome = "gpu" if motor == "surya" else "reserva"           # um arquivo ao lado POR motor
                    ao_lado = antigo.with_suffix(f".{nome}.txt")
                    if not ao_lado.exists():
                        ao_lado.write_text(cab + texto, encoding="utf-8")
                        d[f"ocr_{nome}_ao_lado"] = str(ao_lado.relative_to(ARQUIVO / tag))
                        mudou = True
                    parcial["mantidos"] += 1
                    da_pasta.append({**reg, "acao": "mantido_existente_gpu_ao_lado"})
                    continue
                else:                                                      # sem texto → preenche
                    destino = ARQUIVO / tag / "texto" / f"{i:03d}_{_slug(d.get('titulo', ''))}.txt"
                    d["texto"] = str(destino.relative_to(ARQUIVO / tag))
                    d[f"texto_recuperado_ocr_{'gpu' if motor == 'surya' else 'reserva'}"] = True
                    parcial["preenchidos"] += 1
                    acao = "preenchido"
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_text(cab + texto, encoding="utf-8")
                d.update(chars=len(texto), ocr=True, ocr_motor=str(meta.get("motor") or MOTOR_PADRAO[motor]),
                         ocr_paginas=meta.get("paginas"), ocr_cortado=bool(meta.get("cortado")))
                mudou = True
                da_pasta.append({**reg, "acao": acao})
            return mudou

        r = mutar_manifesto(ARQUIVO / tag, aplicar)
        if r is None:                       # trava não veio ou manifesto ilegível: nada gravado, volta na próxima
            res["manifesto_ocupado"] = res.get("manifesto_ocupado", 0) + len(entregas)
            continue
        for k in ("preenchidos", "substituidos", "nativos_mantidos", "fora_do_manifesto"):
            res[k] += parcial[k]
        corrompidos += parcial["corrompidos"]
        mantidos += parcial["mantidos"]
        perderia += parcial["perderia_cnpj"]
        res["processos"] += int(r is True)
        novos.extend(da_pasta)
    if corrompidos:
        res["texto_corrompido"] = corrompidos
    if mantidos:
        res["mantido_superior"] = mantidos
    if perderia:
        res["mantido_perderia_cnpj"] = perderia
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
