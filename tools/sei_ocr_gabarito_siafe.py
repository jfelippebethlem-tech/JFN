#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gabarito SIAFE do OCR — acerto de cada motor medido em páginas REAIS do acervo, de graça e sem parar.

POR QUE (23/11/2026). A bancada de OCR da casa tem 79 páginas conferidas à mão (18/11) e uma rodada de 23/11; o
acervo tem 147.514 documentos lidos por OCR e nenhuma medida contínua de acerto. Mas uma parte do acervo traz o
gabarito dentro do próprio título: as impressões de Nota de Liquidação, Nota de Empenho e Ordem Bancária anexadas
ao processo ("Nota de Liquidação - NL 2024NL02622 (87496826)"). O SIAFE tem, para o mesmo número e a mesma UG, o
CNPJ do credor e o valor em campo estruturado (`nl_siafe`, `ne_siafe`, `ob_orcamentaria_siafe`). Se o OCR leu
certo, os dois aparecem no texto. Isso dá milhares de pares (página real × verdade estruturada) por motor, por tipo
de documento e por data — a literatura chama de avaliação sem verdade manual com supervisão distante.

CONTROLE POSITIVO. O documento NATIVO (texto do próprio PDF, sem OCR) passa pela mesma casação: se ele não bate em
≥ 90%, o defeito é da casação (número de outra UG, valor formatado diferente), não do OCR — e a medida sai marcada
como NÃO válida. Casação: número no título + exatamente UMA linha do SIAFE cuja UG aparece no corpo do texto
(a UG escolhe a linha; CNPJ e valor, que são o que se mede, não entram na escolha).

O QUE NÃO É. Não é prova de documento nem conferência de número para dossiê (isso é `compliance_agent.sei.ocr_ia_prova`):
é o termômetro do motor. Só leitura — acervo e banco abertos em modo leitura.

    python tools/sei_ocr_gabarito_siafe.py [--limite-pastas N] [--saida data/sei_ocr_gabarito_siafe.json]
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVO = RAIZ / "data" / "sei_arquivo"
DB = RAIZ / "data" / "compliance.db"
SAIDA = RAIZ / "data" / "sei_ocr_gabarito_siafe.json"
PISO_CONTROLE = 0.90

_TABELAS = {   # tipo → (tabela, coluna do número)
    "NL": ("nl_siafe", "numero"),
    "NE": ("ne_siafe", "numero"),
    "OB": ("ob_orcamentaria_siafe", "numero_ob"),
}
_RE_CHAVE = re.compile(r"(20\d\d)(NL|NE|OB)(\d{5})")


def chave_do_titulo(titulo: str) -> tuple[str, str] | None:
    m = _RE_CHAVE.search(re.sub(r"\s+", "", titulo or ""))
    return (m.group(2), m.group(1) + m.group(2) + m.group(3)) if m else None


def valor_br(v) -> str | None:
    """Valor no formato da impressão do SIAFE (1.234,56). Aceita número ou texto já em pt-BR."""
    if v is None or v == "":
        return None
    if isinstance(v, str):
        return v.strip() or None
    s = f"{float(v):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def referencia(linhas: list[tuple], corpo: str) -> tuple | None:
    """A linha do SIAFE deste documento: a única cuja UG emitente aparece no corpo. Nenhuma ou mais de uma → None."""
    boas = [r for r in linhas if r[0] and str(r[0]) in corpo]
    return boas[0] if len(boas) == 1 else None


def conferir(corpo: str, credor: str, valor) -> dict:
    digitos = re.sub(r"\D", "", corpo)
    cred = re.sub(r"\D", "", credor or "")
    vb = valor_br(valor)
    return {"cnpj": bool(cred) and cred in digitos, "valor": bool(vb) and vb in corpo}


def motor(doc: dict) -> str:
    m = str(doc.get("ocr_motor") or "").strip().lower()
    if m.startswith("surya"):
        return "surya"
    if m.startswith("reserva"):
        return "reserva"
    return "tesseract" if str(doc.get("ocr")) == "True" else "nativo"


def _corpo(pasta: Path, rel: str) -> str:
    try:
        bruto = (pasta / rel).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return bruto.split("\n\n", 1)[1] if "\n\n" in bruto else bruto


def medir(arquivo: Path = ARQUIVO, db: Path = DB, limite_pastas: int | None = 3000, semente: int = 23) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    pastas = sorted(p for p in arquivo.iterdir() if p.is_dir())
    random.Random(semente).shuffle(pastas)
    por_motor: dict = defaultdict(lambda: {"n": 0, "cnpj": 0, "valor": 0})
    por_tipo: dict = defaultdict(lambda: {"n": 0, "cnpj": 0, "valor": 0})
    sem_ref = 0
    erros = []
    for pasta in pastas[:limite_pastas]:
        try:
            man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for d in man.get("docs", []) if isinstance(man, dict) else []:
            ch = chave_do_titulo(d.get("titulo") or "")
            if not ch or not d.get("texto"):
                continue
            tipo, numero = ch
            tabela, col = _TABELAS[tipo]
            linhas = con.execute(f"SELECT ug_emitente, credor, valor FROM {tabela} WHERE {col} >= ? AND {col} < ?",
                                 (numero, numero + "~")).fetchall()      # faixa: usa o índice; o SIAFE põe sufixo
            corpo = _corpo(pasta, d["texto"])
            ref = referencia(linhas, corpo) if linhas else None
            if not ref:
                sem_ref += 1
                continue
            r = conferir(corpo, ref[1], ref[2])
            m = motor(d)
            for alvo in (por_motor[m], por_tipo[f"{m}:{tipo}"]):
                alvo["n"] += 1
                alvo["cnpj"] += r["cnpj"]
                alvo["valor"] += r["valor"]
            if m != "nativo" and not (r["cnpj"] and r["valor"]) and len(erros) < 200:
                erros.append({"pasta": pasta.name, "texto": d["texto"], "numero": numero, "motor": m,
                              "credor": ref[1], "valor": valor_br(ref[2]), **r})
    con.close()
    nat = por_motor.get("nativo") or {"n": 0, "cnpj": 0, "valor": 0}
    taxa_nat = min(nat["cnpj"], nat["valor"]) / nat["n"] if nat["n"] else 0.0
    ok = nat["n"] > 0 and taxa_nat >= PISO_CONTROLE
    return {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "pastas_lidas": min(len(pastas), limite_pastas or len(pastas)),
        "por_motor": {k: dict(v) for k, v in por_motor.items()},
        "por_tipo": {k: dict(v) for k, v in sorted(por_tipo.items())},
        "sem_referencia_unica": sem_ref,
        "controle_positivo_ok": ok,
        "veredito": ("medida VÁLIDA: o texto nativo bate com o SIAFE em "
                     f"{taxa_nat:.1%} (piso {PISO_CONTROLE:.0%})") if ok else
                    (f"medida NÃO válida: o controle positivo (nativo) bateu só {taxa_nat:.1%} "
                     f"em {nat['n']} documentos — a casação está errada, não o OCR"),
        "erros": erros,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limite-pastas", type=int, default=3000)
    ap.add_argument("--saida", type=Path, default=SAIDA)
    a = ap.parse_args(argv)
    r = medir(limite_pastas=a.limite_pastas)
    a.saida.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(r["veredito"])
    for m, v in sorted(r["por_motor"].items()):
        n = v["n"] or 1
        print(f"  {m:10s} n={v['n']:>6,}  CNPJ {v['cnpj'] / n:6.1%}  valor {v['valor'] / n:6.1%}".replace(",", "."))
    return 0 if r["controle_positivo_ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
