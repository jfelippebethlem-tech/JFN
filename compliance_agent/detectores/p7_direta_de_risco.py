# -*- coding: utf-8 -*-
"""Detector P7 — contratação direta DE RISCO, com o dado que a casa já tem (NE do painel da CGE).

POR QUE EXISTE. O confronto CGE × JFN de 13/11/2026 (vault `notas/cge-irregularidades-x-jfn-2026-11-13`,
lacuna 2) mediu recall 0/11 nas contratações com irregularidade material. Em 7 delas o JFN já tinha dado de
triagem bastante: o painel de NE da CGE (`dadosabertos_rj.cge_ne_credor`) dizia "Inexigibilidade — patrocínio
de evento", "Inexigibilidade — dez ingressos para congresso", "Dispensa — limpeza" e "Dispensa — Evento". O P6
só testa o TETO da dispensa por valor; inexigibilidade para patrocínio e dispensa para serviço contínuo não
tinham regra nenhuma.

REGRAS (determinísticas; cada uma é INDÍCIO de que vale ler os autos, nunca conclusão):
  1. `inexigibilidade_patrocinio_evento` — inexigibilidade cujo histórico/subitem fala em patrocínio, evento,
     festival, show, ingresso, congresso, seminário, feira. A inviabilidade de competição (art. 74) raramente se
     demonstra para patrocínio; a CGE achou "inviabilidade não demonstrada" e preço "justificado" por referências
     não independentes ............................................................................. 'medio'
  2. `dispensa_servico_continuo_acima_do_teto` — dispensa para serviço CONTÍNUO (limpeza, vigilância, apoio…;
     vocabulário único em `lex_redflags._SERV_CONTINUO_KW`) acima do teto de dispensa por valor do exercício
     (`limites_dispensa`, fonte única): sem amparo por valor, presume-se emergencial (art. 75, VIII), e
     emergência em serviço contínuo costuma ser falta de planejamento (§6º) ............................ 'medio'
  3. `dispensa_evento_acima_do_teto` — dispensa para evento acima do teto do exercício ................ 'medio'
  4. `inexigibilidade_vulto_a_associacao_ou_me` / `inexigibilidade_vulto_a_credor_novo_na_ug` —
     inexigibilidade acima de R$ 1.000.000,00 a associação/fundação/instituto/ME, ou a credor sem NE anterior
     na mesma UG ..................................................................................... 'medio'
  Duas ou mais regras no mesmo empenho → 'forte'.

HONESTIDADE. O valor é EMPENHADO (painel da CGE), não pago: empenho ≠ liquidação ≠ OB. Sem modalidade ou
valor → `nao_avaliavel` (INDISPONÍVEL ≠ 0). O painel cobre 06/02/2023 a 01/06/2026 e 99 UGs: ausência de NE
não prova ausência de contrato. Indício ≠ acusação.

CALLER. `python -m compliance_agent.detectores.p7_direta_de_risco [--gravar]` varre o painel (leitura) e,
com `--gravar`, persiste em `achados.db` (`achado_detector`, mesmo schema da varredura de órgãos).
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora
from compliance_agent.lex_redflags import _eh_servico_continuo
from compliance_agent.limites_dispensa import ato_normativo, limite_dispensa
from compliance_agent.reporting.intel_base import moeda

VULTO_INEXIGIBILIDADE = 1_000_000.00   # régua de materialidade da nota CGE × JFN (lacuna 2, regra iii)

_RX_EVENTO = re.compile(
    r"patroc[ií]n|\bevento|festival|\bshows?\b|ingress|congress|semin[áa]ri|\bfeiras?\b|espet[áa]cul", re.I)
_RX_ASSOC_ME = re.compile(
    r"\bassoc|\bfunda[çc][ãa]o\b|\binstituto\b|\bliga\b|\bme\b\.?$|\bmei\b|\beireli\b|\bepp\b", re.I)


def _modalidade(txt: str) -> str:
    t = (txt or "").lower()
    if "inexig" in t:
        return "inexigibilidade"
    if "dispensa" in t:
        return "dispensa"
    return ""


class P7DiretaDeRisco(Detector):
    """Detector P7 — inexigibilidade para patrocínio/evento, dispensa para serviço contínuo, vulto a associação."""

    id = "P7"
    nome = "Contratação direta de risco (triagem pela NE)"
    familia = "desenho_certame"   # mesma família do P5 (emergência fabricada): contratação direta no planejamento

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")
        mod = _modalidade(contexto.get("modalidade") or "")
        valor = contexto.get("valor")
        if not mod:
            res.motivo_refutacao = ("nao_avaliavel: modalidade ausente" if not contexto.get("modalidade")
                                    else "descartado: não é contratação direta")
            if contexto.get("modalidade"):
                res.status = "descartado"
            return res
        if valor is None or float(valor) <= 0:
            res.motivo_refutacao = "nao_avaliavel: contratação direta sem valor empenhado apurável (INDISPONÍVEL ≠ 0)"
            return res
        valor = float(valor)
        texto = " ".join(str(contexto.get(k) or "") for k in ("historico", "subitem"))
        ano = int(contexto.get("ano") or 0) or None
        teto = limite_dispensa(ano, "compras") if ano else None
        regras: list[str] = []
        ev: list[str] = []

        if mod == "inexigibilidade":
            if _RX_EVENTO.search(texto):
                regras.append("inexigibilidade_patrocinio_evento")
                ev.append("inexigibilidade para patrocínio/evento/ingresso — inviabilidade de competição "
                          "(art. 74) raramente demonstrável nesse objeto")
            if valor > VULTO_INEXIGIBILIDADE:
                if _RX_ASSOC_ME.search(str(contexto.get("credor_nome") or "").strip()):
                    regras.append("inexigibilidade_vulto_a_associacao_ou_me")
                    ev.append(f"inexigibilidade de R$ {moeda(valor)} a associação/fundação/instituto/ME")
                if contexto.get("credor_novo_na_ug"):
                    regras.append("inexigibilidade_vulto_a_credor_novo_na_ug")
                    ev.append(f"inexigibilidade de R$ {moeda(valor)} a credor sem empenho anterior na UG")
        else:  # dispensa
            if teto is None:
                res.motivo_refutacao = "nao_avaliavel: dispensa sem exercício — teto do ano INDISPONÍVEL"
                return res
            acima = valor > teto
            if acima and _eh_servico_continuo([texto]):
                regras.append("dispensa_servico_continuo_acima_do_teto")
                ev.append(f"dispensa de R$ {moeda(valor)} para serviço CONTÍNUO, acima do teto por valor de {ano} "
                          f"(R$ {moeda(teto)}; {ato_normativo(ano)}) — presume-se emergencial (art. 75, VIII), "
                          "e emergência em serviço contínuo costuma ser falta de planejamento (§6º)")
            if acima and _RX_EVENTO.search(texto):
                regras.append("dispensa_evento_acima_do_teto")
                ev.append(f"dispensa de R$ {moeda(valor)} para evento, acima do teto por valor de {ano} "
                          f"(R$ {moeda(teto)})")

        res.valores = {"modalidade": mod, "valor": valor, "natureza_valor": "empenhado (painel CGE) — não é pago",
                       "ano": ano, "teto_dispensa": teto, "regras": regras,
                       "credor_novo_na_ug": contexto.get("credor_novo_na_ug")}
        if not regras:
            res.status = "descartado"
            res.motivo_refutacao = "nenhuma regra de risco casou com a modalidade, o objeto e o valor"
            return res
        res.status = "confirmado"
        res.score = ancora("forte" if len(regras) >= 2 else "medio")
        for e in ev:
            res.add_evidencia("dadosabertos_rj.cge_ne_credor (painel de NE da CGE)", e)
        res.explicacao_inocente = (
            "Patrocínio e evento podem ter inexigibilidade legítima (art. 74, II — artista consagrado; exclusividade "
            "real), e a dispensa acima do teto pode ter amparo emergencial documentado e não causado pela "
            "Administração. Só os autos (ETP, justificativa de preço, parecer) fecham a questão — ler antes de "
            "concluir.")
        return res


def _processo_da_linha(r: sqlite3.Row) -> str:
    try:
        procs = json.loads(r["processos_sei"] or "[]")
    except ValueError:
        procs = []
    return procs[0] if procs else ""


def contextos_do_painel(con: sqlite3.Connection, *, ano_min: int | None = None) -> list[dict[str, Any]]:
    """Um contexto por contratação direta do painel de NE: agrupa as NEs do mesmo (UG, credor, processo SEI) —
    sem processo, cada NE é um grupo. Soma o EMPENHADO (não é pago). Marca `credor_novo_na_ug` quando o credor
    não tem NE anterior naquela UG."""
    con.row_factory = sqlite3.Row
    cond = "WHERE (tipo_de_licitacao LIKE '%nexig%' OR tipo_de_licitacao LIKE '%ispensa%')"
    params: list = []
    if ano_min:
        cond += " AND CAST(ano AS INTEGER) >= ?"
        params.append(int(ano_min))
    primeira: dict[tuple, str] = {}
    for r in con.execute("SELECT unidade_gestora, cnpj_cpf, MIN(data_de_emissao) FROM cge_ne_credor GROUP BY 1, 2"):
        primeira[(r[0], r[1])] = r[2] or ""
    grupos: dict[tuple, dict] = {}
    for r in con.execute(f"SELECT * FROM cge_ne_credor {cond} ORDER BY data_de_emissao", params):
        proc = _processo_da_linha(r)
        chave = (r["unidade_gestora"], r["cnpj_cpf"], proc or r["nota_de_empenho"])
        g = grupos.get(chave)
        if g is None:
            g = grupos[chave] = {
                "processo": proc or f"NE {r['nota_de_empenho']}", "ug": r["unidade_gestora"],
                "credor": r["cnpj_cpf"], "credor_nome": r["credor"], "modalidade": r["tipo_de_licitacao"],
                "subitem": r["subitem"], "historico": r["historico"] or "", "ano": r["ano"], "valor": 0.0,
                "notas_empenho": [], "_inicio": r["data_de_emissao"] or ""}
        g["valor"] += float(r["despesas_empenhadas"] or 0)
        g["notas_empenho"].append(r["nota_de_empenho"])
    saida = []
    for (ug, credor, _), g in grupos.items():
        g["valor"] = round(g["valor"], 2)
        g["credor_novo_na_ug"] = bool(g["_inicio"]) and primeira.get((ug, credor), "") >= g["_inicio"]
        g.pop("_inicio")
        saida.append(g)
    return saida


def varrer(con: sqlite3.Connection, *, ano_min: int | None = None) -> list[ResultadoDetector]:
    """Roda o P7 sobre o painel inteiro e devolve só os disparos (`confirmado`)."""
    det = P7DiretaDeRisco()
    out = []
    for ctx in contextos_do_painel(con, ano_min=ano_min):
        r = det.avaliar(ctx)
        if r.status == "confirmado":
            r.valores.update({"ug": ctx["ug"], "credor": ctx["credor"], "notas_empenho": ctx["notas_empenho"]})
            out.append(r)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--db", default=os.environ.get("JFN_DB_DADOSABERTOS", "data/dadosabertos_rj.db"))
    ap.add_argument("--ano-min", type=int, default=None)
    ap.add_argument("--gravar", action="store_true", help="persiste em achados.db (achado_detector)")
    a = ap.parse_args(argv)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=30)
    try:
        res = varrer(con, ano_min=a.ano_min)
    finally:
        con.close()
    por_regra: dict[str, int] = {}
    for r in res:
        for g in r.valores["regras"]:
            por_regra[g] = por_regra.get(g, 0) + 1
    print(json.dumps({"disparos": len(res), "por_regra": por_regra}, ensure_ascii=False))
    if a.gravar and res:
        from compliance_agent.varredura_orgaos import _persistir, abrir_achados
        ca = abrir_achados()
        try:
            por_ug: dict[str, list] = {}
            for r in res:
                por_ug.setdefault(str(r.valores.get("ug") or "?"), []).append(r)
            n = sum(_persistir(ca, ug, "contratacao_direta", rs) for ug, rs in por_ug.items())
            ca.commit()
        finally:
            ca.close()
        print(json.dumps({"gravados": n}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
