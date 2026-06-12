# -*- coding: utf-8 -*-
"""Sweep DETACHED de benefícios sociais (laranja) dos SÓCIOS de fornecedores do Estado.

Para cada sócio mascarado do QSA (`socios_fornecedor`, 23.691 distintos), tenta resolver o CPF completo
por fontes OFICIAIS/PÚBLICAS (favorecidos PF nas OBs + doadores do TSE — `resolver_multi`), e, quando
resolvido (match 1:1, nome + 6 díg do meio), consulta os 6 benefícios de subsistência por CPF no Portal da
Transparência (`verificar_beneficios`). Sócio dono/recebedor de fornecedor do Estado que recebe benefício de
subsistência = indício clássico de **laranja** (interposição — art. 337-F CP; art. 11 Lei 8.429/92).

RESUMÍVEL por construção: a fila = sócios distintos AINDA NÃO em `socio_beneficio`; cada lote grava e sai.
O `beneficios_supervisor.sh` chama em loop até a fila esvaziar. Índices (favorecidos + TSE) são carregados
UMA vez por invocação (não 1 full-scan de 1,1M OBs por sócio — VM-safe, §8).

HONESTIDADE (regra-mãe): sócio NÃO resolvido é gravado como tal (resolvido=0, INDISPONÍVEL ≠ "não recebe");
benefício só afirmado com `verificado=1`. CPF completo é INTERNO (LGPD); nos produtos sai mascarado.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from compliance_agent.collectors.beneficios_sociais import verificar_beneficios
from compliance_agent.resolucao_cpf import (
    carregar_indice_favorecidos,
    carregar_indice_tse,
    middle6,
    resolver_multi,
)

_DB = Path("data") / "compliance.db"


def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS socio_beneficio (
            socio_nome_norm  TEXT NOT NULL,
            socio_doc        TEXT NOT NULL,           -- doc mascarado como em socios_fornecedor
            middle6          TEXT,
            resolvido        INTEGER DEFAULT 0,
            cpf_resolvido    TEXT DEFAULT '',         -- CPF completo: USO INTERNO (LGPD: mascarado nos produtos)
            fonte            TEXT DEFAULT '',          -- favorecidos_pf | tse_doadores | ''
            confianca        REAL DEFAULT 0,
            verificado       INTEGER DEFAULT 0,        -- API de benefícios respondeu
            recebe_beneficio INTEGER,                  -- 1 / 0 / NULL(INDISPONÍVEL)
            beneficios_json  TEXT DEFAULT '',          -- lista de tipos achados (Bolsa Família, BPC, ...)
            motivo           TEXT DEFAULT '',
            atualizado_em    TEXT,
            PRIMARY KEY (socio_nome_norm, socio_doc)
        )"""
    )
    con.commit()


def _pendentes(con: sqlite3.Connection, limite: int) -> list[tuple[str, str]]:
    """Sócios distintos mascarados ainda não processados (fila resumível)."""
    return con.execute(
        """SELECT DISTINCT s.socio_nome_norm, s.socio_doc
             FROM socios_fornecedor s
            WHERE s.socio_doc LIKE '%*%' AND s.socio_nome_norm <> ''
              AND NOT EXISTS (SELECT 1 FROM socio_beneficio b
                               WHERE b.socio_nome_norm = s.socio_nome_norm AND b.socio_doc = s.socio_doc)
            LIMIT ?""",
        (limite,),
    ).fetchall()


def _gravar(con: sqlite3.Connection, nome: str, doc: str, res: dict, benef: dict | None) -> None:
    tipos = sorted({b.get("tipo") for b in (benef or {}).get("beneficios", []) if b.get("tipo")})
    recebe = None
    verificado = 0
    motivo = res.get("motivo", "")
    if benef is not None:
        verificado = 1 if benef.get("verificado") else 0
        recebe = (1 if benef.get("recebe_beneficio") else 0) if benef.get("verificado") else None
        motivo = benef.get("motivo", "") or motivo
    con.execute(
        """INSERT INTO socio_beneficio
             (socio_nome_norm, socio_doc, middle6, resolvido, cpf_resolvido, fonte, confianca,
              verificado, recebe_beneficio, beneficios_json, motivo, atualizado_em)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(socio_nome_norm, socio_doc) DO UPDATE SET
             middle6=excluded.middle6, resolvido=excluded.resolvido, cpf_resolvido=excluded.cpf_resolvido,
             fonte=excluded.fonte, confianca=excluded.confianca, verificado=excluded.verificado,
             recebe_beneficio=excluded.recebe_beneficio, beneficios_json=excluded.beneficios_json,
             motivo=excluded.motivo, atualizado_em=excluded.atualizado_em""",
        (nome, doc, middle6(doc), 1 if res.get("resolvido") else 0, res.get("cpf", ""),
         res.get("fonte", ""), float(res.get("confianca", 0) or 0), verificado, recebe,
         json.dumps(tipos, ensure_ascii=False), motivo, datetime.now().isoformat(timespec="seconds")),
    )


async def processar_lote(db_path: str | Path | None = None, limite: int = 800, *, pausa: float = 0.0,
                         beneficio_fn=None, pf_idx: dict | None = None, tse_idx: dict | None = None) -> dict:
    """Processa UM lote de até `limite` sócios pendentes e grava em `socio_beneficio`. Retorna o resumo.

    `beneficio_fn(cpf)->dict` (async) e os índices são injetáveis (testes sem rede/SQL); ausentes → reais."""
    p = Path(db_path or _DB)
    con = sqlite3.connect(p)
    try:
        ensure_schema(con)
        pend = _pendentes(con, limite)
        if not pend:
            return {"processados": 0, "resolvidos": 0, "com_beneficio": 0}
        if pf_idx is None:
            pf_idx = carregar_indice_favorecidos(db_path=p)
        if tse_idx is None:
            tse_idx = carregar_indice_tse(db_path=p)
        if beneficio_fn is None:
            beneficio_fn = verificar_beneficios
        resolvidos = com_beneficio = 0
        for nome, doc in pend:
            res = resolver_multi(nome, doc, db_path=p, tse_idx=tse_idx, pf_idx=pf_idx)
            benef = None
            if res.get("resolvido") and res.get("cpf"):
                resolvidos += 1
                benef = await beneficio_fn(res["cpf"])
                if benef.get("verificado") and benef.get("recebe_beneficio"):
                    com_beneficio += 1
                if pausa:
                    await asyncio.sleep(pausa)
            _gravar(con, nome, doc, res, benef)
        con.commit()
        return {"processados": len(pend), "resolvidos": resolvidos, "com_beneficio": com_beneficio}
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Sweep de benefícios sociais dos sócios (laranja) — 1 lote resumível")
    ap.add_argument("--limite", type=int, default=800, help="máx. de sócios por lote")
    ap.add_argument("--pausa", type=float, default=0.3, help="pausa (s) após cada CPF resolvido (rate-limit)")
    a = ap.parse_args()
    load_dotenv(".env")  # chave do Portal (PORTAL_TRANSPARENCIA_KEY) p/ consultar benefícios
    r = asyncio.run(processar_lote(limite=a.limite, pausa=a.pausa))
    # linha que o supervisor lê: "0 socios" → fila vazia → back-off longo
    print(f"[beneficios_sweep] {r['processados']} socios processados "
          f"(resolvidos={r['resolvidos']}, com_beneficio={r['com_beneficio']})")


if __name__ == "__main__":
    main()
