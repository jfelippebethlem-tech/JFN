#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Traz o grafo que a VM-2 montou — e o `id` de `pessoas` NÃO atravessa.

A VM-2 percorre a fatia 1/2 dos credores do SIAFE e monta cadeia societária e contato compartilhado
na base dela. Sem esta colheita, o trabalho fica parado no disco daquela máquina — o mesmo defeito
que já custou dias no sweep SEI, e que só apareceu porque alguém foi olhar.

O CUIDADO QUE ESTA FERRAMENTA EXISTE PARA TER: `pessoas.id` é autoincremento LOCAL. Copiar
`relacionamentos` com os ids de lá apontaria para pessoas erradas aqui — o nó 42 da VM-2 não é o nó
42 da VM-1. A identidade real é o DOCUMENTO (a coluna `cpf` tem UNIQUE nesta base, e a raiz do CNPJ
é o que identifica empresa); sem documento, sobra o nome. Cada ponta é RESOLVIDA por identidade e
recriada se preciso, e só então a aresta entra.

Idempotente: aresta já existente (mesmas pontas, tipo, fonte e data) é contada como repetida e não
duplica. Direção canônica dos tipos simétricos continua valendo — quem a aplica é `salvar_grafo`,
e por isso a inserção passa por ele em vez de escrever SQL à mão.

    python -m tools.colher_vm2_grafo            # relatório
    python -m tools.colher_vm2_grafo --aplicar
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"

_REMOTO = r"""cd ~/JFN && .venv/bin/python -c "
import sqlite3, json
c = sqlite3.connect('file:data/compliance.db?mode=ro', uri=True)
q = '''SELECT a.nome, a.cpf, a.tipo, b.nome, b.cpf, b.tipo,
       r.tipo, r.descricao, r.fonte, r.data_inicio
       FROM relacionamentos r
       JOIN pessoas a ON a.id = r.pessoa_a_id
       JOIN pessoas b ON b.id = r.pessoa_b_id'''
print(json.dumps([list(x) for x in c.execute(q)]))
" """

_REMOTO_FEITOS = (
    "cd ~/JFN && .venv/bin/python -c \""
    "import sqlite3, json;"
    "c=sqlite3.connect('file:data/compliance.db?mode=ro',uri=True);"
    "print(json.dumps([list(x) for x in c.execute("
    "'select cnpj, arestas, valor_pago, processado_em from grafo_persistido')]))\""
)


def _ssh_json(cmd: str, timeout_s: int = 300) -> list:
    try:
        p = subprocess.run(["ssh", "-o", "ConnectTimeout=20", "-o", "BatchMode=yes", "vm2", cmd],
                           capture_output=True, timeout=timeout_s)
    except (subprocess.TimeoutExpired, OSError):
        return []
    if p.returncode != 0:
        return []
    try:
        return json.loads(p.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []


def colher(aplicar: bool = False, db: Path = _DB) -> dict:
    from compliance_agent.osint.persistencia import salvar_grafo
    from compliance_agent.osint.vinculos import GrafoVinculos, no_pf, no_pj

    arestas = _ssh_json(_REMOTO)
    feitos = _ssh_json(_REMOTO_FEITOS)
    if not arestas:
        return {"erro": "não consegui ler o grafo da VM-2 (ssh/tabela ausente)"}

    # Reconstrói um GrafoVinculos com as CHAVES canônicas, não com os ids de lá.
    g = GrafoVinculos()
    for na, ca, ta, nb, cb, tb, tipo, desc, fonte, data in arestas:
        def chave(nome, doc, tp):
            if doc:
                return no_pj(doc) if tp == "empresa" else no_pf(doc)
            return no_pj("", nome) if tp == "empresa" else no_pf("", nome)

        ka, kb = chave(na, ca, ta), chave(nb, cb, tb)
        g.rotular(ka, na or "")
        g.rotular(kb, nb or "")
        g.ligar(ka, kb, tipo, fonte=fonte or "", data=data or "", detalhe=desc or "")

    if not aplicar:
        return {"arestas_na_vm2": len(arestas), "credores_na_vm2": len(feitos),
                "arestas_reconstruidas": len(g.arestas), "aplicado": False}

    con = sqlite3.connect(str(db), timeout=120)
    try:
        r = salvar_grafo(con, g)
        novos_credores = 0
        if feitos:
            locais = {x[0] for x in con.execute("SELECT cnpj FROM grafo_persistido")}
            faltam = [f for f in feitos if f[0] not in locais]
            con.executemany(
                "INSERT OR REPLACE INTO grafo_persistido (cnpj, arestas, valor_pago, "
                "processado_em) VALUES (?,?,?,?)", faltam)
            con.commit()
            novos_credores = len(faltam)
    finally:
        con.close()
    return {"arestas_na_vm2": len(arestas), "credores_na_vm2": len(feitos),
            "arestas_reconstruidas": len(g.arestas), "credores_novos": novos_credores,
            "aplicado": True, **r}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    for k, v in colher(a.aplicar).items():
        print(f"{k:24s} {v}")


if __name__ == "__main__":
    main()
