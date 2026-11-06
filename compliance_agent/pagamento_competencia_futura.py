# -*- coding: utf-8 -*-
"""OB paga ANTES da competência que ela quita — pagamento antecipado ou competência registrada errada.

POR QUE EXISTE (04/11/2026). O campo `competencia` da OB SIAFE nunca era lido. Medido na base: 639 OBs
a credores privados pagas para competência futura (R$ 99,32 mi), de 1 a 33 meses à frente — LEFE
EMERGÊNCIAS MÉDICAS recebeu R$ 6,39 mi em 01/11/2024 por competência 08/2027.

BASE (texto conferido no Planalto em 04/11/2026):
  • Lei 14.133/2021, art. 145 — "Não será permitido pagamento antecipado, parcial ou total, relativo a
    parcelas contratuais"; §1º "A antecipação de pagamento somente será permitida se propiciar sensível
    economia de recursos" (ler o §1º inteiro antes de peça); §2º garantia adicional; §3º devolução se não executado.
  • Lei 4.320/1964, art. 62 — "O pagamento da despesa só será efetuado quando ordenado após sua regular
    liquidação"; art. 63 §2º — liquidação com base nos "comprovantes da entrega do material ou da prestação
    efetiva do serviço". Pagar competência que ainda não ocorreu não tem o que liquidar.

O QUE NÃO CONTA (calibrado no dado real):
  • ente público (natureza 1xxx) e credor que não é CNPJ (UG, CG da folha, BJ de bloqueio judicial);
  • concessionária de energia, gás, água e telecom (CNAE 35, 36, 61) — naturezas excepcionadas pelo
    Decreto RJ 49.134/2024, art. 9º, parágrafo único;
  • organização social (natureza 3999/3069) a 1 mês — repasse mensal antecipado do contrato de gestão.

FORÇA: forte = empresa paga 2–12 meses antes; medio = mais de 12 meses (implausível: erro de registro
ou antecipação — os dois são falha de controle); fraco = 1 mês, ou RP com o ano trocado (pago em jan–mar
por competência out–dez do mesmo ano — `provavel_ano_trocado`).

LIMITES. Indício, não acusação: o contrato pode prever antecipação nos termos do art. 145 §1º, e a
competência pode estar digitada errada no SIAFE. Só o processo SEI da OB fecha.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CNAE_CONCESSIONARIA = ("35", "36", "61")
_NAT_OS = ("3999", "3069")

_SQL = ("SELECT numero_ob, ug_emitente, credor, nome_credor, valor, data_emissao, competencia, processo, "
        "(CAST(substr(competencia,4,4) AS INT)*12 + CAST(substr(competencia,1,2) AS INT)) - "
        "(CAST(substr(data_emissao,7,4) AS INT)*12 + CAST(substr(data_emissao,4,2) AS INT)) AS meses "
        "FROM ob_orcamentaria_siafe WHERE status='Contabilizado' AND valor>0 AND length(credor)=14 "
        "AND competencia GLOB '[0-9][0-9]/[0-9][0-9][0-9][0-9]' "
        "AND data_emissao GLOB '[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]' AND meses > 0")


def _forca(meses: int) -> str:
    return "medio" if meses > 12 else "forte" if meses >= 2 else "fraco"


def pagamento_competencia_futura(db_path=None, estab_path=None) -> dict:
    con = sqlite3.connect(f"file:{db_path or _REPO / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=30)
    try:
        obs = con.execute(_SQL).fetchall()
    finally:
        con.close()
    est = sqlite3.connect(f"file:{estab_path or _REPO / 'data' / 'receita_estab.db'}?mode=ro", uri=True, timeout=30)
    cad: dict[str, tuple] = {}
    try:
        for b in {o[2][:8] for o in obs}:
            n = est.execute("SELECT natureza_cod FROM empresas WHERE cnpj_basico=?", (b,)).fetchone()
            c = est.execute("SELECT cnae_principal FROM estabelecimentos WHERE cnpj_basico=? AND matriz_filial='1'",
                            (b,)).fetchone()
            cad[b] = (str(n[0]) if n and n[0] else "", str(c[0]) if c and c[0] else "")
    finally:
        est.close()

    grupos: dict[tuple, dict] = defaultdict(lambda: {"valor": 0.0, "obs": [], "meses_max": 0})
    for num, ug, credor, nome, valor, dia, comp, proc, meses in obs:
        nat, cnae = cad.get(credor[:8], ("", ""))
        if not nat or nat.startswith("1") or cnae.startswith(_CNAE_CONCESSIONARIA):
            continue
        if nat in _NAT_OS and meses == 1:
            continue
        # pago em jan–mar por competência out–dez do MESMO ano: RP do ano anterior com o ano trocado
        # (04/11/2026: 39 de 57 OBs da faixa de 10–12 meses) — falha de registro, não antecipação
        ano_trocado = int(dia[3:5]) <= 3 and int(comp[:2]) >= 10 and comp[3:] == dia[6:]
        g = grupos[(credor, ug)]
        g.setdefault("_so_ano_trocado", True)
        g["_so_ano_trocado"] = g["_so_ano_trocado"] and ano_trocado
        g.update(credor_cnpj=credor, nome=nome, ug=ug, natureza=nat, cnae=cnae)
        g["valor"] += valor
        if not ano_trocado:              # a força sai só do que é antecipação plausível
            g["meses_max"] = max(g["meses_max"], meses)
        g["obs"].append({"numero_ob": num, "pago_em": dia, "competencia": comp, "meses": meses,
                         "valor": round(valor, 2), "processo": proc, "provavel_ano_trocado": ano_trocado})
    achados = []
    for g in grupos.values():
        g["valor"] = round(g["valor"], 2)
        g["provavel_ano_trocado"] = g.pop("_so_ano_trocado")
        g["forca"] = "fraco" if g["provavel_ano_trocado"] else _forca(g["meses_max"])
        g["n_obs"] = len(g["obs"])
        g["obs"] = sorted(g["obs"], key=lambda o: -o["valor"])[:10]
        achados.append(g)
    ordem = {"forte": 0, "medio": 1, "fraco": 2}
    achados.sort(key=lambda a: (ordem[a["forca"]], -a["valor"]))
    return {"ok": True, "n": len(achados), "por_forca": {k: sum(a["forca"] == k for a in achados) for k in ordem},
            "valor_total": round(sum(a["valor"] for a in achados), 2),
            "nota": "Indício a verificar, não acusação: o contrato pode prever antecipação (L.14.133 art. 145 §1º) "
                    "e a competência pode estar registrada com o ano errado — até 12 meses, isso explica o caso "
                    "tanto quanto a antecipação; a data de emissão da NL decide. OB SIAFE Contabilizada.",
            "achados": achados}
