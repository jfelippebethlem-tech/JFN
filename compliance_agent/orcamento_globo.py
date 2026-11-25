# -*- coding: utf-8 -*-
"""Globo com arcos da aba Orçamento por órgão (O10.7, plano mestre v2 §18.1): para onde vai o dinheiro PAGO.

Um arco = da sede da UG que emitiu a Ordem Bancária até o município (no RJ) ou a UF (fora do RJ) do cadastro na
Receita do CNPJ que recebeu. Espessura = pago por OB do SIAFE no período, com a MESMA leitura e a MESMA regra da
coluna "Pago (OB do SIAFE)" da tabela (`orcamento_orgao._iter_ob`: Contabilizada, tipo Orçamentária, devolvida pelo
banco fora, devolução parcial de valor não coletado fora). A soma dos arcos de cada UG é, por construção e por
teste, o `pago_siafe` da linha da UG na tabela; a soma de tudo é o total do Estado.

O QUE NÃO VIRA PONTO (regras do §18 e da casa)
  · CPF: pessoa física nunca vira ponto e nunca tem nome — o valor vai para o balde "pessoa física", sem nome.
  · Credor genérico do SIAFE (folha de pagamento, inativos, pensionistas, listas de precatório: códigos CG/RP/PP/RF/
    BJ/PR…) e UG do próprio Estado (repasse entre unidades): não são fornecedor com sede — balde próprio, à vista.
  · CNPJ fora do cadastro local da Receita: sede NÃO comprovada → arco tracejado com INDISPONÍVEL, nunca um ponto
    inventado.
  · Sede da UG: município do cadastro de unidades do Estado no PNCP (`territorio/dados/sedes_orgaos.csv`), casado
    pelo nome normalizado. Sem casamento, a origem fica na UF (RJ) e o arco diz "sede da UG não comprovada".

Cor: só Tier 1 realça (achado CONFIRMADO de detector de execução cujo tier, calculado hoje pela régua da O5.1, é 1).
O resto é neutro. Determinístico; só leitura (bancos abertos em `mode=ro`).
"""
from __future__ import annotations

import csv
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from compliance_agent import orcamento_orgao as O

RAIZ = Path(__file__).resolve().parents[1]
DB_RECEITA = RAIZ / "data" / "receita_estab.db"
DB_ACHADOS = RAIZ / "data" / "achados.db"
_DADOS = RAIZ / "compliance_agent" / "territorio" / "dados"
VERSAO = 1

_RE_CNPJ, _RE_CPF, _RE_UG = re.compile(r"\d{14}"), re.compile(r"\d{11}"), re.compile(r"\d{6}")
BALDES = {
    "X:pf": "pessoa física — sem ponto e sem nome",
    "X:generico": "credor genérico do SIAFE (folha, inativos, pensionistas, listas de precatório) — sem sede",
    "X:ug": "outra unidade do próprio Estado (repasse entre UGs) — não é fornecedor",
    "X:exterior": "CNPJ com endereço no exterior — fora do mapa",
    "X:sem_cadastro": "CNPJ fora do cadastro local da Receita — sede INDISPONÍVEL",
}


def _municipios_receita() -> dict[str, str]:
    with open(_DADOS / "municipios_receita_rj.csv", encoding="utf-8") as f:
        return {r["municipio_receita"]: r["cod_ibge"] for r in csv.DictReader(f)}


def _sedes_ug() -> dict[str, str]:
    """nome normalizado da unidade → código IBGE do município de registro (PNCP). Divergente fica de fora."""
    with open(_DADOS / "sedes_orgaos.csv", encoding="utf-8") as f:
        return {r["unidade_norm"]: r["cod_ibge"] for r in csv.DictReader(f) if r["cod_ibge"]}


def tier1_detectores(hoje=None) -> set[str]:
    """Códigos de detector de execução (X1, X2…) cujo tier CALCULADO hoje é 1."""
    from compliance_agent.qualidade import detectores as R
    out = set()
    for k, e in R.carregar().items():
        m = re.match(r"det\.(X\d+)\D", k)
        if m and R.avaliar_tier(e, hoje)["tier"] == 1:
            out.add(m.group(1))
    return out


def _tier1_cnpjs(dets: set[str], db_achados) -> set[str]:
    if not dets or not Path(db_achados).exists():
        return set()
    con = sqlite3.connect(f"file:{db_achados}?mode=ro", uri=True, timeout=30)
    try:
        q = ",".join("?" * len(dets))
        return {str(r[0]) for r in con.execute(
            f"SELECT DISTINCT fornecedor FROM achado_execucao WHERE status='confirmado' AND detector IN ({q})",
            sorted(dets)) if r[0]}
    finally:
        con.close()


def _destinos(cnpjs: list[str], db_receita) -> dict[str, str]:
    """CNPJ → chave do destino: 'M:<ibge>' (município do RJ), 'U:<UF>' (fora do RJ), 'X:exterior', 'X:sem_cadastro'."""
    tab = _municipios_receita()
    out = dict.fromkeys(cnpjs, "X:sem_cadastro")
    if not Path(db_receita).exists():
        return out
    con = sqlite3.connect(f"file:{db_receita}?mode=ro", uri=True, timeout=30)
    try:
        for i in range(0, len(cnpjs), 500):
            lote = cnpjs[i:i + 500]
            for cnpj, uf, mun in con.execute(
                    f"SELECT cnpj, uf, municipio FROM estabelecimentos WHERE cnpj IN ({','.join('?' * len(lote))})",
                    lote):
                uf = str(uf or "").strip().upper()
                if uf == "RJ":
                    ibge = tab.get(str(mun or "").strip())
                    out[cnpj] = f"M:{ibge}" if ibge else "U:RJ"
                elif uf == "EX":
                    out[cnpj] = "X:exterior"
                elif re.fullmatch(r"[A-Z]{2}", uf):
                    out[cnpj] = f"U:{uf}"
    finally:
        con.close()
    return out


def carregar(ano: int, db=None, db_receita=None, db_achados=None, hoje=None) -> dict:
    """Base dos arcos do exercício: por UG emitente, mês e destino, o pago por OB orçamentária (o mesmo `efetivo` da
    tabela) e a parte paga a CNPJ com achado Tier 1. Só tipos de JSON (vai para o cache em disco da rota)."""
    con = O._ro(db or O.DB)
    acc: dict[str, dict[str, dict[str, float]]] = {}
    cred_ug: dict[tuple, float] = defaultdict(float)
    try:
        if not O._tem(con, "ob_orcamentaria_siafe"):
            return {"versao": VERSAO, "ano": int(ano), "disponivel": False, "ugs": {}, "t1": {}}
        for ug, mes, _iso, balde, efetivo, _m, _v, credor in O._iter_ob(con, int(ano)):
            if balde != "orc":
                continue
            cred_ug[(ug, str(mes), credor)] += efetivo
    finally:
        if con is not None:
            con.close()
    cnpjs = sorted({c for (_u, _m, c) in cred_ug if _RE_CNPJ.fullmatch(c)})
    dest = _destinos(cnpjs, db_receita or DB_RECEITA)
    dets = tier1_detectores(hoje)
    t1 = _tier1_cnpjs(dets, db_achados or DB_ACHADOS)
    t1_por: dict[str, dict[str, dict[str, float]]] = {}
    for (ug, mes, c), v in cred_ug.items():
        if _RE_CNPJ.fullmatch(c):
            k = dest[c]
        elif _RE_CPF.fullmatch(c):
            k = "X:pf"
        elif _RE_UG.fullmatch(c):
            k = "X:ug"
        else:
            k = "X:generico"
        b = acc.setdefault(ug, {}).setdefault(mes, {})
        b[k] = b.get(k, 0.0) + v
        if c in t1:
            tb = t1_por.setdefault(ug, {}).setdefault(mes, {})
            tb[k] = tb.get(k, 0.0) + v
    return {"versao": VERSAO, "ano": int(ano), "disponivel": True, "ugs": acc, "t1": t1_por,
            "tier1_detectores": sorted(dets), "tier1_cnpjs": len(t1), "gerado_em": time.strftime("%Y-%m-%d %H:%M")}


def _partes(base: dict, ug: str, corte: int) -> tuple[dict[str, float], dict[str, float]]:
    """Destino → valor da UG até o mês `corte` (o mês "0", data ilegível, conta sempre — igual a `_Ctx.ob_ate`)."""
    v: dict[str, float] = defaultdict(float)
    t: dict[str, float] = defaultdict(float)
    for m, b in (base["ugs"].get(ug) or {}).items():
        if int(m) <= corte:
            for k, x in b.items():
                v[k] += x
    for m, b in (base["t1"].get(ug) or {}).items():
        if int(m) <= corte:
            for k, x in b.items():
                t[k] += x
    return v, t


def montar(base: dict, d: dict) -> dict:
    """Arcos para o payload `d` de `orcamento_orgao.montar` (mesmo exercício e mês). Cada UG da tabela com
    `pago_siafe` vira linhas {orgao, ug, o, oc, d, v, t1}; a soma das linhas da UG é o `pago_siafe` dela no centavo.
    O resíduo de arredondamento (soma de parcelas arredondadas contra o total arredondado) vai para a maior parcela
    da UG e é declarado em `ajuste_centavos`."""
    from compliance_agent.territorio.geo import nome_municipio, norm
    if not base.get("disponivel"):
        return {"ok": False, "motivo": "tabela de OB do SIAFE ausente na base — arcos INDISPONÍVEIS"}
    corte = int(d.get("ob_ate_mes") or 12)
    sedes = _sedes_ug()
    nomes = nome_municipio()
    linhas, ajuste, sem_ob, divergentes = [], 0, 0, []
    for o in d.get("orgaos") or []:
        for x in o.get("ugs") or []:
            if not x.get("espera_ob"):
                continue
            if x.get("pago_siafe") is None:
                sem_ob += 1
                continue
            v, t = _partes(base, x["ug"], corte)
            partes = {k: round(val, 2) for k, val in v.items() if round(val, 2) != 0}
            res = round(x["pago_siafe"] - sum(partes.values()), 2)
            if res:
                if abs(res) > 0.05 or not partes:          # não é arredondamento: a leitura divergiu da tabela
                    divergentes.append({"ug": x["ug"], "tabela": x["pago_siafe"], "arcos": round(sum(partes.values()), 2)})
                    continue
                maior = max(partes, key=lambda k: abs(partes[k]))
                partes[maior] = round(partes[maior] + res, 2)
                ajuste += round(abs(res) * 100)
            ibge = sedes.get(norm(x.get("nome")))
            origem = f"M:{ibge}" if ibge else "U:RJ"
            for k, val in sorted(partes.items(), key=lambda kv: -abs(kv[1])):
                linhas.append({"orgao": o["orgao"], "ug": x["ug"], "o": origem, "oc": bool(ibge), "d": k, "v": val,
                               "t1": round(t.get(k, 0.0), 2)})
    lugares = {}
    for ln in linhas:
        for k in (ln["o"], ln["d"]):
            if k.startswith("M:"):
                lugares[k] = {"nome": nomes.get(k[2:], f"município {k[2:]}"), "tipo": "municipio"}
            elif k.startswith("U:"):
                lugares[k] = {"nome": k[2:], "tipo": "uf"}
    return {
        "ok": True, "versao": VERSAO, "linhas": linhas, "lugares": lugares, "baldes": BALDES,
        "ajuste_centavos": ajuste, "ugs_sem_ob": sem_ob, "divergentes": divergentes,
        "tier1_detectores": base.get("tier1_detectores", []), "tier1_cnpjs": base.get("tier1_cnpjs", 0),
        "regra": ("Espessura = pago por OB orçamentária Contabilizada do SIAFE no período da tabela (devolvida pelo "
                  "banco fora). Origem = sede da UG emitente (cadastro de unidades do PNCP); destino = município (RJ) "
                  "ou UF do cadastro na Receita do CNPJ que recebeu. Cor só para Tier 1."),
        "gerado_em": base.get("gerado_em"),
    }
