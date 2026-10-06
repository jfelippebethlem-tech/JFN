#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quem assinou o despacho — o NOME por trás da matrícula que a Prefeitura publica.

O SEI da Prefeitura publica, na Lista de Andamentos de todo processo público,
`Assinado Documento 6223445 (Despacho) por 15508496`: a **matrícula** de quem assinou, sem o nome.
A folha da Prefeitura (`pcrj_folha_pref`, 12,1 milhões de linhas) tem matrícula E nome. Juntas,
respondem *quem decidiu* — a pergunta que o sistema só sabia responder para o Estado.

FORMATO NÃO É IDENTIDADE, e este foi o defeito que quase matou o cruzamento. A folha guarda a
matrícula com **7 dígitos e zero à esquerda** (`0000190`); a assinatura do SEI traz **8**
(`01531789`). Comparadas como TEXTO: **0 de 69**. Comparadas como NÚMERO: **51 de 69**.

AS 18 QUE NÃO CASAM NÃO SÃO ERRO NEM AUSÊNCIA. Podem ser servidor de outro ente (a Prefeitura
recebe requisitados), matrícula de empresa pública com registro próprio, ou vínculo encerrado antes
da primeira competência da folha (12/2020). `INDISPONÍVEL ≠ inexistente` — elas ficam contadas e
declaradas, nunca somem.

O QUE ISTO DESTRAVA: a mesma pergunta que a fila de agente público faz para o Estado passa a valer
para a Prefeitura — quem assina o ato é sócio de quem recebe? A ponte agora existe pelos dois lados.

    python -m tools.pcrj_assinaturas_x_folha              # grava JSON
    python -m tools.pcrj_assinaturas_x_folha --medir      # só mede
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import time
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_PCRJ = _REPO / "data" / "pcrj.db"
SAIDA = _REPO / "data" / "pcrj_assinaturas.json"

_REMOTO = (
    "cd ~/sei-pcrj && .venv/bin/python -c \""
    "import sqlite3,json;"
    "c=sqlite3.connect('file:data/sei_pcrj.db?mode=ro',uri=True);"
    "print(json.dumps([dict(zip(('numero','documento','tipo','matricula','quando','unidade'),r))"
    " for r in c.execute('select numero,documento,tipo,matricula,quando,unidade"
    " from sei_pcrj_assinatura')]))\""
)


def assinaturas_da_vm2(timeout_s: int = 240) -> list[dict]:
    """Lê as assinaturas capturadas na VM-2. Falha vira lista vazia — nunca derruba nada."""
    try:
        p = subprocess.run(["ssh", "-o", "ConnectTimeout=20", "-o", "BatchMode=yes", "vm2",
                            _REMOTO], capture_output=True, timeout=timeout_s)
    except (subprocess.TimeoutExpired, OSError):
        return []
    if p.returncode != 0:
        return []
    try:
        return json.loads(p.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []


def identificar(assinaturas: list[dict], pcrj: Path = _PCRJ) -> dict:
    """Casa matrícula → nome na folha da Prefeitura, comparando por NÚMERO."""
    mats = {re.sub(r"\D", "", a.get("matricula") or "") for a in assinaturas}
    mats = {m for m in mats if m}
    if not mats or not pcrj.exists():
        return {"assinaturas": len(assinaturas), "matriculas": len(mats),
                "identificadas": 0, "itens": [], "erro": "folha da Prefeitura ausente"}

    con = sqlite3.connect(f"file:{pcrj}?mode=ro", uri=True)
    quem: dict[str, dict] = {}
    try:
        # UMA VARREDURA PARA TODAS, não uma por matrícula. `CAST(matricula AS INTEGER)` impede
        # índice, então cada consulta era uma varredura COMPLETA das 12,1 milhões de linhas —
        # medida: 42 s. Com 69 matrículas, ~48 min contra um teto de 600 s: o passo do sweep
        # registrou rc=124 na única execução da vida e nunca materializou o JSON. Uma varredura
        # única com `IN` custa os mesmos 42 s UMA vez, e o agrupamento vira Python.
        numeros = sorted({int(m) for m in mats if m.isdigit()})
        if numeros:
            ph = ",".join("?" * len(numeros))
            bruto: dict[int, dict[str, dict]] = {}
            for n, nome, orgao_, ua, tf, ate, desde, freq in con.execute(
                    f"SELECT CAST(matricula AS INTEGER), nome, orgao, sigla_ua, tipo_folha, "
                    f"MAX(competencia), MIN(competencia), COUNT(*) FROM pcrj_folha_pref "
                    f"WHERE CAST(matricula AS INTEGER) IN ({ph}) "
                    f"GROUP BY 1, nome", numeros):
                bruto.setdefault(int(n), {})[nome] = {
                    "nome": nome, "orgao": orgao_, "unidade": ua, "tipo_folha": tf,
                    "ate": ate, "desde": desde, "_freq": freq}
            for m in mats:
                if not m.isdigit() or int(m) not in bruto:
                    continue
                nomes = sorted(bruto[int(m)].values(), key=lambda x: -x["_freq"])
                # DUAS PESSOAS NA MESMA MATRÍCULA é homônimo de cadastro, não identificação:
                # a matrícula fica marcada como ambígua em vez de eleger a mais frequente.
                quem[m] = {k: v for k, v in nomes[0].items() if k != "_freq"}
                quem[m]["ambigua"] = len(nomes) > 1
    finally:
        con.close()

    itens = []
    for a in assinaturas:
        m = re.sub(r"\D", "", a.get("matricula") or "")
        p = quem.get(m)
        itens.append({**a, "matricula_num": m,
                      "nome": (p or {}).get("nome", ""), "orgao": (p or {}).get("orgao", ""),
                      "unidade_folha": (p or {}).get("unidade", ""),
                      "ambigua": bool((p or {}).get("ambigua")),
                      "identificada": bool(p)})
    por_pessoa = Counter(x["nome"] for x in itens if x["identificada"])
    return {
        "assinaturas": len(assinaturas), "matriculas": len(mats),
        "identificadas": len(quem), "ambiguas": sum(1 for v in quem.values() if v["ambigua"]),
        "nao_identificadas": len(mats) - len(quem),
        "top_signatarios": por_pessoa.most_common(20),
        "itens": itens,
        "ressalva": (
            "A matrícula é publicada pelo próprio SEI da Prefeitura e o nome vem da folha "
            "municipal — é identificação por CADASTRO, mais forte que casamento por nome. As "
            "matrículas não casadas NÃO são inexistentes: podem ser requisitado de outro ente, "
            "empresa pública com registro próprio, ou vínculo encerrado antes de 12/2020, que é a "
            "primeira competência da folha."),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--medir", action="store_true")
    a = ap.parse_args()
    r = identificar(assinaturas_da_vm2())
    for k, v in r.items():
        if k not in ("itens", "top_signatarios", "ressalva"):
            print(f"{k:22s} {v}")
    for nome, n in (r.get("top_signatarios") or [])[:8]:
        print(f"   {n:3d} assinatura(s)  {nome}")
    if not a.medir and r.get("itens"):
        SAIDA.write_text(json.dumps({"gerado_em": time.strftime("%Y-%m-%d %H:%M"), **r},
                                    ensure_ascii=False), encoding="utf-8")
        print(f"gravado: {SAIDA}")


if __name__ == "__main__":
    main()
