# -*- coding: utf-8 -*-
"""Indicadores de risco da Open Contracting Partnership (guia "Red flags in public procurement", 2024)
aplicados ao ContasRio (contasrio_contrato). Fonte da metodologia:
https://www.open-contracting.org/resources/red-flags-in-public-procurement-a-guide-to-using-data-to-detect-and-mitigate-risks/

R052 — compra pequena seguida de compra muito maior (mesmo fornecedor, mesmo comprador).
  Diferença relativa (2º − 1º)/1º acima da cerca de Tukey Q3 + 1,5·IQR calculada na própria base
  (medido 22/09/2026 sobre 1.879 pares: cerca 3,28 na diferença relativa ≈ 4,3× o primeiro), com o 2º contrato ≥ R$ 1 mi.
  🔴 quando o 1º contrato foi CONTRATAÇÃO DIRETA e o 2º veio em até 365 dias (o "fornecedor-teste"
  do guia: entra sem disputa e depois leva o grande); 🟡 nos demais.
R050 — participação alta no comprador (> 40% do valor contratado pelo órgão no ano). Medido: acende em
  55% dos órgãos-ano com ≥ 5 fornecedores — NÃO discrimina sozinho (regra de prevalência da casa);
  entra só como atributo do sinal R052, nunca como sinal próprio.
R068 — pagamento acima do valor do contrato. Medido: 2 de 14.254 (o valor "atualizado" do ContasRio já
  incorpora aditivos). Controle negativo, registrado aqui e não calculado.

Estatais/entes públicos ficam fora (contratam direto por natureza). Indício, não acusação.

    python -m tools.pcrj_ocp_redflags            # recalcula pcrj_ocp_sinal
    python -m tools.pcrj_ocp_redflags --top 20
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime

from compliance_agent.lex_conflito import _eh_estatal
from compliance_agent.pcrj import db as pcrj_db

VALOR_MIN_SEGUNDO = 1_000_000
# valor simbólico (R$ 0,10 · R$ 1 · R$ 5) é placeholder de registro, não compra: fabricava razões de 50 milhões×
VALOR_MIN_PRIMEIRO = 10_000
# mesmo dia (ou quase) = instrumentos complementares do mesmo processo, não o 'fornecedor-teste'
DIAS_MIN = 7
JANELA_RAPIDA_DIAS = 365
LIMIAR_R050 = 0.40

DDL = """CREATE TABLE IF NOT EXISTS pcrj_ocp_sinal (
    indicador TEXT NOT NULL, favorecido_doc TEXT NOT NULL, favorecido_nome TEXT, orgao TEXT,
    contrato_1 TEXT, processo_1 TEXT, forma_1 TEXT, valor_1 REAL, inicio_1 TEXT,
    contrato_2 TEXT NOT NULL, processo_2 TEXT, forma_2 TEXT, valor_2 REAL, inicio_2 TEXT,
    razao REAL, dias INTEGER, share_orgao_ano REAL, grau TEXT, detalhe TEXT, gerado_em TEXT,
    PRIMARY KEY (indicador, contrato_2));"""


def _data(s):
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y")
    except ValueError:
        return None


def cerca_tukey(valores: list[float]) -> float | None:
    """Q3 + 1,5·IQR (quartis por posição, como no guia). None com menos de 8 pontos."""
    v = sorted(valores)
    if len(v) < 8:
        return None
    q1, q3 = v[len(v) // 4], v[(3 * len(v)) // 4]
    return q3 + 1.5 * (q3 - q1)


def _brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def graduar_r052(forma_1: str | None, dias: int | None) -> str:
    if (forma_1 or "").startswith("Contratação Direta") and dias is not None and 0 <= dias <= JANELA_RAPIDA_DIAS:
        return "🔴"
    return "🟡"


def pares(contratos: list[dict]) -> list[tuple[dict, dict]]:
    """(1º, 2º) por fornecedor × órgão, em ordem de início de vigência (ou publicação)."""
    grupos: dict[tuple, list] = {}
    for c in contratos:
        t = _data(c.get("vigencia_ini")) or _data(c.get("data_publicacao"))
        if t and c.get("favorecido_doc") and (c.get("valor_atualizado") or 0) > 0:
            grupos.setdefault((c["favorecido_doc"], (c.get("orgao") or "")[:4]), []).append((t, c))
    saida = []
    for lst in grupos.values():
        if len(lst) >= 2:
            lst.sort(key=lambda x: x[0])
            saida.append((dict(lst[0][1], _t=lst[0][0]), dict(lst[1][1], _t=lst[1][0])))
    return saida


def calcular(db_path=None) -> dict:
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    con.row_factory = sqlite3.Row
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        contratos = [dict(r) for r in con.execute(
            "SELECT contrato, favorecido_doc, favorecido_nome, orgao, ano, forma_contratacao, valor_atualizado, "
            "vigencia_ini, data_publicacao, processo FROM contasrio_contrato WHERE favorecido_doc IS NOT NULL")]
        # R050 como atributo: participação do fornecedor no valor contratado pelo órgão no ano
        tot, forn = {}, {}
        for c in contratos:
            k = ((c.get("orgao") or "")[:4], c.get("ano"))
            v = c.get("valor_atualizado") or 0
            tot[k] = tot.get(k, 0) + v
            forn[(k, c["favorecido_doc"])] = forn.get((k, c["favorecido_doc"]), 0) + v
        ps = pares(contratos)
        razoes = [(b["valor_atualizado"] - a["valor_atualizado"]) / a["valor_atualizado"] for a, b in ps
                  if a["valor_atualizado"] >= VALOR_MIN_PRIMEIRO]
        cerca = cerca_tukey(razoes)
        con.executescript("DROP TABLE IF EXISTS pcrj_ocp_sinal;" + DDL)
        n = {"🔴": 0, "🟡": 0}
        for a, b in ps:
            if (cerca is None or b["valor_atualizado"] < VALOR_MIN_SEGUNDO or a["valor_atualizado"] < VALOR_MIN_PRIMEIRO
                    or _eh_estatal(b.get("favorecido_nome")) or (b["_t"] - a["_t"]).days < DIAS_MIN):
                continue
            razao = (b["valor_atualizado"] - a["valor_atualizado"]) / a["valor_atualizado"]
            if razao <= cerca:
                continue
            dias = (b["_t"] - a["_t"]).days
            grau = graduar_r052(a.get("forma_contratacao"), dias)
            k = ((b.get("orgao") or "")[:4], b.get("ano"))
            share = (forn.get((k, b["favorecido_doc"]), 0) / tot[k]) if tot.get(k) else None
            detalhe = (f"1º contrato {_brl(a['valor_atualizado'])} ({a.get('forma_contratacao')}, {a.get('vigencia_ini') or a.get('data_publicacao')}) → "
                       f"2º {_brl(b['valor_atualizado'])} ({b.get('forma_contratacao')}) em {dias} dias: {razao + 1:.1f}× o primeiro"
                       + (f"; fornecedor tem {share:.0%} do valor contratado pelo órgão no ano" if share and share > LIMIAR_R050 else ""))
            con.execute("INSERT OR REPLACE INTO pcrj_ocp_sinal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("R052", b["favorecido_doc"], b.get("favorecido_nome"), b.get("orgao"), a["contrato"], a.get("processo"),
                         a.get("forma_contratacao"), a["valor_atualizado"], a.get("vigencia_ini") or a.get("data_publicacao"),
                         b["contrato"], b.get("processo"), b.get("forma_contratacao"), b["valor_atualizado"],
                         b.get("vigencia_ini") or b.get("data_publicacao"), round(razao + 1, 2), dias,
                         round(share, 4) if share is not None else None, grau, detalhe, agora))
            n[grau] += 1
        con.commit()
    finally:
        con.close()
    return {"pares": len(ps), "cerca_tukey": round(cerca, 2) if cerca else None, "sinais_r052": n}


def listar(top: int = 50, db_path=None) -> list[dict]:
    con = pcrj_db.conectar(db_path)
    con.row_factory = sqlite3.Row
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='pcrj_ocp_sinal'").fetchone():
            return []
        return [dict(r) for r in con.execute("SELECT * FROM pcrj_ocp_sinal ORDER BY CASE grau WHEN '🔴' THEN 0 ELSE 1 END, valor_2 DESC LIMIT ?", (top,))]
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=0)
    a = ap.parse_args()
    import json
    if a.top:
        for r in listar(a.top):
            print(f"{r['grau']} {r['favorecido_nome'][:34]:34} {r['orgao'][:28]:28} {r['detalhe'][:150]}")
        return
    print(json.dumps(calcular(), ensure_ascii=False))


if __name__ == "__main__":
    main()
