#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fachada_visual_sweep — classificador VISUAL de fachada em escala sobre os SUSPEITOS de sede.

REUSA o classificador já existente `compliance_agent.verificacao_endereco.classificar_local_por_imagem`
(Mapillary GRÁTIS → satélite Esri GRÁTIS; Street View pago só se `IMG_FONTE_ORDEM` o incluir E houver
cota — este runner NÃO o força). As coords já vêm do sweep Google (`verificacao_sede.geo_lat/geo_lon`),
então NÃO re-geocoda: passa as coords direto ao classificador. Grava `visual_classe/visual_conf/
visual_fonte/visual_em` por CNPJ (INSERT-via-UPDATE, transação curta, busy_timeout=30000).

Alvo padrão: `verificacao_sede WHERE status='INDICIO'` (suspeitos), maior `total_recebido` primeiro.
RESUMÍVEL: pula quem já tem `visual_classe`. VM-safe: load-guard, time-bound, pausa entre alvos.
Honesto: satélite (entorno ±100m) NUNCA acusa (status INDISPONIVEL); só Mapillary/Street View (rente ao
chão) viram INDICIO. Custo: Mapillary token grátis + Gemini pool tier grátis → ZERO cota paga.

Uso:
  PYTHONPATH=. nice -n10 .venv/bin/python -m tools.fachada_visual_sweep \\
      [--status INDICIO] [--limite N] [--max-min 20] [--pausa 0.3] [--so-suspeitos/--todos]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ))

_DB = Path(os.environ.get("JFN_DB") or (_RAIZ / "data" / "compliance.db"))
_VISUAIS = ("visual_classe", "visual_conf", "visual_fonte", "visual_em")


def _carregar_env() -> None:
    """Popula os.environ a partir do .env (igual ao sweep_sede_google): como módulo CLI o .env não está
    carregado e sem MAPILLARY_TOKEN/GEMINI as chamadas viram no-op."""
    for f in (_RAIZ / ".env", Path.home() / ".hermes" / ".env"):
        try:
            for line in Path(f).read_text().splitlines():
                m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$", line)
                if m and not os.environ.get(m.group(1)):
                    os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        except Exception:
            continue


def _garante_colunas(con: sqlite3.Connection) -> None:
    """ALTER TABLE ADD COLUMN idempotente — espelha as colunas visuais de endereco_verificacao."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(verificacao_sede)")}
    tipos = {"visual_classe": "TEXT", "visual_conf": "REAL", "visual_fonte": "TEXT", "visual_em": "TEXT"}
    for nome, typ in tipos.items():
        if nome not in cols:
            con.execute(f"ALTER TABLE verificacao_sede ADD COLUMN {nome} {typ}")
    con.commit()


def _load_ok(teto: float = 4.0) -> bool:
    try:
        return os.getloadavg()[0] < teto
    except Exception:
        return True


def _alvos(con: sqlite3.Connection, status: str | None, limite: int) -> list[sqlite3.Row]:
    """Suspeitos a classificar: têm geo e ainda NÃO têm visual_classe. Maior valor primeiro."""
    where = ["geo_lat IS NOT NULL", "geo_lon IS NOT NULL",
             "(visual_classe IS NULL OR visual_classe = '')"]
    params: list = []
    if status:
        where.append("status = ?")
        params.append(status)
    lim = f" LIMIT {int(limite)}" if limite else ""
    sql = (f"SELECT cnpj, razao, endereco, municipio, uf, geo_lat, geo_lon, total_recebido, status "
           f"FROM verificacao_sede WHERE {' AND '.join(where)} "
           f"ORDER BY total_recebido DESC{lim}")
    return con.execute(sql, params).fetchall()


def _grava(cnpj: str, res: dict) -> None:
    """Transação CURTA: grava o resultado visual de 1 CNPJ. connect(timeout=30)+busy_timeout=30000 (concorre
    com o sweep/cron). Persiste sempre (até INDISPONIVEL/indeterminado) p/ ser resumível e não retentar à toa."""
    con = sqlite3.connect(str(_DB), timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        con.execute(
            "UPDATE verificacao_sede SET visual_classe=?, visual_conf=?, visual_fonte=?, visual_em=? WHERE cnpj=?",
            (res.get("classe") or "", float(res.get("confianca") or 0.0), res.get("fonte") or "",
             dt.datetime.now().isoformat(timespec="seconds"), cnpj))
        con.commit()
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Classificador visual de fachada (reusa classificar_local_por_imagem)")
    ap.add_argument("--status", default="INDICIO",
                    help="status alvo em verificacao_sede (default INDICIO; vazio/'' = qualquer)")
    ap.add_argument("--todos", action="store_true", help="qualquer status (ignora --status)")
    ap.add_argument("--limite", type=int, default=0, help="máx. de alvos (0 = todos os pendentes)")
    ap.add_argument("--max-min", type=float, default=20.0, help="time-bound em minutos (default 20)")
    ap.add_argument("--pausa", type=float, default=0.3, help="pausa entre alvos (s)")
    ap.add_argument("--load-teto", type=float, default=4.0, help="abortar se load1 ≥ este valor")
    a = ap.parse_args()
    _carregar_env()

    # Não forçar o Street View pago: se o dono não definiu IMG_FONTE_ORDEM, fica só Mapillary (grátis).
    # O satélite Esri (grátis) é fallback automático interno. Quem quiser SV define IMG_FONTE_ORDEM e a cota.
    os.environ.setdefault("IMG_FONTE_ORDEM", "mapillary")

    if not os.environ.get("MAPILLARY_TOKEN", "").strip():
        print("[fachada_visual] ⚠ sem MAPILLARY_TOKEN — só satélite (entorno) disponível.", flush=True)

    from compliance_agent.verificacao_endereco import classificar_local_por_imagem  # noqa: E402

    con = sqlite3.connect(str(_DB), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    _garante_colunas(con)
    status = None if a.todos else (a.status or None)
    alvos = _alvos(con, status, a.limite)
    con.close()

    print(f"[fachada_visual] {len(alvos)} alvo(s) pendente(s) "
          f"(status={'qualquer' if status is None else status}, maior R$ primeiro). "
          f"time-bound={a.max_min:.0f}min", flush=True)
    if not alvos:
        print("[fachada_visual] nada a fazer (todos já classificados).", flush=True)
        return 0

    t0 = time.time()
    limite_s = a.max_min * 60.0
    dist: Counter = Counter()
    feitos = 0
    achados: list[str] = []
    indicio = {"terreno_baldio", "area_aberta_rural", "construcao_precaria_barraco"}

    for i, r in enumerate(alvos, 1):
        if time.time() - t0 >= limite_s:
            print(f"[fachada_visual] time-bound {a.max_min:.0f}min atingido — parada limpa.", flush=True)
            break
        if not _load_ok(a.load_teto):
            print(f"[fachada_visual] load1 ≥ {a.load_teto} — parada limpa (retoma no próximo ciclo).", flush=True)
            break
        end = ", ".join(x for x in [r["endereco"], r["municipio"], r["uf"]] if x)
        try:
            res = classificar_local_por_imagem(r["geo_lat"], r["geo_lon"], end)
        except Exception as e:  # noqa: BLE001
            res = {"classe": "", "confianca": 0.0, "fonte": "", "evidencia": f"erro: {str(e)[:60]}"}
        _grava(r["cnpj"], res)
        feitos += 1
        classe = res.get("classe") or "(sem imagem/VLM)"
        dist[classe] += 1
        if res.get("classe") in indicio and res.get("status") == "INDICIO":
            linha = (f"  → {res.get('classe')} (conf {float(res.get('confianca') or 0):.0%}) "
                     f"R$ {r['total_recebido']:,.0f} · {r['razao'][:40]} · {end[:60]}")
            achados.append(linha)
            print(linha, flush=True)
        if i % 25 == 0:
            print(f"  ...{feitos} feitos · {time.time() - t0:.0f}s · dist={dict(dist)}", flush=True)
        time.sleep(a.pausa)

    print(f"\n[fachada_visual] CONCLUÍDO ciclo: {feitos} classificado(s) em {time.time() - t0:.0f}s", flush=True)
    print(f"[fachada_visual] distribuição: {dict(dist)}", flush=True)
    if achados:
        print(f"[fachada_visual] {len(achados)} INDÍCIO(s) rente ao chão (baldio/barraco/rural):", flush=True)
        for l in achados:
            print(l, flush=True)
    else:
        print("[fachada_visual] nenhum indício rente ao chão neste ciclo.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
