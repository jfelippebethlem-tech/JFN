# -*- coding: utf-8 -*-
"""Conferência por RECORTE do número crítico (plano mestre v2 §7 "conferência por recorte"; item O3.6).

O número que o OCR leu (valor, CNPJ, data, nº de processo) é procurado nas LINHAS do lateral do E5; a bbox da linha
que o contém é recortada da MESMA renderização (`ocr._imagens`, 200 dpi), com margem e ampliação, e relida por um
motor de OUTRA FAMÍLIA que a do motor que leu a página (Surya/GPU ⇒ RapidOCR; RapidOCR ⇒ Tesseract; Tesseract ⇒
RapidOCR). Só confirma se o número normalizado (`ocr_ia_prova.extrair(tolerante=True)`) sair IGUAL do recorte: é uma
leitura independente, focada no ponto onde o número está — fonte `recorte:<motor>` de NÍVEL A no E6.

Fora do recorte (declarado, não "confirmado por omissão"):
  · tipos que dependem de palavra-chave fora da linha (NF, contrato, ata) — ficam com as outras fontes;
  · QUANTIDADE: o `ocr_ia_prova` não extrai quantidade (é coluna de tabela; extrator por regex fabricaria o sinal);
  · número sem linha que o contenha inteiro (quebrado entre linhas) ou bbox fora da página: `sem_bbox`.

Puro sobre um leitor injetável (`Leitor`): os testes usam um falso; o real é RapidOCR/Tesseract da casa.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Protocol

from compliance_agent.aplicacao.estagios import ocr as O
from compliance_agent.sei import ocr_ia_prova as P

TIPOS_RECORTE = ("valor", "cnpj", "data", "processo")
MARGEM = 12                      # px a 200 dpi (~1,5 mm): não corta o dígito da borda nem pega a linha vizinha
ESCALA = 2                       # ampliação do recorte (linha de 25–35 px vira 50–70: a faixa boa dos dois motores)
# o detector de linha parte "82.526,42" em duas caixas e a montagem junta com espaço ("82.526, 42", "0 , 00"):
# medido em 9 de 146 recortes de NF (23/11). Só o espaço COLADO num separador entre dígitos sai — nunca dígito-espaço-dígito
_RX_ESPACO_SEP = re.compile(r"(?<=\d)\s*([.,/-])\s*(?=\d)")
_FAMILIA_DO_RECORTE = {"gpu": "rapidocr", "surya": "rapidocr", "rapidocr": "tesseract", "reserva": "tesseract",
                       "tesseract": "rapidocr"}


class Leitor(Protocol):
    familia: str

    def motor(self) -> str: ...

    def ler_imagem(self, img) -> str: ...


def familia_do_motor(motor: str) -> str:
    m = (motor or "").lower()
    for f in ("tesseract", "rapidocr", "reserva", "surya", "gpu"):
        if m.startswith(f) or f in m.split("@")[0]:
            return f
    return m.split("@")[0]


def familia_para(motor_da_pagina: str) -> str | None:
    """Família que relê o recorte de uma página lida por `motor_da_pagina` (nunca a mesma)."""
    return _FAMILIA_DO_RECORTE.get(familia_do_motor(motor_da_pagina))


def compactar(texto: str) -> str:
    return _RX_ESPACO_SEP.sub(r"\1", texto or "")


def _lidos(texto: str) -> set[tuple[str, str]]:
    return {(y["tipo"], y["norma"]) for y in P.extrair(compactar(texto), tolerante=True)}


def linhas_com(pagina: dict, tipo: str, norma: str) -> list[list[float]]:
    """bboxes das linhas do E5 cujo texto, sozinho, contém o número (mesma extração do E6)."""
    out = []
    for ln in pagina.get("linhas") or []:
        bb = ln.get("bbox") or []
        if len(bb) != 4:
            continue
        if any((x["tipo"], x["norma"]) == (tipo, norma) for x in P.extrair(ln.get("texto") or "", tolerante=True)):
            out.append([float(v) for v in bb])
    return out


def recortar(img, bbox: list[float]):
    """Recorte da bbox com `MARGEM`, ampliado `ESCALA`× (Lanczos). None se a bbox cai fora da imagem."""
    import cv2
    h, w = img.shape[:2]
    x0, y0, x1, y1 = bbox
    x0, y0 = max(int(x0) - MARGEM, 0), max(int(y0) - MARGEM, 0)
    x1, y1 = min(int(x1 + 0.999) + MARGEM, w), min(int(y1 + 0.999) + MARGEM, h)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    c = img[y0:y1, x0:x1]
    return cv2.resize(c, ((x1 - x0) * ESCALA, (y1 - y0) * ESCALA), interpolation=cv2.INTER_LANCZOS4)


def conferir(pdf: Path, e5: dict, numeros: list[dict], leitores: dict[str, Leitor]) -> list[dict]:
    """Um registro por número de `TIPOS_RECORTE`: {tipo, norma, pagina, estado, motor?, bbox?, texto?, recorte_sha?}.
    estado: `confere` (o número saiu igual do recorte), `nao_confere`, `sem_bbox`, `sem_leitor` (sem motor de outra
    família neste nó). Lê cada página uma vez e relê cada bbox uma vez."""
    pags = e5.get("paginas") or {}
    alvo: dict[int, list[dict]] = {}
    out = []
    vistos = set()
    for x in numeros:
        k = (x["tipo"], x["norma"], int(x["pagina"]))
        if x["tipo"] not in TIPOS_RECORTE or k in vistos:
            continue
        vistos.add(k)
        alvo.setdefault(k[2], []).append(x)
    for n in sorted(alvo):
        pg = pags.get(str(n)) or {}
        fam = familia_para(pg.get("motor") or "")
        leitor = leitores.get(fam or "")
        img = None
        lidos_bbox: dict[tuple, tuple] = {}          # bbox → (texto, sha): o bloco grande do Surya é lido UMA vez
        for x in alvo[n]:
            r = {"tipo": x["tipo"], "norma": x["norma"], "pagina": n}
            bbs = linhas_com(pg, x["tipo"], x["norma"])
            if not bbs:
                out.append(r | {"estado": "sem_bbox"})
                continue
            if leitor is None:
                out.append(r | {"estado": "sem_leitor", "familia_pedida": fam})
                continue
            if img is None:
                img = next(i for _, i, _, _ in O._imagens(pdf, [n]))
            r |= {"estado": "nao_confere", "motor": leitor.motor()}
            for bb in bbs:
                if tuple(bb) not in lidos_bbox:
                    c = recortar(img, bb)
                    lidos_bbox[tuple(bb)] = (leitor.ler_imagem(c), hashlib.sha256(c.tobytes()).hexdigest()) \
                        if c is not None else None
                if lidos_bbox[tuple(bb)] is None:
                    continue
                txt, sha_c = lidos_bbox[tuple(bb)]
                lidos = _lidos(txt)
                r |= {"bbox": bb, "texto": txt, "recorte_sha": sha_c}
                if (x["tipo"], x["norma"]) in lidos:
                    r["estado"] = "confere"
                    break
            out.append(r)
    return out


def chaves_confirmadas(recortes: list[dict]) -> dict[str, set]:
    """{`recorte:<motor>`: {(tipo, norma)}} — conjunto re-derivado do TEXTO guardado do recorte (não do estado)."""
    out: dict[str, set] = {}
    for r in recortes:
        if r.get("estado") != "confere":
            continue
        if (r["tipo"], r["norma"]) in _lidos(r.get("texto") or ""):
            out.setdefault(f"recorte:{r['motor']}", set()).add((r["tipo"], r["norma"]))
    return out


# ── leitores reais ─────────────────────────────────────────────────────────────────────────────────────────────
class LeitorRapidOCR:
    familia = "rapidocr"

    def __init__(self):
        self._ex = O.ExecutorCPU()

    def motor(self) -> str:
        return self._ex.motor().replace("(CPU)", "(CPU, recorte)")

    def ler_imagem(self, img) -> str:
        import numpy as np
        return self._ex.ler_img(np.ascontiguousarray(img)).texto


class LeitorTesseract:
    familia = "tesseract"

    def motor(self) -> str:
        import pytesseract
        return f"tesseract@{pytesseract.get_tesseract_version()} por psm6 (recorte)"

    def ler_imagem(self, img) -> str:
        import pytesseract
        return pytesseract.image_to_string(img, lang="por", config="--psm 6")


def leitores_do_no() -> dict[str, Leitor]:
    """Os leitores de recorte que este nó tem (sem o pacote, a família fica de fora: `sem_leitor`, declarado)."""
    from importlib.util import find_spec
    out: dict[str, Leitor] = {}
    if find_spec("rapidocr") is not None:
        out["rapidocr"] = LeitorRapidOCR()
    if find_spec("pytesseract") is not None:
        from compliance_agent.sei import ocr_docs
        if ocr_docs._tesseract_ok():
            out["tesseract"] = LeitorTesseract()
    return out
