"""triagem_amarelos — fila de triagem da zona cinzenta (perícias 🟡).

1.988 fornecedores×UG em 🟡 (R$ 39,7 bi pagos) sem fila = invisíveis. Este tool
ranqueia por (score × volume pago × sanção federal ativa) e manda o top-N no
Telegram pedindo o `/veredito` do perito — é o que alimenta a calibração do
núcleo (confirmadas_pelo_perito) e o ledger docs/vereditos_pericia.md → RAG.

Custo ZERO de LLM (ranking determinístico em SQL).

CLI:
  python -m tools.triagem_amarelos             # imprime o top-20
  python -m tools.triagem_amarelos --enviar    # também manda no Telegram
  python -m tools.triagem_amarelos --top 30
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "compliance.db"

# score interno (0-100) pesa mais que volume; sanção federal ativa é multiplicador forte.
_SQL = """
SELECT p.cnpj, p.ug, p.favorecido, p.n_obs, p.total_pago, p.score, p.resumo,
       (SELECT COUNT(*) FROM sancoes_federais s WHERE s.cpf_cnpj = p.cnpj) AS n_sancoes
FROM pericia_fornecedor p
WHERE p.grau = '🟡'
ORDER BY (p.score * 1.0) * (1.0 + MIN(p.total_pago, 1e9) / 1e8)
         * (CASE WHEN (SELECT COUNT(*) FROM sancoes_federais s
                       WHERE s.cpf_cnpj = p.cnpj) > 0 THEN 3.0 ELSE 1.0 END) DESC
LIMIT :top
"""


def _brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def top_amarelos(top: int = 20) -> list[dict]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=15000")
        return [dict(r) for r in con.execute(_SQL, {"top": top})]
    finally:
        con.close()


def formatar(rows: list[dict]) -> str:
    linhas = ["🟡 *Triagem semanal — zona cinzenta (pede /veredito)*",
              "_Ranking: score × volume pago × sanção federal ativa._\n"]
    for i, r in enumerate(rows, 1):
        sanc = f" ⛔{r['n_sancoes']} sanção(ões)" if r["n_sancoes"] else ""
        linhas.append(
            f"{i}. *{(r['favorecido'] or r['cnpj'])[:40]}* (UG {r['ug']}){sanc}\n"
            f"   score {r['score']} · {r['n_obs']} OBs · {_brl(r['total_pago'])}\n"
            f"   `/pericia {r['cnpj']}` → `/veredito ...`")
    linhas.append("\n_Confirmar/descartar treina o núcleo (calibração + caso-ouro via /promover)._")
    return "\n".join(linhas)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--enviar", action="store_true", help="manda no Telegram do dono")
    args = ap.parse_args()

    rows = top_amarelos(args.top)
    texto = formatar(rows)
    print(texto)
    if args.enviar and rows:
        import sys
        sys.path.insert(0, str(REPO))
        from compliance_agent.notifications.telegram import enviar_mensagem
        r = asyncio.run(enviar_mensagem(texto))
        print("\ntelegram:", r.get("ok", False), flush=True)
        return 0 if r.get("ok") else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
