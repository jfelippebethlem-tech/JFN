# -*- coding: utf-8 -*-
"""TSE doador×contrato (Onda 12) — cruza doadores de campanha (TSE) × sócios de fornecedores.

NUANCE LEGAL (Lei 13.165/2015 + ADI 4650): doação de **empresa** a campanha é PROIBIDA desde 2015.
Logo o conflito relevante hoje é **pessoa física (sócio/dono do fornecedor) que doou ↔ é sócia de
empresa que tem contrato com o órgão**. Para ≤2014 há doação direta de empresa. O detector cruza o
QSA (sócios do fornecedor, via registry) contra os doadores do TSE (CPF/nome).

STORAGE (decisão 2026-06-08, p/ rodar liso): store = SQLite DEDICADO `data/doacao_tse.db` com ÍNDICE
em doador_doc e doador_nome → busca sub-ms. SEPARADO do compliance.db (não incha o banco de 1GB nem
briga de WAL com o sweep SIAFE). Guarda-se SÓ o subconjunto RJ; o ZIP nacional NUNCA fica no disco
(stream + apaga). Loader é ON-DEMAND (não entra em cron/sweep) — os ZIPs do TSE têm 376MB–1,3GB.
"""
from __future__ import annotations

import csv
import io
import re
import shutil
import sqlite3
import zipfile
from pathlib import Path

import httpx

from .base import Resultado, agora_iso

_REPO = Path(__file__).resolve().parent.parent.parent
_DB = _REPO / "data" / "doacao_tse.db"

# URL do CDN do TSE por ano (receitas de candidatos). Layout/colunas mudam por eleição → mapeamento
# robusto por nome de coluna (com fallbacks). Confirmado: 2022=376MB, 2020=1.3GB.
_CDN = {
    2022: "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2022.zip",
    2020: "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2020.zip",
    2018: "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2018.zip",
    2016: "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2016.zip",
    2014: "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_2014.zip",
}

# nomes de coluna conhecidos do TSE (variam por ano) → campo canônico
_COLMAP = {
    "doador_doc": ("NR_CPF_CNPJ_DOADOR", "CPF_CNPJ_DOADOR", "NR_CPFCNPJ_DOADOR", "NR_DOCUMENTO_DOADOR"),
    "doador_nome": ("NM_DOADOR", "NM_DOADOR_RFB", "NOME_DOADOR"),
    "beneficiario": ("NM_CANDIDATO", "NM_UE", "NM_PARTIDO", "NM_BENEFICIARIO"),
    "partido": ("SG_PARTIDO", "SIGLA_PARTIDO"),
    "valor": ("VR_RECEITA", "VR_DOCUMENTO", "VALOR_RECEITA"),
    "uf": ("SG_UF", "UF", "SG_UF_DOADOR"),
}


def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(_DB))
    db.execute(
        "CREATE TABLE IF NOT EXISTS doacao_tse ("
        "ano INT, uf TEXT, doador_nome TEXT, doador_doc TEXT, "
        "beneficiario TEXT, partido TEXT, valor REAL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS ix_doc ON doacao_tse(doador_doc)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_nome ON doacao_tse(doador_nome)")
    db.commit()
    return db


def stats() -> dict:
    db = _conn()
    try:
        n = db.execute("SELECT COUNT(*) FROM doacao_tse").fetchone()[0]
        anos = [r[0] for r in db.execute("SELECT DISTINCT ano FROM doacao_tse ORDER BY ano").fetchall()]
        return {"linhas": n, "anos": anos, "db": str(_DB)}
    finally:
        db.close()


def _idx(header: list[str], chaves: tuple[str, ...]) -> int:
    up = [h.strip().upper().strip('"') for h in header]
    for k in chaves:
        if k in up:
            return up.index(k)
    return -1


def carregar_doacoes_rj(ano: int, *, url: str | None = None, min_disco_gb: float = 3.0) -> int:
    """Baixa o ZIP do TSE do ano, extrai SÓ as linhas UF=RJ das receitas e persiste em doacao_tse.
    Storage-safe: stream do ZIP (não extrai nacional p/ disco), apaga o ZIP no fim, guarda só RJ.
    ON-DEMAND (não rodar em cron — ZIPs de 376MB–1.3GB). Retorna nº de linhas RJ inseridas.
    """
    url = url or _CDN.get(ano)
    if not url:
        raise ValueError(f"sem URL do CDN p/ {ano} (anos: {sorted(_CDN)})")
    livre_gb = shutil.disk_usage(str(_REPO)).free / 1e9
    if livre_gb < min_disco_gb:
        raise RuntimeError(f"disco insuficiente ({livre_gb:.1f}GB < {min_disco_gb}GB) — abortado p/ não encher a VM")
    zip_path = Path(f"/tmp/tse_{ano}.zip")
    if not zip_path.exists() or zip_path.stat().st_size < 1000:
        with httpx.stream("GET", url, timeout=600, follow_redirects=True) as r:
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
    db = _conn()
    db.execute("DELETE FROM doacao_tse WHERE ano=?", (ano,))  # idempotente por ano
    inseridas = 0
    try:
        with zipfile.ZipFile(zip_path) as z:
            receitas = [n for n in z.namelist()
                        if re.search(r"receita", n, re.I) and n.lower().endswith(".csv")]
            # OTIMIZAÇÃO storage/CPU: o TSE fornece arquivo POR UF (ex.: receitas_candidatos_2022_RJ.csv).
            # Ler só os *_RJ.csv (2 arquivos) em vez dos 54 nacionais. Fallback: nacional + filtro SG_UF=RJ.
            so_rj = [n for n in receitas if re.search(r"_RJ\.csv$", n, re.I)]
            alvos = so_rj or receitas
            for nome in alvos:
                with z.open(nome) as fh:
                    txt = io.TextIOWrapper(fh, encoding="latin-1", newline="")
                    rd = csv.reader(txt, delimiter=";")
                    try:
                        header = next(rd)
                    except StopIteration:
                        continue
                    ci = {k: _idx(header, v) for k, v in _COLMAP.items()}
                    if ci["doador_doc"] < 0 or ci["uf"] < 0:
                        continue  # não é o arquivo de receitas com doador
                    lote = []
                    for row in rd:
                        try:
                            if (row[ci["uf"]].strip().strip('"').upper() != "RJ"):
                                continue
                            val = row[ci["valor"]].replace(".", "").replace(",", ".").strip('"') if ci["valor"] >= 0 else "0"
                            lote.append((
                                ano, "RJ",
                                row[ci["doador_nome"]].strip('"') if ci["doador_nome"] >= 0 else "",
                                _digitos(row[ci["doador_doc"]]),
                                row[ci["beneficiario"]].strip('"') if ci["beneficiario"] >= 0 else "",
                                row[ci["partido"]].strip('"') if ci["partido"] >= 0 else "",
                                float(val) if val and val.replace(".", "").replace("-", "").isdigit() else 0.0,
                            ))
                        except (IndexError, ValueError):
                            continue
                        if len(lote) >= 5000:
                            db.executemany("INSERT INTO doacao_tse VALUES (?,?,?,?,?,?,?)", lote)
                            inseridas += len(lote); lote = []
                    if lote:
                        db.executemany("INSERT INTO doacao_tse VALUES (?,?,?,?,?,?,?)", lote)
                        inseridas += len(lote)
        db.commit()
    finally:
        db.close()
        try: zip_path.unlink()  # storage-safe: ZIP nacional não fica no disco
        except OSError: pass
    return inseridas


def doador_contrato(cnpj_fornecedor: str) -> Resultado:
    """1) sócios (QSA) do fornecedor via registry. 2) procura esses CPFs/nomes em doacao_tse.
    3) devolve casamentos (sócio doou) + valor + ano + beneficiário. Sinal de CONFLITO POTENCIAL
    (não acusação): sócio do fornecedor financiou campanha. Honesto: dados do TSE (REAL).

    CAVEAT (2026-06-08): as APIs públicas de CNPJ MASCARAM o CPF do sócio (***127777**), então o
    casamento efetivo é por NOME (o CPF só casa com QSA não-mascarado, de fonte gov/paga). Nome pode
    ser ambíguo → o achado é INDÍCIO a conferir, nunca acusação."""
    from . import lookup
    emp = lookup("registry", cnpj=cnpj_fornecedor)
    socios = [(s.get("nome"), _digitos(s.get("doc"))) for s in (emp.dados or {}).get("socios", [])] if emp.ok else []
    if not _DB.exists():
        return Resultado(True, {"fornecedor": cnpj_fornecedor, "n_socios": len(socios),
                                "doacoes_de_socios": [], "nota": "doacao_tse vazia — rodar carregar_doacoes_rj(ano)"},
                         "tse", agora_iso())
    db = _conn()
    achados = []
    try:
        for nome, doc in socios:
            q = "SELECT ano, doador_nome, beneficiario, partido, valor FROM doacao_tse WHERE "
            params: list = []
            conds = []
            if doc:
                conds.append("doador_doc=?"); params.append(doc)
            if nome:
                conds.append("upper(doador_nome)=upper(?)"); params.append(nome)
            if not conds:
                continue
            rows = db.execute(q + " OR ".join(conds), params).fetchall()
            for ano, dn, ben, part, val in rows:
                achados.append({"socio": nome, "ano": ano, "beneficiario": ben,
                                "partido": part, "valor": val})
    finally:
        db.close()
    return Resultado(True, {"fornecedor": cnpj_fornecedor, "n_socios": len(socios),
                            "doacoes_de_socios": achados, "n_doacoes": len(achados)},
                     "tse", agora_iso())


class DoadorContratoTSE:
    """Backend funcao=eleitoral: doador×contrato (QSA do fornecedor × doadores TSE/RJ)."""
    id = "tse_doador_contrato"
    funcao = "eleitoral"

    def disponivel(self) -> bool:
        return True

    def consultar(self, *, cnpj: str, **_) -> Resultado:
        return doador_contrato(cnpj)
