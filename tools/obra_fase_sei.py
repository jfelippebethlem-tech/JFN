#!/usr/bin/env python3
"""Análise inteligente da FASE FÍSICA de obra por processo SEI (perícia).

A perícia financeira (% pago, parada/vencida) sai de `pericia_obras.py`. A FASE FÍSICA real
(fundação/estrutura/acabamento/concluída/parada) exige LER e raciocinar sobre cada processo SEI —
aqui um LLM free (groq) classifica a fase a partir do objeto + análise dos autos (sei_ficha).
Honestidade: se os autos NÃO evidenciam avanço físico (só liquidação/empenho), fase=INDETERMINADO
(INDISPONÍVEL≠concluída). Resumível (pula o que já tem fase). Volume → modelo free.

Uso: python -m tools.obra_fase_sei [--limite N]
"""
import argparse
import json
import os
import sqlite3
from compliance_agent.llm import free_llm

DB = os.environ.get("JFN_DB") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "compliance.db")
FASES = ["NAO_INICIADA", "PROJETO", "FUNDACAO", "ESTRUTURA", "ACABAMENTO", "CONCLUIDA", "PARADA_ABANDONADA", "INDETERMINADO"]
SYS = ("Você é PERITO DE OBRAS PÚBLICAS. Classifique a FASE FÍSICA da obra a partir dos autos. "
       "Fases: " + ", ".join(FASES) + ". Se os autos só têm empenho/liquidação/pagamento sem boletim de "
       "medição/fiscalização/aceite, responda INDETERMINADO (não conclua concluída sem evidência física). "
       "Responda SÓ JSON: {\"fase\":\"...\",\"evidencia\":\"trecho curto\",\"confianca\":0..1}.")


def _tabela(con):
    con.execute("CREATE TABLE IF NOT EXISTS obra_fase (cnpj TEXT, processo TEXT, fase TEXT, "
                "evidencia TEXT, confianca REAL, fonte_modelo TEXT, em TEXT, PRIMARY KEY(cnpj,processo))")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limite", type=int, default=70); a = ap.parse_args()
    con = sqlite3.connect(DB, timeout=30); con.execute("PRAGMA busy_timeout=30000"); con.row_factory = sqlite3.Row
    _tabela(con)
    feitos = {r[0] for r in con.execute("SELECT cnpj FROM obra_fase")}
    OBRA = ("(LOWER(objeto) LIKE '%obra%' OR LOWER(objeto) LIKE '%constru%' OR LOWER(objeto) LIKE '%reforma%' "
            "OR LOWER(objeto) LIKE '%pavimenta%')")
    # obras (cnpj→objeto, maior valor) que têm ficha SEI com análise
    obras = {}
    for r in con.execute(f"SELECT cnpj, objeto, valor_contrato FROM contratos_tcerj WHERE {OBRA} AND cnpj IS NOT NULL "
                         f"ORDER BY valor_contrato DESC"):
        cn = "".join(ch for ch in (r["cnpj"] or "") if ch.isdigit())
        if len(cn) == 14 and cn not in obras:
            obras[cn] = r["objeto"]
    fichas = {}
    for s in con.execute("SELECT cnpjs, numero_sei, objeto, analise, resumo, pericia_contabil FROM sei_ficha"):
        for cn in (s["cnpjs"] or "").replace(";", ",").split(","):
            cn = "".join(ch for ch in cn if ch.isdigit())
            if cn in obras and cn not in fichas:
                fichas[cn] = s
    pend = [(cn, obras[cn], fichas[cn]) for cn in obras if cn in fichas and cn not in feitos][:a.limite]
    print(f"[obra_fase] {len(obras)} obras-cnpj · {len(fichas)} com ficha SEI · {len(pend)} a analisar agora")
    n = 0
    for cnpj, objeto, fic in pend:
        autos = f"OBJETO: {objeto}\nANÁLISE DOS AUTOS: {(fic['analise'] or fic['resumo'] or '')[:2500]}\nPERÍCIA: {(fic['pericia_contabil'] or '')[:800]}"
        try:
            raw = free_llm.groq_chat(autos, system=SYS, max_tokens=400)
            j = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            fase = j.get("fase", "INDETERMINADO"); fase = fase if fase in FASES else "INDETERMINADO"
        except Exception as e:
            fase, j = "INDETERMINADO", {"evidencia": f"erro: {str(e)[:60]}", "confianca": 0}
        con.execute("INSERT OR REPLACE INTO obra_fase VALUES (?,?,?,?,?,?,datetime('now'))",
                    (cnpj, fic["numero_sei"] or "", fase, str(j.get("evidencia", ""))[:300],
                     float(j.get("confianca") or 0), "groq:free"))
        con.commit(); n += 1
        if n % 10 == 0: print(f"  ...{n}/{len(pend)}")
    from collections import Counter
    dist = Counter(r[0] for r in con.execute("SELECT fase FROM obra_fase"))
    con.close()
    print(f"[obra_fase] analisadas {n} · distribuição total de fases: {dict(dist)}")


if __name__ == "__main__":
    main()
