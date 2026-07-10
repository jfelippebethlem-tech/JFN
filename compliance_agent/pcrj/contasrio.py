# -*- coding: utf-8 -*-
"""Despesa por credor da PCRJ — arquivos abertos do Rio Transparente (CGM).

DESCOBERTA (2026-07-10): o portal novo (transparencia.prefeitura.rio) é vitrine;
o app ContasRio (contasrio.rio.rj.gov.br) é Vaadin 8 = server-side, NÃO scrapear.
Os dados abertos reais vivem no ASP legado:
  https://riotransparente.rio.rj.gov.br/web/index.asp?cmd=dadosAbertos
  → arquivos https://riotransparente.rio.rj.gov.br/arquivos/Open_Data_<Família>_<ANO>.csv
Famílias: Empenhos (favorecido + emp/liq/pago + modalidade + fundamentação),
Doc_Pago, Desp, Contratos, Favorecidos, Rec — **2008 a 2023 apenas**.

LIMITAÇÃO HONESTA: 2024+ não há arquivo aberto de despesa por credor
(INDISPONÍVEL ≠ 0); a cobertura recente vem dos empenhos publicados no PNCP
(pcrj_contratos, tipo "Empenho"). Encoding latin-1; separador ';'; valores pt-BR.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import httpx

from compliance_agent.emendas.coletor import parse_brl

BASE = "https://riotransparente.rio.rj.gov.br"
_PAG_DADOS_ABERTOS = f"{BASE}/web/index.asp?cmd=dadosAbertos"
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux aarch64) JFN-fiscalizacao/1.0"}
_TIMEOUT = 120

_REPO = Path(__file__).resolve().parent.parent.parent
DIR_ARQUIVOS = _REPO / "data" / "contasrio"


def descobrir_arquivos() -> dict:
    """Inventário dos CSVs anuais publicados (exclui recortes Covid, redundantes)."""
    try:
        r = httpx.get(_PAG_DADOS_ABERTOS, headers=_UA, timeout=60)
        r.raise_for_status()
        html = r.content.decode("latin-1", errors="replace")
    except Exception as e:
        return {"verificado": False, "arquivos": [], "motivo": f"riotransparente: {e}"}
    arquivos = []
    for m in re.finditer(r'href="([^"]*arquivos/Open_Data_([A-Za-z_]+?)_(\d{4})\.csv)"', html):
        url, familia, ano = m.group(1), m.group(2), int(m.group(3))
        if "covid" in familia.lower():
            continue
        if not url.startswith("http"):
            url = f"{BASE}/{url.lstrip('/')}"
        arquivos.append({"familia": familia, "ano": ano, "url": url})
    arquivos.sort(key=lambda a: (a["familia"], a["ano"]))
    return {"verificado": True, "arquivos": arquivos, "motivo": None}


def baixar(url: str, destino: Path) -> Path:
    """Download em streaming (arquivos de ~50 MB; nada em memória)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".part")
    with httpx.stream("GET", url, headers=_UA, timeout=_TIMEOUT) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
    tmp.replace(destino)
    return destino


_TIPOS_EXTERNOS = {"PESSOA JURIDICA", "PESSOA FISICA"}


def _e_credor_externo(row: dict) -> bool:
    """PESSOA JURIDICA/FISICA = credor externo; ORGAO/MATRICULA = interno.

    Valores reais do arquivo (2023): ORGAO, PESSOA JURIDICA, PESSOA FISICA,
    MATRICULA (servidor — lente da folha, não desta tabela)."""
    return (row.get("Tipo de favorecido") or "").strip().upper() in _TIPOS_EXTERNOS


def _normaliza_doc(row: dict) -> str:
    """O arquivo TIRA zeros à esquerda do documento → repõe (CNPJ 14, CPF 11)
    e mascara CPF (LGPD)."""
    d = re.sub(r"\D", "", row.get("Código do favorecido") or "")
    tipo = (row.get("Tipo de favorecido") or "").strip().upper()
    if tipo == "PESSOA JURIDICA":
        d = d.zfill(14)
        return d
    d = d.zfill(11)
    return f"***{d[3:9]}**"


def carregar_empenhos_csv(con, caminho: Path | str, arquivo_origem: str) -> int:
    """Agrega Open_Data_Empenhos por (exercício, órgão, credor, natureza, fonte)
    e faz upsert em pcrj_despesa. Retorna nº de linhas agregadas gravadas.

    POR QUE agregar: a tabela pcrj_despesa é a lente credor×órgão da perícia;
    o grão empenho-a-empenho (datas, modalidade, fundamentação) fica no arquivo
    em data/contasrio/ para drill-down sob demanda (camada 2).
    """
    ag: dict[tuple, list[float]] = {}
    # o arquivo da CGM é latin-1; amostras/testes podem estar em utf-8 —
    # utf-8 estrito primeiro (falha rápido no latin-1 real), depois latin-1
    with open(caminho, "rb") as fb:
        amostra = fb.read(1 << 20)
    try:
        amostra.decode("utf-8")
        enc = "utf-8-sig"
    except UnicodeDecodeError:
        enc = "latin-1"
    with open(caminho, encoding=enc, newline="") as fh:
        rd = csv.DictReader(fh, delimiter=";")
        for row in rd:
            if not _e_credor_externo(row):
                continue
            chave = (
                int((row.get("Exercício do empenho") or "0").strip() or 0),
                (row.get("Descrição do órgão executor") or "").strip(),
                _normaliza_doc(row),
                (row.get("Favorecido") or "").strip(),
                (row.get("Natureza da despesa") or "").strip(),
                (row.get("Fonte de recursos") or "").strip(),
            )
            v = ag.setdefault(chave, [0.0, 0.0, 0.0])
            v[0] += parse_brl(row.get("Valor empenhado"))
            v[1] += parse_brl(row.get("Valor liquidado"))
            v[2] += parse_brl(row.get("Valor pago"))
    n = 0
    for (exercicio, orgao, doc, nome, natureza, fonte), (emp, liq, pago) in ag.items():
        con.execute(
            """INSERT INTO pcrj_despesa
                 (exercicio, orgao, credor_documento, credor_nome, natureza,
                  fonte_recurso, empenhado, liquidado, pago, arquivo_origem)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(exercicio, orgao, credor_documento, natureza, fonte_recurso, arquivo_origem)
               DO UPDATE SET credor_nome=excluded.credor_nome, empenhado=excluded.empenhado,
                 liquidado=excluded.liquidado, pago=excluded.pago,
                 coletado_em=datetime('now')""",
            (exercicio, orgao, doc, nome, natureza, fonte, emp, liq, pago, arquivo_origem))
        n += 1
    con.commit()
    return n


def coletar_exercicios(con, anos: list[int]) -> dict:
    """Baixa e carrega Open_Data_Empenhos dos anos pedidos (streaming, 1 por vez)."""
    inv = descobrir_arquivos()
    if not inv["verificado"]:
        return inv
    disponiveis = {a["ano"]: a for a in inv["arquivos"] if a["familia"] == "Empenhos"}
    resultado = {}
    for ano in anos:
        if ano not in disponiveis:
            resultado[ano] = "INDISPONÍVEL (sem arquivo aberto — fonte cobre 2008–2023)"
            continue
        destino = DIR_ARQUIVOS / f"Open_Data_Empenhos_{ano}.csv"
        baixar(disponiveis[ano]["url"], destino)
        resultado[ano] = carregar_empenhos_csv(con, destino, destino.name)
    return {"verificado": True, "resultado": resultado, "motivo": None}
