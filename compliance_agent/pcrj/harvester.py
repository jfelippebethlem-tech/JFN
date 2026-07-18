# -*- coding: utf-8 -*-
"""Orquestrador da captação municipal (Saúde + PPPs, 2021+) — Prefeitura do Rio.

Amarra as fontes numa varredura única, escopada e **serial** (VM 2 vCPU, um
pesado por vez): D.O. Rio (doweb) por termos de saúde + PPPs da CCPAR. Materializa
também o mapa de esfera (federal/estadual-RJ/municipal-Rio) do PNCP, para que os
mesmos motores rodem no Estado e na Prefeitura filtrando por esfera — ver
``esfera.py`` e a decisão do dono (não "limpar" o PNCP, e sim classificar).

Uso:
    python -m compliance_agent.pcrj.harvester --anos 2025,2024,2023,2022,2021 --paginas 3
    python -m compliance_agent.pcrj.harvester --so-esfera        # só (re)constrói o mapa
"""
from __future__ import annotations

import argparse
import json
import time

from . import db
from . import doweb
from . import esfera
from . import ppp_ccpar

# Termos de busca da Saúde municipal no D.O. Rio (frase exata). Curado, não exaustivo.
TERMOS_SAUDE = [
    "Secretaria Municipal de Saúde",
    "RioSaúde",
    "Complexo Hospitalar Souza Aguiar",
    "Organização Social de Saúde",
    "contrato de gestão",
    "Coordenadoria Geral de Emergência",
]

# PPPs de saúde conhecidas na CCPAR (slugs). Cresce conforme a CCPAR publica.
PPPS_SAUDE = [
    "complexo-hospitalar-souza-aguiar",
]


def varrer(*, termos=None, anos=None, max_paginas: int = 3, pausa: float = 1.5,
           incluir_ppp: bool = True, incluir_esfera: bool = True, db_path=None) -> dict:
    """Roda a varredura municipal de saúde, serial. Retorna resumo agregado.

    Idempotente (cada coletor faz UPSERT). ``anos`` usa o filtro nativo do D.O.
    (default 2021→2025). Nunca paraleliza (VM-safe).
    """
    db.inicializar(db_path)
    termos = termos or TERMOS_SAUDE
    anos = anos or [2025, 2024, 2023, 2022, 2021]

    resumo = {"esfera": None, "doe": [], "ppp": [], "anos": anos}

    # 1) mapa de esfera (leitura da compliance.db, escrita só na pcrj.db)
    if incluir_esfera:
        try:
            resumo["esfera"] = esfera.construir_mapa(db_path=db_path)
        except Exception as e:  # nunca derruba a varredura
            resumo["esfera"] = {"erro": f"{type(e).__name__}: {e}"}

    # 2) D.O. Rio por termo de saúde (serial)
    for termo in termos:
        try:
            r = doweb.coletar_termo(termo, ano_min=min(anos), max_paginas=max_paginas,
                                    anos=anos, pausa=pausa, db_path=db_path)
            resumo["doe"].append({"termo": termo, "gravadas": r["gravadas"],
                                  "por_tipo": r["por_tipo"], "n_processos": r["com_processo"]})
        except Exception as e:
            resumo["doe"].append({"termo": termo, "erro": f"{type(e).__name__}: {e}"})
        time.sleep(pausa)

    # 3) PPPs da CCPAR (serial)
    if incluir_ppp:
        for slug in PPPS_SAUDE:
            try:
                info = ppp_ccpar.coletar_projeto(slug, db_path=db_path)
                resumo["ppp"].append({"slug": slug, "fase": info.get("fase"),
                                      "n_docs": info.get("n_docs")})
            except Exception as e:
                resumo["ppp"].append({"slug": slug, "erro": f"{type(e).__name__}: {e}"})
            time.sleep(pausa)

    return resumo


def main() -> None:
    ap = argparse.ArgumentParser(description="Orquestrador da captação municipal (Saúde+PPP).")
    ap.add_argument("--anos", default="2025,2024,2023,2022,2021")
    ap.add_argument("--paginas", type=int, default=3)
    ap.add_argument("--sem-ppp", action="store_true")
    ap.add_argument("--so-esfera", action="store_true", help="só (re)constrói o mapa de esfera")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    if a.so_esfera:
        print(json.dumps(esfera.construir_mapa(db_path=a.db), ensure_ascii=False, indent=2))
        return
    anos = [int(x) for x in a.anos.split(",")]
    r = varrer(anos=anos, max_paginas=a.paginas, incluir_ppp=not a.sem_ppp, db_path=a.db)
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
