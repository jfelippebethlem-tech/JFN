# -*- coding: utf-8 -*-
"""Agregados do território: por município (Estado), por AP (PCRJ) e os BALDES.

Regra que não se negocia: contrato de vários municípios/APs NÃO tem o valor repartido — vai inteiro
para o balde "multimunicipio"; o município só ganha a contagem `n_multi` ("participa de N").
`pago` agregado é NULL quando NENHUM contrato do território tem pagamento vinculado (INDISPONÍVEL);
havendo ao menos um, é a soma dos vinculados (e a ficha mostra quantos têm vínculo).
`n_alertas` (Estado) = contratos do território com INDÍCIO da perícia contábil (pago acima do valor registrado);
na PCRJ continua NULL (sem vínculo territorial dos alertas).

GRAU DE CERTEZA (Estado): o mapa soma só os graus pedidos (`graus`); por padrão `explicito` + `unidade`. O grau
`sede` é o mais fraco (objeto da organização atribuído à sede do órgão) e só entra quando a tela pede. Os baldes
trazem SEMPRE a cobertura separada por grau — é ela que o rodapé mostra.
"""
from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from pathlib import Path

from compliance_agent.territorio import base
from compliance_agent.territorio.geo import nome_municipio, ras_por_ap

PERIODOS = {"vigentes": "status='em_execucao'", "2023": "(vig_fim IS NULL OR vig_fim>='2023-01-01')", "tudo": "1=1"}
GRAUS = ("explicito", "unidade", "sede")
GRAUS_PADRAO = ("explicito", "unidade")
_COLS_EST = ("SUM(alerta IS NOT NULL) n_alertas, SUM(status='sem_vigencia') n_sem_vigencia, ")


def graus_validos(graus) -> tuple[str, ...]:
    """Só graus conhecidos, na ordem canônica; vazio/inválido → o padrão (explícito + unidade)."""
    g = tuple(x for x in GRAUS if x in set(graus or ()))
    return g or GRAUS_PADRAO


def filtro_grau(graus) -> str:
    """Fragmento SQL (os valores vêm da lista fechada `GRAUS`, nunca do pedido)."""
    return "grau IN (" + ",".join(f"'{g}'" for g in graus_validos(graus)) + ")"
_COLS = ("COUNT(*) n_contratos, SUM(status='em_execucao') n_em_execucao, SUM(status='executado') n_executados, SUM(status='rescindido') n_rescindidos, "
         "COALESCE(SUM(valor),0) valor_contratado, COALESCE(SUM(CASE WHEN status='em_execucao' THEN valor END),0) valor_em_execucao, "
         "SUM(pago) pago, SUM(CASE WHEN pago IS NOT NULL THEN valor END) valor_com_pago, SUM(pago IS NOT NULL) n_com_pago")


def _linha(r: sqlite3.Row) -> dict:
    d = dict(r)
    vp = d.pop("valor_com_pago", None)
    d["pct_executado"] = (d["pago"] / vp) if d.get("pago") is not None and vp else None
    d.setdefault("n_alertas", None)
    return d


def por_municipio(c: sqlite3.Connection, periodo: str = "tudo", graus=GRAUS_PADRAO) -> list[dict]:
    """Os 92 municípios. Os números somam só os `graus` pedidos; `por_grau` traz SEMPRE os três, para a tela dizer
    quanto de cada município vem de texto explícito, de unidade e de sede."""
    w = PERIODOS.get(periodo, PERIODOS["tudo"])
    nomes = nome_municipio()
    multi: dict[str, int] = {}
    for (js,) in c.execute(f"SELECT municipios_json FROM territorio_contrato_estado WHERE multi=1 AND {w}"):
        for m in json.loads(js or "[]"):
            multi[m["cod_ibge"]] = multi.get(m["cod_ibge"], 0) + 1
    por = {r["cod_ibge"]: _linha(r) for r in c.execute(
        f"SELECT cod_ibge, {_COLS_EST}{_COLS} FROM territorio_contrato_estado WHERE cod_ibge IS NOT NULL AND multi=0 AND {w} "
        f"AND {filtro_grau(graus)} GROUP BY cod_ibge")}
    grau: dict[str, dict] = {}
    for r in c.execute(f"SELECT cod_ibge, grau, COUNT(*) n, COALESCE(SUM(valor),0) valor FROM territorio_contrato_estado "
                       f"WHERE cod_ibge IS NOT NULL AND multi=0 AND {w} GROUP BY cod_ibge, grau"):
        grau.setdefault(r["cod_ibge"], {})[r["grau"] or "explicito"] = {"n": r["n"], "valor": r["valor"]}
    out = []
    for cod, nome in sorted(nomes.items()):
        d = por.get(cod) or {"cod_ibge": cod, "n_contratos": 0, "n_em_execucao": 0, "n_executados": 0, "n_rescindidos": 0, "valor_contratado": 0.0,
                             "valor_em_execucao": 0.0, "pago": None, "n_com_pago": 0, "pct_executado": None, "n_alertas": 0,
                             "n_sem_vigencia": 0}
        d["nome"], d["n_multi"] = nome, multi.get(cod, 0)
        d["por_grau"] = {g: grau.get(cod, {}).get(g, {"n": 0, "valor": 0.0}) for g in GRAUS}
        out.append(d)
    return out


def por_ap(c: sqlite3.Connection, periodo: str = "tudo") -> list[dict]:
    w = PERIODOS.get(periodo, PERIODOS["tudo"])
    multi: dict[int, int] = {}
    for (js,) in c.execute(f"SELECT aps_json FROM territorio_contrato_pcrj WHERE multi=1 AND {w}"):
        for a in json.loads(js or "[]"):
            multi[a] = multi.get(a, 0) + 1
    por = {r["ap"]: _linha(r) for r in c.execute(
        f"SELECT ap, {_COLS} FROM territorio_contrato_pcrj WHERE ap IS NOT NULL AND multi=0 AND {w} GROUP BY ap")}
    out = []
    for ap, ras in ras_por_ap().items():
        d = por.get(ap) or {"ap": ap, "n_contratos": 0, "n_em_execucao": 0, "n_executados": 0, "n_rescindidos": 0, "valor_contratado": 0.0,
                            "valor_em_execucao": 0.0, "pago": None, "n_com_pago": 0, "pct_executado": None, "n_alertas": None}
        d["nome"], d["ras"], d["n_multi"] = f"AP {ap}", ras, multi.get(ap, 0)
        out.append(d)
    return out


def baldes_estado(c: sqlite3.Connection, periodo: str = "tudo") -> dict:
    w = PERIODOS.get(periodo, PERIODOS["tudo"])
    um = lambda cond: dict(c.execute(  # noqa: E731
        f"SELECT COUNT(*) n, COALESCE(SUM(valor),0) valor FROM territorio_contrato_estado WHERE {cond} AND {w}").fetchone())
    b = {"sem_municipio": um("cod_ibge IS NULL AND multi=0 AND regiao IS NULL AND abrangencia IS NULL"),
         "estado_inteiro": um("cod_ibge IS NULL AND multi=0 AND abrangencia IS NOT NULL"), "multimunicipio": um("multi=1"),
         "regiao": um("cod_ibge IS NULL AND multi=0 AND regiao IS NOT NULL"),
         "atribuido": um("cod_ibge IS NOT NULL AND multi=0"), "total": um("1=1")}
    # cobertura por GRAU DE CERTEZA (o banco de antes da fase 12 não tem a coluna: aí só os baldes clássicos)
    if "grau" in {r[1] for r in c.execute("PRAGMA table_info(territorio_contrato_estado)")}:
        for g in GRAUS:
            b["atribuido_" + g] = um(f"cod_ibge IS NOT NULL AND multi=0 AND grau='{g}'")
        b["sem_vigencia"] = um("status='sem_vigencia'")
        b["com_pago"] = dict(c.execute(f"SELECT COUNT(*) n, COALESCE(SUM(valor),0) valor, COALESCE(SUM(pago),0) pago "
                                       f"FROM territorio_contrato_estado WHERE pago IS NOT NULL AND {w}").fetchone())
    return b


def baldes_pcrj(c: sqlite3.Connection, periodo: str = "tudo") -> dict:
    w = PERIODOS.get(periodo, PERIODOS["tudo"])
    um = lambda cond: dict(c.execute(  # noqa: E731
        f"SELECT COUNT(*) n, COALESCE(SUM(valor),0) valor FROM territorio_contrato_pcrj WHERE {cond} AND {w}").fetchone())
    return {"sem_ap": um("ap IS NULL AND multi=0 AND abrangencia IS NULL"), "cidade_inteira": um("ap IS NULL AND multi=0 AND abrangencia IS NOT NULL"),
            "multi_ap": um("multi=1"), "atribuido": um("ap IS NOT NULL AND multi=0"), "total": um("1=1")}


def rodar(log=print) -> dict:
    """Regrava `territorio_mun_agg`, `territorio_ap_agg` e `territorio_baldes` (recorte "tudo")."""
    db = base.abrir(escrita=True)
    agora = base.agora()
    db.execute("DELETE FROM territorio_mun_agg")
    for d in por_municipio(db):
        db.execute("INSERT INTO territorio_mun_agg VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (d["cod_ibge"], d["nome"], d["n_em_execucao"], d["n_executados"], d["valor_contratado"], d["valor_em_execucao"],
                    d["pago"], d["n_alertas"], d["n_multi"], agora))
    db.execute("DELETE FROM territorio_ap_agg")
    for d in por_ap(db):
        db.execute("INSERT INTO territorio_ap_agg VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (d["ap"], json.dumps(d["ras"], ensure_ascii=False), d["n_em_execucao"], d["n_executados"], d["valor_contratado"],
                    d["valor_em_execucao"], d["pago"], d["n_alertas"], d["n_multi"], agora))
    be, bp = baldes_estado(db), baldes_pcrj(db)
    db.execute("DELETE FROM territorio_baldes")
    for nome, v in {**be, **{"pcrj_" + k: x for k, x in bp.items()}}.items():
        db.execute("INSERT INTO territorio_baldes VALUES(?,?,?,?)", (nome, v["n"], v["valor"], agora))
    base.por_meta(db, "atualizado_em", agora)
    db.commit()
    db.close()
    # cópias de consulta dos cadastros versionados (o brief os quer em data/)
    origem = Path(__file__).resolve().parent / "dados" / "pcrj_orgao_ap.csv"
    shutil.copyfile(origem, base.DATA / "territorio_pcrj_orgao_ap.csv")
    with open(base.DATA / "territorio_baldes.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["balde", "n", "valor"])
        for nome, v in {**be, **{"pcrj_" + k: x for k, x in bp.items()}}.items():
            w.writerow([nome, v["n"], f"{v['valor']:.2f}"])
    log(f"[agrega] baldes Estado: {be} · PCRJ: {bp}")
    return {"estado": be, "pcrj": bp}
