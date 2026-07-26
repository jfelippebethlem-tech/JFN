# -*- coding: utf-8 -*-
"""Sweep de sede real — SEM Google, SEM Mapillary.

Substitui `tools/sweep_sede_google.py` (Places/Street View/Geocoding), que desde o
desligamento do billing em 2026-06-25 rodava em VAZIO: 1.272 endereços processados
por ciclo, 0 foto, ~22 min de CPU por nada.

O motor é `compliance_agent.geo.sede_real`, que troca foto por base cadastral:
6,17 milhões de estabelecimentos da Receita em `data/receita_estab.db`, indexados
por prédio. Custo por CNPJ: ~7 ms, offline, R$ 0,00 — a base inteira numa passada,
contra os meses de cota que o Street View exigia.

    python -m tools.sweep_sede_real                 # base toda, offline
    python -m tools.sweep_sede_real --com-rede --top 200   # OSM/CEP nos piores
    python -m tools.sweep_sede_real --cnpj 03686998000118  # 1 alvo, detalhado

HONESTIDADE: grava `apuravel=0` quando não dá para saber e NUNCA converte
ausência de dado em acusação. `veredito` é triagem (indício ≠ acusação).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from compliance_agent.geo import sede_real

RAIZ = Path(__file__).resolve().parent.parent
DB = os.environ.get("JFN_DB") or str(RAIZ / "data" / "compliance.db")

_DDL = """
CREATE TABLE IF NOT EXISTS verificacao_sede_real (
  cnpj TEXT PRIMARY KEY,
  razao TEXT,
  veredito TEXT,
  apuravel INTEGER,
  score_suspeita INTEGER,
  score_substancia INTEGER,
  no_predio INTEGER,
  no_predio_terceiros INTEGER,
  na_sala_terceiros INTEGER,
  contabilidade_na_sala INTEGER,
  filiais_proprias INTEGER,
  com_mesmo_telefone INTEGER,
  com_mesmo_email INTEGER,
  osm_classe TEXT,
  cep_coerente INTEGER,
  sinais TEXT,
  com_rede INTEGER,
  verificado_em TEXT
)
"""


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute(_DDL)
    return con


def _alvos(con: sqlite3.Connection, limite: int | None, refazer: bool) -> list[str]:
    """Fornecedores por valor recebido (quem recebeu mais é apurado antes)."""
    sql = """
      SELECT o.favorecido_cpf, SUM(o.valor) tot
        FROM ordens_bancarias o
       WHERE LENGTH(COALESCE(o.favorecido_cpf,'')) = 14
    """
    if not refazer:
        sql += " AND o.favorecido_cpf NOT IN (SELECT cnpj FROM verificacao_sede_real)"
    sql += " GROUP BY 1 ORDER BY tot DESC"
    if limite:
        sql += f" LIMIT {int(limite)}"
    return [r[0] for r in con.execute(sql)]


def _gravar(con: sqlite3.Connection, cnpj: str, perfil: dict, ver: dict, com_rede: bool) -> None:
    cep_ok = perfil.get("cep_coerente")
    con.execute(
        "INSERT INTO verificacao_sede_real (cnpj, razao, veredito, apuravel, "
        "score_suspeita, score_substancia, no_predio, no_predio_terceiros, "
        "na_sala_terceiros, contabilidade_na_sala, filiais_proprias, "
        "com_mesmo_telefone, com_mesmo_email, osm_classe, cep_coerente, sinais, "
        "com_rede, verificado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(cnpj) DO UPDATE SET razao=excluded.razao, veredito=excluded.veredito, "
        "apuravel=excluded.apuravel, score_suspeita=excluded.score_suspeita, "
        "score_substancia=excluded.score_substancia, no_predio=excluded.no_predio, "
        "no_predio_terceiros=excluded.no_predio_terceiros, "
        "na_sala_terceiros=excluded.na_sala_terceiros, "
        "contabilidade_na_sala=excluded.contabilidade_na_sala, "
        "filiais_proprias=excluded.filiais_proprias, "
        "com_mesmo_telefone=excluded.com_mesmo_telefone, com_mesmo_email=excluded.com_mesmo_email, "
        "osm_classe=excluded.osm_classe, cep_coerente=excluded.cep_coerente, "
        "sinais=excluded.sinais, com_rede=excluded.com_rede, verificado_em=excluded.verificado_em",
        (cnpj, perfil.get("razao"), ver["veredito"], int(bool(ver["apuravel"])),
         ver["score_suspeita"], ver["score_substancia"], perfil.get("no_predio"),
         perfil.get("no_predio_terceiros"), perfil.get("na_sala_terceiros"),
         perfil.get("contabilidade_na_sala"), perfil.get("filiais_proprias"),
         perfil.get("com_mesmo_telefone"), perfil.get("com_mesmo_email"),
         (perfil.get("osm") or {}).get("classe"),
         None if cep_ok is None else int(cep_ok),
         json.dumps(ver["sinais"], ensure_ascii=False), int(com_rede),
         datetime.now().isoformat()))


def _detalhar(cnpj: str, com_rede: bool) -> None:
    p = sede_real.perfil_sede(cnpj, com_rede=com_rede)
    if not p:
        print(f"{cnpj}: não localizado na base de estabelecimentos (INAPURÁVEL)")
        return
    v = sede_real.avaliar_sede(p)
    print(f"\n{cnpj} — {p.get('razao') or '(sem nome fantasia)'}")
    print(f"  {p.get('logradouro')} {p.get('numero')} {p.get('complemento') or ''}".rstrip())
    print(f"  {p.get('bairro')} · CEP {p.get('cep')} · {p.get('uf')}")
    print(f"\n  VEREDITO: {v['veredito'].upper()}  "
          f"(suspeita {v['score_suspeita']} · substância {v['score_substancia']})")
    for s in v["sinais"]:
        marca = "▲" if s["direcao"] == "suspeita" else "▼"
        print(f"    {marca} {s['id']:26s} {s['peso']:3d}  {s['detalhe']}")
    if not v["apuravel"]:
        print(f"    (inapurável: {v.get('motivo')})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cnpj", help="apura um CNPJ e imprime o laudo (não grava)")
    ap.add_argument("--top", type=int, help="limita o lote aos N maiores recebedores")
    ap.add_argument("--com-rede", action="store_true",
                    help="acrescenta OSM/CEP (mais lento: ~1,5 s por CNPJ)")
    ap.add_argument("--refazer", action="store_true", help="reavalia quem já tem veredito")
    ap.add_argument("--max-segundos", type=int, default=1800, help="bound de tempo")
    args = ap.parse_args()

    if args.cnpj:
        _detalhar(args.cnpj, args.com_rede)
        return

    t0 = time.time()
    con = _con()
    alvos = _alvos(con, args.top, args.refazer)
    print(f"[sede_real] {len(alvos)} CNPJ(s) na fila · rede={'sim' if args.com_rede else 'não'}")
    contagem: dict[str, int] = {}
    feitos = nao_achados = 0
    for cnpj in alvos:
        if time.time() - t0 > args.max_segundos:
            print(f"[sede_real] bound de {args.max_segundos}s atingido — para aqui (resumível)")
            break
        try:
            p = sede_real.perfil_sede(cnpj, com_rede=args.com_rede)
        except (sqlite3.Error, OSError, ValueError) as exc:
            print(f"  {cnpj}: erro {type(exc).__name__}: {exc}")
            continue
        if not p:
            nao_achados += 1
            continue
        v = sede_real.avaliar_sede(p)
        try:
            _gravar(con, cnpj, p, v, args.com_rede)
        except sqlite3.OperationalError as exc:
            print(f"  {cnpj}: banco ocupado ({exc}) — segue")
            continue
        contagem[v["veredito"]] = contagem.get(v["veredito"], 0) + 1
        feitos += 1
        if feitos % 200 == 0:
            con.commit()
    con.commit()
    con.close()
    print(f"[sede_real] CONCLUÍDO {datetime.now().isoformat(timespec='seconds')}: "
          f"{feitos} avaliado(s) · {nao_achados} fora da base (INAPURÁVEL) · "
          f"{time.time() - t0:.0f}s")
    for v in ("forte_suspeita", "suspeita", "indefinido", "sede_provavel", "inapuravel"):
        if contagem.get(v):
            print(f"    {v:16s} {contagem[v]:6d}")


if __name__ == "__main__":
    main()
