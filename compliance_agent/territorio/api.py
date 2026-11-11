# -*- coding: utf-8 -*-
"""API do território (só leitura de `data/territorio.db`).

    GET /api/territorio/estado?metrica=&periodo=      mapa: os 92 municípios + baldes
    GET /api/territorio/estado/{cod_ibge}?periodo=    ficha do município
    GET /api/territorio/pcrj?periodo=                 mapa: as 5 APs + baldes
    GET /api/territorio/pcrj/{ap}?periodo=            ficha da AP
    GET /api/territorio/baldes                        sem município / multimunicípio / região / sem AP

Toda resposta traz `fonte` e `atualizado_em`, com `ETag` e `Cache-Control: max-age=600`. A
autenticação é a do painel (middleware `_auth_jfn` do `server.py`): router novo não precisa de
`Depends`. Motor nunca rodado → 503 com o motivo (a tela escreve INDISPONÍVEL, nunca zero).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from compliance_agent.territorio import agrega, atribui_estado, atribui_pcrj, base
from compliance_agent.territorio.geo import nome_municipio, norm, ras_por_ap

router = APIRouter()
_PERIODOS = tuple(agrega.PERIODOS)
_METRICAS = ("valor_contratado", "valor_em_execucao", "pago", "n_contratos", "n_alertas")
_NOTA_ALERTAS = "INDISPONÍVEL — os alertas da casa não têm vínculo territorial (só 275 de 62 mil têm empresa vinculada)"
_NOTA_PAGO_ESTADO = ("pago = OBs do SIAFE (status Contabilizado) do mesmo processo SEI ao mesmo CNPJ; contrato sem vínculo "
                     "fica sem valor (INDISPONÍVEL)")


def _responder(request: Request, corpo: dict, status: int = 200) -> Response:
    txt = json.dumps(corpo, ensure_ascii=False, separators=(",", ":"))
    etag = '"' + hashlib.sha1(txt.encode("utf-8")).hexdigest()[:20] + '"'
    cab = {"ETag": etag, "Cache-Control": "private, max-age=600"}
    if status == 200 and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=cab)
    return Response(content=txt, status_code=status, media_type="application/json", headers=cab if status == 200 else None)


def _abrir():
    try:
        c = base.abrir()
        c.execute("SELECT 1 FROM territorio_contrato_estado LIMIT 1")
        return c
    except sqlite3.OperationalError:
        return None


def _indisponivel() -> JSONResponse:
    return JSONResponse({"erro": "territorio.db ausente — rode `python -m compliance_agent.territorio.cli --full`"}, status_code=503)


def _periodo(p: str | None) -> str:
    return p if p in _PERIODOS else "vigentes"


def _conf_texto(c) -> str:
    return base.meta(c, "confianca_texto", "media") or "media"


def _contrato(r: sqlite3.Row, conf_texto: str) -> dict:
    d = {k: r[k] for k in ("contrato_id", "objeto", "orgao", "fornecedor_cnpj", "fornecedor_nome", "valor", "vig_ini", "vig_fim",
                           "status", "pago", "metodo", "confianca", "evidencia", "multi")}
    d["pct_pago"] = (r["pago"] / r["valor"]) if r["pago"] is not None and r["valor"] else None
    if d["metodo"] == "texto" and conf_texto == "baixa":
        d["confianca"] = "baixa"
    d["multi"] = bool(d["multi"])
    return d


def _ficha(c, tabela: str, onde: str, args: tuple, periodo: str, conf_texto: str) -> dict:
    w = f"{onde} AND {agrega.PERIODOS[periodo]}"
    k = dict(c.execute(f"SELECT {agrega._COLS} FROM {tabela} WHERE multi=0 AND {w}", args).fetchone())
    vp = k.pop("valor_com_pago", None)
    k["pct_executado"] = (k["pago"] / vp) if k.get("pago") is not None and vp else None
    for z in ("n_contratos", "n_em_execucao", "n_executados", "n_rescindidos", "n_com_pago"):
        k[z] = k[z] or 0
    # o mesmo órgão chega com grafias diferentes de cada fonte ("Univ Est do Norte Fluminense Darcy Rib" no PNCP,
    # "UNIV EST DO NORTE FLUMINENSE DARCY RIBEIRO" no SIGA): soma pelo nome normalizado, mostra a 1ª grafia
    por_orgao: dict[str, dict] = {}
    for r in c.execute(f"SELECT orgao, COUNT(*) n, COALESCE(SUM(valor),0) valor FROM {tabela} WHERE multi=0 AND {w} GROUP BY orgao ORDER BY valor DESC", args):
        o = por_orgao.setdefault(norm(r["orgao"])[:34], {"orgao": r["orgao"], "n": 0, "valor": 0.0})
        o["n"] += r["n"]
        o["valor"] += r["valor"]
    orgaos = sorted(por_orgao.values(), key=lambda x: -x["valor"])[:10]
    forn = [dict(r) for r in c.execute(
        f"SELECT fornecedor_cnpj cnpj, MAX(fornecedor_nome) nome, COUNT(*) n, COALESCE(SUM(valor),0) valor FROM {tabela} "
        f"WHERE multi=0 AND {w} GROUP BY fornecedor_cnpj ORDER BY valor DESC LIMIT 10", args)]
    ctr = [_contrato(r, conf_texto) for r in c.execute(
        f"SELECT * FROM {tabela} WHERE multi=0 AND {w} ORDER BY (status='em_execucao') DESC, valor DESC LIMIT 200", args)]
    return {"kpis": k, "orgaos": orgaos, "fornecedores": forn, "contratos": ctr, "n_contratos_total": k["n_contratos"],
            "alertas": None, "nota_alertas": _NOTA_ALERTAS}


@router.get("/api/territorio/estado")
def territorio_estado(request: Request, metrica: str = Query("valor_contratado"), periodo: str = Query("vigentes")):
    c = _abrir()
    if c is None:
        return _indisponivel()
    try:
        p = _periodo(periodo)
        return _responder(request, {
            "fonte": atribui_estado.FONTE, "atualizado_em": base.meta(c, "atualizado_em"), "periodo": p,
            "metrica": metrica if metrica in _METRICAS else "valor_contratado", "municipios": agrega.por_municipio(c, p),
            "baldes": agrega.baldes_estado(c, p), "confianca_texto": _conf_texto(c), "nota_pago": _NOTA_PAGO_ESTADO,
            "nota_alertas": _NOTA_ALERTAS,
            "fora_do_escopo": {"unidade_municipal": int(base.meta(c, "estado_fora_municipal", "0") or 0),
                               "fora_do_executivo": int(base.meta(c, "estado_fora_outro", "0") or 0)}})
    finally:
        c.close()


@router.get("/api/territorio/estado/{cod_ibge}")
def territorio_municipio(request: Request, cod_ibge: str, periodo: str = Query("vigentes")):
    nome = nome_municipio().get(cod_ibge)
    if not nome:
        return JSONResponse({"erro": "município desconhecido (código IBGE de 7 dígitos do RJ)"}, status_code=404)
    c = _abrir()
    if c is None:
        return _indisponivel()
    try:
        p, ct = _periodo(periodo), _conf_texto(c)
        f = _ficha(c, "territorio_contrato_estado", "cod_ibge=?", (cod_ibge,), p, ct)
        multi = [_contrato(r, ct) for r in c.execute(
            f"SELECT * FROM territorio_contrato_estado WHERE multi=1 AND municipios_json LIKE ? AND {agrega.PERIODOS[p]} "
            "ORDER BY valor DESC LIMIT 50", (f'%"{cod_ibge}"%',))]
        f["kpis"]["n_multi"] = len(multi)
        f["contratos"] += multi
        f.update(fonte=atribui_estado.FONTE, atualizado_em=base.meta(c, "atualizado_em"), cod_ibge=cod_ibge, nome=nome,
                 periodo=p, nota_pago=_NOTA_PAGO_ESTADO)
        return _responder(request, f)
    finally:
        c.close()


@router.get("/api/territorio/pcrj")
def territorio_pcrj(request: Request, periodo: str = Query("vigentes")):
    c = _abrir()
    if c is None:
        return _indisponivel()
    try:
        p = _periodo(periodo)
        return _responder(request, {"fonte": atribui_pcrj.FONTE, "atualizado_em": base.meta(c, "atualizado_em"), "periodo": p,
                                    "aps": agrega.por_ap(c, p), "baldes": agrega.baldes_pcrj(c, p),
                                    "confianca_texto": _conf_texto(c), "nota_alertas": _NOTA_ALERTAS})
    finally:
        c.close()


@router.get("/api/territorio/pcrj/{ap}")
def territorio_ap(request: Request, ap: int, periodo: str = Query("vigentes")):
    ras = ras_por_ap().get(ap)
    if ras is None:
        return JSONResponse({"erro": "AP desconhecida (1 a 5)"}, status_code=404)
    c = _abrir()
    if c is None:
        return _indisponivel()
    try:
        p, ct = _periodo(periodo), _conf_texto(c)
        f = _ficha(c, "territorio_contrato_pcrj", "ap=?", (ap,), p, ct)
        f["kpis"]["n_multi"] = c.execute(
            f"SELECT COUNT(*) FROM territorio_contrato_pcrj, json_each(aps_json) j WHERE multi=1 AND j.value=? AND {agrega.PERIODOS[p]}",
            (ap,)).fetchone()[0]
        f.update(fonte=atribui_pcrj.FONTE, atualizado_em=base.meta(c, "atualizado_em"), ap=ap, nome=f"AP {ap}", ras=ras, periodo=p)
        return _responder(request, f)
    finally:
        c.close()


@router.get("/api/territorio/baldes")
def territorio_baldes(request: Request, periodo: str = Query("tudo")):
    c = _abrir()
    if c is None:
        return _indisponivel()
    try:
        p = _periodo(periodo) if periodo in _PERIODOS else "tudo"
        return _responder(request, {"fonte": "data/territorio.db", "atualizado_em": base.meta(c, "atualizado_em"), "periodo": p,
                                    "estado": agrega.baldes_estado(c, p), "pcrj": agrega.baldes_pcrj(c, p)})
    finally:
        c.close()
