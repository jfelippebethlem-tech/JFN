#!/usr/bin/env python3
"""Lex SÓ nos contratos do FUNESBOM (não no corpus inteiro): pericía execução das fichas bombeiros
(SEI-2700%) com docs e ainda não avaliadas, em ordem de nº de docs. Reusa avaliar_processo canônico.
Cadeia `gerar_sync` = Gemini primeiro (→ groq → openrouter:free → nvidia); o docstring antigo dizia "sem
Gemini" e estava errado. Honestidade: indício≠acusação; INDISPONÍVEL≠irregular."""
import argparse
import json
import tools.lex_execucao as L
from compliance_agent.llm.comotor import juizo

# co-motor (13/11/2026): Claude (assinatura, com teto) + a cascata de sempre, vereditos cruzados;
# mesma tarefa e mesmo orçamento do lex_execucao
gerar_sync = juizo("pericia_execucao")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=20)
    a = ap.parse_args()
    con = L._con()
    try:
        # veredito vazio NÃO é feito (régua única do lex_execucao: volta após 7 dias)
        ja = {r[0] for r in con.execute(L.SQL_JA_AVALIADO)}
        rows = con.execute("SELECT numero_sei,objeto,valores,documentos,red_flags FROM sei_ficha "
                           "WHERE n_docs>0 AND numero_sei LIKE 'SEI-2700%' ORDER BY n_docs DESC").fetchall()
        n = 0
        for ns, obj, val, docs, rf in rows:
            if ns in ja:
                continue
            try:
                dl = json.loads(docs) if docs else []
                rfl = json.loads(rf) if rf else []
            except Exception:
                dl, rfl = [], []
            res = L.avaliar_processo(con, ns, obj or "", val or "",
                                     dl if isinstance(dl, list) else [], rfl, gerar_sync)
            if res:
                v = res["verdict"]
                print(f"  {ns}: exec={v.get('execucao_comprovada','?')} risco={v.get('nota_risco_execucao','?')}")
            n += 1
            if n >= a.max:
                break
        print(f"[lex_bombeiros] periciados nesta passada: {n}")
    finally:
        con.close()

if __name__ == "__main__":
    main()
