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
    """
    cnpj = _so_digitos(cnpj)
    out = {"n_obs": 0, "total_pago": 0.0, "sei_processos": [], "n_sei": 0}
    if not os.path.exists(_DB):
        return out
    con = sqlite3.connect(_DB)
    try:
        row = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(valor),0) FROM ordens_bancarias WHERE favorecido_cpf=?",
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


# ───────────────────────── cruzamento principal ─────────────────────────

async def cruzar_async(cnpj: str) -> dict:
    """Monta o cruzamento sócio × OB × SEI × endereço para um CNPJ. Ver docstring do módulo."""
    from compliance_agent import rede_societaria as rs

    cnpj = _so_digitos(cnpj)
    out = {
        "cnpj": cnpj, "tem_rede": False, "socios": [], "relacionados": [],
        "endereco": {}, "obs_sei": obs_e_sei(cnpj), "indicios": [], "_nota": "",
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
                {filtro} AND ef.municipio IS NOT NULL AND ef.municipio!=''
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
    import argparse, json
    ap = argparse.ArgumentParser(description="Cruzamento sócio×OB×SEI×endereço")
    ap.add_argument("cnpj")
    a = ap.parse_args()
    print(json.dumps(cruzar(a.cnpj), ensure_ascii=False, indent=2))
