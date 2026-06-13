# -*- coding: utf-8 -*-
"""
lex_conflito — conflito de interesse: doações eleitorais (TSE) × fornecedores do Estado (OBs).
JFN 2.0, Onda 2. Fonte 100% gratuita (TSE Dados Abertos + base interna de OBs/QSA).

REQUISITO-CHAVE (instrução do dono): o cruzamento NÃO é só doador-CNPJ == fornecedor-CNPJ. Tem que casar
**doadores TSE × SÓCIOS (QSA) das empresas que receberam OB/contrato**. Ou seja, o doador (CPF/CNPJ) pode ser
SÓCIO da contratada, não a contratada em si — é assim que se pega o vínculo escondido.

⚠️ LGPD: `socios_fornecedor.socio_doc` vem MASCARADO (ex.: `***550179**` — só 6 dígitos do meio do CPF).
Então o match doador↔sócio é por NOME normalizado (sinal forte) corroborado pelo CPF mascarado (6 dígitos) quando
possível — princípio de ≥2 sinais independentes (OSINT). Saída = INDÍCIO a verificar, nunca acusação.

Uso:
    cd ~/JFN && PYTHONPATH=. .venv/bin/python -m compliance_agent.lex_conflito --cnpj 12345678000199
    from compliance_agent.lex_conflito import conflito
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata

from compliance_agent.database.models import _resolver_db


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _norm_nome(s: str) -> str:
    s = (s or "").upper()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^A-Z ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _mask_cpf(cpf: str) -> str:
    """Formata um CPF de 11 dígitos no mesmo padrão mascarado do QSA: ***DDDDDD** (6 dígitos do meio)."""
    d = _digits(cpf)
    return f"***{d[3:9]}**" if len(d) == 11 else ""


def _empresas_com_ob(con) -> dict[str, dict]:
    """CNPJ -> {n_ob, total} a partir de ordens_bancarias (TFE) + ob_orcamentaria_siafe (SIAFE)."""
    emp: dict[str, dict] = {}
    for sql, campo in [("SELECT favorecido_cpf, COUNT(*), COALESCE(SUM(valor),0) FROM ordens_bancarias "
                        "WHERE favorecido_cpf IS NOT NULL GROUP BY favorecido_cpf", "tfe"),
                       ("SELECT credor, COUNT(*), 0 FROM ob_orcamentaria_siafe WHERE credor IS NOT NULL GROUP BY credor", "siafe")]:
        try:
            for c, n, tot in con.execute(sql):
                d = _digits(c)
                if len(d) != 14:
                    continue
                e = emp.setdefault(d, {"n_ob": 0, "total": 0.0})
                e["n_ob"] += n or 0
                e["total"] += float(tot or 0)
        except sqlite3.Error:
            continue
    return emp


def _ugs_sei_por_empresa(con, cnpjs: set[str], max_ug: int = 8, max_sei: int = 12) -> dict[str, dict]:
    """Para cada CNPJ contratado, devolve {ugs:[{ug, nome, total, n_ob}], seis:[numero_sei...]}.

    Fonte: ordens_bancarias (TFE, tem ug_codigo/ug_nome/numero_sei) + ob_orcamentaria_siafe (SIAFE, tem
    ug_pagadora/processo). UG resolvida pelo CÓDIGO via mapa canônico (a OB às vezes rotula com o órgão
    superior — ver compliance_agent/ugs.py). Só leitura; seguro com o sweep rodando (WAL)."""
    if not cnpjs:
        return {}
    try:
        from compliance_agent import ugs as _ugs
        _rotulo = _ugs.rotulo
    except Exception:
        def _rotulo(cod, nome=""):  # fallback sem mapa canônico
            return (nome or f"UG {cod}").strip()

    out: dict[str, dict] = {c: {"_ug": {}, "_sei": {}} for c in cnpjs}
    place = ",".join("?" * len(cnpjs))
    alvos = list(cnpjs)

    # (1) TFE — favorecido_cpf guarda o CNPJ (14 díg.); ug_codigo + ug_nome + numero_sei
    try:
        for cnpj_e, ugc, ugn, sei, n, tot in con.execute(
                f"SELECT favorecido_cpf, ug_codigo, ug_nome, numero_sei, COUNT(*), COALESCE(SUM(valor),0) "
                f"FROM ordens_bancarias WHERE favorecido_cpf IN ({place}) "
                f"GROUP BY favorecido_cpf, ug_codigo, ug_nome, numero_sei", alvos):
            d = _digits(cnpj_e)
            if d not in out:
                continue
            cod = _digits(ugc) or (ugc or "")
            rot = _rotulo(cod, ugn or "")
            u = out[d]["_ug"].setdefault(rot, {"ug": cod, "nome": rot, "total": 0.0, "n_ob": 0})
            u["total"] += float(tot or 0); u["n_ob"] += int(n or 0)
            if sei and str(sei).strip():
                out[d]["_sei"][str(sei).strip()] = out[d]["_sei"].get(str(sei).strip(), 0) + int(n or 0)
    except sqlite3.Error:
        pass

    # (2) SIAFE — credor guarda o CNPJ; ug_pagadora/ug_emitente + processo (=SEI de origem)
    try:
        for cnpj_e, ugp, uge, proc, n, tot in con.execute(
                f"SELECT credor, ug_pagadora, ug_emitente, processo, COUNT(*), COALESCE(SUM(valor),0) "
                f"FROM ob_orcamentaria_siafe WHERE credor IN ({place}) "
                f"GROUP BY credor, ug_pagadora, ug_emitente, processo", alvos):
            d = _digits(cnpj_e)
            if d not in out:
                continue
            cod = _digits(ugp) or _digits(uge) or (ugp or uge or "")
            rot = _rotulo(cod, "")
            u = out[d]["_ug"].setdefault(rot, {"ug": cod, "nome": rot, "total": 0.0, "n_ob": 0})
            u["total"] += float(tot or 0); u["n_ob"] += int(n or 0)
            if proc and str(proc).strip():
                out[d]["_sei"][str(proc).strip()] = out[d]["_sei"].get(str(proc).strip(), 0) + int(n or 0)
    except sqlite3.Error:
        pass

    # consolida: top UGs por valor, top SEIs por nº de OBs
    res: dict[str, dict] = {}
    for c, agg in out.items():
        ugs_l = sorted(agg["_ug"].values(), key=lambda x: x["total"], reverse=True)
        for u in ugs_l:
            u["total"] = round(u["total"], 2)
        seis_l = [s for s, _ in sorted(agg["_sei"].items(), key=lambda kv: kv[1], reverse=True)]
        res[c] = {"ugs": ugs_l[:max_ug], "seis": seis_l[:max_sei],
                  "n_ugs": len(ugs_l), "n_seis": len(seis_l)}
    return res


def conflito(cnpj: str | None = None, candidato: str | None = None, limite: int = 200) -> dict:
    """Rede de conflito doador↔(empresa|sócio da empresa)↔OB.

    - cnpj: foca numa empresa (mostra doações DELA e dos SÓCIOS dela).
    - candidato: foca em quem RECEBEU (lista doadores-empresa/sócio que viraram fornecedores).
    - nenhum: varredura geral (top por valor de OB), até `limite`.
    Retorna {ok, rede:[{doador, doc, candidato, partido, ano, valor_doacao, empresa_cnpj, empresa, n_ob,
    total_ob, via:"direto"|"socio", sinais[]}], _fonte, _nota}.
    """
    _DB = _resolver_db()
    if not _DB.exists():
        return {"ok": False, "erro": "compliance.db ausente"}
    con = sqlite3.connect(str(_DB))
    try:
        n_doacoes = con.execute("SELECT COUNT(*) FROM doacoes_eleitorais").fetchone()[0]
        if n_doacoes == 0:
            return {"ok": True, "rede": [], "_fonte": "TSE Dados Abertos",
                    "_nota": "INDISPONÍVEL: base doacoes_eleitorais vazia — rodar coletor TSE "
                             "(compliance_agent.collectors.tse baixar_doacoes_ano) antes."}
        emp = _empresas_com_ob(con)

        # filtro de doações
        where, params = "", []
        if candidato:
            where = "WHERE UPPER(nome_candidato) LIKE ?"; params = [f"%{candidato.upper()}%"]
        doacoes = con.execute(
            "SELECT cpf_cnpj_doador, nome_doador, nome_candidato, partido, ano_eleicao, COALESCE(SUM(valor),0) "
            f"FROM doacoes_eleitorais {where} GROUP BY cpf_cnpj_doador, nome_doador, nome_candidato, partido, ano_eleicao",
            params).fetchall()

        # índice de sócios por nome_norm e por cpf mascarado (p/ o cruzamento via sócio)
        socios_por_nome: dict[str, list[str]] = {}
        socios_por_doc: dict[str, list[str]] = {}
        for cnpj_emp, nome_norm, doc in con.execute(
                "SELECT cnpj, socio_nome_norm, socio_doc FROM socios_fornecedor WHERE socio_nome_norm!=''"):
            d = _digits(cnpj_emp)
            if nome_norm:
                socios_por_nome.setdefault(nome_norm, []).append(d)
            if doc:
                socios_por_doc.setdefault(str(doc).strip(), []).append(d)

        alvo_cnpj = _digits(cnpj) if cnpj else None
        rede = []
        for doc_doador, nome_doador, cand, partido, ano, valor in doacoes:
            dd = _digits(doc_doador)
            nome_norm = _norm_nome(nome_doador)
            empresas_vinculadas: dict[str, dict] = {}

            # (a) DIRETO: doador-PJ é a própria empresa com OB
            if len(dd) == 14 and dd in emp:
                empresas_vinculadas[dd] = {"via": "direto", "sinais": ["doador_cnpj==fornecedor"]}

            # (b) VIA SÓCIO: doador (PF/PJ) é SÓCIO de empresa com OB — casa por nome e/ou cpf mascarado
            cnpjs_socio: set[str] = set()
            if nome_norm and nome_norm in socios_por_nome:
                cnpjs_socio |= {c for c in socios_por_nome[nome_norm]}
            if len(dd) == 11:
                mc = _mask_cpf(dd)
                if mc and mc in socios_por_doc:
                    cnpjs_socio |= set(socios_por_doc[mc])
            for c in cnpjs_socio:
                if c in emp:
                    # confiança: nome + cpf-mascarado batendo = 2 sinais
                    sinais = []
                    if nome_norm in socios_por_nome and c in socios_por_nome[nome_norm]:
                        sinais.append("nome_socio")
                    if len(dd) == 11 and _mask_cpf(dd) in socios_por_doc and c in socios_por_doc[_mask_cpf(dd)]:
                        sinais.append("cpf_mascarado")
                    prev = empresas_vinculadas.get(c)
                    if not prev or prev["via"] == "socio":
                        empresas_vinculadas[c] = {"via": "socio", "sinais": sinais or ["nome_socio"]}

            for c, meta in empresas_vinculadas.items():
                if alvo_cnpj and c != alvo_cnpj:
                    continue
                e = emp[c]
                rede.append({
                    "doador": nome_doador, "doc": doc_doador, "candidato": cand, "partido": partido,
                    "ano": ano, "valor_doacao": round(float(valor or 0), 2),
                    "empresa_cnpj": c, "n_ob": e["n_ob"], "total_ob": round(e["total"], 2),
                    "via": meta["via"], "sinais": meta["sinais"],
                })

        # score simples: via direto + corroboração de 2 sinais pesa mais; ordenar por (valor_ob, valor_doacao)
        for r in rede:
            r["score"] = (2 if r["via"] == "direto" else 1) + (1 if len(r["sinais"]) >= 2 else 0)
        rede.sort(key=lambda r: (r["total_ob"], r["valor_doacao"]), reverse=True)
        rede = rede[:limite]

        # enriquece SÓ as empresas que sobraram na rede: UG pagadora (canônica) + processos SEI
        cnpjs_rede = {r["empresa_cnpj"] for r in rede}
        det = _ugs_sei_por_empresa(con, cnpjs_rede)
        for r in rede:
            d = det.get(r["empresa_cnpj"], {})
            r["ugs"] = d.get("ugs", [])
            r["seis"] = d.get("seis", [])

        return {"ok": True, "rede": rede, "n_doacoes_base": n_doacoes,
                "_fonte": "TSE Dados Abertos + OBs (TFE/SIAFE) + QSA BrasilAPI",
                "_nota": "INDÍCIO a verificar (presunção de legitimidade). socio_doc é mascarado (LGPD); "
                         "match por nome+CPF-mascarado. Score = via + corroboração, não prova."}
    finally:
        con.close()


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Conflito doador(TSE)↔sócio↔fornecedor(OB).")
    ap.add_argument("--cnpj"); ap.add_argument("--candidato"); ap.add_argument("--limite", type=int, default=50)
    a = ap.parse_args()
    print(json.dumps(conflito(cnpj=a.cnpj, candidato=a.candidato, limite=a.limite), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
