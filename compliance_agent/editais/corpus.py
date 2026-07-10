# -*- coding: utf-8 -*-
"""Corpus de editais municipais: baixa texto do edital + itens → edital_documento.

POR QUE endpoint cru de itens: pncp.buscar_itens não traz materialOuServico (M/S),
que é o único classificador PREENCHIDO na PCRJ (CATMAT vem ~0%) e serve de
pré-partição barata no agrupamento. Degrada honesto: sem documento acessível →
documento_disponivel=0 (fica fora do peer-diff, não vira 'sem cláusula').
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter

import httpx

from compliance_agent.collectors import pncp
from compliance_agent.collectors.pncp import PNCP_BASE, _parse_id_pncp


def _material_predominante(itens: list[dict]) -> str | None:
    vals = [it.get("materialOuServico") for it in itens if it.get("materialOuServico")]
    return Counter(vals).most_common(1)[0][0] if vals else None


async def _itens_crus(id_pncp: str) -> list[dict]:
    pr = _parse_id_pncp(id_pncp)
    if not pr:
        return []
    cnpj, ano, seq = pr
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{PNCP_BASE}/orgaos/{cnpj}/compras/{ano}/{seq}/itens",
                            headers={"User-Agent": "JFN-Compliance/2.0"})
            return r.json() if r.status_code == 200 else []
    except Exception:
        return []


async def coletar_um(con, numero_controle_pncp: str) -> dict:
    docs = await pncp.baixar_documentos(numero_controle_pncp)
    itens = await _itens_crus(numero_controle_pncp)
    texto = "\n".join(d.get("texto", "") for d in docs)
    disp = 1 if texto.strip() else 0
    lic = con.execute("select ano, orgao_cnpj, objeto, valor_estimado from pcrj_licitacoes "
                      "where numero_controle_pncp=?", (numero_controle_pncp,)).fetchone()
    con.execute(
        """INSERT INTO edital_documento (numero_controle_pncp, ano, orgao_cnpj, objeto,
              material_servico, valor_estimado, texto, itens_json, documento_disponivel)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(numero_controle_pncp) DO UPDATE SET texto=excluded.texto,
              itens_json=excluded.itens_json, documento_disponivel=excluded.documento_disponivel,
              material_servico=excluded.material_servico, coletado_em=datetime('now')""",
        (numero_controle_pncp, lic["ano"] if lic else None, lic["orgao_cnpj"] if lic else None,
         lic["objeto"] if lic else None, _material_predominante(itens),
         lic["valor_estimado"] if lic else None, texto[:400_000],
         json.dumps(itens, ensure_ascii=False)[:400_000], disp))
    con.commit()
    return {"verificado": True, "documento_disponivel": disp, "n_chars": len(texto)}


async def coletar_corpus(con, limite: int | None = None, pausa: float = 0.4) -> dict:
    pend = [r[0] for r in con.execute(
        """select l.numero_controle_pncp from pcrj_licitacoes l
           left join edital_documento e on e.numero_controle_pncp = l.numero_controle_pncp
           where e.numero_controle_pncp is null and l.objeto is not null
           order by l.data_abertura desc""").fetchall()]
    if limite:
        pend = pend[:limite]
    com_doc = 0
    for nc in pend:
        try:
            r = await coletar_um(con, nc)
            com_doc += r["documento_disponivel"]
        except Exception as e:  # 1 edital ruim não derruba o corpus (INDISPONÍVEL ≠ 0)
            print(f"  edital {nc}: falhou ({e})", flush=True)
        await asyncio.sleep(pausa)
    return {"verificado": True, "processados": len(pend), "com_documento": com_doc}
