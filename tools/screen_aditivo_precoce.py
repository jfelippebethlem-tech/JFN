#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aditivo de VALOR logo depois da assinatura — a assinatura de planejamento falho.

POR QUE EXISTE. Em 09/08/2026 a CGE apontou, na Secretaria das Cidades, um acréscimo de **45,4%
dezessete dias após a assinatura** de um contrato de pavimentação (R$ 99,6 mi → R$ 144,9 mi). O
raciocínio dela é o que este screen generaliza, com as palavras do próprio relatório: *"acréscimos
significativos logo no início da execução contratual podem indicar falha no planejamento da
contratação (subestimação deliberada do valor para aprovação do certame) ou direcionamento de
recursos adicionais à empresa previamente escolhida"*.

A casa **não conseguia** medir isso: `contrato_aditivo` não guardava a data do termo, embora o PNCP
a entregue em todo `dataAssinatura`. Corrigido o coletor, este é o consumidor.

O QUE SEPARA ACHADO DE RUÍDO, e está tudo declarado na saída:

  · **Só aditivo de VALOR conta.** Prorrogação (art. 107), reajuste e reequilíbrio (art. 124, II,
    "d") não são acréscimo de escopo — a natureza vem da régua única `limites_aditivo`, a mesma do
    X1 e do d11. Foi confundir isso que gerou 45% dos falsos positivos da varredura de execução.
  · **Prazo curto é o sinal.** Desequilíbrio econômico superveniente não se forma em duas semanas:
    quanto mais cedo o acréscimo, menos sustentável é a tese de recomposição e mais provável é que
    o valor do certame estivesse subestimado. O padrão é 90 dias, ajustável.
  · **O percentual não é veredito.** Acréscimo dentro dos 25% do art. 125 é lícito; o que este
    screen mede é a PRECOCIDADE, e ela vale mesmo abaixo do teto. Quando passa do teto, o caso
    acumula os dois problemas — e isso sai marcado.

    python -m tools.screen_aditivo_precoce --dias 90
    python -m tools.screen_aditivo_precoce --md --gravar
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
DIAS_PRECOCE = 90
MIN_ACRESCIMO = 50_000.0


def _dia(s: str | None) -> date | None:
    try:
        return datetime.strptime(str(s or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def medir(db: str = "", dias: int = DIAS_PRECOCE,
          min_acrescimo: float = MIN_ACRESCIMO) -> list[dict[str, Any]]:
    from compliance_agent.limites_aditivo import classificar_natureza, teto_acrescimo
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        linhas = con.execute(
            "SELECT a.numero_controle_pncp ncp, a.numero_termo, a.objeto, a.valor_acrescido, "
            "  a.data_assinatura d_termo, a.tipo_termo, a.processo, a.qualif_acrescimo, "
            "  a.qualif_vigencia, a.qualif_reajuste, a.fundamento_legal, a.prazo_aditado_dias, "
            "  c.data_assinatura d_contrato, c.valor_inicial, c.fornecedor_nome, c.orgao_nome, "
            "  c.objeto obj_contrato "
            "FROM contrato_aditivo a JOIN pcrj_contratos c "
            "  ON c.numero_controle_pncp = a.numero_controle_pncp "
            "WHERE a.data_assinatura IS NOT NULL AND c.data_assinatura IS NOT NULL").fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()

    fora = []
    for r in linhas:
        dt_t, dt_c = _dia(r["d_termo"]), _dia(r["d_contrato"])
        if not dt_t or not dt_c:
            continue
        atraso = (dt_t - dt_c).days
        if atraso < 0 or atraso > dias:
            continue
        natureza, origem = classificar_natureza(
            r["objeto"], fundamento_legal=r["fundamento_legal"],
            qualif_acrescimo=r["qualif_acrescimo"], qualif_vigencia=r["qualif_vigencia"],
            qualif_reajuste=r["qualif_reajuste"], prazo_aditado_dias=r["prazo_aditado_dias"])
        if natureza != "valor":
            continue                       # prorrogação/reajuste/reequilíbrio não é acréscimo
        acresc = float(r["valor_acrescido"] or 0)
        if acresc < min_acrescimo:
            continue
        inicial = float(r["valor_inicial"] or 0)
        pct = (acresc / inicial * 100) if inicial > 0 else None
        teto = teto_acrescimo("reforma" if "reforma" in (r["obj_contrato"] or "").lower() else None)
        fora.append({
            "contrato": r["ncp"], "termo": r["numero_termo"] or "",
            "orgao": r["orgao_nome"] or "", "fornecedor": r["fornecedor_nome"] or "",
            "assinado_em": str(r["d_contrato"])[:10], "aditado_em": str(r["d_termo"])[:10],
            "dias": atraso, "valor_inicial": round(inicial, 2), "acrescimo": round(acresc, 2),
            "pct": round(pct, 1) if pct is not None else None,
            # acima do teto do art. 125 acumula os DOIS problemas — precocidade e limite
            "acima_do_teto": bool(pct is not None and pct / 100 > teto),
            "teto_pct": round(teto * 100),
            "processo": r["processo"] or "", "objeto": (r["objeto"] or "")[:160],
            # de ONDE saiu a classificação — quem auditar o achado precisa saber
            "natureza_origem": origem,
        })
    fora.sort(key=lambda d: (d["dias"], -d["acrescimo"]))
    return fora


def cobertura(db: str = "") -> dict[str, Any]:
    """Quantos termos a casa consegue AVALIAR — sem isto, "0 achados" lê-se como "nada a apurar".

    DUAS restrições, e a que limita NÃO é a que eu declarava. A primeira é a data: o sinal depende de
    duas (contrato e termo), e a do termo só passou a ser guardada em 2026-08-09. Essa está em 95,1%.

    A segunda é o VALOR, e é ela que manda: o achado é "aditivo **de valor** nos primeiros N dias", e
    medido em 2026-08-10 **82,8% dos termos trazem `valorAcrescido` zero ou nulo** (o PNCP publica a
    linha do termo, não o que ela move — ver `limites_de_fonte`). Declarar só a cobertura de data faz
    "1 achado" parecer conclusão sobre o Estado inteiro quando é conclusão sobre um sexto dele.
    Publicar a folga errada é pior que não publicar folga nenhuma.
    """
    from compliance_agent.reporting.intel_base import _DB
    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=60)
    try:
        tot = con.execute("SELECT COUNT(*) FROM contrato_aditivo").fetchone()[0]
        com = con.execute("SELECT COUNT(*) FROM contrato_aditivo "
                          "WHERE data_assinatura IS NOT NULL").fetchone()[0]
        par = con.execute("SELECT COUNT(*) FROM contrato_aditivo a JOIN pcrj_contratos c "
                          "ON c.numero_controle_pncp = a.numero_controle_pncp "
                          "WHERE a.data_assinatura IS NOT NULL "
                          "AND c.data_assinatura IS NOT NULL").fetchone()[0]
        # o gargalo REAL: sem valor não há "aditivo de valor", por mais datas que existam
        com_valor = con.execute("SELECT COUNT(*) FROM contrato_aditivo a JOIN pcrj_contratos c "
                                "ON c.numero_controle_pncp = a.numero_controle_pncp "
                                "WHERE a.data_assinatura IS NOT NULL "
                                "AND c.data_assinatura IS NOT NULL "
                                "AND COALESCE(a.valor_acrescido,0) > 0").fetchone()[0]
    except sqlite3.OperationalError:
        return {"estado": "sem_dado"}
    finally:
        con.close()
    return {"estado": "medido", "termos": tot, "com_data_do_termo": com,
            "com_as_duas_datas": par,
            # `avaliaveis` e `pct` passam a significar o que a tela realmente consegue avaliar: com
            # data E com valor. Antes diziam 95,1% (só data) e faziam a folga parecer confortável.
            "avaliaveis": com_valor,
            "pct": round(100.0 * com_valor / tot, 1) if tot else 0.0,
            "pct_so_datas": round(100.0 * par / tot, 1) if tot else 0.0,
            "gargalo": "valor_acrescido ausente ou zero em 82,8% dos termos (limite do PNCP)"}


RESSALVA = (
    "Aditivo é lícito e acréscimo dentro dos 25% do art. 125 também. O que se mede aqui é a "
    "PRECOCIDADE: acréscimo de escopo logo após a assinatura enfraquece a tese de recomposição — "
    "desequilíbrio superveniente não se forma em duas semanas — e sugere valor de certame "
    "subestimado. Só termo de natureza VALOR entra (prorrogação, reajuste e reequilíbrio ficam "
    "fora, pela régua do art. 125). Indício a apurar nos autos: motivação, parecer jurídico e "
    "dotação. Cobertura: só contratos com aditivo coletado do PNCP e com as DUAS datas."
)


def markdown(itens: list[dict], dias: int) -> str:
    from compliance_agent.reporting.intel_base import moeda
    L = [f"# Aditivo de valor nos primeiros {dias} dias de contrato", "", f"> {RESSALVA}", "",
         "| Dias | Órgão | Fornecedor | Inicial | Acréscimo | % | Acima do teto |",
         "|---:|---|---|---:|---:|---:|---|"]
    for x in itens:
        L.append(f"| {x['dias']} | {x['orgao'][:26]} | {x['fornecedor'][:28]} | "
                 f"R$ {moeda(x['valor_inicial'])} | R$ {moeda(x['acrescimo'])} | "
                 f"{'—' if x['pct'] is None else f'{x['pct']:.1f}%'} | "
                 f"{'SIM (art. 125: ' + str(x['teto_pct']) + '%)' if x['acima_do_teto'] else 'não'} |")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=DIAS_PRECOCE)
    ap.add_argument("--min-acrescimo", type=float, default=MIN_ACRESCIMO)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--gravar", action="store_true")
    a = ap.parse_args(argv)
    itens = medir(dias=a.dias, min_acrescimo=a.min_acrescimo)[: a.top]
    if a.md or a.gravar:
        texto = markdown(itens, a.dias)
        print(texto)
        if a.gravar:
            alvo = _REPO / "data" / "aditivo_precoce.md"
            alvo.write_text(texto, encoding="utf-8")
            print(f"gravado: {alvo}")
    else:
        cob = cobertura()
        if cob.get("estado") == "medido":
            print(f"cobertura: {cob['avaliaveis']} de {cob['termos']} termos avaliáveis "
                  f"({cob['pct']}%) — com as duas datas E com valor")
        print(f"{len(itens)} aditivo(s) de VALOR nos primeiros {a.dias} dias:")
        for x in itens:
            pct = "—" if x["pct"] is None else f"{x['pct']:5.1f}%"
            print(f"   {x['dias']:3d}d  {x['fornecedor'][:30]:30} R$ {x['acrescimo']:>13,.2f} "
                  f"{pct} {'⚠ acima do teto' if x['acima_do_teto'] else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
