#!/usr/bin/env python3
"""bombeiros_integra_supervisor — monta o CORPUS de texto (íntegra + OCR) dos processos
de licitação do CBMERJ/FUNESBOM a partir do cache do SEI, e reporta a LACUNA de coleta.

Por que existe: `ler_processo` já extrai a íntegra COMPLETA dos docs (com OCR de scans via
`_conteudo_doc`) e grava em `data/sei_cache/cdp_*.json`; o `_ficha_e_storage` depois TRIMA isso
no storage. Para a perícia de direcionamento precisamos do texto INTEIRO — então aqui lemos o
cache cru (não-trimado) e concatenamos num corpus auditável. A íntegra da licitação costuma estar
na CADEIA (relacionados) do processo de pagamento, não no despacho — por isso classificamos a
cobertura e listamos quem ainda é "só despacho" (precisa recoletar com árvore mais funda).

NÃO abre browser (100% leitura de cache) → seguro rodar junto com o sei_sweep.
A COLETA funda (browser) é feita pelo pipeline canônico:
    PYTHONPATH=. .venv/bin/python -m tools.sei_bombeiros_sweep --max N   (segue árvore prof.=6)

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.bombeiros_integra_supervisor [--max N] [--min-chars 500]
Saídas:
    data/corpus_bombeiros_integra.txt      (corpus de texto, só processos com conteúdo)
    data/bombeiros_integra_cobertura.csv   (status por processo: integra|so_despacho|nao_coletado)
    data/bombeiros_integra.log             (log da execução)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FILA = REPO / "data" / "bombeiros_sei_fila.json"
CACHE = REPO / "data" / "sei_cache"
CORPUS = REPO / "data" / "corpus_bombeiros_integra.txt"
COBERTURA = REPO / "data" / "bombeiros_integra_cobertura.csv"
LOG = REPO / "data" / "bombeiros_integra.log"
SEP = "=" * 80


def _log(msg: str) -> None:
    linha = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(linha, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(linha + "\n")


def _cdp_path(sei: str) -> Path:
    return CACHE / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', sei)}.json"


def _texto_principal(d: dict) -> str:
    # `texto` é o frame inteiro (inclui menu lateral lixo); mantemos uma amostra útil.
    return (d.get("texto") or "").strip()


def _docs_texto(d: dict) -> list[str]:
    out = []
    for c in d.get("conteudo_documentos") or []:
        if isinstance(c, dict) and c.get("conteudo"):
            nome = c.get("nome") or c.get("titulo") or c.get("tipo") or "doc"
            out.append(f"[{nome}]\n{c['conteudo'].strip()}")
        elif isinstance(c, str) and c.strip():
            out.append(c.strip())
    return out


def _cadeia_texto(d: dict) -> list[str]:
    out = []
    for rel in d.get("cadeia") or []:
        if not isinstance(rel, dict):
            continue
        t = (rel.get("texto") or "").strip()
        if t:
            ident = rel.get("numero") or rel.get("proc") or rel.get("url") or "relacionado"
            out.append(f"[CADEIA {ident}]\n{t}")
    return out


def _conteudo_chars(d: dict) -> int:
    return sum(len(x) for x in _docs_texto(d)) + sum(len(x) for x in _cadeia_texto(d))


def main() -> None:
    ap = argparse.ArgumentParser(description="Monta corpus íntegra+OCR dos bombeiros (lê cache, sem browser)")
    ap.add_argument("--max", type=int, default=0, help="limita N processos (0 = todos)")
    ap.add_argument("--min-chars", type=int, default=500,
                    help="mínimo de chars de conteúdo p/ contar como íntegra (default 500)")
    a = ap.parse_args()

    if not FILA.exists():
        _log(f"ERRO: fila não encontrada: {FILA}")
        return
    fila = json.loads(FILA.read_text(encoding="utf-8"))
    if a.max:
        fila = fila[: a.max]
    _log(f"INÍCIO: {len(fila)} processos na fila; min-chars={a.min_chars}")

    n_integra = n_despacho = n_nao = 0
    chars_total = 0
    cob_rows = []
    with open(CORPUS, "w", encoding="utf-8") as corpus:
        corpus.write(f"# CORPUS ÍNTEGRA+OCR — Licitações CBMERJ/FUNESBOM\n# Gerado {time.strftime('%Y-%m-%d %H:%M')} — fonte: data/sei_cache/cdp_*.json\n# Honestidade: indício != acusação; conteúdo cru p/ análise de direcionamento.\n\n")
        for x in fila:
            sei = x["sei"]
            forn = x.get("forn") or x.get("fornecedor") or ""
            valor = float(x.get("valor") or 0)
            score = x.get("score") or ""
            cdp = _cdp_path(sei)
            if not cdp.exists():
                n_nao += 1
                cob_rows.append((sei, forn, f"{valor:.2f}", score, "nao_coletado", 0, 0))
                continue
            try:
                d = json.loads(cdp.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                _log(f"  {sei}: cdp ilegível ({type(e).__name__})")
                n_nao += 1
                cob_rows.append((sei, forn, f"{valor:.2f}", score, "cdp_ilegivel", 0, 0))
                continue
            docs = _docs_texto(d)
            cadeia = _cadeia_texto(d)
            conteudo_chars = sum(len(x) for x in docs) + sum(len(x) for x in cadeia)
            tem_cadeia = bool(d.get("cadeia"))
            if conteudo_chars >= a.min_chars or tem_cadeia:
                n_integra += 1
                chars_total += conteudo_chars
                status = "integra"
                # escreve no corpus
                corpus.write(SEP + "\n")
                corpus.write(f"SEI: {sei} | FORN: {forn} | R$ {valor:,.2f} | score {score}\n")
                corpus.write(f"URL: {d.get('url', '')}\n")
                cnpjs = d.get("cnpjs") or []
                if cnpjs:
                    corpus.write(f"CNPJs detectados: {', '.join(cnpjs[:20])}\n")
                corpus.write("\n--- TEXTO PRINCIPAL ---\n")
                corpus.write(_texto_principal(d)[:4000] + "\n")
                for i, dt in enumerate(docs, 1):
                    corpus.write(f"\n--- DOC {i} ---\n{dt}\n")
                for ct in cadeia:
                    corpus.write(f"\n--- {ct.splitlines()[0]} ---\n" + "\n".join(ct.splitlines()[1:]) + "\n")
                corpus.write("\n" + SEP + "\n\n")
            else:
                n_despacho += 1
                status = "so_despacho"
            cob_rows.append((sei, forn, f"{valor:.2f}", score, status,
                             len(docs), 1 if tem_cadeia else 0))

    with open(COBERTURA, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sei", "fornecedor", "valor", "score", "status", "n_docs", "tem_cadeia"])
        w.writerows(cob_rows)

    _log(f"FIM: íntegra={n_integra} | só_despacho={n_despacho} | não_coletado={n_nao} | "
         f"corpus={chars_total:,} chars -> {CORPUS.name}")
    _log(f"cobertura -> {COBERTURA.name}")
    # lacuna acionável
    falta = n_despacho + n_nao
    if falta:
        _log(f"LACUNA: {falta} processos sem íntegra completa — recoletar com árvore funda: "
             f"PYTHONPATH=. .venv/bin/python -m tools.sei_bombeiros_sweep --max <N>")


if __name__ == "__main__":
    main()
