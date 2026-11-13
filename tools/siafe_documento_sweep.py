#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""siafe_documento_sweep — amplia a cobertura de Nota de Empenho e Nota de Liquidação, UG a UG.

POR QUE EXISTE (04/11/2026). Os detectores de ordem cronológica (Dec. RJ 49.134 art. 9º) e de DEA recorrente
só valem nas UGs com NE e NL COMPLETAS (`siafe_documento_cobertura`). Coletar uma UG grande leva 15–30 min de
navegador; a varredura faz isso em janelas, sem disputar a sessão única do SIAFE.

GUARDA-CORPOS:
  • uma coleta por vez, cada uma em subprocesso que pega o lock do siafe_runner E o `browser_lock(siafe)` —
    o mesmo do dreno e do coletor da OB (duas sessões na mesma conta derrubam uma à outra);
  • prazo (`--ate HH:MM`): não começa coleta nova depois dele — o diário do SIAFE é às 05:00;
  • carga: não começa coleta nova com load de 1 min acima de `--load-max`;
  • ordem: UG de maior valor pago (OB Contabilizada) primeiro; pula UG completa há menos de 30 dias.

Uso:
    PYTHONPATH=. .venv/bin/python tools/siafe_documento_sweep.py --exercicio 2025 --ate 04:40 --max-ugs 3
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from compliance_agent.siafe_documento import prazo_absoluto

_REPO = Path(__file__).resolve().parents[1]
_DB = _REPO / "data" / "compliance.db"
_FRESCA_DIAS = 30


def fila(exercicio: int, db=None, max_ugs: int = 3) -> list[tuple[str, str]]:
    """[(ug, tipo)] na ordem de coleta: maior valor pago primeiro; tipo que já está completo e fresco fica fora."""
    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=30)
    try:
        ugs = [r[0] for r in con.execute(
            # valor pago a FORNECEDOR (credor CNPJ): por valor bruto a previdência e a folha encabeçavam a fila,
            # e nelas a ordem cronológica não se aplica (Dec. 49.134 art. 9º p.ú. a)
            "SELECT ug_emitente FROM ob_orcamentaria_siafe WHERE exercicio=? AND status='Contabilizado' "
            "AND length(credor)=14 GROUP BY 1 ORDER BY SUM(valor) DESC", (int(exercicio),))]
        try:
            cob = {(r[0], r[1]): (r[2], r[3]) for r in con.execute(
                "SELECT ug_emitente, tipo, completo, em FROM siafe_documento_cobertura WHERE exercicio=?",
                (int(exercicio),))}
        except sqlite3.OperationalError:
            cob = {}
    finally:
        con.close()
    limite = (datetime.now() - timedelta(days=_FRESCA_DIAS)).strftime("%F %T")
    saida, n = [], 0
    for ug in ugs:
        faltam = [t for t in ("NE", "NL") if not (cob.get((ug, t), (0, ""))[0] and cob[(ug, t)][1] >= limite)]
        if not faltam:
            continue
        saida += [(ug, t) for t in faltam]
        n += 1
        if n >= max_ugs:
            break
    return saida


def _agora() -> datetime:
    return datetime.now()


def _passou(prazo: datetime) -> bool:
    """`prazo` é absoluto (ver `siafe_documento.prazo_absoluto`): comparar `HH:MM` como texto fazia a execução
    das 23:20 com `--ate 02:55` parar na hora (laudo 13/11/2026)."""
    return _agora() >= prazo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exercicio", type=int, default=datetime.now().year - 1)
    ap.add_argument("--ate", default="04:40", help="não começa coleta nova depois deste horário (HH:MM)")
    ap.add_argument("--max-ugs", type=int, default=3)
    ap.add_argument("--load-max", type=float, default=3.0)
    ap.add_argument("--ugs", default="", help="UGs separadas por vírgula, NESTA ordem (fila dirigida)")
    ap.add_argument("--tipos", default="NE,NL", help="NE, NL ou NE,NL")
    a = ap.parse_args()
    tipos = [t.strip().upper() for t in a.tipos.split(",") if t.strip()]
    if a.ugs:
        # fila DIRIGIDA (12/11/2026): o resolvedor de duplicidade precisa do PROCESSO das NEs de 2023 das UGs
        # cujas OBs vieram sem processo (SIAFE 1 desativado; o SIAFE 2 ainda serve 2023). Mesma regra de
        # frescor da fila por valor: tipo completo há < 30 dias fica fora.
        alvo = [u.strip() for u in a.ugs.split(",") if u.strip()]
        livres = set(fila(a.exercicio, max_ugs=10 ** 6))
        trabalho = [(u, t) for u in alvo for t in tipos if (u, t) in livres][: a.max_ugs * len(tipos)]
    else:
        trabalho = [x for x in fila(a.exercicio, max_ugs=a.max_ugs) if x[1] in tipos]
    prazo = prazo_absoluto(a.ate, _agora())
    ate_abs = prazo.strftime("%Y-%m-%dT%H:%M")
    print(f"[{time.strftime('%F %T')}] fila: {trabalho} · prazo {ate_abs}", flush=True)
    for ug, tipo in trabalho:
        if _passou(prazo):
            print(f"  prazo {ate_abs} atingido — paro antes de {ug}/{tipo}", flush=True)
            break
        carga = os.getloadavg()[0]
        if carga > a.load_max:
            print(f"  load {carga:.2f} > {a.load_max} — paro antes de {ug}/{tipo}", flush=True)
            break
        t0 = time.time()
        # o prazo vai PARA DENTRO do coletor: ele para entre fatias e faz logout. Matar no meio deixaria a sessão
        # viva no servidor e o login seguinte (o diário das 05:00) cairia na sessão órfã.
        r = subprocess.run([sys.executable, "-m", "compliance_agent.siafe_documento", "--tipo", tipo, "--ug", ug,
                            "--exercicio", str(a.exercicio), "--ate", ate_abs], cwd=_REPO, capture_output=True,
                           text=True, timeout=7200)
        ult = (r.stdout.strip().splitlines() or [""])[-1]
        try:
            d = json.loads(ult)
            resumo = {k: d.get(k) for k in ("ok", "ingeridas", "capou", "cobertura_pela_ob", "etapa")}
        except ValueError:
            resumo = {"rc": r.returncode, "saida": (ult or r.stderr.strip()[-200:])[:200]}
        print(f"  {ug}/{tipo} em {time.time() - t0:.0f}s: {resumo}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
