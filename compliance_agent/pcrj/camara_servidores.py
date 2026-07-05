# -*- coding: utf-8 -*-
"""Coletor da RELAÇÃO DE SERVIDORES da Câmara Municipal do Rio (dados abertos).

Fonte (dados abertos oficiais):
    https://aplicsc.camara.rj.gov.br/scriptcase/Sistemas/Portal_Transparencia/
        DadosAbertos/Cons_Relacao_Servidores_API_csv/?ANOINGRESSO=<ano>
O endpoint é um ScriptCase: a chamada por ano REGENERA um CSV temporário
(``/scriptcase/tmp/Relacao_Servidores.csv``) que precisa ser lido logo em seguida
(mesma requisição sequencial). Sem cabeçalho; ISO-8859-15; campos entre aspas e ';'.

Colunas (posicionais):
    0 Nome · 1 Vínculo · 2 Símbolo · 3 Cargo · 4 Lotação · 5 Data(ato) · 6 Data(pub) · 7 Nº

A **Lotação** já traz o gabinete parlamentar ("Gabinete Parlamentar Nº 48"). Não há CPF.

Certificado: a cadeia TLS do servidor é incompleta (falta intermediária). Como é dado
PÚBLICO e somente-leitura, usamos ``verify=False`` (documentado); nenhuma credencial trafega.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import time
from datetime import datetime, timezone

import requests
import urllib3

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.nomes import normalizar

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_API = ("https://aplicsc.camara.rj.gov.br/scriptcase/Sistemas/Portal_Transparencia/"
        "DadosAbertos/Cons_Relacao_Servidores_API_csv/?ANOINGRESSO={ano}")
_TMP = "https://aplicsc.camara.rj.gov.br/scriptcase/tmp/Relacao_Servidores.csv"

ANO_MIN = 1990
_RE_GABINETE = re.compile(r"gabinete\s+parlamentar\s+n[º°o.\s]*(\d+)", re.IGNORECASE)


def _limpar(campo: str) -> str:
    """Tira aspas e espaços de padding (a fonte enche os campos de espaços à direita)."""
    return (campo or "").strip().strip('"').strip()


def _classificar_lotacao(lotacao: str) -> tuple[int | None, str]:
    """(gabinete_num, tipo_lotacao) a partir do texto da lotação."""
    m = _RE_GABINETE.search(lotacao or "")
    if m:
        return int(m.group(1)), "gabinete_parlamentar"
    low = (lotacao or "").lower()
    if any(k in low for k in ("diretoria", "divis", "departament", "secretaria",
                              "coordena", "assessor", "presid", "procurad", "mesa")):
        return None, "administrativo"
    return None, "outro" if lotacao else "indefinido"


def baixar_ano(ano: int, session: requests.Session, timeout: int = 60) -> list[dict]:
    """Baixa e parseia a relação de servidores que ingressaram em ``ano``.

    Retorna lista de dicts já normalizados. Degrada honesto: erro/timeout → [] (loga).
    """
    try:
        session.get(_API.format(ano=ano), verify=False, timeout=timeout)
        resp = session.get(_TMP, verify=False, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  [ano {ano}] ERRO de rede: {exc}")
        return []

    texto = resp.content.decode("iso-8859-15", errors="replace")
    linhas: list[dict] = []
    agora = datetime.now(timezone.utc).isoformat()
    for row in csv.reader(io.StringIO(texto), delimiter=";", quotechar='"'):
        if not row or not _limpar(row[0]):
            continue
        campos = [_limpar(c) for c in row]
        campos += [""] * (8 - len(campos))       # padroniza tamanho
        nome, vinculo, simbolo, cargo, lotacao, data1, data2, doc_num = campos[:8]
        gab, tipo = _classificar_lotacao(lotacao)
        linhas.append({
            "nome": nome, "nome_norm": normalizar(nome), "vinculo": vinculo,
            "simbolo": simbolo, "cargo": cargo, "lotacao": lotacao,
            "gabinete_num": gab, "tipo_lotacao": tipo, "ano_ingresso": ano,
            "data1": data1, "data2": data2, "doc_num": doc_num, "coletado_em": agora,
        })
    return linhas


def coletar(ano_min: int = ANO_MIN, ano_max: int | None = None,
            db_path=None, pausa: float = 0.3) -> dict:
    """Itera todos os anos de ingresso, grava em ``pcrj_camara_servidores``.

    Idempotente (UPSERT por PK). Retorna resumo {anos, linhas, gabinetes}.
    """
    ano_max = ano_max or datetime.now(timezone.utc).year
    _db.inicializar(db_path)
    con = _db.conectar(db_path)
    session = requests.Session()
    total = 0
    anos_com_dado = 0
    try:
        for ano in range(ano_min, ano_max + 1):
            linhas = baixar_ano(ano, session)
            if not linhas:
                continue
            anos_com_dado += 1
            con.executemany(
                """INSERT INTO pcrj_camara_servidores
                   (nome,nome_norm,vinculo,simbolo,cargo,lotacao,gabinete_num,
                    tipo_lotacao,ano_ingresso,data1,data2,doc_num,coletado_em)
                   VALUES (:nome,:nome_norm,:vinculo,:simbolo,:cargo,:lotacao,
                    :gabinete_num,:tipo_lotacao,:ano_ingresso,:data1,:data2,
                    :doc_num,:coletado_em)
                   ON CONFLICT DO UPDATE SET
                    vinculo=excluded.vinculo, simbolo=excluded.simbolo,
                    tipo_lotacao=excluded.tipo_lotacao, data1=excluded.data1,
                    data2=excluded.data2, coletado_em=excluded.coletado_em""",
                linhas,
            )
            con.commit()
            total += len(linhas)
            print(f"  [ano {ano}] {len(linhas)} servidores")
            time.sleep(pausa)
        gab = con.execute(
            "SELECT COUNT(DISTINCT gabinete_num) n FROM pcrj_camara_servidores "
            "WHERE gabinete_num IS NOT NULL").fetchone()["n"]
        distintos = con.execute(
            "SELECT COUNT(DISTINCT nome_norm) n FROM pcrj_camara_servidores").fetchone()["n"]
    finally:
        con.close()
    return {"anos": anos_com_dado, "linhas": total, "pessoas_distintas": distintos,
            "gabinetes": gab}


def main() -> None:
    ap = argparse.ArgumentParser(description="Coletor de servidores da Câmara Municipal RJ")
    ap.add_argument("--ano-min", type=int, default=ANO_MIN)
    ap.add_argument("--ano-max", type=int, default=None)
    args = ap.parse_args()
    resumo = coletar(ano_min=args.ano_min, ano_max=args.ano_max)
    print(f"\nRESUMO: {resumo}")


if __name__ == "__main__":
    main()
