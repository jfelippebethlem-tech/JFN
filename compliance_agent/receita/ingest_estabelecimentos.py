# -*- coding: utf-8 -*-
"""Ingestão do dump "Estabelecimentos" da Receita Federal (dados abertos CNPJ).

Fonte: zips oficiais da RFB (layout 2026-05) já baixados em
``data/receita_dump/Estabelecimentos*.zip`` — CSV com separador ``;``,
encoding latin-1, campos entre aspas, 30 colunas (ver ``LAYOUT``).

Filtro deliberado de escopo (documentado em ``deve_ingerir``): o Brasil
inteiro tem ~66M de linhas e não cabe no perfil desta VM (2 vCPU); ingerimos
apenas UF=RJ + os ``cnpj_basico`` de ``_nossas_raizes.txt`` (universo já
fiscalizado, nacional). Honestidade: o que ficou de fora está INDISPONÍVEL
no DB, não é "inexistente".

Uso (CLI):
    python -m compliance_agent.receita.ingest_estabelecimentos \\
        --zip 'data/receita_dump/Estabelecimentos*.zip' \\
        --db data/compliance.db --raizes data/receita_dump/_nossas_raizes.txt

VM-safe: streaming puro (zipfile + TextIOWrapper), lotes de 5000, sem pandas.
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import sqlite3
import unicodedata
import zipfile

# Ordem oficial das colunas do CSV (layout RFB 2026-05, 30 campos).
LAYOUT = [
    "cnpj_basico", "cnpj_ordem", "cnpj_dv", "matriz_filial", "nome_fantasia",
    "situacao_cadastral", "data_situacao", "motivo_situacao",
    "nome_cidade_exterior", "pais", "data_inicio_atividade",
    "cnae_principal", "cnae_secundaria", "tipo_logradouro", "logradouro",
    "numero", "complemento", "bairro", "cep", "uf", "municipio",
    "ddd1", "telefone1", "ddd2", "telefone2", "ddd_fax", "fax",
    "correio_eletronico", "situacao_especial", "data_situacao_especial",
]

# Código RFB → texto (chave sem zeros à esquerda; código desconhecido fica cru).
_SITUACAO = {"1": "NULA", "2": "ATIVA", "3": "SUSPENSA", "4": "INAPTA", "8": "BAIXADA"}

# Colunas persistidas na tabela `estabelecimentos` (mesmas chaves do dict de
# `parse_linha`); `cnpj` é a PK.
_COLUNAS = [
    "cnpj", "cnpj_basico", "matriz_filial", "nome_fantasia",
    "situacao_cadastral", "data_situacao", "motivo_situacao",
    "data_inicio_atividade", "cnae_principal", "cnae_secundaria",
    "tipo_logradouro", "logradouro", "numero", "complemento", "bairro",
    "cep", "uf", "municipio", "telefone1", "telefone2",
    "correio_eletronico", "endereco_norm",
    "situacao_especial", "data_situacao_especial",
]

_LOTE = 5000
_PROGRESSO_A_CADA = 500_000


def _so_digitos(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def parse_linha(campos: list[str]) -> dict | None:
    """Converte uma linha crua do CSV num dict normalizado (ou None se malformada).

    Normalizações: cnpj completo 14 dígitos (basico+ordem+dv), telefones
    ddd+numero só dígitos, cep só dígitos, e-mail lower/strip, situação
    cadastral mapeada para texto e ``endereco_norm`` (UPPER, sem acento,
    espaços colapsados) para cruzamento de endereço compartilhado.
    """
    if len(campos) < len(LAYOUT):
        return None
    r = dict(zip(LAYOUT, campos))
    cnpj = _so_digitos(r["cnpj_basico"] + r["cnpj_ordem"] + r["cnpj_dv"])
    if len(cnpj) != 14:
        return None
    situacao = r["situacao_cadastral"].strip()
    endereco = " ".join((r["tipo_logradouro"] + " " + r["logradouro"] + " "
                         + r["numero"] + " " + r["bairro"] + " "
                         + _so_digitos(r["cep"])).split())
    return {
        "cnpj": cnpj,
        "cnpj_basico": r["cnpj_basico"],
        "matriz_filial": r["matriz_filial"],
        "nome_fantasia": r["nome_fantasia"],
        "situacao_cadastral": _SITUACAO.get(situacao.lstrip("0") or "0", situacao),
        "data_situacao": r["data_situacao"],
        "motivo_situacao": r["motivo_situacao"],
        "data_inicio_atividade": r["data_inicio_atividade"],
        "cnae_principal": r["cnae_principal"],
        "cnae_secundaria": r["cnae_secundaria"],
        "tipo_logradouro": r["tipo_logradouro"],
        "logradouro": r["logradouro"],
        "numero": r["numero"],
        "complemento": r["complemento"],
        "bairro": r["bairro"],
        "cep": _so_digitos(r["cep"]),
        "uf": r["uf"],
        "municipio": r["municipio"],
        "telefone1": _so_digitos(r["ddd1"] + r["telefone1"]),
        "telefone2": _so_digitos(r["ddd2"] + r["telefone2"]),
        "correio_eletronico": r["correio_eletronico"].strip().lower(),
        "endereco_norm": _sem_acento(endereco).upper(),
        "situacao_especial": r["situacao_especial"],
        "data_situacao_especial": r["data_situacao_especial"],
    }


def deve_ingerir(row: dict, raizes: set[str]) -> bool:
    """Filtro de escopo: UF=RJ OU raiz (cnpj_basico) do nosso universo.

    Deliberado: o dump nacional (~66M linhas) não cabe no perfil da VM
    (2 vCPU / disco); RJ inteiro + as raízes de ``_nossas_raizes.txt``
    (empresas já fiscalizadas, inclusive filiais fora do RJ) cobrem o
    universo de interesse. Fora disso = INDISPONÍVEL no DB, não ≠ 0.
    """
    return row["uf"] == "RJ" or row["cnpj_basico"] in raizes


def _criar_schema(conn: sqlite3.Connection) -> None:
    cols = ", ".join(f"{c} TEXT" for c in _COLUNAS if c != "cnpj")
    conn.execute(f"CREATE TABLE IF NOT EXISTS estabelecimentos "
                 f"(cnpj TEXT PRIMARY KEY, {cols})")
    for col in ("endereco_norm", "telefone1", "correio_eletronico",
                "cnae_principal", "cnpj_basico"):
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_estab_{col} "
                     f"ON estabelecimentos({col})")


def _carregar_raizes(raizes_path: str | None) -> set[str]:
    if not raizes_path:
        return set()
    with open(raizes_path, encoding="utf-8") as fh:
        return {ln.strip() for ln in fh if ln.strip()}


def ingerir(zip_glob: str, db_path: str, raizes_path: str | None = None) -> dict:
    """Ingere os zips do glob em ``db_path`` (tabela ``estabelecimentos``).

    Streaming: nunca materializa o CSV; INSERT OR REPLACE em lotes de 5000,
    uma transação por lote. Retorna {'lidas', 'ingeridas', 'arquivos'}.
    """
    raizes = _carregar_raizes(raizes_path)
    arquivos = sorted(glob.glob(zip_glob))
    conn = sqlite3.connect(db_path)
    _criar_schema(conn)
    sql = (f"INSERT OR REPLACE INTO estabelecimentos ({', '.join(_COLUNAS)}) "
           f"VALUES ({', '.join('?' * len(_COLUNAS))})")
    lidas = ingeridas = 0
    lote: list[tuple] = []

    def _flush() -> None:
        nonlocal lote
        if lote:
            with conn:
                conn.executemany(sql, lote)
            lote = []

    for zpath in arquivos:
        with zipfile.ZipFile(zpath) as zf:
            for membro in zf.namelist():
                with zf.open(membro) as raw:
                    texto = io.TextIOWrapper(raw, encoding="latin-1", newline="")
                    for campos in csv.reader(texto, delimiter=";"):
                        lidas += 1
                        if lidas % _PROGRESSO_A_CADA == 0:
                            print(f"[ingest] {lidas:,} lidas / "
                                  f"{ingeridas:,} ingeridas ({zpath})", flush=True)
                        row = parse_linha(campos)
                        if row is None or not deve_ingerir(row, raizes):
                            continue
                        lote.append(tuple(row[c] for c in _COLUNAS))
                        ingeridas += 1
                        if len(lote) >= _LOTE:
                            _flush()
    _flush()
    conn.close()
    return {"lidas": lidas, "ingeridas": ingeridas, "arquivos": len(arquivos)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingestão do dump Estabelecimentos (RFB) — RJ + nossas raízes")
    ap.add_argument("--zip", required=True, help="glob dos zips (entre aspas)")
    ap.add_argument("--db", required=True, help="caminho do sqlite alvo")
    ap.add_argument("--raizes", default=None,
                    help="txt com cnpj_basico (8 díg.) por linha")
    args = ap.parse_args()
    resumo = ingerir(args.zip, args.db, args.raizes)
    print(f"[ingest] FIM: {resumo['lidas']:,} lidas, "
          f"{resumo['ingeridas']:,} ingeridas, {resumo['arquivos']} arquivos")


if __name__ == "__main__":
    main()
