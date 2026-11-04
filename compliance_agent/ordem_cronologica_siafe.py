# -*- coding: utf-8 -*-
"""Quebra da ordem cronológica de pagamentos — medida no SIAFE, pela data da NL e por fonte de recursos.

BASE (texto conferido em 04/11/2026):
  • Lei 14.133/2021, art. 141 (Planalto) — "será observada a ordem cronológica para cada fonte diferenciada de
    recursos"; §1º alteração "mediante prévia justificativa da autoridade competente" e comunicação ao controle;
    §2º a inobservância imotivada "ensejará a apuração"; §3º publicação mensal da ordem e das justificativas.
  • Decreto RJ 49.134/2024 (LegisWeb; conferir no DOERJ antes de peça):
      – art. 9º: ordem "da data de emissão da Nota de Liquidação por fonte de recursos";
      – parágrafo único, a–o: naturezas FORA da ordem — a alínea o) exclui "todas aquelas que não se enquadram
        como fornecimento de bens, locações, realização de obras, prestação de serviços";
      – art. 10: alteração só com justificativa prévia (I emergência; II ME/EPP com risco de descontinuidade;
        III sistemas estruturantes; IV falência/RJ; V integridade do patrimônio); §2º apuração de responsabilidade.

UNIVERSO (alínea o lida como lista POSITIVA): NL Contabilizada cuja NE é de elemento 30 (material), 35
(consultoria), 37 (locação de mão de obra), 39 (serviços PJ), 40 (TIC), 51 (obras) ou 52 (equipamentos), a
credor CNPJ privado (natureza ≠ 1xxx — alínea n) fora de concessionária/combustível (CNAE 35, 36, 61, 4731,
4681 — alínea g). Pessoal, diárias, sentenças, tributos, indenizações e bolsistas ficam fora pela natureza.

O TESTE. Na mesma UG, fonte e ANO DA NL (RP tem fila própria, arts. 22–23), a NL A foi PRETERIDA quando foi
liquidada ANTES de B e B foi paga (1ª OB Contabilizada) antes de A — o achado é A (quem esperou), com a lista
de quem furou; A paga DEPOIS (as duas OBs na base). `dias_esperando` = quanto A esperou depois que B foi paga. A sem OB na
base vai para `pendentes` — cobertura parcial da OB não prova falta de pagamento. Só UGs com NE e NL
COMPLETAS (`siafe_documento_cobertura`).

LIMITES. Indício: o art. 10 permite alterar a ordem com justificativa prévia (ME/EPP, emergência…) — a
justificativa tem de existir no processo e estar publicada (art. 10 §3º). Só UGs com NE e NL coletadas
(`compliance_agent/siafe_documento.py`); "sem pagamento" é piso de cobertura da OB SIAFE, não prova.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_ELEMENTOS = {"30", "35", "37", "39", "40", "51", "52"}
_CNAE_FORA = ("35", "36", "61", "4731", "4681")

_DIAS_FORTE, _DIAS_MEDIO = 30, 10
_NAT_ESTATAL = ("2011", "2038")   # empresa pública / SEM — alíneas m) e n); conservador: pode excluir estatal federal

_SQL = """SELECT l.numero, l.ug_emitente, l.exercicio, l.ano_nl, l.data_emissao, l.credor, l.nome_credor, l.valor, l.processo,
                 e.fonte, e.natureza,
                 (SELECT MIN(substr(o.data_emissao,7,4)||'-'||substr(o.data_emissao,4,2)||'-'||substr(o.data_emissao,1,2))
                    FROM ob_orcamentaria_siafe o WHERE o.nl=l.numero AND o.ug_emitente=l.ug_emitente
                     AND o.status='Contabilizado') AS pago_em
          FROM nl_siafe l JOIN ne_siafe e ON e.numero=l.ne AND e.ug_emitente=l.ug_emitente AND e.exercicio=l.exercicio
          WHERE l.status='Contabilizado' AND l.valor>0 AND length(l.credor)=14 AND e.fonte<>''"""


def _iso(d: str) -> str:
    return f"{d[6:10]}-{d[3:5]}-{d[0:2]}" if d and len(d) >= 10 else ""


def _dias(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def ordem_cronologica(db_path=None, estab_path=None, hoje: str | None = None) -> dict:
    hoje = hoje or date.today().isoformat()
    con = sqlite3.connect(f"file:{db_path or _REPO / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row      # por NOME: incluir `ano_nl` no SELECT deslocou o credor e zerou tudo calado
    try:
        from compliance_agent.siafe_documento import ugs_completas
        completas = ugs_completas(con)      # só UG com NE E NL inteiras: coleta capada fabricava quebra
        linhas = [r for r in con.execute(_SQL).fetchall() if (str(r["ug_emitente"]), int(r["exercicio"])) in completas]
    finally:
        con.close()
    est = sqlite3.connect(f"file:{estab_path or _REPO / 'data' / 'receita_estab.db'}?mode=ro", uri=True, timeout=30)
    cad = {}
    try:
        for b in {r["credor"][:8] for r in linhas}:
            n = est.execute("SELECT natureza_cod FROM empresas WHERE cnpj_basico=?", (b,)).fetchone()
            c = est.execute("SELECT cnae_principal FROM estabelecimentos WHERE cnpj_basico=? AND matriz_filial='1'",
                            (b,)).fetchone()
            cad[b] = (str(n[0]) if n and n[0] else "", str(c[0]) if c and c[0] else "")
    finally:
        est.close()

    filas: dict[tuple, list[dict]] = defaultdict(list)
    for r in linhas:
        nl, ug, ano, dia, credor = r["numero"], r["ug_emitente"], r["ano_nl"], r["data_emissao"], r["credor"]
        nome, valor, proc, fonte, natureza, pago = (r["nome_credor"], r["valor"], r["processo"], r["fonte"],
                                                    r["natureza"], r["pago_em"])
        nat, cnae = cad.get(credor[:8], ("", ""))
        if ((natureza or "")[4:6] not in _ELEMENTOS or not nat or nat.startswith("1") or nat in _NAT_ESTATAL
                or cnae.startswith(_CNAE_FORA)):
            continue
        # fila por UG, FONTE e ANO DA NL: Restos a Pagar têm ordem própria (Dec. 49.134 arts. 22–23, quebra com
        # autorização do CPDP) — misturar RP de 2019 com NL de 2025 fabricava "furou a fila" (04/11/2026).
        filas[(ug, fonte, ano)].append({"nl": nl, "liquidada": _iso(dia), "pago_em": pago, "credor": credor,
                                   "nome": nome, "valor": valor, "processo": proc, "natureza": natureza})
    # UNIDADE DO ACHADO = a NL PRETERIDA (o credor que esperou na fila), com quem passou na frente dela.
    # Contar por quem furou repetia a mesma vítima uma vez por fura-fila: na 166100, 29 "fortes" eram UMA NL.
    achados, pendentes = [], set()
    for (ug, fonte, ano), fila in filas.items():
        pagas = [x for x in fila if x["pago_em"]]
        for a in fila:
            furaram = [b for b in pagas if b is not a and b["liquidada"] > a["liquidada"]
                       and (not a["pago_em"] or b["pago_em"] < a["pago_em"])]
            if not furaram:
                continue
            if not a["pago_em"]:
                # sem OB na base NÃO prova que não pagou (a cobertura da OB SIAFE é parcial): conferir à parte
                pendentes.add(a["nl"])
                continue
            primeiro = min(b["pago_em"] for b in furaram)
            furaram.sort(key=lambda b: -b["valor"])
            achados.append({**a, "ug": ug, "fonte": fonte, "ano_nl": ano, "n_furaram": len(furaram),
                            "valor_que_passou": round(sum(b["valor"] for b in furaram), 2),
                            "espera_max_dias": _dias(primeiro, a["pago_em"]),
                            "furaram": [{"nl": b["nl"], "nome": b["nome"], "liquidada": b["liquidada"],
                                         "pago_em": b["pago_em"], "valor": b["valor"]} for b in furaram[:10]]})
    # Espera de poucos dias é agenda, não quebra: a PD vai ao Tesouro com 2 dias úteis de antecedência
    # (Dec. 49.134 art. 14 §3º). Medido no ITERJ/2025: as 10 inversões tinham 1–6 dias.
    curtas = [x for x in achados if x["espera_max_dias"] < _DIAS_MEDIO]
    achados = [x for x in achados if x["espera_max_dias"] >= _DIAS_MEDIO]
    for x in achados:
        x["forca"] = "forte" if x["espera_max_dias"] >= _DIAS_FORTE else "medio"
    achados.sort(key=lambda x: (-x["espera_max_dias"], -x["valor_que_passou"]))
    return {"ok": True, "n": len(achados), "ugs_cobertas": sorted({u for u, _, _ in filas}),
            "por_forca": {k: sum(x["forca"] == k for x in achados) for k in ("forte", "medio")},
            "inversoes_curtas": len(curtas),
            "pendentes": len(pendentes),
            "nota": "Indício a verificar, não acusação: o Decreto RJ 49.134/2024 (art. 9º) manda pagar na ordem da "
                    "data da NL por fonte; o art. 10 admite alterar com justificativa prévia (ME/EPP, emergência…), "
                    "que tem de estar no processo e publicada. Só UGs com NE e NL coletadas.",
            "achados": achados}
