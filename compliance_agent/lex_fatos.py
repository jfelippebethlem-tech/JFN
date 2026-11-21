# -*- coding: utf-8 -*-
"""Lex — BASE ÚNICA DE FATOS do parecer (camada determinística).

POR QUE EXISTE (20/11/2026). O parecer de referência dizia duas coisas ao mesmo tempo: o grau saía 🟢 e
"nenhum indício disparou" enquanto o mérito apontava empresa recém-aberta, capital 432× menor que o
recebido e salto de 3.400% no pago; a linha de cobertura dizia "capital: INDISPONÍVEL" e o mérito usava
o capital; a cadência somava 6 OBs e o teste de redondos falava de 3. A causa era uma só: cada seção
consultava a SUA fonte (o espelho TFE no contexto do /relatorio, o cadastro com chaves diferentes,
linhas com OB de valor zero misturadas às pagas) e tirava a SUA conclusão.

Este módulo é a fonte única. Tudo o que o parecer afirma sobre dinheiro sai de UMA consulta ao SIAFE
(`ob_orcamentaria_siafe`, régua `cruzamentos_intel._ob_paga` — o espelho TFE nunca é "pago"), e tudo o
que afirma sobre o cadastro sai de UM dicionário normalizado. Cada fato carrega a fonte e o estado
(VERIFICADO / PENDENTE / INDISPONÍVEL — `docs/REGRAS-DE-QUALIDADE.md`). INDISPONÍVEL ≠ 0.

Só leitura: abre o banco em modo `ro` e nunca escreve.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections import OrderedDict, defaultdict
from datetime import date

from compliance_agent.collectors.arquivos import caminho_db, dir_dados

logger = logging.getLogger(__name__)

VERIFICADO, PENDENTE, INDISPONIVEL = "VERIFICADO", "PENDENTE", "INDISPONÍVEL"
FONTE_OB = "SIAFE · ob_orcamentaria_siafe (régua _ob_paga)"
FONTE_NE = "SIAFE · ne_siafe (notas de empenho)"
FONTE_NL = "SIAFE · nl_siafe (notas de liquidação)"


def brl(v) -> str:
    """1234567.89 → '1.234.567,89' (milhar e 2 casas, padrão BR)."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v: float, casas: int = 1) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def inteiro(n) -> str:
    return f"{int(n or 0):,}".replace(",", ".")


def iso(d) -> str:
    """'31/12/2025' (texto do SIAFE) ou '2025-12-31…' → '2025-12-31'; '' se não reconhecer."""
    s = str(d or "").strip()
    if len(s) >= 10 and s[2] == "/" and s[5] == "/":
        return f"{s[6:10]}-{s[3:5]}-{s[0:2]}"
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return ""


def processo_canonico(s) -> str:
    """Nº de processo SEI → chave canônica 'UUUUUU/N/AAAA' pela régua da casa (`ob_processo.chave_processo`:
    'SEI-330002/031566/24', 'sei-330002/31566/2024' e '330002/031566/2024' são o MESMO processo); '' se não casar."""
    try:
        from compliance_agent.ob_processo import chave_processo
        return chave_processo(str(s or "")) or ""
    except (ImportError, ValueError, TypeError):  # sem a régua, nenhum processo é reconhecido (declarado como não identificado)
        return ""


def processo_legivel(canon: str) -> str:
    """'330020/406/2025' → 'SEI-330020/000406/2025' (forma do SEI-RJ)."""
    p = canon.split("/")
    return f"SEI-{p[0]}/{int(p[1]):06d}/{p[2]}" if len(p) == 3 and p[1].isdigit() else canon


def _slug_acervo(canon: str) -> str:
    p = canon.split("/")
    return f"{p[0]}_{int(p[1]):06d}_{p[2]}" if len(p) == 3 and p[1].isdigit() else ""


def fato(nome: str, valor: str, fonte: str, estado: str, nota: str = "") -> dict:
    return {"fato": nome, "valor": valor, "fonte": fonte, "estado": estado, "nota": nota}


# ─────────────────────────────── cadastro (uma fonte, chaves normalizadas) ───────────────────────────────

def cadastro(ctx: dict) -> dict:
    """Cadastro do fornecedor NORMALIZADO a partir do enriquecimento do contexto. As chaves variavam
    (`data_entrada` no enriquecimento real, `entrada` no forense; `capital_social` × `capital`;
    `data_abertura` × `abertura`) e cada consumidor lia uma — daí o mesmo capital ser 'INDISPONÍVEL'
    numa seção e R$ 10.000,00 em outra. Aqui sai um dicionário só, com a fonte declarada."""
    emp = ((ctx.get("enriq") or {}).get("dados") or {}).get("empresa") or {}
    fonte = str(ctx.get("fonte_enriq") or (ctx.get("enriq") or {}).get("_fonte") or "").strip()
    fonte = f"Receita Federal · cadastro CNPJ (via {fonte})" if fonte else "Receita Federal · cadastro CNPJ (enriquecimento do contexto)"
    socios = []
    for s in emp.get("socios") or []:
        if not isinstance(s, dict):
            continue
        socios.append({"nome": s.get("nome") or s.get("nome_socio") or "",
                       "qualificacao": s.get("qualificacao") or s.get("qual") or "",
                       "entrada": iso(s.get("data_entrada") or s.get("entrada") or "")})
    cap = emp.get("capital_social", emp.get("capital"))
    try:
        cap = float(cap) if cap not in (None, "") else None
    except (TypeError, ValueError):
        cap = None
    return {"tem": bool(emp), "fonte": fonte,
            "razao_social": emp.get("razao_social") or ctx.get("nome") or "",
            "abertura": iso(emp.get("data_abertura") or emp.get("abertura") or ""),
            "capital": cap, "situacao": (emp.get("situacao") or "").strip(),
            "porte": emp.get("porte") or "", "cnae": emp.get("cnae_principal") or emp.get("atividade") or "",
            "logradouro": emp.get("logradouro") or "", "numero": emp.get("numero") or "",
            "complemento": emp.get("complemento") or "", "bairro": emp.get("bairro") or "",
            "municipio": emp.get("municipio") or "", "uf": emp.get("uf") or "",
            "socios": socios, "_bruto": emp}


def cadastral_para_dd(cad: dict) -> dict | None:
    """Mesmo cadastro, nas chaves que o motor de due diligence (`investigacao_dd.investigar`) lê. None quando
    não há cadastro (o motor então tenta a própria fonte) — nunca um dict inventado."""
    if not cad.get("tem"):
        return None
    bruto = cad.get("_bruto") or {}
    out = dict(bruto)       # o que o cadastro bruto traz (endereço, doc mascarado do sócio) segue intacto
    out.update({k: cad[k] for k in ("razao_social", "abertura", "capital", "situacao", "porte", "cnae", "logradouro",
                                    "numero", "complemento", "bairro", "municipio", "uf")
                if cad.get(k) not in (None, "")})
    brutos = [s for s in bruto.get("socios") or [] if isinstance(s, dict)]
    out["socios"] = [dict(sb, nome=s["nome"], qualificacao=s["qualificacao"], data_entrada=s["entrada"])
                     for sb, s in zip(brutos, cad.get("socios") or [])]
    return out


# ─────────────────────────────── SIAFE: OB, NE, NL (uma consulta por tabela) ───────────────────────────────

def _con():
    return sqlite3.connect(f"file:{caminho_db()}?mode=ro", uri=True, timeout=30)


def _tem_tabela(con, nome: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)).fetchone())


def _motivo_nao_paga(r: dict) -> str:
    st = (r.get("status") or "").strip()
    if st != "Contabilizado":
        return f"status '{st or 'vazio'}'"
    if (r.get("status_envio") or "") == "Erro no Pagamento":
        return "devolvida pelo banco (Erro no Pagamento)"
    if (r.get("tipo_regularizacao") or "") == "Pagamento Complementar":
        return "pagamento complementar (já contido na OB principal)"
    if not (r.get("numero_ob") or ""):
        return "OB sem número"
    return "reemitida (a reemissão é que pagou)"


def base_siafe(*, cnpj: str = "", ug: str = "") -> dict:
    """Lê, de UMA vez, as OBs do SIAFE do alvo (fornecedor por raiz de CNPJ, ou UG emitente) e, para
    fornecedor, as NE e NL do mesmo credor. Devolve a série de OBs PAGAS (régua `_ob_paga`, valor > 0),
    as regularizações de valor zero, as OBs não pagas com o motivo, e a execução da despesa.

    Estado: INDISPONÍVEL se a tabela não existe ou a leitura falhou (nunca zero fabricado)."""
    cnpj = re.sub(r"\D", "", cnpj or "")
    out: dict = {"estado": INDISPONIVEL, "motivo": "", "alvo": cnpj or ug, "tipo": "fornecedor" if cnpj else "orgao",
                 "pagas": [], "regularizacoes": [], "nao_pagas": [], "ne": [], "nl": [],
                 "coletado_em": "", "fonte": FONTE_OB}
    if not cnpj and not ug:
        out["motivo"] = "alvo sem CNPJ e sem UG"
        return out
    try:
        con = _con()
    except sqlite3.Error as exc:
        out["motivo"] = f"banco indisponível ({str(exc)[:80]})"
        return out
    con.row_factory = sqlite3.Row
    try:
        if not _tem_tabela(con, "ob_orcamentaria_siafe"):
            out["motivo"] = "tabela ob_orcamentaria_siafe ausente na base"
            return out
        from compliance_agent.cruzamentos_intel import _ob_paga
        regua = _ob_paga(con)
        if cnpj:
            raiz = cnpj[:8]
            # raiz do CNPJ = matriz + filiais (mesma pessoa jurídica). Intervalo em vez de LIKE: usa o índice.
            filtro, params = "credor >= ? AND credor < ?", (raiz, raiz + "~")
        else:
            filtro, params = "ug_emitente = ?", (str(ug),)
        # traz TODAS as OBs e marca `paga` pela régua _ob_paga (o eixo contábil precisa das não pagas)
        rows = con.execute(  # ob-qualquer-status
            "SELECT numero_ob, ug_emitente, data_emissao, status, status_envio, tipo_regularizacao, nl, processo, "
            f"credor, nome_credor, valor, exercicio, coletado_em, CASE WHEN {regua} THEN 1 ELSE 0 END AS paga "
            f"FROM ob_orcamentaria_siafe WHERE {filtro}", params).fetchall()
        for r in rows:
            d = dict(r)
            d["data"] = iso(d.get("data_emissao"))
            d["valor"] = float(d.get("valor") or 0)
            d["credor"] = re.sub(r"\D", "", str(d.get("credor") or ""))
            if cnpj and d["credor"][:8] != cnpj[:8]:
                continue
            out["coletado_em"] = max(out["coletado_em"], str(d.get("coletado_em") or ""))
            if d["paga"]:
                (out["pagas"] if d["valor"] > 0 else out["regularizacoes"]).append(d)
            else:
                d["motivo"] = _motivo_nao_paga(d)
                out["nao_pagas"].append(d)
        if cnpj:
            raiz = cnpj[:8]
            if _tem_tabela(con, "ne_siafe"):
                out["ne"] = [dict(r) for r in con.execute(
                    "SELECT numero, ug_emitente, exercicio, data_emissao, status, processo, natureza, fonte, valor, "
                    "coletado_em FROM ne_siafe WHERE credor >= ? AND credor < ?", (raiz, raiz + "~"))]
                out["tem_ne"] = True
            if _tem_tabela(con, "nl_siafe"):
                out["nl"] = [dict(r) for r in con.execute(
                    "SELECT numero, ug_emitente, exercicio, data_emissao, status, ne, processo, valor, valor_retido, "
                    "coletado_em FROM nl_siafe WHERE credor >= ? AND credor < ?", (raiz, raiz + "~"))]
                out["tem_nl"] = True
        out["estado"] = VERIFICADO
    except sqlite3.Error as exc:
        out["motivo"] = f"leitura do SIAFE falhou ({str(exc)[:80]})"
        out["estado"] = INDISPONIVEL
    finally:
        con.close()
    out["pagas"].sort(key=lambda d: (d["data"], d.get("numero_ob") or ""))
    for lst in ("ne", "nl"):
        for d in out[lst]:
            d["data"] = iso(d.get("data_emissao"))
            d["valor"] = float(d.get("valor") or 0)
    return out


def _orgao(ug: str) -> str:
    try:
        from compliance_agent import ugs
        return ugs.rotulo(ug, "")
    except (ImportError, KeyError, ValueError, TypeError):  # rótulo é cosmético; o código da UG basta
        return f"UG {ug}"


def pagamentos(base: dict) -> dict:
    """A base SIAFE no formato que os consumidores do Lex já leem (`por_ano.linhas`, `total_geral`,
    `por_orgao_geral`, `hhi`). Só OB PAGA com valor > 0 entra nas linhas: as regularizações de valor zero
    ficam contadas à parte (`n_regularizacoes`) — misturá-las fazia a cadência contar 6 OBs onde o pago
    tinha 3. O ano é o da DATA da OB (o mesmo da sazonalidade), para que o total por ano feche com ela."""
    from compliance_agent.reporting.intel_dados import _hhi
    p: dict = {"tem_dados": False, "anos": [], "total_geral": 0.0, "n_geral": 0, "por_ano": OrderedDict(),
               "por_orgao_geral": {}, "por_favorecido_geral": {}, "hhi": {}, "fonte": FONTE_OB,
               "estado": base.get("estado"), "n_regularizacoes": len(base.get("regularizacoes") or []),
               "coletado_em": base.get("coletado_em", "")}
    if base.get("estado") != VERIFICADO or not base.get("pagas"):
        return p
    por_ano: dict = {}
    org: dict = defaultdict(float)
    fav: dict = defaultdict(float)
    fav_nome: dict = {}
    for d in base["pagas"]:
        ano = int(d["data"][:4]) if d["data"] else int(d.get("exercicio") or 0)
        b = por_ano.setdefault(ano, {"n": 0, "total": 0.0, "linhas": [], "por_orgao": defaultdict(float)})
        o = _orgao(d.get("ug_emitente") or "")
        b["n"] += 1
        b["total"] += d["valor"]
        b["por_orgao"][o] += d["valor"]
        b["linhas"].append({"numero_ob": d.get("numero_ob") or "—", "data": d["data"] or "—", "orgao": o,
                            "ug": d.get("ug_emitente") or "", "valor": d["valor"], "nl": d.get("nl") or "",
                            "processo": d.get("processo") or "", "cnpj": d.get("credor") or "",
                            "favorecido": d.get("nome_credor") or ""})
        org[o] += d["valor"]
        fav[d.get("credor") or d.get("nome_credor") or "—"] += d["valor"]
        fav_nome[d.get("credor") or d.get("nome_credor") or "—"] = d.get("nome_credor") or d.get("credor") or "—"
    for b in por_ano.values():
        b["total"] = round(b["total"], 2)
        b["por_orgao"] = dict(sorted(b["por_orgao"].items(), key=lambda kv: -kv[1]))
    p["por_ano"] = OrderedDict(sorted(por_ano.items()))
    p["anos"] = list(p["por_ano"])
    p["n_geral"] = sum(b["n"] for b in por_ano.values())
    p["total_geral"] = round(sum(d["valor"] for d in base["pagas"]), 2)
    p["total"] = p["total_geral"]
    p["n_obs"] = p["n_geral"]
    p["por_orgao_geral"] = dict(sorted(org.items(), key=lambda kv: -kv[1]))
    p["por_favorecido_geral"] = {fav_nome[k]: v for k, v in sorted(fav.items(), key=lambda kv: -kv[1])}
    p["hhi"] = _hhi(p["por_favorecido_geral"] if base.get("tipo") == "orgao" else p["por_orgao_geral"])
    p["tem_dados"] = True
    return p


# ─────────────────────────────── execução da despesa (NE × NL × OB) ───────────────────────────────

def execucao(base: dict) -> dict:
    """Empenhado × liquidado × pago (Lei 4.320/64, arts. 58-65) e o encadeamento OB → NL → NE.

    Honestidade: a ingestão de NE e NL do SIAFE é PARCIAL (as telas são coletadas por fatia); somar NE e NL
    e comparar com o pago como se a base estivesse completa fabricaria "pago acima do empenhado". Por isso a
    cobertura é medida OB a OB (a NL que a OB cita está na base?) e os totais de NE/NL saem como PISO, PENDENTE."""
    pagas = base.get("pagas") or []
    nl_idx = {(n["numero"], str(n["ug_emitente"])): n for n in base.get("nl") or []}
    ne_idx = {(n["numero"], str(n["ug_emitente"])): n for n in base.get("ne") or []}
    pago = sum(d["valor"] for d in pagas)
    com_nl = [d for d in pagas if (d.get("nl") or "", str(d.get("ug_emitente") or "")) in nl_idx]
    v_com_nl = sum(d["valor"] for d in com_nl)
    ne_cont = [n for n in base.get("ne") or [] if (n.get("status") or "") == "Contabilizado"]
    nl_cont = [n for n in base.get("nl") or [] if (n.get("status") or "") == "Contabilizado"]
    # OB por NL: pago acima do liquidado NA MESMA NL (comparação homogênea: as duas pontas estão na base).
    por_nl: dict = defaultdict(lambda: {"v": 0.0, "obs": [], "datas": []})
    for d in com_nl:
        k = (d["nl"], str(d["ug_emitente"]))
        por_nl[k]["v"] += d["valor"]
        por_nl[k]["obs"].append(d.get("numero_ob") or "")
        por_nl[k]["datas"].append(d["data"])
    acima, antes = [], []
    for k, agg in por_nl.items():
        nl = nl_idx[k]
        if (nl.get("status") or "") == "Contabilizado" and agg["v"] > float(nl.get("valor") or 0) + 0.02:
            acima.append({"nl": k[0], "ug": k[1], "pago": round(agg["v"], 2), "liquidado": float(nl.get("valor") or 0),
                          "obs": agg["obs"]})
        dnl = nl.get("data") or ""
        for ob, dob in zip(agg["obs"], agg["datas"]):
            if dnl and dob and dob < dnl:
                antes.append({"ob": ob, "data_ob": dob, "nl": k[0], "data_nl": dnl, "ug": k[1]})
    return {"pago": round(pago, 2), "n_pagas": len(pagas),
            "empenhado_piso": round(sum(n["valor"] for n in ne_cont), 2), "n_ne": len(ne_cont),
            "liquidado_piso": round(sum(n["valor"] for n in nl_cont), 2), "n_nl": len(nl_cont),
            "retido_piso": round(sum(float(n.get("valor_retido") or 0) for n in nl_cont), 2),
            "ne_anuladas": [n for n in base.get("ne") or [] if (n.get("status") or "") != "Contabilizado"],
            "nl_anuladas": [n for n in base.get("nl") or [] if (n.get("status") or "") != "Contabilizado"],
            "cobertura_nl_valor": (v_com_nl / pago * 100) if pago else 0.0,
            "cobertura_nl_n": (len(com_nl) / len(pagas) * 100) if pagas else 0.0,
            "pago_sem_nl_na_base": round(pago - v_com_nl, 2),
            "pago_acima_da_nl": sorted(acima, key=lambda x: -(x["pago"] - x["liquidado"])),
            "ob_antes_da_nl": antes, "ne_idx": ne_idx, "nl_idx": nl_idx,
            "tem_ne": bool(base.get("tem_ne")), "tem_nl": bool(base.get("tem_nl"))}


def canon_de(chave: str) -> str:
    return chave if _slug_acervo(chave) else ""


def processos(base: dict, exe: dict) -> list[dict]:
    """Processo por processo: NE → NL → OB, com o processo SEI resolvido pela própria cadeia (a OB raramente
    traz o processo; a NE traz). Processo não resolvido fica num balde declarado, nunca some."""
    ne_idx, nl_idx = exe["ne_idx"], exe["nl_idx"]
    grupos: dict = defaultdict(lambda: {"obs": [], "nls": set(), "nes": set(), "ugs": set()})
    for d in base.get("pagas") or []:
        ug = str(d.get("ug_emitente") or "")
        nl = nl_idx.get((d.get("nl") or "", ug))
        ne = ne_idx.get(((nl or {}).get("ne") or "", ug)) if nl else None
        candidatos = [x for x in (d.get("processo"), (nl or {}).get("processo"), (ne or {}).get("processo")) if x]
        canon = next((c for c in map(processo_canonico, candidatos) if c), "")
        bruto = candidatos[0] if candidatos else ""
        chave = canon or (str(bruto).strip() or "(processo não identificado na cadeia OB→NL→NE)")
        g = grupos[chave]
        g["obs"].append(d)
        g["ugs"].add(ug)
        g["bruto"] = bruto
        if nl:
            g["nls"].add((nl["numero"], ug))
        if ne:
            g["nes"].add((ne["numero"], ug))
    out = []
    for chave, g in grupos.items():
        obs = g["obs"]
        nls = [nl_idx[k] for k in g["nls"]]
        nes = [ne_idx[k] for k in g["nes"]]
        datas = sorted(d["data"] for d in obs if d["data"])
        out.append({"processo": processo_legivel(chave) if chave == canon_de(chave) else chave,
                    "canon": chave if chave == canon_de(chave) else "", "ugs": sorted(g["ugs"]),
                    "n_obs": len(obs), "pago": round(sum(d["valor"] for d in obs), 2),
                    "primeira_ob": datas[0] if datas else "", "ultima_ob": datas[-1] if datas else "",
                    "n_nl": len(nls), "liquidado": round(sum(float(n.get("valor") or 0) for n in nls), 2),
                    "primeira_nl": min((n["data"] for n in nls if n.get("data")), default=""),
                    "n_ne": len(nes), "empenhado": round(sum(float(n.get("valor") or 0) for n in nes), 2),
                    "primeira_ne": min((n["data"] for n in nes if n.get("data")), default=""),
                    "naturezas": sorted({str(n.get("natureza") or "") for n in nes if n.get("natureza")})})
    out.sort(key=lambda x: -x["pago"])
    return out


_FASES_ACERVO = (("planejamento", "planejamento (DFD/ETP/TR)"), ("selecao", "seleção (edital/ata/propostas)"),
                 ("contratacao", "contratação (contrato/termo)"), ("execucao", "execução (atesto/medição)"),
                 ("despesa", "despesa (NE/NL/OB e NF)"))


def acervo_processo(canon: str) -> dict:
    """O que o acervo SEI da casa (`data/sei_arquivo`, ARQUIVO primeiro) tem do processo: captura, conferência
    documento a documento e quais fases da contratação estão representadas. Só leitura do manifesto."""
    slug = _slug_acervo(canon)
    if not slug:
        return {"estado": INDISPONIVEL, "motivo": "processo sem número SEI reconhecível"}
    pasta = dir_dados() / "sei_arquivo" / slug
    man = pasta / "manifest.json"
    if not man.exists():
        return {"estado": INDISPONIVEL, "motivo": "processo não capturado no acervo SEI da casa"}
    try:
        m = json.loads(man.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"estado": INDISPONIVEL, "motivo": f"manifesto ilegível ({str(exc)[:60]})"}
    ldt = m.get("linha_do_tempo") or {}
    conf = m.get("conferencia_documentos") or {}
    def _n(v) -> int:   # manifestos antigos gravam a contagem (int); os novos, a lista de documentos
        return len(v) if isinstance(v, (list, tuple)) else int(v) if isinstance(v, (int, float)) else 0
    fases = {k: _n(ldt.get(k)) for k, _ in _FASES_ACERVO} if isinstance(ldt, dict) else {}
    return {"estado": VERIFICADO if m.get("captura_completa") else PENDENTE,
            "n_docs": len(m.get("docs") or []), "captura_completa": bool(m.get("captura_completa")),
            "conferencia": conf, "fases": fases,
            "faltam_fases": [rot for k, rot in _FASES_ACERVO if not fases.get(k)],
            "gerado_em": str(m.get("gerado_em") or "")[:10], "exemplos": {k: list(ldt.get(k))[:2] for k, _ in _FASES_ACERVO
                         if isinstance(ldt, dict) and isinstance(ldt.get(k), (list, tuple))}}


# ─────────────────────────────── padrões da casa que dispararam para o alvo ───────────────────────────────

_EIXO_PADRAO = {"iss_declarado_retido_nao_retido": "contabil", "ob_antes_da_entrega": "contabil",
                "atesto_antes_do_periodo": "contabil", "despesa_sem_previo_empenho": "contabil",
                "compra_fora_do_siafe": "contabil", "retificacao_altera_valor": "contabil"}


def padroes_do_alvo(canons: set[str], cnpj: str) -> dict:
    """Achados dos padrões da casa (`data/padroes/*.json`, gerados pelos detectores de padrão) cujo processo
    pertence ao alvo — casamento pelo nº de processo canônico (ou CNPJ do credor quando o padrão o grava).
    Só leitura dos JSON já materializados; o parecer não roda detector."""
    raiz = dir_dados() / "padroes"
    out = {"estado": INDISPONIVEL, "achados": [], "lidos": [], "motivo": ""}
    if not raiz.exists():
        out["motivo"] = "pasta data/padroes ausente"
        return out
    cnpj = re.sub(r"\D", "", cnpj or "")
    for arq in sorted(raiz.glob("*.json")):
        if arq.name.startswith("_") or arq.stat().st_size > 5_000_000:
            continue
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        pid = str(d.get("id") or arq.stem)
        out["lidos"].append({"id": pid, "gerado_em": str(d.get("gerado_em") or "")[:10],
                             "n_achados": len(d.get("achados") or [])})
        for a in d.get("achados") or []:
            if not isinstance(a, dict):
                continue
            c = processo_canonico(a.get("processo"))
            doc = re.sub(r"\D", "", str(a.get("cnpj") or a.get("credor_cnpj") or ""))
            if (c and c in canons) or (cnpj and len(doc) == 14 and doc[:8] == cnpj[:8]):
                out["achados"].append({"padrao": pid, "eixo": _EIXO_PADRAO.get(pid, "juridico"),
                                       "processo": a.get("processo") or "", "grau": a.get("grau") or "",
                                       "prova": str(a.get("prova") or a.get("evidencia") or "")[:400],
                                       "porque": str(a.get("porque") or "")[:400],
                                       "fonte": str(a.get("fonte") or d.get("fonte") or "")[:200],
                                       "gerado_em": str(d.get("gerado_em") or "")[:10]})
    out["estado"] = VERIFICADO
    return out


# ─────────────────────────────── sinais derivados (viram ACHADO, com régua explícita) ───────────────────────────────

def achados_contabeis(exe: dict) -> list[dict]:
    """Inconsistências de registro que o código prova contra o próprio SIAFE (as duas pontas na base):
    pago acima do liquidado NA MESMA NL e OB emitida antes da NL que ela cita. Valor e documentos citados."""
    ach = []
    acima = exe.get("pago_acima_da_nl") or []
    if acima:
        exc = sum(a["pago"] - a["liquidado"] for a in acima)
        ex = acima[0]
        ach.append({"rf": "C-PAGO>NL", "grav": 3 if exc >= 100_000 else 2, "eixo": "contabil",
                    "obs": f"Em **{len(acima)}** nota(s) de liquidação a soma das OBs pagas que a citam supera o "
                           f"valor liquidado — excedente de **R$ {brl(exc)}** (maior: {ex['nl']} da UG {ex['ug']}, "
                           f"pago R$ {brl(ex['pago'])} × liquidado R$ {brl(ex['liquidado'])}; OBs "
                           f"{', '.join(o for o in ex['obs'][:4] if o)}). Fonte: {FONTE_OB} × {FONTE_NL}.",
                    "valor": exc})
    antes = exe.get("ob_antes_da_nl") or []
    if antes:
        ex = antes[0]
        ach.append({"rf": "C-OB<NL", "grav": 2, "eixo": "contabil",
                    "obs": f"**{len(antes)}** OB(s) emitida(s) em data ANTERIOR à da nota de liquidação que citam "
                           f"(ex.: {ex['ob']} de {ex['data_ob']} × {ex['nl']} de {ex['data_nl']}, UG {ex['ug']}). "
                           "O pagamento pressupõe a liquidação (art. 62 da Lei 4.320/64). Fonte: "
                           f"{FONTE_OB} × {FONTE_NL}."})
    return ach


def achados_padroes(pad: dict) -> list[dict]:
    """Cada padrão da casa que disparou num processo do alvo vira achado (o grau do padrão decide a gravidade)."""
    out = []
    por: dict = defaultdict(list)
    for a in pad.get("achados") or []:
        por[a["padrao"]].append(a)
    for pid, lst in sorted(por.items()):
        forte = any(str(a.get("grau")).lower() in ("forte", "alto", "vermelho") for a in lst)
        ex = lst[0]
        out.append({"rf": f"P/{pid}", "grav": 3 if forte else 2, "eixo": ex["eixo"],
                    "obs": f"Padrão da casa **{pid}** disparou em **{len(lst)}** processo(s) deste fornecedor "
                           f"(ex.: {ex['processo']}): {ex['prova'][:260]}",
                    "inocente": ex.get("porque") or "", "fonte_padrao": ex.get("fonte") or "",
                    "processos": sorted({a["processo"] for a in lst})})
    return out


def idade_na_primeira_ob(cad: dict, primeira: str) -> float | None:
    ab = cad.get("abertura") or ""
    if len(ab) == 10 and len(primeira or "") >= 10:
        try:
            d0 = date(int(ab[:4]), int(ab[5:7]), int(ab[8:10]))
            d1 = date(int(primeira[:4]), int(primeira[5:7]), int(primeira[8:10]))
            return (d1 - d0).days / 365.25
        except ValueError:
            return None
    return None
