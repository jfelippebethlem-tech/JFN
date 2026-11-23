# -*- coding: utf-8 -*-
"""Confirmação do OCR — documento a documento, apontando as páginas (plano de reescrita, Fase 5).

POR QUE (23/11/2026). A leitura integral só lê o que sabemos estar certo (dono: "só entra no lote o que sabemos ser
100% correto e não duplicado"; "nos processos que temos certeza que o ocr, a extração, estão todos certos em tudo").
27,1% do texto do acervo veio de OCR e 7.960 processos têm ao menos um documento de OCR. A trava `ocr_ia_prova`
confere número a número, mas só para o OCR por IA (Surya/RapidOCR): documento de Tesseract "passa direto" — e o
Tesseract errou 8,2% na bancada de 40 páginas (91,8%). Exemplo medido: na mesma página, Surya leu "Data 45/02/17" e
RapidOCR "Data: 20 y 02315" — dois motores que discordam não provam nada.

REGRA. Documento de OCR (qualquer motor) está CONFIRMADO quando:
  1. existe ao menos uma leitura INDEPENDENTE (outro motor; nunca o próprio — a mesma leitura não confirma a si);
  2. TODO número crítico do texto canônico (CNPJ, valor, data, processo, contrato, NE/OB/NF…) é confirmado por
     outra leitura, pelo SIAFE do mesmo processo ou por documento nativo do mesmo processo
     (`ocr_ia_prova.confirmar_numeros` — concordância LITERAL do número normalizado; DV válido não confirma);
  3. as PALAVRAS batem com a melhor outra leitura (F1 de tokens ≥ `LIMIAR_PALAVRAS`) — pega a leitura desastrosa
     cujos números por acaso coincidem.
Senão: `a_conferir`, com os números sem confirmação e, quando há leitura paginada, as PÁGINAS onde eles estão — só
essas vão à conferência por recorte / Opus / humano. Sem segunda leitura: `sem_segunda_leitura` (pede uma).

Registro durável: `data/sei_ocr_confirmacao.jsonl` (só acrescenta; a última linha de (tag, i) vale).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

from compliance_agent.sei import ocr_ia_prova as P

RAIZ = Path(__file__).resolve().parents[2]
REGISTRO = RAIZ / "data" / "sei_ocr_confirmacao.jsonl"
VERSAO = "oc-1"
LIMIAR_PALAVRAS = 0.80
_TOKEN = re.compile(r"[a-záéíóúâêôãõçà]{3,}", re.I)


def motor_do_doc(doc: dict) -> str:
    m = str(doc.get("ocr_motor") or "")
    if m.startswith("surya"):
        return "gpu"
    if m.startswith("reserva"):
        return "reserva"
    return "tesseract"


def _f1_palavras(a: str, b: str) -> float:
    ta, tb = Counter(t.lower() for t in _TOKEN.findall(a)), Counter(t.lower() for t in _TOKEN.findall(b))
    if not ta or not tb:
        return 0.0
    comum = sum((ta & tb).values())
    p, r = comum / sum(tb.values()), comum / sum(ta.values())
    return 0.0 if comum == 0 else 2 * p * r / (p + r)


_ROTULADOS = {"contrato", "processo", "ne", "ob", "nf", "ata", "empenho"}


def _digitos_presentes(d: dict, planas: dict[str, str]) -> bool:
    """Número cujo RECONHECIMENTO depende de rótulo ("CONTRATO Nº", "NE", "OB"…): ruído no rótulo ("C0NTRATO") faz o
    extrator não vê-lo na outra leitura. Confirma se a MESMA sequência numérica (zeros à esquerda livres, separadores
    / . - iguais) aparece literalmente numa leitura independente. Valor, CNPJ e data NÃO entram: dependem só do
    número, e o extrator já os acha sem rótulo."""
    if d["tipo"] not in _ROTULADOS:
        return False
    partes = [p for p in re.split(r"[/.\-]", d["norma"]) if p]
    if not partes or sum(len(p) for p in partes) < 5:
        return False
    rx = re.compile(r"(?<!\d)" + r"\s*[/.\-]\s*".join(r"0*" + re.escape(p.lstrip("0") or "0") for p in partes) + r"(?!\d)")
    return any(rx.search(t) for t in planas.values())


def confirmar(canonico: str, leituras: dict[str, object], externos: dict[str, set] | None = None,
              outros_docs: dict[str, set] | None = None) -> dict:
    """`leituras` = {fonte: texto} ou {fonte: {página: texto}} (paginada). Devolve o estado do documento."""
    planas = {f: ("\n".join(v[k] for k in sorted(v)) if isinstance(v, dict) else str(v)) for f, v in leituras.items()}
    planas = {f: t for f, t in planas.items() if t.strip()}
    numeros = P.extrair(canonico)
    if not planas:
        return {"estado": "sem_segunda_leitura", "numeros": len(numeros), "numeros_a_conferir": [],
                "paginas_a_conferir": [], "similaridade": None, "fontes": []}
    decididos = P.confirmar_numeros(numeros, planas, externos, outros_docs) if numeros else []
    pendentes = [d for d in decididos if d["estado"] != "confirmado" and not _digitos_presentes(d, planas)]
    sim = max(_f1_palavras(canonico, t) for t in planas.values())
    paginas: set[int] = set()
    for v in leituras.values():
        if isinstance(v, dict) and pendentes:
            for pg, t in v.items():
                lidos = P.extrair(t, tolerante=True)
                for d in pendentes:
                    if any(x["tipo"] == d["tipo"] and (x["norma"] == d["norma"] or P._parecido(d["tipo"], d["norma"],
                                                                                             x["norma"])) for x in lidos):
                        paginas.add(int(pg))
    ok = not pendentes and sim >= LIMIAR_PALAVRAS
    return {"estado": "confirmado" if ok else "a_conferir", "numeros": len(numeros),
            "numeros_a_conferir": [{k: d[k] for k in ("tipo", "norma", "literal", "estado")} for d in pendentes],
            "paginas_a_conferir": sorted(paginas), "similaridade": round(sim, 4), "fontes": sorted(planas)}


# ── leituras disponíveis de um documento do acervo ────────────────────────────────────────────────────────────
_CRU = {"gpu": ".ocr_gpu.txt", "reserva": ".ocr_reserva.txt"}


def leituras_do_doc(pasta: Path, doc: dict, cache: Path | None = None) -> dict[str, object]:
    """Outras leituras do MESMO documento, sem o próprio motor: cópias ao lado no arquivo (`.gpu/.reserva/.tesseract
    .txt`) e entregas cruas PAGINADAS do cache (`integra_<tag>/NNN.ocr_gpu.txt`, `.ocr_reserva.txt`, ou `.zst`)."""
    from compliance_agent.sei import acervo_texto
    from compliance_agent.sei.cache_arquivo import ler_bytes
    proprio = motor_do_doc(doc)
    out: dict[str, object] = {}
    rel = doc.get("texto")
    if rel:
        base = Path(pasta) / rel
        for nome in ("gpu", "reserva", "tesseract"):
            if nome == proprio:
                continue
            try:
                t = acervo_texto.sem_etiqueta(base.with_suffix(f".{nome}.txt").read_text(encoding="utf-8",
                                                                                      errors="ignore"),
                                              str(doc.get("titulo") or ""))
            except OSError:
                continue
            if len(t.strip()) >= acervo_texto.MIN_CHARS_CONTEUDO:
                out[f"{nome}_ao_lado"] = t
    cache = cache or (RAIZ / "data" / "sei_cache")
    i = str(doc.get("i", ""))
    if i.isdigit():
        for nome, suf in _CRU.items():
            if nome == proprio:
                continue
            cru = ler_bytes(cache / f"integra_{Path(pasta).name}" / f"{int(i):03d}{suf}")
            if cru:
                pags = P.paginas_da_ia(cru.decode("utf-8", "replace"))
                if pags:
                    out[f"{nome}_paginas"] = pags
    return out


def avaliar_processo(pasta: Path, *, siafe: bool = True) -> list[dict]:
    """Avalia todos os documentos de OCR do processo; devolve uma linha por documento (para o registro)."""
    from compliance_agent.sei import acervo_texto
    man = json.loads((Path(pasta) / "manifest.json").read_text(encoding="utf-8"))
    tag = Path(pasta).name
    externos = None
    if siafe:
        try:
            externos = P.fontes_externas(str(man.get("processo") or tag.replace("_", "/")))
        except (sqlite3.Error, OSError, ValueError):   # fonte externa indisponível não derruba a avaliação
            externos = None
    out = []
    for d in man.get("docs") or []:
        if not isinstance(d, dict) or not (d.get("ocr") or d.get("ocr_motor")) or not d.get("texto"):
            continue
        canon = acervo_texto.ler(pasta, d)
        r = confirmar(canon, leituras_do_doc(pasta, d), externos, P.outros_documentos(Path(pasta), d.get("i")))
        out.append({"tag": tag, "i": d.get("i"), "motor": motor_do_doc(d), **r, "versao": VERSAO,
                    "em": time.strftime("%Y-%m-%d %H:%M:%S")})
    return out


def registrar(linhas: list[dict], arq: Path = REGISTRO) -> None:
    arq.parent.mkdir(parents=True, exist_ok=True)
    with arq.open("a", encoding="utf-8") as f:
        for ln in linhas:
            f.write(json.dumps(ln, ensure_ascii=False) + "\n")


def confirmados(arq: Path = REGISTRO) -> set[tuple[str, str]]:
    """(tag, i) cuja ÚLTIMA avaliação é `confirmado` — o que a porta da leitura integral aceita."""
    ultimo: dict[tuple[str, str], str] = {}
    try:
        with arq.open(encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                ultimo[(r["tag"], str(r["i"]))] = r["estado"]
    except OSError:
        return set()
    return {k for k, e in ultimo.items() if e == "confirmado"}


def main(argv: list[str] | None = None) -> int:
    """Avalia os processos com documento de OCR e captura completa e grava o registro (o que a porta da leitura
    integral consulta). `--limite` controla a rodada; processos já avaliados nesta versão são pulados."""
    ap = argparse.ArgumentParser(description="Confirmação do OCR por documento (Fase 5)")
    ap.add_argument("--limite", type=int, default=50)
    a = ap.parse_args(argv)
    feitos = {r_tag for r_tag, _ in _avaliados()}
    n = 0
    for m in sorted((RAIZ / "data" / "sei_arquivo").glob("*/manifest.json")):
        if n >= a.limite:
            break
        tag = m.parent.name
        if tag in feitos:
            continue
        try:
            man = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if man.get("captura_completa") is not True or not any(
                isinstance(d, dict) and (d.get("ocr") or d.get("ocr_motor")) for d in man.get("docs") or []):
            continue
        registrar(avaliar_processo(m.parent))
        n += 1
    print(f"{n} processo(s) avaliado(s); confirmados no registro: {len(confirmados())}")
    return 0


def _avaliados(arq: Path = REGISTRO) -> set[tuple[str, str]]:
    out = set()
    try:
        with arq.open(encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if r.get("versao") == VERSAO:
                    out.add((r["tag"], str(r["i"])))
    except OSError:
        pass
    return out


if __name__ == "__main__":
    sys.exit(main())
