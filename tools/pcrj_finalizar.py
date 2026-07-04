# -*- coding: utf-8 -*-
"""Finalização AUTÔNOMA do sweep all-RJ (roda destacado; sem Claude/LLM no loop).

Espera o cruzamento inverso (comissionados-candidatos, todo o RJ) terminar, regenera a
perícia (com a §VI preenchida) + os relatórios, e envia pelo Yoda (Telegram) sozinho.
Token-safe: nenhuma chamada de modelo; só polling de arquivo + geração determinística.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_LOG = Path(__file__).resolve().parents[1] / "logs" / "pcrj_inverso_allrj.log"


def _sweep_terminou() -> bool:
    try:
        return "INVERSO FIM" in _LOG.read_text(errors="replace")
    except FileNotFoundError:
        return False


def _sweep_vivo() -> bool:
    import subprocess
    return subprocess.run(["pgrep", "-f", "inverso_allrj"],
                          capture_output=True).returncode == 0


async def _main() -> None:
    # 1) espera o sweep terminar (ou morrer) — poll a cada 2 min, teto 30h
    limite = time.time() + 30 * 3600
    while not _sweep_terminou():
        if not _sweep_vivo() and not _sweep_terminou():
            print("[finalizar] sweep morreu sem FIM — finalizando com o que há.", flush=True)
            break
        if time.time() > limite:
            print("[finalizar] timeout de 30h — finalizando com o parcial.", flush=True)
            break
        time.sleep(120)
    print("[finalizar] sweep concluído — regenerando produtos.", flush=True)

    # 2) checkpoint do WAL (evita lock residual)
    import sqlite3
    from compliance_agent.pcrj import db as _db
    con = sqlite3.connect(str(_db.DB_PATH), timeout=60)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()

    # 3) regenera perícia + relatórios (determinístico)
    from compliance_agent.pcrj import pericia, relatorio, relatorio_gabinete as rg
    res_p = await pericia.gerar()
    await relatorio.gerar()
    await rg.gerar_completo()
    print(f"[finalizar] perícia: {res_p}", flush=True)

    # 4) contagem do achado principal p/ a legenda
    con = sqlite3.connect(str(_db.DB_PATH), timeout=60)
    try:
        n = con.execute("SELECT COUNT(DISTINCT nome_norm) FROM pcrj_comissionado_candidato").fetchone()[0]
    except Exception:
        n = 0
    con.close()

    # 5) envia pelo Yoda (sem LLM)
    from compliance_agent.envfile import carregar_env
    carregar_env()
    from compliance_agent.notifications.telegram import enviar_arquivo
    cap = (f"PCRJ — PERÍCIA COMPLETA (all-RJ). Cruzamento inverso concluído: {n} comissionados "
           "da Prefeitura (2021+) que já foram candidatos em todo o RJ. Inclui direção temporal "
           "Prefeitura↔Câmara, datas de entrada/saída, concomitância e domicílio em outra cidade.")
    r = await enviar_arquivo(res_p["pdf"], caption=cap)
    print(f"[finalizar] Yoda enviado: {r.get('ok')} {r.get('error','')}", flush=True)
    print("[finalizar] FIM", flush=True)


if __name__ == "__main__":
    asyncio.run(_main())
