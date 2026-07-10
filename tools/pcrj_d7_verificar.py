#!/usr/bin/env python3
"""Verificador do D7 — mata ou confirma cada indício de fracionamento na origem.

O falso-positivo conhecido do D7: entregas de ATA DE REGISTRO DE PREÇOS geram N
empenhos pequenos legítimos. Este verificador resolve, para cada fornecedor
flagueado, a COMPRA de origem de cada empenho no PNCP (numeroControlePncpCompra
→ /orgaos/{cnpj}/compras/{ano}/{seq}) e olha a MODALIDADE:

  Dispensa (8) / Inexigibilidade (9)  → indício SE MANTÉM
  Pregão/Concorrência (ata, SRP)      → indício DERRUBADO (compra licitada)

Atualiza alertas.status: 'confirmado' | 'descartado' | 'novo' (sem dado).
Uso: .venv/bin/python tools/pcrj_d7_verificar.py [--desde 20240101]
Só LÊ o compliance.db fora do lock (updates de status são curtos).
"""
import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compliance_agent.collectors import pncp  # noqa: E402
from compliance_agent.emendas import db as edb  # noqa: E402

MODALIDADES_DIRETAS = {8, 9}   # Dispensa, Inexigibilidade


async def _modalidade_da_compra(numero_compra: str, cache: dict) -> tuple[int | None, str]:
    """'CNPJ-1-SEQ/ANO' → (modalidadeId, modalidadeNome) via API de consulta."""
    if not numero_compra:
        return None, "sem link de compra"
    if numero_compra in cache:
        return cache[numero_compra]
    parsed = pncp._parse_id_pncp(numero_compra)
    if not parsed:
        cache[numero_compra] = (None, f"id não parseável: {numero_compra}")
        return cache[numero_compra]
    cnpj, ano, seq = parsed
    # POR QUE consulta e não gestão: /api/pncp/v1 devolve 301 p/ compras;
    # /api/consulta/v1 responde 200 com modalidadeId/Nome (verificado ao vivo)
    j = await pncp._get_consulta(f"/orgaos/{cnpj}/compras/{ano}/{seq}", {})
    if not j:
        cache[numero_compra] = (None, "compra INDISPONÍVEL no PNCP")
    else:
        cache[numero_compra] = (j.get("modalidadeId"),
                                j.get("modalidadeNome") or str(j.get("modalidadeId")))
    await asyncio.sleep(0.3)
    return cache[numero_compra]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="20240101")
    args = ap.parse_args()
    d_ini = datetime.strptime(args.desde, "%Y%m%d").date()

    con = edb.conectar()
    alertas = con.execute(
        """select id, titulo, evidencias from alertas
           where tipo='pcrj_d7_fracionamento' and status='novo'""").fetchall()
    if not alertas:
        print("nenhum alerta d7 pendente")
        return
    cache: dict = {}
    resumo = []
    for a in alertas:
        ev = json.loads(a["evidencias"])
        modalidades: dict[str, str] = {}
        diretas = licitadas = sem_dado = 0
        # cada empenho/contrato flagueado é buscado DIRETO na API de gestão
        # ('CNPJ-2-SEQ/ANO' → /orgaos/{cnpj}/contratos/{ano}/{seq}) — a consulta
        # por cnpjFornecedor retorna vazio p/ empenhos (verificado ao vivo)
        for nc in ev.get("controles_pncp", []):
            parsed = pncp._parse_id_pncp(nc)
            if not parsed:
                sem_dado += 1
                continue
            cnpj_org, ano, seq = parsed
            c = await pncp._get_pncp(f"/orgaos/{cnpj_org}/contratos/{ano}/{seq}", {})
            await asyncio.sleep(0.3)
            if not c:
                sem_dado += 1
                modalidades[nc] = "contrato INDISPONÍVEL"
                continue
            mid, mnome = await _modalidade_da_compra(c.get("numeroControlePncpCompra"), cache)
            modalidades[nc] = mnome
            if mid in MODALIDADES_DIRETAS:
                diretas += 1
            elif mid is None:
                sem_dado += 1
            else:
                licitadas += 1
        if diretas >= 3:
            status, veredito = "confirmado", f"CONFIRMA — {diretas} origens em contratação direta"
        elif licitadas and not diretas:
            status, veredito = "descartado", f"DERRUBA — origens licitadas/ata ({licitadas})"
        else:
            status, veredito = "novo", f"INCONCLUSIVO (diretas={diretas} licitadas={licitadas} sem_dado={sem_dado})"
        con.execute("update alertas set status=? where id=?", (status, a["id"]))
        ev["verificacao_origem"] = {"veredito": veredito, "modalidades": modalidades,
                                    "verificado_em": datetime.now().isoformat(timespec="seconds")}
        con.execute("update alertas set evidencias=? where id=?",
                    (json.dumps(ev, ensure_ascii=False), a["id"]))
        con.commit()
        resumo.append((a["titulo"][:60], veredito))
        print(f"{a['titulo'][:60]} → {veredito}", flush=True)
    print("\n== resumo ==")
    for t, v in resumo:
        print(f"  {v[:9]} | {t}")


if __name__ == "__main__":
    asyncio.run(main())
