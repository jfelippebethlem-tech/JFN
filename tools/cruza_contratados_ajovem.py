#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cruza os CONTRATADOS do Ambiente Jovem (folha nominal pública da ONG, data/ajovem_contratados.json)
com: (1) benefício assistencial — Bolsa Família/BPC/Auxílio (pcrj_benef.db, por fragmento de CPF EXATO,
fallback nome); (2) candidaturas TSE (tse_candidatura, por nome — traz cargo/ano/município/eleito e
naturalidade=ORIGEM); (3) nomeação em folha ESTADUAL (registros_folha, por CPF EXATO) e ALERJ
(alerj_folha, por nome) e municipal do Rio (pcrj_folha_pref, por nome).

Honestidade: match por CPF (frag/estadual) é forte; por nome é INDÍCIO (homônimo sinalizado). Indício
≠ acusação. CPF de terceiros exibido mascarado no relatório (a fonte da OS o expôs, mas nós mascaramos).
Saída: JSON com achados + resumo.
"""
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BENEF = REPO / "data" / "pcrj_benef.db"
PCRJ = REPO / "data" / "pcrj.db"
COMPL = REPO / "data" / "compliance.db"
SRC = REPO / "data" / "ajovem_contratados.json"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", " ", s)).strip()


def frag6(cpf: str) -> str:
    d = re.sub(r"\D", "", cpf or "")
    return d[3:9] if len(d) == 11 else ""


def mask(cpf: str) -> str:
    d = re.sub(r"\D", "", cpf or "")
    return f"***{d[3:9]}**" if len(d) == 11 else "***"


def main():
    pessoas = json.load(open(SRC))
    for p in pessoas:
        p["nome_norm"] = norm(p["nome"])
        p["frag"] = frag6(p["cpf"])

    bcon = sqlite3.connect(f"file:{BENEF}?mode=ro", uri=True)
    pcon = sqlite3.connect(f"file:{PCRJ}?mode=ro", uri=True)
    ccon = sqlite3.connect(f"file:{COMPL}?mode=ro", uri=True)
    for con in (bcon, pcon, ccon):
        con.row_factory = sqlite3.Row

    achados = []
    n_benef = n_cand = n_nomeado_est = n_nomeado_mun = 0
    for p in pessoas:
        nn, frag, cpf = p["nome_norm"], p["frag"], re.sub(r"\D", "", p["cpf"])
        rec = {"nome": p["nome"], "cpf_mask": mask(p["cpf"]), "funcao": p.get("funcao", ""),
               "adm": p.get("adm", ""), "beneficio": [], "candidaturas": [], "nomeacao": []}

        # 1) BENEFÍCIO — por fragmento de CPF EXATO (forte); fallback nome quando frag vazio na base
        rows = []
        if frag:
            rows = bcon.execute(
                "SELECT beneficio,municipio,COUNT(DISTINCT competencia) n,MIN(competencia),MAX(competencia) "
                "FROM pcrj_beneficio WHERE cpf_frag=? AND nome_norm=? GROUP BY beneficio,municipio",
                (frag, nn)).fetchall()
        if not rows:
            rows = bcon.execute(
                "SELECT beneficio,municipio,COUNT(DISTINCT competencia) n,MIN(competencia),MAX(competencia) "
                "FROM pcrj_beneficio WHERE nome_norm=? GROUP BY beneficio,municipio", (nn,)).fetchall()
            via = "nome (indício)"
        else:
            via = "CPF (forte)"
        if rows:
            n_benef += 1
            for r in rows:
                rec["beneficio"].append({"programa": r[0], "municipio": r[1], "meses": r[2],
                                         "de": r[3], "ate": r[4], "via": via})

        # 2) CANDIDATURAS TSE — por nome (CPF mascarado no TSE)
        cand = pcon.execute(
            "SELECT ano,cargo,municipio,partido,COALESCE(eleito,''),COALESCE(uf_nascimento,''),"
            "COALESCE(municipio_nascimento,'') FROM tse_candidatura WHERE nome_norm=? ORDER BY ano", (nn,)).fetchall()
        if cand:
            n_cand += 1
            for c in cand:
                rec["candidaturas"].append({"ano": c[0], "cargo": c[1], "municipio": c[2],
                                            "partido": c[3], "eleito": c[4], "uf_nasc": c[5],
                                            "mun_nasc": c[6]})

        # 3) NOMEAÇÃO — estadual por CPF EXATO (registros_folha), ALERJ e municipal por nome
        est = ccon.execute(
            "SELECT DISTINCT orgao_nome,cargo,vinculo FROM registros_folha WHERE REPLACE(REPLACE(REPLACE("
            "cpf,'.',''),'/',''),'-','')=? LIMIT 5", (cpf,)).fetchall()
        for e in est:
            rec["nomeacao"].append({"esfera": "Estadual", "orgao": e[0], "cargo": e[1],
                                    "vinculo": e[2], "via": "CPF (forte)"})
        alerj = ccon.execute("SELECT DISTINCT cargo FROM alerj_folha WHERE nome_norm=? LIMIT 3", (nn,)).fetchall()
        for a in alerj:
            rec["nomeacao"].append({"esfera": "ALERJ", "orgao": "ALERJ", "cargo": a[0],
                                    "vinculo": "", "via": "nome (indício)"})
        mun = pcon.execute("SELECT DISTINCT orgao,tipo_folha FROM pcrj_folha_pref WHERE nome_norm=? LIMIT 3",
                           (nn,)).fetchall()
        for mrow in mun:
            rec["nomeacao"].append({"esfera": "Municipal-Rio", "orgao": mrow[0], "cargo": "",
                                    "vinculo": mrow[1], "via": "nome (indício)"})
        if est:
            n_nomeado_est += 1
        if mun or alerj:
            n_nomeado_mun += 1

        if rec["beneficio"] or rec["candidaturas"] or rec["nomeacao"]:
            achados.append(rec)

    bcon.close(); pcon.close(); ccon.close()
    resumo = {"total_contratados": len(pessoas), "com_algum_achado": len(achados),
              "recebem_beneficio": n_benef, "ja_candidatos": n_cand,
              "nomeados_estadual_cpf": n_nomeado_est, "nomeados_alerj_ou_municipal": n_nomeado_mun}
    out = {"resumo": resumo, "achados": sorted(
        achados, key=lambda r: (not r["candidaturas"], not r["nomeacao"], not r["beneficio"]))}
    json.dump(out, open(REPO / "data" / "ajovem_cruzamento.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(resumo, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
