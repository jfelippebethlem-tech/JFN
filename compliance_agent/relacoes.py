# -*- coding: utf-8 -*-
"""Módulo de RELAÇÕES — onde cada sócio/empresa se relaciona com OUTRA empresa fornecedora e órgão.

Pergunta do dono: dado um alvo (CNPJ de empresa, nome de sócio, ou UG de órgão), MAPEIA:
- **sócio ↔ empresa** (QSA — `socios_fornecedor`)
- **empresa ↔ empresa** por **sócio em comum** ou **endereço em comum** (indício de grupo econômico / concorrência fictícia)
- **empresa ↔ órgão** (`ordens_bancarias` — quais UGs pagaram a empresa e as relacionadas; UG **em comum** = mais forte)

Bounded/indexado (ix_socio_cnpj, ix_socio_norm, ix_end_norm, ix_ordens_bancarias_favorecido_cpf) — VM-safe.
Honestidade (regra-mãe): relação é **FATO** (sócio/endereço/contrato em comum), **não prova** de ilícito. Sócio em
comum entre concorrentes da **mesma UG** é **indício** de conluio/concorrência fictícia (a confirmar no certame/SEI).
CPF de sócio mascarado (LGPD) — o cruzamento usa nome normalizado + doc mascarado.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

_DB = Path("data") / "compliance.db"
# endereços genéricos que NÃO caracterizam co-endereço (evita falso vínculo)
_END_GENERICO = re.compile(r"\b(SALA|LOJA|ANDAR|S/?N|SN|ZERO|CENTRO)\b")


def _con(db_path: str | Path | None):
    return sqlite3.connect(f"file:{Path(db_path or _DB)}?mode=ro", uri=True)


def _norm(s: str) -> str:
    s = (s or "").upper().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _orgaos_de(con, cnpj: str, limite: int = 12) -> list[dict]:
    """UGs que pagaram este CNPJ (OB = verdade), por valor. Indexado por favorecido_cpf."""
    rows = con.execute(
        "SELECT ug_codigo, MAX(ug_nome) nome, COUNT(*) n, ROUND(SUM(valor),2) tot "
        "FROM ordens_bancarias WHERE favorecido_cpf=? AND ug_codigo IS NOT NULL "
        "GROUP BY ug_codigo ORDER BY tot DESC LIMIT ?", (cnpj, limite)).fetchall()
    return [{"ug": r[0], "nome": r[1], "n_ob": r[2], "total": r[3] or 0.0} for r in rows]


def relacoes(alvo: str, db_path: str | Path | None = None, limite: int = 40) -> dict:
    """Mapa de relações do alvo. Resolve: 14 díg→empresa, 6 díg→UG, senão→nome de sócio."""
    raw = str(alvo or "").strip()
    dig = _digits(raw)
    try:
        con = _con(db_path)
        try:
            if len(dig) == 14:
                return _empresa(con, dig, limite)
            if len(dig) == 6:
                return _orgao(con, dig, limite)
            return _socio(con, _norm(raw), raw, limite)
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "_nota": f"INDISPONÍVEL: {str(exc)[:160]}"}


def _empresa(con, cnpj: str, limite: int) -> dict:
    socios = con.execute(
        "SELECT socio_nome, socio_nome_norm, socio_doc, qualificacao FROM socios_fornecedor WHERE cnpj=?",
        (cnpj,)).fetchall()
    razao = con.execute(
        "SELECT razao FROM socios_fornecedor WHERE cnpj=? AND razao<>'' LIMIT 1", (cnpj,)).fetchone()
    razao = razao[0] if razao else (con.execute(
        "SELECT razao FROM endereco_fornecedor WHERE cnpj=? LIMIT 1", (cnpj,)).fetchone() or ["?"])[0]

    # empresa ↔ empresa por SÓCIO em comum — dedup por RAIZ (matriz/filial = MESMA PJ, não conta como vínculo).
    raiz_alvo = cnpj[:8]
    via_socio: dict[str, dict] = {}  # keyed by RAIZ (8) da relacionada
    norms = [s[1] for s in socios if s[1]]
    if norms:
        ph = ",".join("?" * len(norms))
        for c2, r2, sn, doc2 in con.execute(
                f"SELECT DISTINCT cnpj, razao, socio_nome, socio_doc FROM socios_fornecedor "
                f"WHERE socio_nome_norm IN ({ph}) AND substr(cnpj,1,8)<>?",
                norms + [raiz_alvo]).fetchall()[: limite * 6]:
            rz = c2[:8]
            via_socio.setdefault(rz, {"cnpj": c2, "razao": r2, "socios_comuns": set()})
            via_socio[rz]["socios_comuns"].add(sn)

    # empresa ↔ empresa por ENDEREÇO em comum (não genérico)
    via_end: list[dict] = []
    er = con.execute("SELECT endereco_norm FROM endereco_fornecedor WHERE cnpj=? LIMIT 1", (cnpj,)).fetchone()
    end_norm = (er[0] if er else "") or ""
    if end_norm and len(end_norm) > 12 and not _END_GENERICO.search(end_norm):
        vistos_rz: set = {raiz_alvo}
        for c2, r2 in con.execute(
                "SELECT DISTINCT cnpj, razao FROM endereco_fornecedor WHERE endereco_norm=? AND substr(cnpj,1,8)<>? LIMIT ?",
                (end_norm, raiz_alvo, limite * 4)).fetchall():
            if c2[:8] in vistos_rz:
                continue  # dedup por raiz (filial = mesma PJ)
            vistos_rz.add(c2[:8])
            via_end.append({"cnpj": c2, "razao": r2})
            if len(via_end) >= limite:
                break

    # empresa ↔ órgão
    orgaos = _orgaos_de(con, cnpj)
    ugs_alvo = {o["ug"] for o in orgaos}

    # enriquecer relacionadas: órgãos EM COMUM (indício mais forte de conluio). via_socio é keyed por RAIZ.
    rel = []
    for rz, d in list(via_socio.items())[:limite]:
        ugs2 = {o["ug"] for o in _orgaos_de(con, d["cnpj"], 6)}
        rel.append({"cnpj": d["cnpj"], "razao": d["razao"], "via": "sócio",
                    "socios_comuns": sorted(d["socios_comuns"])[:4],
                    "ugs_em_comum": sorted(ugs_alvo & ugs2)})
    rel.sort(key=lambda x: (-len(x["ugs_em_comum"]), -len(x["socios_comuns"])))

    return {"ok": True, "tipo": "empresa", "alvo": cnpj, "razao": razao,
            "n_socios": len(socios),
            "socios": [{"nome": s[0], "doc": s[2], "qualificacao": s[3]} for s in socios],
            "empresas_via_socio": rel, "empresas_via_endereco": via_end,
            "orgaos": orgaos, "leitura": _leitura_empresa(razao, rel, via_end, orgaos)}


def _socio(con, nome_norm: str, nome_raw: str, limite: int) -> dict:
    rows = con.execute(
        "SELECT DISTINCT cnpj, razao, qualificacao FROM socios_fornecedor WHERE socio_nome_norm=? LIMIT ?",
        (nome_norm, limite)).fetchall()
    empresas = []
    for c, r, q in rows:
        empresas.append({"cnpj": c, "razao": r, "qualificacao": q, "orgaos": _orgaos_de(con, c, 5)})
    return {"ok": True, "tipo": "socio", "alvo": nome_raw, "n_empresas": len(empresas),
            "empresas": empresas,
            "leitura": (f"**{nome_raw}** aparece no QSA de **{len(empresas)}** fornecedor(es) do Estado. "
                        "Sócio em comum entre fornecedores é vínculo factual; se concorrem na MESMA UG, indício de "
                        "concorrência fictícia (a confirmar). CPF mascarado (LGPD)." if empresas else
                        f"Nenhum fornecedor com o sócio '{nome_raw}' (INDISPONÍVEL — nome exato ou ainda não no QSA).")}


def _orgao(con, ug: str, limite: int) -> dict:
    forn = con.execute(
        "SELECT favorecido_cpf, MAX(favorecido_nome) nome, COUNT(*) n, ROUND(SUM(valor),2) tot "
        "FROM ordens_bancarias WHERE ug_codigo=? AND length(favorecido_cpf)=14 "
        "GROUP BY favorecido_cpf ORDER BY tot DESC LIMIT ?", (ug, limite)).fetchall()
    return {"ok": True, "tipo": "orgao", "alvo": ug, "n_fornecedores_top": len(forn),
            "fornecedores": [{"cnpj": f[0], "nome": f[1], "n_ob": f[2], "total": f[3] or 0.0} for f in forn],
            "leitura": (f"UG {ug}: top {len(forn)} fornecedores PJ por valor. Para ver vínculos (sócio/endereço "
                        "em comum) entre eles, consultar cada CNPJ. Concentração + sócio comum = indício a apurar.")}


def _m(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _leitura_empresa(razao, rel, via_end, orgaos) -> str:
    n_org = len(orgaos)
    tot = sum(o["total"] for o in orgaos)
    com_ug = [r for r in rel if r["ugs_em_comum"]]
    L = [f"**{razao}** recebeu de **{n_org}** órgão(s) (R$ {_m(tot)} no top)."]
    if rel:
        L.append(f"Tem **{len(rel)}** empresa(s) ligada(s) por **sócio em comum**" +
                 (f", das quais **{len(com_ug)}** contratam com a MESMA UG — **indício** de concorrência fictícia/"
                  "grupo econômico a confirmar." if com_ug else " (sem UG em comum entre elas)."))
    if via_end:
        L.append(f"**{len(via_end)}** empresa(s) no **mesmo endereço** (co-endereço — possível grupo/fachada).")
    if not rel and not via_end:
        L.append("Sem vínculo de sócio/endereço com outros fornecedores na base (INDISPONÍVEL ≠ inexistência).")
    return " ".join(L)


def render_md(r: dict) -> str:
    """Markdown do mapa de relações (para CLI / relatório / Yoda)."""
    if not r.get("ok"):
        return f"_Relações INDISPONÍVEL: {r.get('_nota','')}_"
    L = [f"# Relações — {r.get('razao') or r.get('alvo')}", "", r.get("leitura", ""), ""]
    if r.get("tipo") == "empresa":
        if r.get("orgaos"):
            L += ["## Órgãos (OB = pagamento)", "| UG | Órgão | OBs | Total (R$) |", "|---|---|--:|--:|"]
            L += [f"| {o['ug']} | {(o['nome'] or '')[:30]} | {o['n_ob']} | {_m(o['total'])} |" for o in r["orgaos"]]
            L += [""]
        if r.get("empresas_via_socio"):
            L += ["## Empresas ligadas por SÓCIO em comum (raiz distinta)",
                  "| Empresa | Sócios em comum | UG em comum |", "|---|---|---|"]
            L += [f"| {e['razao'][:34]} | {', '.join(e['socios_comuns'])} | {', '.join(e['ugs_em_comum']) or '—'} |"
                  for e in r["empresas_via_socio"][:20]]
            L += [""]
        if r.get("empresas_via_endereco"):
            L += ["## Empresas no MESMO endereço (co-endereço)",
                  "| Empresa | CNPJ |", "|---|---|"]
            L += [f"| {e['razao'][:40]} | {e['cnpj']} |" for e in r["empresas_via_endereco"][:20]]
            L += [""]
    elif r.get("tipo") == "socio":
        L += ["## Empresas do sócio", "| Empresa | Qualificação | Órgãos |", "|---|---|--:|"]
        L += [f"| {e['razao'][:34]} | {e['qualificacao'] or ''} | {len(e['orgaos'])} |" for e in r.get("empresas", [])]
    elif r.get("tipo") == "orgao":
        L += ["## Top fornecedores PJ", "| Fornecedor | CNPJ | Total (R$) |", "|---|---|--:|"]
        L += [f"| {(f['nome'] or '')[:34]} | {f['cnpj']} | {_m(f['total'])} |" for f in r.get("fornecedores", [])]
    L += ["", "> Relação é FATO (sócio/endereço/contrato em comum), não prova. Sócio comum entre concorrentes da "
          "mesma UG = indício de conluio a confirmar. CPF mascarado (LGPD)."]
    return "\n".join(L)


if __name__ == "__main__":  # pragma: no cover
    import sys
    if len(sys.argv) < 2:
        print("uso: python -m compliance_agent.relacoes <CNPJ | nome do sócio | UG>")
        sys.exit(1)
    print(render_md(relacoes(" ".join(sys.argv[1:]))))
