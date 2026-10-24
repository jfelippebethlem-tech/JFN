# -*- coding: utf-8 -*-
"""
siafe_recoletar_dias — automelhoria de DADO: recoleta os dias do SIAFE parados no platô do teto de consulta.

POR QUE EXISTE. Em 24/10/2026 o verificador do diário nunca tinha disparado (contava linhas do DOM) e 8 dias
de 2026 estavam parados em 981–997 OBs — a assinatura do teto. Recoletados à mão: 21/10 foi de 992 para 1.719.
Isto vira laço automático: `suspeitos()` acha os dias no platô, `--auto` os recoleta com `coletar_por_data`
(que agora decide o estouro pelo colhido e subdivide), e o dia recoletado entra em
`data/siafe_dias_verificados.json` — para o sensor de dados do loop de automelhoria não insistir nele.

Uso:
  python tools/siafe_recoletar_dias.py --listar            # dias suspeitos (só SQL)
  python tools/siafe_recoletar_dias.py --auto [--max 3]    # recoleta os suspeitos ainda não verificados
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
DB = _REPO / "data" / "compliance.db"
VERIFICADOS = _REPO / "data" / "siafe_dias_verificados.json"
PLATO = (975, 1000)          # [min, max): faixa em que a colheita bate no teto (platô medido 980–997)


def verificados() -> dict:
    try:
        return json.loads(VERIFICADOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _contar(dia: str, exercicio: int, db: Path = DB) -> int:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE exercicio=? AND data_emissao=?",
                           (exercicio, dia)).fetchone()[0]
    finally:
        con.close()


def suspeitos(exercicio: int | None = None, db: Path = DB) -> list[tuple[str, int]]:
    """Dias do exercício com contagem no platô e ainda não verificados. `data_emissao` é TEXTO DD/MM/AAAA."""
    ano = exercicio or datetime.now().year
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT data_emissao, COUNT(*) FROM ob_orcamentaria_siafe WHERE exercicio=? "
                           "GROUP BY data_emissao", (ano,)).fetchall()
    finally:
        con.close()
    ok = verificados()
    return sorted(((d, n) for d, n in rows if PLATO[0] <= n < PLATO[1] and d not in ok),
                  key=lambda x: datetime.strptime(x[0], "%d/%m/%Y"), reverse=True)


async def recoletar(dias: list[str], exercicio: int) -> dict:
    from compliance_agent import siafe_ob_orcamentaria as M
    ok, out = verificados(), {}
    for d in dias:
        antes = _contar(d, exercicio)
        r = await M.coletar_por_data(exercicio, d)
        out[d] = {k: r.get(k) for k in ("ok", "estouro", "ingeridas", "erro")} | {"antes": antes}
        # VERIFICADO SÓ COM PROVA: subdividiu (estouro) OU a colheita viu ao menos o que a base já tem.
        # Medido em 24/10/2026 no 17/03: colheu 879 com 998 na base — a rolagem parou antes do fim; marcar
        # como verificado seria declarar cura sem efeito. Fica inconclusivo, o sensor insiste e escala.
        if r.get("ok") and (r.get("estouro") or (r.get("ingeridas") or 0) >= antes):
            ok[d] = {"quando": datetime.now().isoformat(timespec="seconds"), "estouro": r.get("estouro"),
                     "ingeridas": r.get("ingeridas")}
            VERIFICADOS.write_text(json.dumps(ok, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{datetime.now():%F %T}] dia {d}: {out[d]}", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--max", type=int, default=3)
    ap.add_argument("--exercicio", type=int, default=None)
    a = ap.parse_args()
    ano = a.exercicio or datetime.now().year
    sus = suspeitos(ano)
    if a.listar or not a.auto:
        print(json.dumps(sus, ensure_ascii=False))
        return 0
    if sus:
        asyncio.run(recoletar([d for d, _ in sus[:a.max]], ano))
    else:
        print(f"[{datetime.now():%F %T}] nenhum dia no platô por verificar em {ano}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(_REPO))
    sys.exit(main())
