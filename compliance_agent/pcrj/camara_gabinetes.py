# -*- coding: utf-8 -*-
"""Mapa Gabinete Parlamentar Nº → Vereador titular (Câmara Municipal RJ).

Fonte: "Tabela atual de núcleos dos gabinetes" (planilha .xls publicada em
transparencia.camara.rj.gov.br/vereadores/gabinetes-dos-vereadores/lotacao).
Colunas: Núcleo · Gabinete Parlamentar (Nº NN) · Vereador titular · Suplente em exercício.

Sem esse mapa, a lotação da relação de servidores só diz "Gabinete Parlamentar Nº 48";
com ele, atribuímos o vereador — que é o que o cruzamento precisa ("de qual gabinete").
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone

import pandas as pd
import requests
import urllib3

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.nomes import normalizar

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_URL = "https://transparencia.camara.rj.gov.br/996-tabela-atual-de-nucleos-dos-gabinetes/file"
_RE_NUM = re.compile(r"(\d+)")


def _num(txt) -> int | None:
    m = _RE_NUM.search(str(txt or ""))
    return int(m.group(1)) if m else None


def coletar(db_path=None, url: str = _URL) -> dict:
    """Baixa a planilha, parseia e grava em ``pcrj_gabinetes`` (idempotente). Retorna resumo."""
    resp = requests.get(url, verify=False, timeout=60)
    resp.raise_for_status()
    df = pd.read_excel(io.BytesIO(resp.content), header=None, sheet_name=0)

    _db.inicializar(db_path)
    con = _db.conectar(db_path)
    agora = datetime.now(timezone.utc).isoformat()
    n = 0
    try:
        for _, row in df.iterrows():
            gab = _num(row.get(1))
            vereador = str(row.get(2) or "").strip()
            # pula cabeçalho / linhas sem número de gabinete ou sem vereador
            if gab is None or not vereador or vereador.lower() == "nan":
                continue
            suplente = str(row.get(3) or "").strip()
            if suplente and suplente.lower() != "nan":
                vereador_efetivo = suplente          # suplente em exercício assume o gabinete
                obs = f"titular {vereador.rstrip('*')}; suplente em exercício"
            else:
                vereador_efetivo = vereador.rstrip("*")
                obs = None
            con.execute(
                """INSERT INTO pcrj_gabinetes (gabinete_num,vereador,vereador_norm,coletado_em)
                   VALUES (?,?,?,?)
                   ON CONFLICT(gabinete_num) DO UPDATE SET
                     vereador=excluded.vereador, vereador_norm=excluded.vereador_norm,
                     coletado_em=excluded.coletado_em""",
                (gab, vereador_efetivo + (f" ({obs})" if obs else ""),
                 normalizar(vereador_efetivo), agora),
            )
            n += 1
        con.commit()
    finally:
        con.close()
    return {"gabinetes_mapeados": n}


if __name__ == "__main__":
    print(coletar())
