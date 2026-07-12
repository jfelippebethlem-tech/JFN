#!/usr/bin/env python3
"""Consulta nominal ao portal de remuneração p/ os casos ALTA de natureza NÃO INFORMADA.

Fecha a lacuna da perícia de benefícios: a folha em bloco da Prefeitura não publica cargo/forma
de provimento — este runner consulta o contracheque (POST puro, sem browser) SÓ para quem importa:
certeza ALTA + eh_nomeado=None + lado Prefeitura. O cargo obtido alimenta pcrj_prefeitura_consulta,
de onde a classificação (pericia_beneficios._classificar_vinculo) o lê na próxima geração.

Competência da consulta = o mês MAIS RECENTE da pessoa na folha (maior chance de match); se a
competência certa devolver vazio, tenta a primeira. Throttle validado: workers=2, pausa=0.4
(0 bloqueios); sem divResultados = INDISPONÍVEL (≠ 0), a Sessao já retenta com backoff.
Retomável: quem já foi consultado HOJE é pulado (re-rodar continua de onde parou).

Uso: .venv/bin/python tools/consulta_nominal_alta.py [--limite N] [--workers 2] [--pausa 0.4]
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from compliance_agent.pcrj import db as _db  # noqa: E402
from compliance_agent.pcrj import pericia_beneficios as pb  # noqa: E402
from compliance_agent.pcrj.nomes import normalizar  # noqa: E402
from compliance_agent.pcrj.pcrj_remuneracao import Sessao  # noqa: E402


def _alvos(certezas: tuple[str, ...], desde_dias: int) -> list[dict]:
    """Casos (certeza no recorte) + natureza não informada + lado Prefeitura, com a(s)
    competência(s) de consulta. Pula quem já foi consultado nos últimos `desde_dias` dias
    (retomada de varredura longa que atravessa a meia-noite)."""
    d = pb.analisar()
    regs = [r for r in d["registros"]
            if r["certeza"] in certezas and r["eh_nomeado"] is None and "Prefeitura" in r["poder"]]
    con = _db.conectar()
    corte = (datetime.now(timezone.utc) - timedelta(days=desde_dias)).date().isoformat()
    ja_feitos = {r[0] for r in con.execute(
        "SELECT DISTINCT nome_norm FROM pcrj_prefeitura_consulta WHERE consultado_em>=?", (corte,))}
    alvos = []
    for r in regs:
        if r["nome_norm"] in ja_feitos:
            continue
        row = con.execute("SELECT MAX(competencia), MIN(competencia) FROM pcrj_folha_pref "
                          "WHERE nome_norm=?", (r["nome_norm"],)).fetchone()
        comps = [c for c in {row[0], row[1]} if c]
        alvos.append({"nome_norm": r["nome_norm"], "nome": r["nome"],
                      "comps": sorted(comps, reverse=True)})
    con.close()
    print(f"alvos {'+'.join(certezas)}+NÃO INFORMADO: {len(regs)} · já consultados (≤{desde_dias}d): "
          f"{len(regs) - len(alvos)} · a consultar: {len(alvos)}", flush=True)
    return alvos


def _consultar(alvo: dict, sess: Sessao) -> dict:
    """Consulta na(s) competência(s) da pessoa; devolve matches por matrícula (nome EXATO)."""
    matches, erro = {}, False
    for comp in alvo["comps"]:
        mes, ano = int(comp[4:6]), int(comp[:4])
        linhas = sess.consultar_nome(alvo["nome"], mes, ano)
        if linhas is None:
            erro = True
            continue
        for row in linhas:
            if normalizar(row.get("nome", "")) != alvo["nome_norm"]:
                continue
            matches.setdefault(row.get("matricula") or "?", row)
        if matches:
            break                      # a competência mais recente já resolveu
    return {**alvo, "matches": matches, "erro": erro}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--pausa", type=float, default=0.4)
    ap.add_argument("--certeza", default="alta", choices=["alta", "media", "todas"])
    ap.add_argument("--desde-dias", type=int, default=3,
                    help="pula quem já foi consultado há menos de N dias (retomada)")
    args = ap.parse_args()

    certezas = {"alta": ("ALTA",), "media": ("MÉDIA",), "todas": ("ALTA", "MÉDIA")}[args.certeza]
    alvos = _alvos(certezas, args.desde_dias)
    if args.limite:
        alvos = alvos[:args.limite]
    if not alvos:
        print("nada a consultar")
        return

    sessoes = [Sessao(pausa=args.pausa) for _ in range(args.workers)]
    con = _db.conectar()
    con.execute("PRAGMA busy_timeout=180000")   # convive com o cron mensal que escreve no pcrj.db
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cont = {"indicio_nome_unico": 0, "homonimo_ambiguo": 0, "nao_encontrado": 0,
            "indisponivel": 0, "comissao": 0, "carreira": 0}
    feitos = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(lambda t: _consultar(t[1], sessoes[t[0] % args.workers]),
                          enumerate(alvos)):
            if res["matches"]:
                conf = "indicio_nome_unico" if len(res["matches"]) == 1 else "homonimo_ambiguo"
            else:
                conf = "indisponivel" if res["erro"] else "nao_encontrado"
            cont[conf] += 1
            # substitui o estado anterior da pessoa (evita duplicata; a tabela não tem PK)
            con.execute("DELETE FROM pcrj_prefeitura_consulta WHERE nome_norm=?",
                        (res["nome_norm"],))
            for _mat, row in (res["matches"] or {"": None}).items():
                cargo = (row or {}).get("cargo") or None
                if cargo:
                    cont["comissao" if pb._cargo_comissionado(cargo) else "carreira"] += 1
                con.execute(
                    """INSERT INTO pcrj_prefeitura_consulta
                       (nome_norm,encontrado,nome_pcrj,orgao,cargo,vinculo,remuneracao,
                        confianca,bruto,consultado_em) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (res["nome_norm"], 1 if row else 0, (row or {}).get("nome"),
                     (row or {}).get("lotacao"), cargo, None,
                     (row or {}).get("valor_liquido"), conf,
                     json.dumps(row, ensure_ascii=False) if row else None, agora))
            feitos += 1
            if feitos % 25 == 0:
                con.commit()
                print(f"  ...{feitos}/{len(alvos)} · {cont}", flush=True)
    con.commit()
    con.close()
    print(json.dumps({"consultados": feitos, **cont}, ensure_ascii=False))


if __name__ == "__main__":
    main()
