#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sweep_sede_google — verifica a REALIDADE da sede de TODA a base via Google (Geocoding+AddrVal+Places).

Substitui a verificação por Nominatim (que gerava INDÍCIO falso — Min. da Fazenda, Praça dos Três Poderes —
ver auditoria 2026-06-13). Grava em `verificacao_sede`. Estratégia de cota (pedido do dono: tudo no mês):
  • **dedup por PRÉDIO** (logradouro+nº+CEP) — todas as empresas no mesmo prédio herdam 1 verificação;
  • ordem **menor valor de contrato → maior** (pedido do dono);
  • cota estoura num prédio novo → **herda de prédio-irmão no mesmo CEP** já verificado (grátis, `aproximado_cep`);
  • **Places só nos suspeitos** (residencial / sem geo preciso / endereço incompleto), por empresa.
Cada API capada em 9999/31d (guard cliente). Resumível (pula quem já está) e quota-bounded (para no teto).

VM-safe: rode com `nice -n10 ionice -c2 -n6`, load-guard, pausas. Uso:
  PYTHONPATH=. .venv/bin/python -m tools.sweep_sede_google [--limite N] [--max-horas 6] [--pausa 0.2]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compliance_agent import sede_google as sg  # noqa: E402

_DB = Path("data") / "compliance.db"


def _carregar_env() -> None:
    """Popula o os.environ a partir do .env — sede_google lê GOOGLE_MAPS_KEY do ambiente; como módulo CLI o
    .env não está carregado (no jfn.service está). Sem isto as chamadas viram no-op (bug do lote 1)."""
    import re as _re
    for f in (Path(__file__).resolve().parents[1] / ".env", Path.home() / ".hermes" / ".env"):
        try:
            for line in Path(f).read_text().splitlines():
                m = _re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$", line)
                if m and not os.environ.get(m.group(1)):
                    os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        except Exception:
            continue

_DDL = """
CREATE TABLE IF NOT EXISTS verificacao_sede (
  cnpj TEXT PRIMARY KEY, predio_key TEXT, cep TEXT,
  razao TEXT, endereco TEXT, municipio TEXT, uf TEXT,
  total_recebido REAL,
  geo_tipo TEXT, geo_lat REAL, geo_lon REAL, geo_municipio TEXT,
  addr_completo INTEGER, addr_validacao TEXT, addr_residencial INTEGER, addr_acao TEXT,
  places_achou INTEGER, places_status TEXT, places_nome TEXT, places_endereco TEXT,
  places_bate_nome INTEGER, places_bate_mun INTEGER,
  aproximado_cep INTEGER DEFAULT 0,
  status TEXT, nivel TEXT, evidencia TEXT, sinais TEXT, verificado_em TEXT
);
CREATE INDEX IF NOT EXISTS ix_vs_predio ON verificacao_sede(predio_key);
CREATE INDEX IF NOT EXISTS ix_vs_cep ON verificacao_sede(cep);
CREATE INDEX IF NOT EXISTS ix_vs_status ON verificacao_sede(status);
"""


def _load_ok(teto: float = 4.0) -> bool:
    try:
        return os.getloadavg()[0] < teto
    except Exception:
        return True


def _suspeito(geo: dict | None, addr: dict | None) -> bool:
    """Vale gastar 1 Places? (residencial, ou geo impreciso, ou endereço incompleto)."""
    g, a = geo or {}, addr or {}
    if a.get("residencial") is True:
        return True
    if (g.get("location_type") or "") not in ("ROOFTOP", "RANGE_INTERPOLATED"):
        return True
    if a.get("completo") is False:
        return True
    return False


def _alvos(con: sqlite3.Connection, limite: int) -> list[dict]:
    """Fornecedores PJ com endereço, ainda NÃO verificados, ordenados por R$ recebido ASC (menor→maior)."""
    lim = f" LIMIT {int(limite)}" if limite else ""
    sql = f"""
        SELECT ef.cnpj, ef.razao, ef.endereco, ef.municipio, ef.uf, ef.cep,
               COALESCE(ob.total, 0) AS total_recebido
        FROM endereco_fornecedor ef
        LEFT JOIN (SELECT favorecido_cpf AS cnpj, SUM(valor) AS total
                   FROM ordens_bancarias WHERE length(favorecido_cpf)=14 GROUP BY favorecido_cpf) ob
               ON ob.cnpj = ef.cnpj
        WHERE length(ef.cnpj)=14 AND ef.endereco IS NOT NULL AND ef.endereco != ''
          AND ef.cnpj NOT IN (SELECT cnpj FROM verificacao_sede)
        ORDER BY total_recebido ASC{lim}
    """
    return [dict(r) for r in con.execute(sql).fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=0, help="máx. de fornecedores a processar (0 = todos)")
    ap.add_argument("--max-horas", type=float, default=6.0, help="time-bound (h)")
    ap.add_argument("--pausa", type=float, default=0.2, help="pausa entre chamadas (s)")
    a = ap.parse_args()
    _carregar_env()

    con = sqlite3.connect(str(_DB), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.row_factory = sqlite3.Row
    con.executescript(_DDL)
    con.commit()

    alvos = _alvos(con, a.limite)
    print(f"{len(alvos)} fornecedor(es) a verificar (ordem: menor→maior R$). "
          f"Cotas: {({x: sg.cota_restante(x) for x in ('geocoding', 'addressvalidation', 'places')})}",
          flush=True)

    # caches da sessão: prédio (geo+addr) e CEP (fallback do overflow)
    predio_cache: dict[str, dict] = {}
    cep_cache: dict[str, dict] = {}
    # pré-carrega o que já existe no banco (resumível entre execuções)
    for r in con.execute("SELECT predio_key, cep, geo_tipo, geo_lat, geo_lon, geo_municipio, "
                         "addr_completo, addr_validacao, addr_residencial, addr_acao FROM verificacao_sede "
                         "WHERE geo_tipo IS NOT NULL"):
        sig = {"geocode": {"location_type": r["geo_tipo"], "lat": r["geo_lat"], "lon": r["geo_lon"],
                           "municipio": r["geo_municipio"]},
               "validacao": ({"completo": bool(r["addr_completo"]) if r["addr_completo"] is not None else None,
                              "validacao": r["addr_validacao"], "acao": r["addr_acao"],
                              "residencial": (None if r["addr_residencial"] is None else bool(r["addr_residencial"]))}
                             if r["addr_validacao"] is not None else None)}
        predio_cache.setdefault(r["predio_key"], sig)
        if r["cep"]:
            cep_cache.setdefault(r["cep"], sig)

    t0 = time.time()
    novos = herdados_predio = herdados_cep = sem_cota = places_usados = 0
    escrita = con.cursor()
    for i, c in enumerate(alvos, 1):
        if (time.time() - t0) > a.max_horas * 3600:
            print("  time-bound atingido — parando (resumível)."); break
        if not _load_ok():
            print("  ⏸ load alto — pausando 30s"); time.sleep(30)
        bk = sg.predio_key(c["endereco"], c["cep"])
        cep = sg.cep_de(c["cep"])
        aprox = 0
        if bk in predio_cache:
            sig = dict(predio_cache[bk]); herdados_predio += 1
        elif sg.cota_restante("geocoding") > 0 and sg.cota_restante("addressvalidation") > 0:
            sig = sg.coletar_sinais(c["razao"], c["endereco"], c["municipio"], c["uf"],
                                    c["cep"], com_places=False)
            predio_cache[bk] = {"geocode": sig.get("geocode"), "validacao": sig.get("validacao")}
            if cep:
                cep_cache.setdefault(cep, predio_cache[bk])
            novos += 1
            time.sleep(a.pausa)
        elif cep in cep_cache:
            sig = dict(cep_cache[cep]); aprox = 1; herdados_cep += 1
        else:
            sem_cota += 1
            continue   # sem cota e sem irmão no CEP → fica p/ a próxima janela
        # Places só nos suspeitos, por empresa, se houver cota
        places = None
        if _suspeito(sig.get("geocode"), sig.get("validacao")) and sg.cota_restante("places") > 0:
            places = sg.buscar_negocio(c["razao"], c["endereco"], c["municipio"])
            places_usados += 1
            time.sleep(a.pausa)
        sig = {**sig, "places": places}
        vd = sg.verdict_de_sinais(sig, c["total_recebido"])
        g, v, p = sig.get("geocode") or {}, sig.get("validacao") or {}, sig.get("places") or {}
        escrita.execute(
            "INSERT OR REPLACE INTO verificacao_sede (cnpj,predio_key,cep,razao,endereco,municipio,uf,"
            "total_recebido,geo_tipo,geo_lat,geo_lon,geo_municipio,addr_completo,addr_validacao,"
            "addr_residencial,addr_acao,places_achou,places_status,places_nome,places_endereco,"
            "places_bate_nome,places_bate_mun,aproximado_cep,status,nivel,evidencia,sinais,verificado_em) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (c["cnpj"], bk, cep, c["razao"], c["endereco"], c["municipio"], c["uf"], c["total_recebido"],
             g.get("location_type"), g.get("lat"), g.get("lon"), g.get("municipio"),
             (None if v.get("completo") is None else int(v.get("completo"))), v.get("validacao"),
             (None if v.get("residencial") is None else int(v.get("residencial"))), v.get("acao"),
             (None if p.get("achou") is None else int(bool(p.get("achou")))), p.get("status"),
             p.get("nome"), p.get("endereco"),
             (None if p.get("bate_nome") is None else int(bool(p.get("bate_nome")))),
             (None if p.get("bate_mun") is None else int(bool(p.get("bate_mun")))),
             aprox, vd["status"], vd["nivel"], vd["evidencia"], json.dumps(sig, ensure_ascii=False),
             dt.datetime.now().isoformat(timespec="seconds")))
        if i % 50 == 0:  # commit frequente: crash perde no máx. ~50 (resumível)
            con.commit()
            print(f"  …{i}/{len(alvos)} novos={novos} herda_predio={herdados_predio} "
                  f"herda_cep={herdados_cep} places={places_usados} sem_cota={sem_cota}", flush=True)
    con.commit()
    print(f"\nFIM: processados={novos + herdados_predio + herdados_cep} | API-novos={novos} "
          f"herda_predio={herdados_predio} herda_cep={herdados_cep} places={places_usados} sem_cota={sem_cota}")
    print(f"Cotas restantes: {({x: sg.cota_restante(x) for x in ('geocoding', 'addressvalidation', 'places')})}")
    print("Distribuição de status:")
    for r in con.execute("SELECT status, COUNT(*) n FROM verificacao_sede GROUP BY status ORDER BY n DESC"):
        print(f"  {r['status']:14} {r['n']}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
