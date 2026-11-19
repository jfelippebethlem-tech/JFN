# -*- coding: utf-8 -*-
"""ISS declarado RETIDO na NFS-e e não retido no pagamento — padrão (docs/PADROES-DE-IRREGULARIDADE.md).

ORIGEM (18/11/2026, perícia por agente): FAETEC × Scalle Construções (Grupo Nolasco), SEI-260005/007167/2024 —
NFS-e de Magé 1001711 diz "VALOR ISS RETIDO: R$ 128.111,34" e "ISSQN RETIDO Sim"; a NL só retém o IRRF. Mesmo
fornecedor em 260005/012007/2025 (NFS-e 1002673, R$ 151.660,53). O layout de Magé não era lido pelo
`compliance_agent/detector_iss_retido.py` — o extrator `_mage` foi acrescentado lá (não há segundo detector).

DOIS SINAIS
  · `nf_x_ob` — a prova do `detector_iss_retido`: W = Σ bruto das NFs − Σ OB paga ao prestador fecha ao centavo
    com as retenções federais declaradas e NÃO com elas + o ISS → o valor do ISS foi pago ao prestador.
    VERIFICADO → forte; PENDENTE (há OB a terceiro no processo/NL ou guia de ISS nos autos) → medio.
  · `retencao_devolvida` — "Ordem Bancária de Retenção" de ISS impressa nos autos com "Status de Envio Erro no
    Pagamento" (em geral com Guia de Devolução) e SEM outra OB de ISS ao mesmo credor da retenção e mesmo valor
    (±R$ 0,01) emitida no mesmo dia ou depois — nem nos autos nem no SIAFE (credor = CNPJ da Prefeitura). O ISS retido
    do prestador voltou ao caixa do Estado e não chegou ao Município. Controle positivo: INEA × Lytoranea,
    SEI-070002/019996/2025, OB 2026OB02539 R$ 1.021.316,75 (Belford Roxo), GD 2026GD00114.
    POR QUE LÊ O SEI E NÃO O SIAFE: medido em 18/11/2026, a OB de retenção (TIPO 13, extra-orçamentária) NÃO está em
    `ob_orcamentaria_siafe` — 2026OB02539/243200 não existe lá; as 1.879 OB "Erro no Pagamento" a municípios da tabela
    são repasses orçamentários, não ISS. Grau medio; fraco se o erro tem menos de 30 dias.

HIPÓTESES INOCENTES: ver o docstring do detector (regime por NF, federais não retidas, OB separada ao Município,
arredondamento, OCR, órfão). Para `retencao_devolvida`: reemissão com valor somado a outra retenção (não casa por
valor) e reemissão por outra UG — por isso medio, não forte; a GD (`gd_siafe`) parou em 31/08/2026.

Valor pago = Σ OB paga ao PRESTADOR no processo (filtro `_ob_paga`), PISO — a soma por processo está sendo refeita.
Indício para requerer guias e extratos, não acusação.
"""
from __future__ import annotations

import re
from datetime import timedelta

from compliance_agent.padroes import _pagamento_comum as C

ID = "iss_declarado_retido_nao_retido"

JANELA_RECENTE_DIAS = 30
_RE_OB = re.compile(r"\b(20\d{2}OB\d{5})\b")
_RE_TITULO_OB = re.compile(r"ordem\s+banc", re.I)


def achado_nf_x_ob(r: dict) -> dict | None:
    """Registro do `detector_iss_retido` → achado do padrão (ou None)."""
    if r.get("classe") != "ISS_NAO_RETIDO" or r.get("estado") not in ("VERIFICADO", "PENDENTE"):
        return None
    nfs = r.get("nfs") or []
    n0 = nfs[0] if nfs else {}
    pago = round(sum(float(o.get("valor") or 0) for o in r.get("obs") or []), 2) or None
    prova = (f"{n0.get('titulo_sei') or n0.get('documento')} — NFS-e {n0.get('numero')} ({n0.get('formato')}): "
             f"bruto R$ {C.fmt(n0.get('bruto') or 0)}, ISS retido pelo tomador R$ {C.fmt(n0.get('iss') or 0)}"
             f"{f' (+{len(nfs) - 1} NF)' if len(nfs) > 1 else ''}; Σ OB ao prestador R$ {C.fmt(r.get('ob') or 0)} = "
             f"bruto − {'+'.join(r.get('subconjunto_federal') or []) or 'nada'} (sem o ISS)")
    return {"processo": r["processo"], "grau": "forte" if r["estado"] == "VERIFICADO" else "medio",
            "sinal": "nf_x_ob", "credor": r.get("credor"), "nome_credor": r.get("nome_credor"), "ug": r.get("ug"),
            "prova": prova, "valor_pago_ob": pago, "iss_nao_retido": r.get("iss"),
            "obs": [o.get("numero_ob") for o in r.get("obs") or []],
            "porque": (r.get("motivo") or "") + (" · PENDENTE: há OB a terceiro no processo/NL ou guia de ISS nos "
                                                  "autos — conferir se é o ISS" if r["estado"] == "PENDENTE" else ""),
            "fonte": "SEI (NFS-e no manifesto) × SIAFE ob_orcamentaria_siafe (_ob_paga)"}


def ler_ob_retencao(texto: str) -> dict | None:
    """Impressão SIAFE de 'Ordem Bancária de Retenção' → {numero, ug, emissao, valor, tipo, credor_retencao,
    cnpj_retencao, status_envio, gd}. Só OB de retenção (tem 'Tipo de Retenção'); valor = o do cabeçalho."""
    t = texto or ""
    if not re.search(r"Ordem Banc[áa]ria de Reten[çc][ãa]o", t, re.I):
        return None
    mn = _RE_OB.search(t)
    mv = re.search(r"Valor por Extenso.*?\n\s*(" + C.MOEDA + r")\s*\n", t, re.S)
    mt = re.search(r"Tipo de Reten[çc][ãa]o\s*\n\s*([^\n]+)", t)
    if not (mn and mv and mt):
        return None
    me = re.search(re.escape(mn[1]) + r"\s*\n\s*(\d{2}/\d{2}/\d{2,4})", t)
    mu = re.search(r"UG Emitente.*?\n\s*(\d{6})\s*-", t, re.S)
    mc = re.search(r"Credor da Reten[çc][ãa]o\s*\n\s*(\d{14})\s*-\s*([^\n]+)", t) or \
        re.search(r"Credor da Reten[çc][ãa]o\s*\n\s*()([^\n]+)", t)
    ms = re.search(r"Status de\s*\n?\s*Envio\s*\n\s*([^\n]+)", t)
    emissao = None
    if me:
        d, m_, a = me[1].split("/")
        emissao = f"{d}/{m_}/{a if len(a) == 4 else '20' + a}"
    return {"numero": mn[1], "ug": mu[1] if mu else None, "emissao": emissao, "valor": C.num(mv[1]),
            "tipo": mt[1].strip(), "cnpj_retencao": (mc[1] if mc else "") or None,
            "credor_retencao": (mc[2].strip() if mc else ""), "status_envio": ms[1].strip() if ms else None,
            "gd": (re.search(r"\b(20\d{2}GD\d{5})\b", t) or [None, None])[1]}


# Cabeçalho = a linha inteira é o título (sem re.I: "Ordem bancária paga e liberada com sucesso." é o RETORNO do banco,
# no meio da OB, e cortava a Guia de Devolução fora do segmento).
_RE_CABECALHO_OB = re.compile(
    r"^[ \t]*Ordem Banc[áa]ria(?: de Reten[çc][ãa]o| Or[çc]ament[áa]ria| Extra-?or[çc]ament[áa]ria)?[ \t]*$", re.M)


def ler_obs_retencao(texto: str) -> list[dict]:
    """Um documento pode juntar VÁRIAS OB impressas (SEI-040002/001422/2026 doc 1: 8 OB, 7 de retenção) — cada
    cabeçalho "Ordem Bancária …" abre um segmento; a página 2 da mesma OB não repete o cabeçalho."""
    t = texto or ""
    cortes = [m.start() for m in _RE_CABECALHO_OB.finditer(t)] or [0]
    segs = [t[a:b] for a, b in zip(cortes, cortes[1:] + [len(t)])]
    return [o for o in (ler_ob_retencao(sg) for sg in segs) if o]


def _e_iss(ob: dict) -> bool:
    return bool(re.match(r"ISS", ob.get("tipo") or "", re.I))


def _mesmo_credor(a: dict, b: dict) -> bool:
    if a.get("cnpj_retencao") and b.get("cnpj_retencao"):
        return a["cnpj_retencao"] == b["cnpj_retencao"]
    return C.norm(a.get("credor_retencao")) == C.norm(b.get("credor_retencao"))


def reemitida(ob: dict, outras: list[dict]) -> dict | None:
    """OB de retenção do MESMO tipo, ao mesmo credor da retenção, mesmo valor (±0,01), número diferente, não devolvida,
    emitida no mesmo dia ou depois. `outras` = OB dos autos (SEI) e/ou OB pagas do SIAFE já no mesmo formato."""
    d0 = C.data_br(ob.get("emissao"))
    for p in outras:
        if p.get("numero") == ob.get("numero") or (p.get("status_envio") or "").lower().startswith("erro"):
            continue
        if p.get("tipo") and not _e_iss(p):
            continue
        if _mesmo_credor(ob, p) and abs(float(p.get("valor") or 0) - float(ob.get("valor") or 0)) <= 0.01:
            dp = C.data_br(p.get("emissao"))
            if d0 is None or dp is None or dp >= d0:
                return p
    return None


def achado_devolvida(proc: str, ob: dict, reemissao: dict | None, doc: str, pago=None, ultima=None) -> dict | None:
    """OB de retenção de ISS devolvida ('Erro no Pagamento') sem reemissão → achado medio (fraco se recente)."""
    if reemissao is not None or not _e_iss(ob) or not (ob.get("status_envio") or "").lower().startswith("erro"):
        return None
    d0 = C.data_br(ob.get("emissao"))
    recente = bool(d0 and ultima and (ultima - d0) < timedelta(days=JANELA_RECENTE_DIAS))
    return {"processo": proc, "grau": "fraco" if recente else "medio", "sinal": "retencao_devolvida",
            "credor": ob.get("cnpj_retencao"), "nome_credor": ob.get("credor_retencao"), "ug": ob.get("ug"),
            "prova": (f"{doc} — Ordem Bancária de Retenção {ob['numero']} ({ob.get('emissao')}), Tipo de Retenção "
                      f"{ob.get('tipo')}, Credor da Retenção {ob.get('credor_retencao')}, R$ {C.fmt(ob['valor'])}: "
                      f"\"Status de Envio Erro no Pagamento\""
                      + (f", Guia de Devolução {ob['gd']}" if ob.get("gd") else "")
                      + "; nenhuma OB de ISS ao mesmo credor e valor emitida depois (autos nem SIAFE)"),
            "valor_pago_ob": pago, "valor_retencao_devolvida": round(float(ob["valor"]), 2),
            "porque": ("o ISS retido do prestador voltou ao caixa do Estado; a reemissão pode ter saído somada a outra "
                       "guia, por outro processo ou depois da última peça capturada"
                       + (" — erro com menos de 30 dias da data da coleta" if recente else "")),
            "fonte": "SEI (impressão SIAFE da OB de retenção) + ob_orcamentaria_siafe (_ob_paga, credor)"}


def _obs_sei(pasta, man) -> list[tuple[dict, str]]:
    out, vistos = [], set()
    for d in C.docs(man):
        if not _RE_TITULO_OB.search(str(d.get("titulo") or "")):
            continue
        for ob in ler_obs_retencao(C.ler(pasta, man, d)):
            if (ob["numero"], ob["ug"]) not in vistos:
                vistos.add((ob["numero"], ob["ug"]))
                out.append((ob, C.numero_doc(d)))
    return out


def _siafe_como_retencao(con, cnpj: str, ug: str | None) -> list[dict]:
    from compliance_agent.cruzamentos_intel import _ob_paga
    q = (f"SELECT numero_ob, ug_emitente, data_emissao, valor FROM ob_orcamentaria_siafe WHERE credor=? "
         f"AND {_ob_paga(con)}" + (" AND ug_emitente=?" if ug else ""))
    return [{"numero": r[0], "ug": r[1], "emissao": r[2], "valor": r[3], "cnpj_retencao": cnpj, "tipo": ""}
            for r in con.execute(q, (cnpj, ug) if ug else (cnpj,))]


def devolvidas(pastas_: list, con, hoje=None) -> tuple[list[dict], dict]:
    """Varre as OB de retenção impressas nos autos (título 'Ordem Bancária')."""
    from datetime import date
    hoje = hoje or date.today()
    out, cob = [], {"ob_retencao_lidas": 0, "ob_retencao_iss_devolvidas": 0}
    for pasta in pastas_:
        man = C.manifesto(pasta)
        if not man:
            continue
        obs = _obs_sei(pasta, man)
        cob["ob_retencao_lidas"] += len(obs)
        proc = C.processo(pasta.name)
        for ob, doc in obs:
            if not (_e_iss(ob) and (ob.get("status_envio") or "").lower().startswith("erro")):
                continue
            cob["ob_retencao_iss_devolvidas"] += 1
            outras = [o for o, _ in obs]
            if reemitida(ob, outras) is None and ob.get("cnpj_retencao"):
                outras += _siafe_como_retencao(con, ob["cnpj_retencao"], ob.get("ug"))
            pago = C.pago(C.obs_pagas(con, [proc]).get(proc, []))
            a = achado_devolvida(proc, ob, reemitida(ob, outras), doc, pago, hoje)
            if a:
                out.append(a)
    return out, cob


def varrer(limite: int | None = None) -> dict:
    from compliance_agent import detector_iss_retido as D
    r = D.varrer(workers=1, limite=limite)
    achados = [a for a in (achado_nf_x_ob(x) for x in r["registros"]) if a]
    con = C.con_ro()
    try:
        dev, cob_dev = devolvidas(C.pastas()[:limite] if limite else C.pastas(), con)
    finally:
        con.close()
    achados += dev
    cob = {**r["cobertura"], "registros_decididos": len(r["registros"]),
           "indisponiveis": sum(1 for x in r["registros"] if x["classe"] == "INDISPONIVEL"),
           **cob_dev,
           "nota": "valor_pago_ob = Σ OB paga ao prestador no processo (PISO); gd_siafe parada em 31/08/2026"}
    return C.resultado(ID, r["cobertura"].get("processos_com_nf_lida", 0), cob, achados,
                       "detector_iss_retido (NFS-e × OB) + ob_orcamentaria_siafe.status_envio")
