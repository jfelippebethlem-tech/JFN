#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""socios_reverso_grep — busca REVERSA ampla: dado um sócio (nome + doc mascarado), acha TODOS os CNPJs
do Brasil onde ele aparece. Marca quais CNPJs são NOSSOS fornecedores.

TRÊS CAMADAS (ordem; degrada graciosamente):
  1) TABELA `socios_reverso` (pré-computada por `socios_reverso_build`): INSTANTÂNEA e NÃO precisa de dump.
     Cobre os NOSSOS administradores/sócios (conjunto bounded já em `socios_receita`). É a via padrão.
  2) STREAM-GREP no `socios_full.csv.zst` (cadastro de sócios COMPLETO do Brasil, enxuto+comprimido): SÓ se
     o alvo NÃO está na tabela (pessoa nova, qualquer um). `zstdcat | grep` em streaming, baixa RAM, e NÃO
     exige os 1,9 GB de ZIPs — o .zst (300-700 MB) os substitui. É o que permite apagar os ZIPs.
  3) FALLBACK stream-grep nos Socios*.zip, só se o .zst não existir mas os ZIPs estiverem presentes. Se
     nem .zst nem ZIP existirem, avisa que é preciso (re)gerar o dump enxuto (`socios_dump_refresh.sh`).

Desambiguação de homônimo: casa NOME (normalizado) + os 6 dígitos do CPF mascarado (***NNNNNN**).

Uso:
  PYTHONPATH=. .venv/bin/python -m tools.socios_reverso_grep --nome "FILIPE RAMOS PEREIRA" --doc "***002167**"
  PYTHONPATH=. .venv/bin/python -m tools.socios_reverso_grep --nome "..." --cpf6 002167
  PYTHONPATH=. .venv/bin/python -m tools.socios_reverso_grep --nome "..." --doc "..." --forcar-zip  # ignora tabela
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sqlite3
import unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"
_DUMP = _REPO / "data" / "receita_dump"
_ZST = _DUMP / "socios_full.csv.zst"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return " ".join(s.split())


def _raizes_nossas() -> set[str]:
    f = _DUMP / "_nossas_raizes.txt"
    return {ln.strip() for ln in f.read_text().splitlines() if ln.strip()} if f.exists() else set()


def _doc_de_cpf6(cpf6: str) -> str:
    """reconstrói o doc mascarado ***NNNNNN** a partir dos 6 dígitos do meio."""
    return f"***{cpf6.zfill(6)}**"


def buscar_tabela(nome: str, cpf6: str) -> list[dict] | None:
    """Consulta a tabela pré-computada `socios_reverso` (instantâneo, SEM ZIP).
    Retorna a lista de achados se a pessoa estiver na tabela; None se NÃO estiver (alvo desconhecido)."""
    nome_n = _norm(nome)
    doc = _doc_de_cpf6(cpf6)
    raizes = _raizes_nossas()
    con = sqlite3.connect(str(_DB))
    try:
        rows = con.execute(
            "SELECT cnpj_basico, qualif_cod, doc_socio FROM socios_reverso "
            "WHERE doc_socio = ? AND nome_norm = ?", (doc, nome_n)).fetchall()
    except sqlite3.OperationalError:
        con.close()
        return None  # tabela ainda não existe -> trata como ausente
    con.close()
    if not rows:
        return None
    achados: dict[str, dict] = {}
    for cb, cod, d in rows:
        achados.setdefault(cb, {
            "cnpj_basico": cb, "qualif_cod": cod, "data": "",
            "doc": d, "nosso_fornecedor": cb in raizes,
        })
    return sorted(achados.values(), key=lambda x: (not x["nosso_fornecedor"], x["cnpj_basico"]))


def buscar(nome: str, cpf6: str, forcar_zip: bool = False) -> tuple[list[dict], str]:
    """Orquestra 3 camadas: 1) tabela `socios_reverso`; 2) stream-grep no socios_full.csv.zst (qualquer
    pessoa, sem ZIPs); 3) fallback stream-grep nos ZIPs se o .zst não existir. Retorna (achados, fonte)
    onde fonte ∈ {'tabela','zst','zip','indisponivel'}."""
    if not forcar_zip:
        viat = buscar_tabela(nome, cpf6)
        if viat is not None:
            return viat, "tabela"
    # camada 2: o cadastro completo enxuto+comprimido (substitui os 1,9 GB de ZIPs)
    if _ZST.exists():
        return buscar_zst(nome, cpf6), "zst"
    # camada 3: fallback nos ZIPs brutos, se ainda presentes
    zips = sorted(_DUMP.glob("Socios*.zip"))
    if not zips:
        return [], "indisponivel"
    return buscar_zip(nome, cpf6), "zip"


def buscar_zst(nome: str, cpf6: str) -> list[dict]:
    """Stream-grep no socios_full.csv.zst (sócios COMPLETO do Brasil, 5 colunas, comprimido). Mesmo
    casamento que buscar_zip (nome normalizado + cpf6), porém SEM precisar dos ZIPs: `zstdcat | grep`
    em streaming, baixa RAM. Layout: cnpj_basico;ident;nome_socio;cpf_cnpj_socio;qualif_cod."""
    nome_n = _norm(nome)
    raizes = _raizes_nossas()
    toks = nome_n.split()
    pat = re.escape(toks[0]) + ".*" + re.escape(toks[-1]) if len(toks) >= 2 else re.escape(nome_n)
    achados: dict[str, dict] = {}
    # zstdcat (descomprime em streaming) | grep (filtra candidatos byte-safe) -> só candidatos no Python
    p1 = subprocess.Popen(["zstdcat", str(_ZST)], stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["grep", "-a", "-i", "-E", pat], stdin=p1.stdout, stdout=subprocess.PIPE)
    p1.stdout.close()
    try:
        for raw in p2.stdout:
            ln = raw.decode("latin1", "ignore").rstrip("\r\n")
            c = [x.strip('"') for x in ln.split(";")]
            if len(c) < 5:
                continue
            if _norm(c[2]) != nome_n:
                continue
            doc = c[3] or ""
            d6 = re.sub(r"\D", "", doc)
            if d6 != cpf6:
                continue
            cb = c[0]
            achados.setdefault(cb, {
                "cnpj_basico": cb, "qualif_cod": c[4], "data": "",
                "doc": doc, "nosso_fornecedor": cb in raizes,
            })
    finally:
        p2.stdout.close()
        p2.wait()
        p1.wait()
    return sorted(achados.values(), key=lambda x: (not x["nosso_fornecedor"], x["cnpj_basico"]))


def buscar_zip(nome: str, cpf6: str) -> list[dict]:
    """Stream-grep: a Receita não armazena o nome normalizado, então gerar variantes do nome para o grep
    barato (latin1) e confirmar no Python com normalização + cpf6."""
    nome_n = _norm(nome)
    raizes = _raizes_nossas()
    # grep barato: primeiro+último token (acentos viram '.' p/ casar latin1), case-insensitive
    toks = nome_n.split()
    pat = re.escape(toks[0]) + ".*" + re.escape(toks[-1]) if len(toks) >= 2 else re.escape(nome_n)
    achados: dict[str, dict] = {}
    zips = sorted(_DUMP.glob("Socios*.zip"))
    for zf in zips:
        # unzip -p | grep (case-insensitive, byte-safe) — só linhas candidatas chegam ao Python
        p1 = subprocess.Popen(["unzip", "-p", str(zf)], stdout=subprocess.PIPE)
        p2 = subprocess.Popen(["grep", "-a", "-i", "-E", pat], stdin=p1.stdout, stdout=subprocess.PIPE)
        p1.stdout.close()
        for raw in p2.stdout:
            ln = raw.decode("latin1", "ignore").rstrip("\r\n")
            c = [x.strip('"') for x in ln.split(";")]
            if len(c) < 5:
                continue
            if _norm(c[2]) != nome_n:
                continue
            doc = c[3] or ""
            d6 = re.sub(r"\D", "", doc)  # do ***NNNNNN** sobra NNNNNN
            if d6 != cpf6:
                continue
            cb = c[0]
            achados.setdefault(cb, {
                "cnpj_basico": cb, "qualif_cod": c[4], "data": c[5] if len(c) > 5 else "",
                "doc": doc, "nosso_fornecedor": cb in raizes,
            })
        p2.stdout.close()
        p2.wait()
        p1.wait()
    return sorted(achados.values(), key=lambda x: (not x["nosso_fornecedor"], x["cnpj_basico"]))


def _enriquecer_razao(achados: list[dict]) -> None:
    """tenta nome do CNPJ a partir das nossas OB (só p/ os que são nossos fornecedores)."""
    if not achados:
        return
    con = sqlite3.connect(str(_DB))
    for a in achados:
        if a["nosso_fornecedor"]:
            r = con.execute(
                "SELECT favorecido_nome FROM ordens_bancarias WHERE substr(favorecido_cpf,1,8)=? "
                "AND favorecido_nome IS NOT NULL LIMIT 1", (a["cnpj_basico"],)).fetchone()
            a["razao"] = r[0] if r else ""
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--nome", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--doc", help="doc mascarado ***NNNNNN**")
    g.add_argument("--cpf6", help="os 6 dígitos do meio do CPF")
    ap.add_argument("--forcar-zip", action="store_true", help="ignora a tabela e força stream-grep nos ZIPs")
    args = ap.parse_args()
    cpf6 = args.cpf6 if args.cpf6 else re.sub(r"\D", "", args.doc)
    print(f"[reverso] buscando '{_norm(args.nome)}' cpf6={cpf6} ...")
    res, fonte = buscar(args.nome, cpf6, forcar_zip=args.forcar_zip)
    if fonte == "tabela":
        print("[reverso] fonte: TABELA socios_reverso (instantâneo, sem dump)")
    elif fonte == "zst":
        print("[reverso] fonte: stream-grep no socios_full.csv.zst (sócios completo do Brasil, sem ZIPs)")
    elif fonte == "zip":
        print(f"[reverso] fonte: stream-grep nos ZIPs (alvo fora da tabela) — {len(list(_DUMP.glob('Socios*.zip')))} zips")
    else:
        print("[reverso] alvo NÃO está na tabela socios_reverso, e não há socios_full.csv.zst nem ZIPs presentes.")
        print("[reverso] => regenere o dump enxuto do mês para consultar qualquer pessoa:")
        print("[reverso]    tools/socios_dump_refresh.sh   (baixa, gera socios_full.csv.zst, apaga só os ZIPs)")
        raise SystemExit(2)
    _enriquecer_razao(res)
    print(f"[reverso] {len(res)} CNPJ(s) básico(s) onde a pessoa aparece:")
    for a in res:
        flag = "  <<< NOSSO FORNECEDOR" if a["nosso_fornecedor"] else ""
        razao = f"  [{a.get('razao','')}]" if a.get("razao") else ""
        print(f"  {a['cnpj_basico']}  qualif={a['qualif_cod']}  data={a['data']}{razao}{flag}")
    nossos = sum(1 for a in res if a["nosso_fornecedor"])
    print(f"[reverso] destes, {nossos} são NOSSOS fornecedores.")
