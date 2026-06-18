# -*- coding: utf-8 -*-
"""
Cruzamento unificado: SÓCIOS × OBs do SIAFE × processos SEI × ENDEREÇOS das empresas.

Para um fornecedor (CNPJ), amarra num único quadro:
  • os SÓCIOS dele (QSA / rede_societaria);
  • os outros fornecedores que COMPARTILHAM um sócio (empresas-irmãs / grupo econômico);
  • a pegada financeira de cada um nas OBs do SIAFE (nº de OBs, total pago) — fonte de verdade;
  • os PROCESSOS SEI que originaram esses pagamentos (ordens_bancarias.numero_sei/numero_processo
    + contratos_tcerj.processo);
  • o ENDEREÇO (sede) de cada empresa — sinalizando quando empresas com sócio comum também
    COMPARTILHAM A SEDE (indício forte de grupo econômico/laranja — art. 337-F CP, art. 11 Lei 8.429).

Tudo best-effort e honesto: indícios a verificar, nunca acusação. Degrada com elegância
(seção some/avisa) quando o QSA não foi ingerido ou a base está vazia.

Uso:
    from compliance_agent.cruzamento import cruzar
    cz = cruzar("19088605000104")        # síncrono; faz lookup de endereço best-effort
"""
from __future__ import annotations

import asyncio
import os
import re
import sqlite3
from datetime import datetime

_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DB = os.environ.get("JFN_DB", os.path.join(_BASE, "data", "compliance.db"))

# quantos relacionados (sócio comum) enriquecer com endereço via rede (limite p/ rate-limit BrasilAPI)
_MAX_LOOKUP = int(os.environ.get("JFN_CRUZ_MAX_LOOKUP", "8"))


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


# ───────────────────────── OBs do SIAFE + processos SEI por CNPJ ─────────────────────────

def obs_e_sei(cnpj: str) -> dict:
    """Pegada nas OBs do SIAFE + processos SEI de um CNPJ.

    {n_obs, total_pago, sei_processos: [str], n_sei}

    total_pago = total recebido do Estado (TODAS as UGs), só OBs de valor > 0.
    Não confundir com o pago por uma UG específica (as seções 1/1-D/1-K filtram por UG).
    """
    cnpj = _so_digitos(cnpj)
    out = {"n_obs": 0, "total_pago": 0.0, "sei_processos": [], "n_sei": 0}
    if not os.path.exists(_DB):
        return out
    con = sqlite3.connect(_DB)
    try:
        # total_pago = total recebido do Estado (TODAS as UGs); só valores positivos
        # (exclui estornos/anulações de sinal negativo). Não filtra por UG aqui de propósito.
        row = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN valor>0 THEN valor ELSE 0 END),0) "
            "FROM ordens_bancarias WHERE favorecido_cpf=?",
            (cnpj,)).fetchone()
        out["n_obs"], out["total_pago"] = int(row[0] or 0), float(row[1] or 0.0)

        seis: set[str] = set()
        for col in ("numero_sei", "numero_processo"):
            for (v,) in con.execute(
                f"SELECT DISTINCT {col} FROM ordens_bancarias "
                f"WHERE favorecido_cpf=? AND {col} IS NOT NULL AND {col}!=''", (cnpj,)):
                if v:
                    seis.add(v.strip())
        # processos SEI também via contratos do TCE-RJ (chave = nº do processo)
        try:
            for (v,) in con.execute(
                "SELECT DISTINCT processo FROM contratos_tcerj WHERE cnpj=? AND processo IS NOT NULL AND processo!=''",
                (cnpj,)):
                if v:
                    for p in str(v).split(","):
                        p = p.strip()
                        if p:
                            seis.add(p)
        except sqlite3.OperationalError:
            pass
        out["sei_processos"] = sorted(seis)
        out["n_sei"] = len(seis)
    finally:
        con.close()
    return out


# ───────────────────────── endereço (stored → lazy fetch) ─────────────────────────

async def _garantir_enderecos(cnpjs: list[str]) -> dict:
    """Garante endereço de cada CNPJ: lê o armazenado; se faltar, busca na BrasilAPI e persiste.

    Retorna {cnpj: {endereco, endereco_norm, municipio, uf, cep, razao}}. Best-effort.
    """
    from compliance_agent import rede_societaria as rs
    res: dict = {}
    faltam: list[str] = []
    for c in cnpjs:
        c = _so_digitos(c)
        if not c:
            continue
        e = rs.endereco_de(c)
        if e:
            res[c] = e
        else:
            faltam.append(c)

    if faltam:
        import httpx
        from compliance_agent.collectors.cnpj import buscar_cnpj
        con = rs._con()
        agora = datetime.now().isoformat(timespec="seconds")
        try:
            async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "JFN-Compliance/1.0"}) as client:
                for c in faltam[:_MAX_LOOKUP]:
                    try:
                        d = await buscar_cnpj(c, client=client)
                        if d and "error" not in d:
                            rs._gravar_endereco(con, c, d, agora)
                            con.commit()
                            res[c] = rs.endereco_de(c)
                    except Exception:
                        pass
                    await asyncio.sleep(0.4)
        finally:
            con.close()
    return res


def fornecedores_no_mesmo_endereco(endereco_norm: str, cnpj_excluir: str = "") -> list[dict]:
    """Outros fornecedores (com endereço ingerido) sediados no MESMO endereço normalizado.

    Independe de sócio em comum — pega 'empresas no mesmo imóvel' que a rede societária não veria.
    Dois+ fornecedores recebendo do Estado na MESMA sede é red flag forte (fachada/laranja/
    direcionamento — art. 337-F CP). Retorna [{cnpj, razao, n_obs, total_pago, n_sei}].

    total_pago de cada empresa = total recebido do Estado (TODAS as UGs), só OBs > 0 —
    não é o pago por uma UG específica. Rotular assim ao exibir.
    """
    endereco_norm = (endereco_norm or "").strip()
    if not endereco_norm or len(endereco_norm) < 12 or not os.path.exists(_DB):
        return []  # endereço vazio/curto demais não é evidência confiável de co-localização
    cnpj_excluir = _so_digitos(cnpj_excluir)
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT cnpj, razao FROM endereco_fornecedor WHERE endereco_norm=? AND cnpj!=?",
            (endereco_norm, cnpj_excluir)).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        os_ = obs_e_sei(r["cnpj"])
        out.append({"cnpj": r["cnpj"], "razao": r["razao"] or "",
                    "n_obs": os_["n_obs"], "total_pago": os_["total_pago"], "n_sei": os_["n_sei"]})
    # prioriza quem também recebe OBs (mais relevante p/ o controle)
    out.sort(key=lambda x: (-x["total_pago"], -x["n_obs"]))
    return out


# ───────────────────────── cruzamento principal ─────────────────────────

async def cruzar_async(cnpj: str) -> dict:
    """Monta o cruzamento sócio × OB × SEI × endereço para um CNPJ. Ver docstring do módulo."""
    from compliance_agent import rede_societaria as rs

    cnpj = _so_digitos(cnpj)
    out = {
        "cnpj": cnpj, "tem_rede": False, "socios": [], "relacionados": [],
        "endereco": {}, "obs_sei": obs_e_sei(cnpj), "coendereco": [], "indicios": [],
        "red_flags": [], "_nota": "",
    }

    rede = rs.rede_por_socio(cnpj)
    out["socios"] = rede.get("socios", []) or []
    out["cidade"] = ""  # cidade-sede do alvo (município/UF) — preenchida abaixo
    relacionados = rede.get("relacionados", []) or []
    if not out["socios"] and not relacionados:
        out["_nota"] = rede.get("_nota") or "QSA deste CNPJ ainda não ingerido na rede societária."
    elif out["socios"] and not relacionados:
        out["_nota"] = (f"QSA ingerido ({len(out['socios'])} sócio(s)), porém nenhuma outra empresa da base "
                        "compartilha sócio com este CNPJ.")

    # endereços: o do alvo + os dos relacionados (bounded)
    alvo_e_rel = [cnpj] + [r["cnpj"] for r in relacionados]
    ends = await _garantir_enderecos(alvo_e_rel)
    out["endereco"] = ends.get(cnpj, {})
    end_alvo_norm = (out["endereco"].get("endereco_norm") or "")

    def _cidade(e: dict) -> str:
        m, uf = (e.get("municipio") or "").strip(), (e.get("uf") or "").strip()
        return f"{m}/{uf}" if m and uf else (m or uf or "")

    cidade_alvo = _cidade(out["endereco"])
    out["cidade"] = cidade_alvo
    mun_alvo = (out["endereco"].get("municipio") or "").strip().upper()

    # RED FLAG: outros fornecedores na MESMA sede (independe de sócio comum — pega fachada/laranja)
    coend = fornecedores_no_mesmo_endereco(end_alvo_norm, cnpj_excluir=cnpj)
    out["coendereco"] = coend
    coend_pagos = [c for c in coend if c["total_pago"] > 0]
    if coend:
        _msg = (f"{len(coend)} outro(s) fornecedor(es) com sede no MESMO endereço do alvo "
                f"({out['endereco'].get('endereco','')}); "
                f"{len(coend_pagos)} deles também recebem OBs do Estado. Compartilhar sede sem sócio "
                "declarado em comum é red flag de empresa de fachada/laranja a verificar (art. 337-F CP; "
                "art. 11 Lei 8.429/92).")
        out["red_flags"].append({"codigo": "R-COEND", "nivel": "ALTO" if coend_pagos else "MÉDIO",
                                 "descricao": _msg})

    enriquecidos = []
    for r in relacionados:
        rc = _so_digitos(r["cnpj"])
        os_ = obs_e_sei(rc)
        e = ends.get(rc, {})
        mesmo_end = bool(end_alvo_norm) and e.get("endereco_norm") == end_alvo_norm
        mesma_cid = bool(mun_alvo) and (e.get("municipio") or "").strip().upper() == mun_alvo
        enriquecidos.append({
            "cnpj": rc, "razao": r.get("razao") or "", "socios_comuns": r.get("socios_comuns") or "",
            "n_obs": os_["n_obs"], "total_pago": os_["total_pago"], "n_sei": os_["n_sei"],
            "endereco": e.get("endereco") or "", "cidade": _cidade(e),
            "mesmo_endereco": mesmo_end, "mesma_cidade": mesma_cid,
        })
    # ordena: mesmo endereço > mesma cidade > maior valor pago
    enriquecidos.sort(key=lambda x: (not x["mesmo_endereco"], not x["mesma_cidade"], -x["total_pago"]))
    out["relacionados"] = enriquecidos
    out["tem_rede"] = bool(enriquecidos)

    # indícios
    coligadas_pagas = [r for r in enriquecidos if r["total_pago"] > 0]
    mesma_sede = [r for r in enriquecidos if r["mesmo_endereco"]]
    # mesma cidade (mas não mesma sede) — sinal mais fraco, ainda assim relevante p/ cluster geográfico
    mesma_cidade = [r for r in enriquecidos if r["mesma_cidade"] and not r["mesmo_endereco"]]
    if coligadas_pagas:
        out["indicios"].append(
            f"{len(coligadas_pagas)} empresa(s) com sócio em comum TAMBÉM recebem OBs do Estado — "
            "verificar disputa nas mesmas licitações (frustração da competitividade, art. 337-F CP).")
    if mesma_sede:
        out["indicios"].append(
            f"{len(mesma_sede)} empresa(s) com sócio em comum COMPARTILHAM a mesma sede do alvo — "
            "indício forte de grupo econômico/laranja (art. 337-F CP; art. 11 Lei 8.429/92).")
    if mesma_cidade:
        out["indicios"].append(
            f"{len(mesma_cidade)} empresa(s) com sócio em comum sediadas na MESMA CIDADE do alvo "
            f"({cidade_alvo}) — cluster geográfico a verificar (empresas-irmãs/fachada).")
    return out


def cruzar(cnpj: str) -> dict:
    """Wrapper síncrono (CLI / uso fora de loop async)."""
    return asyncio.run(cruzar_async(cnpj))


# ───────────────────────── descoberta: clusters de mesma sede ─────────────────────────

def clusters_mesmo_endereco(min_forn: int = 2, limite: int = 50, so_com_obs: bool = True) -> dict:
    """Varre TODA a base ingerida e acha grupos de fornecedores que dividem a MESMA sede.

    Ferramenta de auditoria proativa (não parte de um CNPJ): ranqueia os imóveis com mais fornecedores
    distintos e/ou maior valor pago do Estado. Cluster de empresas no mesmo endereço recebendo recursos
    públicos é red flag clássico de fachada/laranja/direcionamento (art. 337-F CP; art. 11 Lei 8.429/92).

    {ok, n_clusters, clusters:[{endereco, municipio, uf, n_fornecedores, total_pago, empresas:[{cnpj,razao,
     n_obs,total_pago}]}], _nota}

    total_pago (do cluster e de cada empresa) = total recebido do Estado (TODAS as UGs),
    só OBs > 0 — somatório vindo de obs_e_sei(). Rotular assim ao exibir.
    """
    out = {"ok": False, "n_clusters": 0, "clusters": [], "_nota": ""}
    if not os.path.exists(_DB):
        out["_nota"] = "compliance.db ausente."
        return out
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    try:
        grupos = con.execute(
            """SELECT endereco_norm, COUNT(*) n, MAX(endereco) endereco, MAX(municipio) municipio, MAX(uf) uf
               FROM endereco_fornecedor
               WHERE endereco_norm!='' AND length(endereco_norm)>=12
               GROUP BY endereco_norm HAVING n>=? ORDER BY n DESC""", (min_forn,)).fetchall()
        clusters = []
        for g in grupos:
            membros = con.execute(
                "SELECT cnpj, razao FROM endereco_fornecedor WHERE endereco_norm=?", (g["endereco_norm"],)).fetchall()
            empresas, total_pago, n_com_obs = [], 0.0, 0
            for m in membros:
                os_ = obs_e_sei(m["cnpj"])
                if os_["total_pago"] > 0 or os_["n_obs"] > 0:
                    n_com_obs += 1
                total_pago += os_["total_pago"]
                empresas.append({"cnpj": m["cnpj"], "razao": m["razao"] or "",
                                 "n_obs": os_["n_obs"], "total_pago": os_["total_pago"]})
            if so_com_obs and n_com_obs < min_forn:
                continue  # só interessa quando ≥min_forn co-localizados de fato recebem do Estado
            empresas.sort(key=lambda x: -x["total_pago"])
            clusters.append({"endereco": g["endereco"], "municipio": g["municipio"] or "", "uf": g["uf"] or "",
                             "n_fornecedores": len(empresas), "n_com_obs": n_com_obs,
                             "total_pago": total_pago, "empresas": empresas})
    finally:
        con.close()
    clusters.sort(key=lambda c: (-c["total_pago"], -c["n_fornecedores"]))
    out["clusters"] = clusters[:limite]
    out["n_clusters"] = len(clusters)
    out["ok"] = bool(clusters)
    if not clusters:
        out["_nota"] = ("Nenhum cluster com fornecedores que recebem OBs na fração ingerida. "
                        "Amplie a base: `rede_societaria --ingerir-top`.")
    return out


# ───────────────────────── concentração geográfica de fornecedores ─────────────────────────

def cidades_de_orgao(ug: str | None = None, anos: list[int] | None = None, limite: int = 20) -> dict:
    """Cidades que concentram os FORNECEDORES de um órgão (ou de todo o Estado, se ug=None).

    Cruza ordens_bancarias (pagamentos) com endereco_fornecedor (cidade-sede do CNPJ). É um red flag
    clássico quando muitos fornecedores de uma UG têm sede na MESMA cidade pequena/distante (empresas
    de fachada / direcionamento). Honesto sobre COBERTURA: só ranqueia o que tem endereço ingerido.

    {ok, ug, cobertura_valor (0..1), cobertura_forn (0..1), total_pago, cidades:[{cidade, uf, total_pago,
     n_fornecedores, n_obs, pct}], _nota}
    """
    out = {"ok": False, "ug": ug, "cobertura_valor": 0.0, "cobertura_forn": 0.0,
           "total_pago": 0.0, "cidades": [], "_nota": ""}
    if not os.path.exists(_DB):
        out["_nota"] = "compliance.db ausente."
        return out
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    try:
        filtro, params = "WHERE ob.favorecido_cpf IS NOT NULL AND length(ob.favorecido_cpf)=14", []
        if ug:
            filtro += " AND ob.ug_codigo=?"
            params.append(str(ug))
        if anos:
            filtro += " AND ob.exercicio IN (%s)" % ",".join("?" * len(anos))
            params += [str(a) for a in anos]

        # universo: total pago e nº de fornecedores do órgão (denominador da cobertura)
        tot = con.execute(
            f"SELECT COALESCE(SUM(ob.valor),0), COUNT(DISTINCT ob.favorecido_cpf) "
            f"FROM ordens_bancarias ob {filtro}", params).fetchone()
        total_pago, total_forn = float(tot[0] or 0.0), int(tot[1] or 0)
        if total_pago <= 0 and total_forn == 0:
            out["_nota"] = "Nenhuma OB para este filtro."
            con.close(); return out

        # agregação por cidade, só para CNPJs com endereço ingerido
        rows = con.execute(
            f"""SELECT ef.municipio AS municipio, ef.uf AS uf,
                       SUM(ob.valor) AS total_pago,
                       COUNT(DISTINCT ob.favorecido_cpf) AS n_forn,
                       COUNT(*) AS n_obs
                FROM ordens_bancarias ob
                JOIN endereco_fornecedor ef ON ef.cnpj = ob.favorecido_cpf
                {filtro} AND length(ob.favorecido_cpf)=14 AND length(ef.cnpj)=14
                  AND ef.municipio IS NOT NULL AND ef.municipio!=''
                GROUP BY ef.municipio, ef.uf
                ORDER BY total_pago DESC""", params).fetchall()
    finally:
        con.close()

    pago_conhecido = sum(float(r["total_pago"] or 0) for r in rows)
    forn_conhecido = sum(int(r["n_forn"] or 0) for r in rows)
    out["total_pago"] = total_pago
    out["cobertura_valor"] = round(pago_conhecido / total_pago, 3) if total_pago else 0.0
    out["cobertura_forn"] = round(forn_conhecido / total_forn, 3) if total_forn else 0.0
    base = pago_conhecido or 1.0
    out["cidades"] = [{
        "cidade": r["municipio"], "uf": r["uf"] or "", "total_pago": float(r["total_pago"] or 0),
        "n_fornecedores": int(r["n_forn"] or 0), "n_obs": int(r["n_obs"] or 0),
        "pct": round(float(r["total_pago"] or 0) / base * 100, 1),
    } for r in rows[:limite]]
    out["ok"] = bool(out["cidades"])
    if out["cobertura_valor"] < 0.5:
        out["_nota"] = (f"Cobertura parcial: só {out['cobertura_valor']*100:.0f}% do valor pago tem endereço "
                        "ingerido. Rode `rede_societaria --ingerir-top` p/ ampliar.")
    return out


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Cruzamento sócio×OB×SEI×endereço + descobertas")
    ap.add_argument("cnpj", nargs="?", help="CNPJ p/ cruzamento individual")
    ap.add_argument("--clusters", action="store_true", help="varre a base: grupos de fornecedores na mesma sede")
    ap.add_argument("--orgao", metavar="UG", help="concentração geográfica dos fornecedores de uma UG")
    ap.add_argument("--limite", type=int, default=30)
    a = ap.parse_args()
    if a.clusters:
        r = clusters_mesmo_endereco(limite=a.limite)
        print(f"Clusters de mesma sede (com OBs): {r['n_clusters']}\n")
        for c in r["clusters"]:
            print(f"• {c['n_fornecedores']} forn. ({c['n_com_obs']} c/ OB) · R$ {c['total_pago']:,.2f} · "
                  f"{c['municipio']}/{c['uf']} · {c['endereco'][:60]}")
            for e in c["empresas"][:6]:
                print(f"    - {e['cnpj']} {(e['razao'] or '')[:42]} · {e['n_obs']} OBs · R$ {e['total_pago']:,.2f}")
        if r["_nota"]:
            print("\n" + r["_nota"])
    elif a.orgao:
        print(json.dumps(cidades_de_orgao(ug=a.orgao, limite=a.limite), ensure_ascii=False, indent=2))
    elif a.cnpj:
        print(json.dumps(cruzar(a.cnpj), ensure_ascii=False, indent=2))
    else:
        ap.error("informe um CNPJ, ou --clusters, ou --orgao UG")
