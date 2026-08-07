#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""O signatário do despacho municipal é sócio de quem a Prefeitura paga?

A pergunta que a ponte matrícula→nome destravou. E a força dela está na PROCEDÊNCIA das duas
pontas: o signatário vem por CADASTRO (matrícula publicada pelo próprio SEI × folha municipal),
não por casamento de nome; a sociedade vem do cadastro nacional da Receita.

O QUE NÃO É SINAL, e foi medido antes de qualquer número: **16 dos 48 signatários (33%) aparecem
no QSA nacional**, com 96 vínculos. Estar no quadro societário de alguma empresa é a NORMA — a
medição do índice de agente público já dava 28% para servidores do Estado. Servidor pode ser sócio.

O SINAL é o cruzamento: a empresa em que ele é sócio **receber do mesmo poder público cujo ato ele
assina**. Aí a pergunta deixa de ser sobre a pessoa e passa a ser sobre o ato — art. 9º, III da Lei
8.429/1992 e o dever de impedimento do art. 20 da Lei 9.784/1999.

ESTADO EM 2026-08-07: **zero**. A amostra é de 165 assinaturas, de ~10 processos — a captura da
árvore começou hoje. À medida que o sweep da VM-2 percorre os 4.057 processos com porta aberta, a
amostra vai a milhares e a resposta se refaz sozinha. Zero aqui é *não observado nesta amostra*,
nunca *não existe*.

    python -m tools.pcrj_signatario_x_qsa
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import time
import unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_ZST = _REPO / "data" / "receita_dump" / "socios_full.csv.zst"
_ESTAB = _REPO / "data" / "receita_estab.db"
_ASSIN = _REPO / "data" / "pcrj_assinaturas.json"
SAIDA = _REPO / "data" / "pcrj_signatario_x_qsa.json"

_MIN_TERMOS = 3     # "JOSE SILVA" casa com meio município


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z ]", " ", s)).strip().upper()


def signatarios() -> dict[str, dict]:
    """Signatários identificados por matrícula, sem os ambíguos e sem nome curto."""
    if not _ASSIN.exists():
        return {}
    d = json.loads(_ASSIN.read_text(encoding="utf-8"))
    fora: dict[str, dict] = {}
    for x in d.get("itens", []):
        if not x.get("identificada") or x.get("ambigua") or not x.get("nome"):
            continue
        n = _norm(x["nome"])
        if len(n.split()) >= _MIN_TERMOS:
            fora.setdefault(n, x)
    return fora


def levantar() -> dict:
    alvo = signatarios()
    if not alvo or not _ZST.exists():
        return {"signatarios": len(alvo), "erro": "sem signatários ou sem cadastro nacional",
                "itens": []}

    proc = subprocess.Popen(["zstd", "-dcq", str(_ZST)], stdout=subprocess.PIPE,
                            preexec_fn=lambda: os.nice(10))
    vinculos = []
    try:
        for bruto in proc.stdout:
            p = bruto.decode("utf-8", "replace").rstrip("\n").split(";")
            if len(p) < 5 or p[1].strip('"') != "2":
                continue
            n = _norm(p[2].strip('"'))
            if n in alvo:
                vinculos.append({"nome_norm": n, "nome": p[2].strip('"'),
                                 "doc": p[3].strip('"'), "raiz": p[0].strip('"'),
                                 "qualificacao": p[4].strip('"')})
    finally:
        proc.stdout.close()
        proc.wait()

    con = sqlite3.connect(f"file:{_REPO / 'data' / 'compliance.db'}?mode=ro", uri=True)
    pago: dict[str, float] = {}
    try:
        for doc, v in con.execute("SELECT credor_documento, SUM(pago) FROM pcrj_despesa "
                                  "WHERE pago > 0 GROUP BY 1"):
            d = re.sub(r"\D", "", str(doc or ""))
            if len(d) == 14:
                pago[d[:8]] = pago.get(d[:8], 0.0) + float(v or 0)
    except sqlite3.Error:
        pass
    finally:
        con.close()

    razao: dict[str, str] = {}
    raizes = {v["raiz"] for v in vinculos}
    if raizes and _ESTAB.exists():
        est = sqlite3.connect(f"file:{_ESTAB}?mode=ro", uri=True)
        try:
            if est.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='empresas'"
                           ).fetchone():
                lista = sorted(raizes)
                for i in range(0, len(lista), 900):
                    lote = lista[i:i + 900]
                    ph = ",".join("?" * len(lote))
                    for r in est.execute(
                            f"SELECT cnpj_basico, razao_social FROM empresas "
                            f"WHERE cnpj_basico IN ({ph})", lote):
                        razao[r[0]] = str(r[1] or "")
        finally:
            est.close()

    itens = []
    for v in vinculos:
        if v["raiz"] not in pago:
            continue
        meta = alvo[v["nome_norm"]]
        itens.append({
            "signatario": v["nome"], "orgao": meta.get("orgao", ""),
            "unidade": meta.get("unidade_folha", ""), "processo": meta.get("numero", ""),
            "documento": meta.get("documento", ""), "tipo_doc": meta.get("tipo", ""),
            "empresa": razao.get(v["raiz"], v["raiz"]), "cnpj_basico": v["raiz"],
            "qualificacao": v["qualificacao"], "pago_pela_prefeitura": pago[v["raiz"]],
        })
    itens.sort(key=lambda x: -x["pago_pela_prefeitura"])
    return {
        "signatarios": len(alvo),
        "no_qsa_nacional": len({v["nome_norm"] for v in vinculos}),
        "vinculos_societarios": len(vinculos),
        "com_empresa_paga_pela_prefeitura": len(itens),
        "itens": itens,
        "ressalva": (
            "Estar no QSA de alguma empresa NÃO é sinal: 33% dos signatários identificados "
            "aparecem no cadastro nacional, e a medição do índice de agente público do Estado dá "
            "28% — servidor pode ser sócio. O sinal é a empresa receber do MESMO poder público "
            "cujo ato ele assina. Zero aqui significa NÃO OBSERVADO NESTA AMOSTRA (165 assinaturas, "
            "~10 processos), nunca inexistente: a captura da árvore começou em 07/08/2026 e cresce "
            "a cada rodada do sweep."),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--medir", action="store_true")
    a = ap.parse_args()
    r = levantar()
    for k, v in r.items():
        if k not in ("itens", "ressalva"):
            print(f"{k:34s} {v}")
    from compliance_agent.reporting.intel_base import moeda

    for x in r.get("itens", [])[:10]:
        print(f"   {x['signatario'][:30]:30s} | {x['orgao'][:24]:24s} | "
              f"{x['empresa'][:30]:30s} {moeda(x['pago_pela_prefeitura'])}")
    if not a.medir:
        SAIDA.write_text(json.dumps({"gerado_em": time.strftime("%Y-%m-%d %H:%M"), **r},
                                    ensure_ascii=False), encoding="utf-8")
        print(f"gravado: {SAIDA}")


if __name__ == "__main__":
    main()
