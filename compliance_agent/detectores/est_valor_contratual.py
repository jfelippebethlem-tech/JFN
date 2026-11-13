# -*- coding: utf-8 -*-
"""Valor contratual excedido sem aditivo e aditivo acima do teto do art. 125 — ESFERA ESTADUAL.

POR QUE EXISTE. O confronto CGE × JFN de 13/11/2026 (vault `notas/cge-irregularidades-x-jfn-2026-11-13`,
lacuna 5) achou dois casos estaduais que o JFN não viu primeiro: contrato pago acima do valor sem aditivo e
aditivo de 45,4% num contrato de obra. O detector equivalente só existia no município (`pcrj/pericia_gastos.d11`,
sobre a base do PNCP). No Estado, a ponte contrato ↔ pagamento que funciona é o contrato do TCE-RJ
(`contratos_tcerj`: processo SEI + CNPJ + valor) × a OB do SIAFE (`ob_orcamentaria_siafe`: processo + credor).
A ponte por `contrato_aditivo.processo` foi medida e reprovada em 2026-08-11 (13 casamentos; ver
`varredura_execucao`); a ponte TCE-RJ × SIAFE casou 58 de 300 contratos sorteados (19%) em 13/11/2026 — o resto
é contrato sem OB ainda ou com processo de pagamento diferente do processo de contratação. É cobertura PARCIAL,
declarada, não universo.

DOIS ACHADOS:
  `EST-VALOR-EXCEDIDO` — Σ OB Contabilizada (mesmo credor E mesmo processo) acima do valor contratado mais o que
      os aditivos conhecidos acrescem (acréscimo do art. 125 e reajuste/reequilíbrio, que também mudam o valor).
      Com os aditivos conhecidos e excedente acima do teto do art. 125 → 'forte' (nem aditivo regular cobriria);
      senão 'medio'. Sem aditivos
      coletados, a lacuna é DECLARADA (`aditivos_nao_coletados`): não coletado ≠ inexistente, e reajuste por
      apostila (art. 136) muda o valor sem aditivo.
  `EST-ADITIVO-TETO` — acréscimo de valor (natureza pela régua única `limites_aditivo.classificar_natureza`) acima
      do teto: 25%, ou 50% em reforma de edifício/equipamento (`limites_aditivo`, fonte única) → 'critico'
      (violação objetiva); com lacuna de natureza (termo misto/sem natureza) → 'forte'.

HONESTIDADE. Pago = só OB Contabilizada do SIAFE (empenho ≠ liquidação ≠ OB). `valor_contrato` do TCE-RJ pode ser
o valor inicial ou o atualizado — a fonte não diz; está na explicação inocente. Indício ≠ acusação.

CALLER. `python -m compliance_agent.detectores.est_valor_contratual [--limite N] [--gravar]` (leitura do
compliance.db; `--gravar` persiste em `achados.db`, `achado_detector`).
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from compliance_agent.detectores.base import ResultadoDetector, ancora
from compliance_agent.limites_aditivo import acrescimo_computavel, ato_normativo, estouro, teto_acrescimo, tipo_objeto
from compliance_agent.reporting.intel_base import moeda

TOL_CENTAVOS = 0.02          # materialidade de arredondamento (R$), a mesma da auditoria de contrato

_RX_PROC = re.compile(r"(\d{6})\D*(\d{6})\D*(\d{4}|\d{2})(?!\d)")


def processo_canonico(s: str | None) -> str | None:
    """Nº de processo SEI → 'UUUUUUNNNNNNAAAA'. O SIAFE grava o ano com 2 ou 4 dígitos ('…/24' e '…/2024')."""
    m = _RX_PROC.search(s or "")
    if not m:
        return None
    ano = m.group(3)
    return m.group(1) + m.group(2) + (ano if len(ano) == 4 else "20" + ano)


def _pago(contrato: dict, obs: list[dict]) -> tuple[float, int]:
    alvo = processo_canonico(contrato.get("processo"))
    cnpj = re.sub(r"\D", "", str(contrato.get("cnpj") or ""))
    soma, n = 0.0, 0
    for o in obs:
        if not str(o.get("status") or "").lower().startswith("contabiliz"):
            continue
        if re.sub(r"\D", "", str(o.get("credor") or "")) != cnpj:
            continue
        if processo_canonico(o.get("processo")) != alvo:
            continue
        soma += float(o.get("valor") or 0)
        n += 1
    return round(soma, 2), n


def avaliar(contrato: dict, obs: list[dict], aditivos: list[dict] | None = None) -> list[ResultadoDetector]:
    """Os dois testes sobre UM contrato. `aditivos=None` = não coletados (lacuna declarada), `[]` = nenhum."""
    proc = str(contrato.get("processo") or contrato.get("id") or "?")
    vc = contrato.get("valor_contrato")
    if not vc or float(vc) <= 0 or not processo_canonico(contrato.get("processo")):
        motivo = "nao_avaliavel: contrato sem valor ou sem processo SEI reconhecível (INDISPONÍVEL ≠ 0)"
        return [ResultadoDetector(detector=d, processo=proc, motivo_refutacao=motivo)
                for d in ("EST-VALOR-EXCEDIDO", "EST-ADITIVO-TETO")]
    vc = float(vc)
    tipo = tipo_objeto(contrato.get("objeto"))
    teto = teto_acrescimo(tipo)
    comp = acrescimo_computavel(aditivos) if aditivos is not None else None
    base = {"valor_contrato": vc, "teto": teto, "tipo_objeto": tipo or "padrao", "ato": ato_normativo(),
            "unidade": contrato.get("unidade"), "cnpj": contrato.get("cnpj"), "contrato_id": contrato.get("id")}
    inocente = ("O valor do TCE-RJ pode ser o INICIAL (sem os aditivos e apostilas posteriores); reajuste por "
                "apostila (art. 136) e aditivo não coletado aumentam o valor sem aparecer aqui; OB do mesmo processo "
                "pode pagar contrato sucessor. Conferir o histórico do contrato nos autos antes de concluir.")
    saida: list[ResultadoDetector] = []

    # ── valor excedido ──
    pago, n_ob = _pago(contrato, obs)
    coberto = vc
    lacunas: list[str] = []
    if comp is None:
        lacunas.append("aditivos_nao_coletados")
    else:
        coberto += comp["acrescimo"] + sum(v for k, v in comp["fora_do_teto"].items() if k in ("reajuste", "misto"))
        lacunas += comp["lacunas"]
    r = ResultadoDetector(detector="EST-VALOR-EXCEDIDO", processo=proc, explicacao_inocente=inocente)
    excedente = pago - coberto
    r.valores = {**base, "pago_ob_contabilizada": pago, "n_ob": n_ob, "valor_coberto": round(coberto, 2),
                 "excedente": round(excedente, 2), "pct_excedente": round(100 * (pago / vc - 1), 2),
                 "lacunas": lacunas}
    if excedente > TOL_CENTAVOS:
        r.status = "confirmado"
        # 'forte' só com os aditivos CONHECIDOS: sem eles, o excedente pode ser aditivo não coletado (medido em
        # 13/11/2026: 390 de 493 disparos seriam 'forte' às cegas — ruído, não sinal)
        r.score = ancora("forte" if comp is not None and pago / vc - 1 > teto else "medio")
        r.add_evidencia(
            "ob_orcamentaria_siafe × contratos_tcerj",
            f"R$ {moeda(pago)} pagos em {n_ob} OB Contabilizada(s) ao credor do contrato, no processo {proc}, contra "
            f"R$ {moeda(vc)} contratados" + (f" (R$ {moeda(coberto)} com os aditivos conhecidos)" if comp else "")
            + f" — excedente de R$ {moeda(excedente)} ({100 * (pago / vc - 1):.1f}% sobre o contratado)"
            + (f", acima do teto de {teto:.0%} do {ato_normativo()}" if pago / vc - 1 > teto else "")
            + ("; aditivos do contrato NÃO coletados (não coletado ≠ inexistente)" if comp is None else ""))
    else:
        r.status = "descartado"
        r.motivo_refutacao = f"pago (R$ {moeda(pago)}) dentro do valor coberto (R$ {moeda(coberto)})"
    saida.append(r)

    # ── aditivo acima do teto ──
    t = ResultadoDetector(detector="EST-ADITIVO-TETO", processo=proc, explicacao_inocente=inocente)
    if comp is None:
        t.motivo_refutacao = "nao_avaliavel: aditivos do contrato não coletados (não coletado ≠ inexistente)"
        t.valores = dict(base)
    else:
        e = estouro(vc, aditivos, tipo)
        t.valores = {**base, "acrescimo": round(e["acrescimo"], 2), "pct": e["pct"], "lacunas": e["lacunas"]}
        if e["estourou"]:
            t.status = "confirmado"
            t.score = ancora("forte" if e["lacunas"] else "critico")
            t.add_evidencia("contrato_aditivo (PNCP) × contratos_tcerj",
                            f"acréscimo de R$ {moeda(e['acrescimo'])} = {100 * e['pct']:.1f}% do valor contratado "
                            f"(R$ {moeda(vc)}), acima do teto de {teto:.0%} do {e['ato']}"
                            + (" (reforma de edifício/equipamento)" if tipo else ""))
        else:
            t.status = "descartado"
            t.motivo_refutacao = f"acréscimo {100 * (e['pct'] or 0):.1f}% ≤ teto de {teto:.0%}"
    saida.append(t)
    return saida


def varrer(con: sqlite3.Connection, *, limite: int | None = None) -> list[ResultadoDetector]:
    """Contratos do TCE-RJ × OB do SIAFE (uma consulta por credor, pelo índice `credor`). Devolve os disparos."""
    con.row_factory = sqlite3.Row
    aditivos: dict[str, list[dict]] = {}
    try:
        for a in con.execute("SELECT * FROM contrato_aditivo WHERE processo IS NOT NULL AND processo != ''"):
            k = processo_canonico(a["processo"])
            if k:
                aditivos.setdefault(k, []).append(dict(a))
    except sqlite3.OperationalError:
        aditivos = {}
    sql = ("SELECT id, processo, valor_contrato, cnpj, objeto, unidade, fornecedor FROM contratos_tcerj "
           "WHERE valor_contrato > 0 AND length(cnpj) = 14 AND processo IS NOT NULL ORDER BY cnpj")
    contratos = [dict(r) for r in con.execute(sql + (f" LIMIT {int(limite)}" if limite else ""))]
    obs_por_credor: dict[str, list[dict]] = {}
    out: list[ResultadoDetector] = []
    for c in contratos:
        if c["cnpj"] not in obs_por_credor:
            obs_por_credor.clear()            # contratos vêm ordenados por CNPJ: guarda só o credor corrente
            obs_por_credor[c["cnpj"]] = [dict(o) for o in con.execute(
                "SELECT numero_ob, status, credor, processo, valor FROM ob_orcamentaria_siafe WHERE credor = ?",
                (c["cnpj"],))]
        ads = aditivos.get(processo_canonico(c["processo"]) or "")
        out += [r for r in avaliar(c, obs_por_credor[c["cnpj"]], ads) if r.status == "confirmado"]
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--db", default=os.environ.get("JFN_DB", "data/compliance.db"))
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--gravar", action="store_true", help="persiste em achados.db (achado_detector)")
    a = ap.parse_args(argv)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=30)
    try:
        res = varrer(con, limite=a.limite)
    finally:
        con.close()
    resumo: dict[str, Any] = {}
    for r in res:
        resumo[r.detector] = resumo.get(r.detector, 0) + 1
    print(json.dumps({"disparos": resumo}, ensure_ascii=False))
    if a.gravar and res:
        from compliance_agent.varredura_orgaos import _persistir, abrir_achados
        ca = abrir_achados()
        try:
            por_ug: dict[str, list] = {}
            for r in res:
                por_ug.setdefault(str(r.valores.get("unidade") or "?"), []).append(r)
            n = sum(_persistir(ca, ug, "contrato_estadual", rs) for ug, rs in por_ug.items())
            ca.commit()
        finally:
            ca.close()
        print(json.dumps({"gravados": n}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
