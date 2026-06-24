#!/usr/bin/env python3
"""Sweep: flag de empresas SEM marcação no Google (red flag de fachada).

Empresa que recebe do Estado mas o Google Places NÃO acha negócio no endereço (`places_achou=0`),
ou cujo Places diz FECHADA (`places_status=CLOSED_*`), e mesmo assim foi marcada AFASTADO ("ok"),
é indício de fachada. Aqui flagamos em `verificacao_sede`:
  - `nivel='SEM_GOOGLE'`   → places_achou=0 (sem presença no Google)
  - `nivel='FECHADO_GOOGLE'` → places_status CLOSED_*
Flip AFASTADO→INDICIO p/ surgir na lista de suspeitos. **Indício ≠ acusação** (nem todo negócio
legítimo está no Google) — por isso grava evidência explícita. Idempotente, resumível.

Uso: python -m tools.sweep_sem_google [--dry]
"""
import argparse, os, sqlite3, sys

DB = os.environ.get("JFN_DB") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "compliance.db")

REGRAS_FECHADO_OPTIN = True  # FECHADO_GOOGLE ruidoso (match errado) — fora do default
REGRAS = [
    ("SEM_GOOGLE", "places_achou=0",
     "Google Places NÃO encontrou negócio no endereço (sem marcação no Google) — recebeu do Estado. Indício de fachada, não acusação."),
    ("FECHADO_GOOGLE", "UPPER(COALESCE(places_status,'')) LIKE 'CLOSED%'",
     "Google Places marca o estabelecimento como FECHADO — mas recebeu do Estado. Indício, não acusação."),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="só conta, não grava")
    a = ap.parse_args()
    try:
        from compliance_agent.sede_google import e_ente_publico
    except Exception:
        def e_ente_publico(_): return False
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    # exclusões: vereditos HUMANOS de legítima (real/pular) — ex.: PVAX (galpão real)
    vetado = {r[0] for r in con.execute("SELECT cnpj FROM fachada_veredito WHERE status IN ('real','pular')")}
    total = 0
    for nivel, cond, ev in REGRAS:
        base = (f"FROM verificacao_sede WHERE ({cond}) AND COALESCE(total_recebido,0) > 0 AND status='AFASTADO'")
        cands = con.execute(f"SELECT cnpj, razao, total_recebido {base}").fetchall()
        # filtra ente público + veredito humano (em Python, heurística de razão)
        alvos = [r for r in cands if r[0] not in vetado and not e_ente_publico(r[1] or "")]
        excl = len(cands) - len(alvos)
        val = sum(r[2] or 0 for r in alvos)
        print(f"[{nivel}] {len(alvos)} empresas · R$ {val:,.2f} (excluídos {excl}: ente público/veredito-humano)" + (" (dry)" if a.dry else ""))
        if not a.dry and alvos:
            for cnpj, razao, tr in alvos:
                con.execute("UPDATE verificacao_sede SET status='INDICIO', nivel=?, evidencia=? WHERE cnpj=? AND status='AFASTADO'", (nivel, ev, cnpj))
            con.commit()
            total += len(alvos)
    if not a.dry:
        print(f"[sweep_sem_google] flagradas: {total} (AFASTADO→INDICIO). Top por valor:")
        for r in con.execute(
            "SELECT razao, total_recebido, nivel FROM verificacao_sede "
            "WHERE nivel IN ('SEM_GOOGLE','FECHADO_GOOGLE') ORDER BY total_recebido DESC LIMIT 10"):
            print(f"   R$ {r[1]:>14,.2f} | {r[2]:14} | {(r[0] or '')[:40]}")
    con.close()


if __name__ == "__main__":
    main()
