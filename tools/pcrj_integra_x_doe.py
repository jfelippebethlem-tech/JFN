# -*- coding: utf-8 -*-
"""Cruza as ÍNTEGRAS dos contratos municipais (PNCP) com os EXTRATOS do D.O. Rio — a captura vira achado.

O handoff de 08/09/2026 deixou 560 processos SEI citados nas íntegras "como acervo, sem virar
achado". O elo que faltava era o D.O.: 303 desses processos aparecem em `pcrj_doe_materia`, e
`doe_minerador.minerar_extratos` transforma cada página em eventos (contrato, aditivo,
apostilamento, ratificação…). Este módulo materializa o cruzamento e dele extrai SINAIS POSITIVOS:

  contratacao_direta      fundamento art. 74/75 (14.133) ou 24/25 (8.666) no extrato — informativo
  emergencial             art. 75, VIII ou "emergenc" no extrato
  emergencial_incumbente  emergencial + o MESMO fornecedor já contratava com o MESMO órgão antes
                          (o padrão do caso AGILE/SEEDUC: a "emergência" recai no incumbente)
  acrescimo_acima_teto    aditivos de ACRÉSCIMO (classificados por `limites_aditivo`) somando mais que o teto
                          do art. 125 (fonte única; inclusivo); prorrogação/reajuste não contam
  valor_divergente        valor do extrato ≠ valor global PNCP (> 5%) — inconsistência entre fontes

HONESTIDADE: ausência de extrato no D.O. NÃO é sinal — `pcrj_doe_materia` cobre só o que o coletor
diário capturou (páginas por termo de busca). Cobertura vai no resumo, nunca como achado.
Indício ≠ acusação: cada sinal traz a evidência (id_materia, trecho) para conferência humana.

    python -m tools.pcrj_integra_x_doe            # materializa contrato_doe_evento + contrato_doe_sinal
    python -m tools.pcrj_integra_x_doe --resumo   # só lê e imprime
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from compliance_agent.pcrj.doe_minerador import minerar_extratos  # noqa: E402
from compliance_agent.limites_aditivo import ato_normativo, estouro  # noqa: E402
from compliance_agent.reporting.intel_base import moeda  # noqa: E402

logger = logging.getLogger("pcrj_integra_x_doe")
DB = _REPO / "data" / "compliance.db"
PCRJ_DB = _REPO / "data" / "pcrj.db"
TOLERANCIA_VALOR = 0.05

DDL = """
CREATE TABLE IF NOT EXISTS contrato_doe_evento (
    numero_controle_pncp TEXT, processo TEXT, id_materia INTEGER, data_doe TEXT, tipo TEXT,
    cabecalho TEXT, contrato_num TEXT, aditivo_n INTEGER, data_assinatura TEXT, partes TEXT,
    objeto TEXT, prazo TEXT, valor REAL, fundamento TEXT, mesmo_fornecedor INTEGER, gerado_em TEXT
);
CREATE INDEX IF NOT EXISTS ix_cde_pncp ON contrato_doe_evento(numero_controle_pncp);
CREATE TABLE IF NOT EXISTS contrato_doe_sinal (
    numero_controle_pncp TEXT, sinal TEXT, grau TEXT, detalhe TEXT, evidencia TEXT, gerado_em TEXT
);
CREATE INDEX IF NOT EXISTS ix_cds_pncp ON contrato_doe_sinal(numero_controle_pncp);
"""

_STOP = {"LTDA", "ME", "EPP", "SA", "S/A", "EIRELI", "EMPRESA", "DE", "DO", "DA", "DOS", "DAS", "E", "COMERCIO",
         "SERVICOS", "SERVICO", "CIA", "COMPANHIA", "GRUPO", "INDUSTRIA", "CONSTRUCOES", "CONSTRUTORA"}


def _norm(s: str) -> str:
    import re
    import unicodedata
    return re.sub(r"[^A-Z0-9 ]", " ", unicodedata.normalize("NFKD", (s or "").upper()).encode("ascii", "ignore").decode())


def casa_fornecedor(fornecedor_nome: str, partes: str | None) -> bool | None:
    """Um processo SEI gera VÁRIOS contratos (ata, lotes): 282 de 376 eventos eram de OUTRO fornecedor
    no mesmo processo (AGILE ligada a aditivo da VR Benefícios). `None` = extrato sem "Partes"
    (não dá para saber); `True` só quando os dois primeiros tokens distintivos do nome aparecem."""
    if not partes:
        return None
    toks = [t for t in _norm(fornecedor_nome).split() if len(t) >= 3 and t not in _STOP][:2]
    if not toks:
        return None
    alvo = _norm(partes)
    return all(t in alvo.split() for t in toks)


def sinais_do_contrato(contrato: dict, eventos: list[dict], historico: list[dict]) -> list[dict]:
    """Sinais POSITIVOS de um contrato a partir dos seus eventos no D.O.

    `contrato`: numero_controle_pncp, valor_global, fornecedor_documento, orgao_cnpj, data_assinatura.
    `historico`: contratos ANTERIORES do mesmo fornecedor com o mesmo órgão (já filtrados por data).
    Puro (sem I/O) para ser testável."""
    out: list[dict] = []
    proprios = [e for e in eventos if e.get("mesmo_fornecedor") is not False]      # True ou desconhecido
    certos = [e for e in eventos if e.get("mesmo_fornecedor") is True]             # só com "Partes" batendo
    if not proprios:
        return out
    eventos = proprios
    diretos = [e for e in eventos if e.get("fundamento")]
    if diretos:
        e = diretos[0]
        out.append({"sinal": "contratacao_direta", "grau": "🟡",
                    "detalhe": f"{e['fundamento']} ({e['tipo']} no D.O. de {e.get('data_doe')})",
                    "evidencia": {"id_materia": e.get("id_materia"), "fundamento": e["fundamento"]}})
    emerg = [e for e in eventos if (e.get("fundamento") == "art. 75, VIII")
             or "emergenc" in ((e.get("objeto") or "") + (e.get("partes") or "")).lower()]
    if emerg:
        e = emerg[0]
        if historico and e.get("mesmo_fornecedor") is True:
            h = historico[0]
            out.append({"sinal": "emergencial_incumbente", "grau": "🔴",
                        "detalhe": (f"emergência recai no incumbente: o mesmo fornecedor já contratava com o Município "
                                    f"desde {h.get('data_assinatura')} ({h.get('numero_controle_pncp')}; `unidade` do PNCP "
                                    f"não distingue secretaria — conferir a pasta nas Partes do extrato)"),
                        "evidencia": {"id_materia": e.get("id_materia"), "anterior": h.get("numero_controle_pncp"),
                                      "n_anteriores": len(historico)}})
        else:
            out.append({"sinal": "emergencial", "grau": "🟡",
                        "detalhe": f"contratação emergencial ({e.get('fundamento') or 'objeto menciona emergência'})",
                        "evidencia": {"id_materia": e.get("id_materia")}})
    base = contrato.get("valor_global") or 0
    # Teto e classificação (acréscimo × prorrogação × reajuste) vêm da FONTE ÚNICA do art. 125 —
    # `limites_aditivo.estouro` — nunca de uma fração local. Só aditivos do MESMO fornecedor entram.
    aditivos = [{"objeto": e.get("objeto"), "valor": e.get("valor"), "id_materia": e.get("id_materia")}
                for e in certos if e.get("tipo") == "aditivo" and e.get("valor")]
    est = estouro(base, aditivos) if aditivos else None
    if est and est["aferivel"] and est["estourou"]:
        ids = [i.get("id_materia") for i in est["itens"] if i.get("tipo") == "valor"]
        out.append({"sinal": "acrescimo_acima_teto", "grau": "🔴",
                    "detalhe": (f"acréscimos declarados em {len(ids)} aditivo(s) somam {moeda(est['acrescimo'])} = "
                                f"{100 * est['pct']:.1f}% do valor PNCP (teto {100 * est['teto']:.0f}%, "
                                f"{ato_normativo()}) — conferir se o valor publicado é o do acréscimo ou o do período"),
                    "evidencia": {"ids_materia": ids, "soma": est["acrescimo"], "base": base, "teto": est["teto"]}})
    extratos = [e for e in certos if e.get("tipo") == "contrato" and e.get("valor")]
    if base > 0 and extratos:
        e = extratos[0]
        desvio = abs(e["valor"] - base) / base
        if desvio > TOLERANCIA_VALOR:
            out.append({"sinal": "valor_divergente", "grau": "🟡",
                        "detalhe": f"extrato no D.O. {moeda(e['valor'])} × PNCP {moeda(base)} ({100 * desvio:.0f}%)",
                        "evidencia": {"id_materia": e.get("id_materia"), "doe": e["valor"], "pncp": base}})
    return out


def _carregar_contratos(con: sqlite3.Connection) -> dict[str, dict]:
    sql = ("SELECT i.numero_controle_pncp, i.fornecedor_nome, i.valor_global, i.processos_sei, i.ano, "
           "c.orgao_cnpj, c.orgao_nome, c.fornecedor_documento, c.data_assinatura, c.valor_global "
           "FROM contrato_integra i LEFT JOIN pcrj_contratos c USING (numero_controle_pncp) "
           "WHERE i.processos_sei IS NOT NULL AND i.processos_sei NOT IN ('', '[]')")
    out = {}
    for r in con.execute(sql):
        try:
            procs = json.loads(r[3] or "[]")
        except ValueError:
            procs = []
        out[r[0]] = {"numero_controle_pncp": r[0], "fornecedor_nome": r[1], "valor_global": r[9] or r[2],
                     "processos": procs, "ano": r[4], "orgao_cnpj": r[5], "orgao_nome": r[6],
                     "fornecedor_documento": r[7], "data_assinatura": r[8]}
    return out


def _historico(con: sqlite3.Connection, c: dict) -> list[dict]:
    if not (c.get("fornecedor_documento") and c.get("orgao_cnpj") and c.get("data_assinatura")):
        return []
    rows = con.execute(
        "SELECT numero_controle_pncp, data_assinatura, valor_global FROM pcrj_contratos "
        "WHERE fornecedor_documento=? AND orgao_cnpj=? AND data_assinatura < ? AND numero_controle_pncp <> ? "
        "ORDER BY data_assinatura", (c["fornecedor_documento"], c["orgao_cnpj"], c["data_assinatura"],
                                     c["numero_controle_pncp"])).fetchall()
    return [{"numero_controle_pncp": r[0], "data_assinatura": r[1], "valor_global": r[2]} for r in rows]


def materializar() -> dict:
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    con.executescript(DDL)
    contratos = _carregar_contratos(con)
    por_processo: dict[str, list[str]] = {}
    for num, c in contratos.items():
        for p in c["processos"]:
            por_processo.setdefault(p, []).append(num)
    pc = sqlite3.connect(f"file:{PCRJ_DB}?mode=ro", uri=True, timeout=60)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    eventos_por_contrato: dict[str, list[dict]] = {}
    paginas = 0
    for id_materia, data, procs_js, texto in pc.execute(
            "SELECT id_materia, data, processos, texto FROM pcrj_doe_materia"):
        try:
            pagina_procs = set(json.loads(procs_js or "[]"))
        except ValueError:
            pagina_procs = set()
        if not (pagina_procs & por_processo.keys()):
            continue
        paginas += 1
        for e in minerar_extratos(texto or ""):
            for p in e["processos"]:
                for num in por_processo.get(p, ()):
                    ev = {**e, "processo": p, "id_materia": id_materia, "data_doe": data,
                          "mesmo_fornecedor": casa_fornecedor(contratos[num]["fornecedor_nome"], e.get("partes"))}
                    eventos_por_contrato.setdefault(num, []).append(ev)
    pc.close()
    with con:
        con.execute("DROP TABLE IF EXISTS contrato_doe_evento")   # esquema pode mudar entre versões
        con.executescript(DDL)
        con.execute("DELETE FROM contrato_doe_sinal")
        n_ev = n_sin = 0
        por_sinal: dict[str, int] = {}
        for num, evs in eventos_por_contrato.items():
            for e in evs:
                con.execute(
                    "INSERT INTO contrato_doe_evento VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (num, e["processo"], e["id_materia"], e["data_doe"], e["tipo"], e["cabecalho"], e["contrato_num"],
                     e.get("aditivo_n"), e["data_assinatura"], e["partes"], e["objeto"], e["prazo"], e["valor"],
                     e["fundamento"], None if e["mesmo_fornecedor"] is None else int(e["mesmo_fornecedor"]), agora))
                n_ev += 1
            for s in sinais_do_contrato(contratos[num], evs, _historico(con, contratos[num])):
                con.execute("INSERT INTO contrato_doe_sinal VALUES (?,?,?,?,?,?)",
                            (num, s["sinal"], s["grau"], s["detalhe"], json.dumps(s["evidencia"], ensure_ascii=False),
                             agora))
                n_sin += 1
                por_sinal[s["sinal"]] = por_sinal.get(s["sinal"], 0) + 1
    res = {"contratos_com_processo": len(contratos), "paginas_doe_cruzadas": paginas,
           "contratos_com_evento": len(eventos_por_contrato), "eventos": n_ev, "sinais": n_sin, "por_sinal": por_sinal}
    con.close()
    return res


def resumo() -> dict:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    out = {"por_sinal": dict(con.execute(
        "SELECT sinal || ' ' || grau, count(*) FROM contrato_doe_sinal GROUP BY 1").fetchall())}
    out["top"] = [dict(zip(("contrato", "sinal", "grau", "detalhe"), r)) for r in con.execute(
        "SELECT s.numero_controle_pncp, s.sinal, s.grau, s.detalhe FROM contrato_doe_sinal s "
        "LEFT JOIN pcrj_contratos c USING (numero_controle_pncp) "
        "ORDER BY CASE s.grau WHEN '🔴' THEN 0 ELSE 1 END, c.valor_global DESC LIMIT 12")]
    con.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resumo", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not a.resumo:
        print(json.dumps(materializar(), ensure_ascii=False, indent=1))
    print(json.dumps(resumo(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
