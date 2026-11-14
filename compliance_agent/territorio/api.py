# -*- coding: utf-8 -*-
"""API do território (só leitura de `data/territorio.db`).

    GET /api/territorio/estado?metrica=&periodo=&graus=      mapa: os 92 municípios + baldes + cobertura por grau
    GET /api/territorio/estado/{cod_ibge}?periodo=&graus=    ficha do município (contratos, órgãos, fornecedores,
                                                             por ano e mês, indícios)
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
_NOTA_ALERTAS_ESTADO = ("indício = contrato cujo PAGO (OB do SIAFE) supera o valor registrado, pela perícia contábil da casa; "
                        "é sinal a conferir nos termos aditivos, não acusação. Os demais alertas da casa não têm vínculo territorial")
_NOTA_PAGO_ESTADO = ("pago = OB do SIAFE Contabilizada do mesmo processo SEI ao mesmo CNPJ (ou vinculada pelos autos), sem a OB "
                     "devolvida pelo banco — o mesmo cálculo da perícia contábil; contrato sem vínculo fica INDISPONÍVEL (≠ zero)")
_NOTA_EXECUCAO = ("em execução = fim da vigência (com aditivo de prazo publicado no PNCP) igual ou posterior a hoje e sem termo de "
                  "rescisão; o SIGA/TCE-RJ não publica aditivos — contrato Ativo lá com vigência registrada vencida conta como executado; "
                  "contrato sem fim de vigência na fonte fica fora de \"vigentes\"")
_NOTA_GRAU = {"explicito": "município, distrito, bairro ou CEP escrito no objeto/extrato",
              "unidade": "inferido de unidade de endereço conhecido (compradora de sítio único ou citada no objeto: CNES, ISP-RJ, TSE)",
              "sede": "objeto da própria organização, atribuído ao município da sede do órgão (cadastro de unidades do PNCP) — o grau mais fraco"}
_VERSAO = "12"
_TETO_CONTRATOS = 300


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


def _doc(doc: str | None) -> tuple[str | None, str]:
    """(CNPJ para o dossiê | None, documento para exibir). CPF NUNCA sai inteiro (LGPD): mascarado e sem link."""
    d = "".join(ch for ch in (doc or "") if ch.isdigit())
    if len(d) == 14:
        return d, f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return None, (f"{d[:3]}.***.***-{d[-2:]}" if len(d) == 11 else "")


def _contrato(r: sqlite3.Row, conf_texto: str) -> dict:
    d = {k: r[k] for k in ("contrato_id", "objeto", "orgao", "fornecedor_nome", "valor", "vig_ini", "vig_fim",
                           "status", "pago", "metodo", "confianca", "evidencia", "multi")}
    d["fornecedor_cnpj"], d["fornecedor_doc"] = _doc(r["fornecedor_cnpj"])
    d["pct_pago"] = (r["pago"] / r["valor"]) if r["pago"] is not None and r["valor"] else None
    if d["metodo"] == "texto" and conf_texto == "baixa":
        d["confianca"] = "baixa"
    d["multi"] = bool(d["multi"])
    cols = r.keys()
    for k in ("fonte", "grau", "situacao_fonte", "data_assinatura", "processo", "n_obs", "pago_motivo", "alerta"):
        if k in cols:
            d[k] = r[k]
    if d.get("objeto") and len(d["objeto"]) > 600:
        d["objeto"] = d["objeto"][:600].rstrip() + "…"
    return d


def _versao_ok(c) -> bool:
    return base.meta(c, "estado_versao") == _VERSAO


def _desatualizado() -> JSONResponse:
    return JSONResponse({"erro": "territorio.db é de versão anterior do motor — rode "
                                 "`python -m compliance_agent.territorio.cli --full --so estado`"}, status_code=503)


def _graus(graus: str | None) -> tuple[str, ...]:
    return agrega.graus_validos((graus or "").split(","))


def _serie(linhas: list[sqlite3.Row]) -> dict:
    """POR ANO E MÊS. Contratado = pelo mês da ASSINATURA (na falta, início da vigência); pago = pelo mês da OB.
    O que não tem data (ou tem pago sem série mensal) é contado à parte — nunca espalhado."""
    anos: dict[str, dict] = {}
    sem_data = {"n": 0, "valor": 0.0}
    pago_sem_serie = {"n": 0, "valor": 0.0}

    def mes(am: str) -> dict:
        a = anos.setdefault(am[:4], {"ano": am[:4], "n": 0, "valor": 0.0, "pago": 0.0, "meses": {}})
        return a["meses"].setdefault(am, {"mes": am, "n": 0, "valor": 0.0, "pago": 0.0})

    for r in linhas:
        dt = (r["data_assinatura"] or r["vig_ini"] or "")[:7]
        if len(dt) == 7 and dt[:4].isdigit() and "1990" <= dt[:4] <= "2100":
            m = mes(dt)
            m["n"] += 1
            m["valor"] += r["valor"] or 0
        else:
            sem_data["n"] += 1
            sem_data["valor"] += r["valor"] or 0
        if r["pago"] is not None:
            if r["pago_mensal_json"]:
                for am, v in json.loads(r["pago_mensal_json"]).items():
                    mes(am)["pago"] += v
            else:
                pago_sem_serie["n"] += 1
                pago_sem_serie["valor"] += r["pago"]
    out = []
    for a in sorted(anos.values(), key=lambda x: x["ano"], reverse=True):
        ms = sorted(a["meses"].values(), key=lambda x: x["mes"])
        for m in ms:
            m["valor"], m["pago"] = round(m["valor"], 2), round(m["pago"], 2)
        a.update(n=sum(m["n"] for m in ms), valor=round(sum(m["valor"] for m in ms), 2), pago=round(sum(m["pago"] for m in ms), 2), meses=ms)
        out.append(a)
    return {"anos": out, "sem_data": sem_data, "pago_sem_serie_mensal": pago_sem_serie,
            "criterio": "contratado pelo mês da assinatura (na falta, início da vigência); pago pelo mês da OB do SIAFE"}


def _ficha_estado(c, cod_ibge: str, periodo: str, graus: tuple[str, ...], conf_texto: str) -> dict:
    """Ficha do município: tudo sai da MESMA lista de contratos (uma leitura), para os totais fecharem entre si."""
    w = agrega.PERIODOS[periodo]
    todos = c.execute(f"SELECT * FROM territorio_contrato_estado WHERE cod_ibge=? AND multi=0 AND {w}", (cod_ibge,)).fetchall()
    linhas = [r for r in todos if (r["grau"] or "explicito") in graus]
    com_pago = [r for r in linhas if r["pago"] is not None]
    vp = sum(r["valor"] or 0 for r in com_pago)
    pago = round(sum(r["pago"] for r in com_pago), 2) if com_pago else None
    k = {"n_contratos": len(linhas), "n_em_execucao": sum(r["status"] == "em_execucao" for r in linhas),
         "n_executados": sum(r["status"] == "executado" for r in linhas), "n_rescindidos": sum(r["status"] == "rescindido" for r in linhas),
         "n_sem_vigencia": sum(r["status"] == "sem_vigencia" for r in linhas),
         "valor_contratado": round(sum(r["valor"] or 0 for r in linhas), 2),
         "valor_em_execucao": round(sum(r["valor"] or 0 for r in linhas if r["status"] == "em_execucao"), 2),
         "pago": pago, "n_com_pago": len(com_pago), "pct_executado": (pago / vp) if pago is not None and vp else None,
         "n_alertas": sum(1 for r in linhas if r["alerta"])}

    def grupo(chave, rotulo) -> list[dict]:
        g: dict[str, dict] = {}
        for r in linhas:
            o = g.setdefault(chave(r), {**rotulo(r), "n": 0, "valor": 0.0, "pago": None, "n_com_pago": 0})
            o["n"] += 1
            o["valor"] += r["valor"] or 0
            if r["pago"] is not None:
                o["pago"] = (o["pago"] or 0.0) + r["pago"]
                o["n_com_pago"] += 1
        return sorted(g.values(), key=lambda x: -x["valor"])

    # o mesmo órgão chega com grafias diferentes de cada fonte: soma pelo nome-base normalizado, mostra a grafia com sigla
    orgaos = grupo(lambda r: norm(atribui_estado.unidade_base(r["orgao"]))[:34], lambda r: {"orgao": r["orgao"]})

    def forn(r):
        cnpj, doc = _doc(r["fornecedor_cnpj"])
        return {"cnpj": cnpj, "doc": doc, "nome": r["fornecedor_nome"]}
    fornecedores = grupo(lambda r: r["fornecedor_cnpj"] or norm(r["fornecedor_nome"]), forn)
    ordenados = sorted(linhas, key=lambda r: (r["status"] != "em_execucao", -(r["valor"] or 0)))
    por_grau = [{"grau": g, "nota": _NOTA_GRAU[g], "n": sum(1 for r in todos if (r["grau"] or "explicito") == g),
                 "valor": round(sum(r["valor"] or 0 for r in todos if (r["grau"] or "explicito") == g), 2), "incluido": g in graus}
                for g in agrega.GRAUS]
    alertas = [{"contrato_id": r["contrato_id"], "texto": r["alerta"], "orgao": r["orgao"], "fornecedor_nome": r["fornecedor_nome"],
                "valor": r["valor"], "pago": r["pago"]} for r in sorted(linhas, key=lambda r: -(r["pago"] or 0)) if r["alerta"]]
    return {"kpis": k, "por_grau": por_grau, "orgaos": orgaos[:15], "n_orgaos": len(orgaos), "fornecedores": fornecedores[:15],
            "n_fornecedores": len(fornecedores), "contratos": [_contrato(r, conf_texto) for r in ordenados[:_TETO_CONTRATOS]],
            "n_contratos_total": len(linhas), "serie": _serie(linhas), "alertas": alertas, "nota_alertas": _NOTA_ALERTAS_ESTADO}


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
def territorio_estado(request: Request, metrica: str = Query("valor_contratado"), periodo: str = Query("vigentes"),
                      graus: str = Query("explicito,unidade")):
    c = _abrir()
    if c is None:
        return _indisponivel()
    try:
        if not _versao_ok(c):
            return _desatualizado()
        p, g = _periodo(periodo), _graus(graus)
        num = lambda chave: int(float(base.meta(c, chave, "0") or 0))  # noqa: E731
        return _responder(request, {
            "fonte": atribui_estado.FONTE, "atualizado_em": base.meta(c, "atualizado_em"), "periodo": p, "graus": list(g),
            "metrica": metrica if metrica in _METRICAS else "valor_contratado", "municipios": agrega.por_municipio(c, p, g),
            "baldes": agrega.baldes_estado(c, p), "confianca_texto": _conf_texto(c), "nota_pago": _NOTA_PAGO_ESTADO,
            "pago_apurado_em": base.meta(c, "estado_pago_em"), "nota_execucao": _NOTA_EXECUCAO, "nota_grau": _NOTA_GRAU,
            "nota_alertas": _NOTA_ALERTAS_ESTADO,
            "fora_do_escopo": {"unidade_municipal": num("estado_fora_municipal"), "fora_do_executivo": num("estado_fora_outro"),
                               "siga_cancelado": num("estado_siga_cancelado"), "siga_em_elaboracao": num("estado_siga_rascunho"),
                               "siga_repeticoes": num("estado_siga_repetidos")},
            "possivel_duplicidade": {"n": num("estado_possivel_duplicidade_n"),
                                     "valor": float(base.meta(c, "estado_possivel_duplicidade_valor", "0") or 0)}})
    finally:
        c.close()


@router.get("/api/territorio/estado/{cod_ibge}")
def territorio_municipio(request: Request, cod_ibge: str, periodo: str = Query("vigentes"), graus: str = Query("explicito,unidade")):
    nome = nome_municipio().get(cod_ibge)
    if not nome:
        return JSONResponse({"erro": "município desconhecido (código IBGE de 7 dígitos do RJ)"}, status_code=404)
    c = _abrir()
    if c is None:
        return _indisponivel()
    try:
        if not _versao_ok(c):
            return _desatualizado()
        p, ct, g = _periodo(periodo), _conf_texto(c), _graus(graus)
        f = _ficha_estado(c, cod_ibge, p, g, ct)
        multi = [_contrato(r, ct) for r in c.execute(
            f"SELECT * FROM territorio_contrato_estado WHERE multi=1 AND municipios_json LIKE ? AND {agrega.PERIODOS[p]} "
            "ORDER BY valor DESC LIMIT 50", (f'%"{cod_ibge}"%',))]
        f["kpis"]["n_multi"] = len(multi)
        f["contratos"] += multi
        f.update(fonte=atribui_estado.FONTE, atualizado_em=base.meta(c, "atualizado_em"), cod_ibge=cod_ibge, nome=nome,
                 periodo=p, graus=list(g), nota_pago=_NOTA_PAGO_ESTADO, nota_execucao=_NOTA_EXECUCAO,
                 pago_apurado_em=base.meta(c, "estado_pago_em"))
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
        if not _versao_ok(c):
            return _desatualizado()
        return _responder(request, {"fonte": "data/territorio.db", "atualizado_em": base.meta(c, "atualizado_em"), "periodo": p,
                                    "estado": agrega.baldes_estado(c, p), "pcrj": agrega.baldes_pcrj(c, p)})
    finally:
        c.close()
