# -*- coding: utf-8 -*-
"""Cruza os nomeados (Câmara/Prefeitura) com BENEFICIÁRIOS de Bolsa Família / BPC.

Fonte PÚBLICA e legal: dados abertos do Portal da Transparência (download por mês, sem
API key). Servidor/comissionado recebendo benefício assistencial é 🔴 indício de irregularidade.

⚠️ HONESTIDADE (o achado de 1ª corrida): cruzar por NOME contra um arquivo NACIONAL de ~20mi
de beneficiários é DOMINADO POR HOMÔNIMO — um nome comum bate com dezenas de pessoas distintas.
Por isso capturamos o FRAGMENTO DE CPF MASCARADO (6 dígitos do meio, públicos) e contamos
PESSOAS DISTINTAS por nome. Sinal defensável = nome que bate com **1 pessoa única** (n_pessoas=1),
melhor ainda se o benefício é no **Rio**. Mesmo assim é indício: sem o CPF completo do servidor
(só por requisição) não se prova que é a MESMA pessoa. Nunca usa base vazada.

VM-safe: baixa 1 zip → filtra em STREAMING → apaga o zip. Grava em banco DEDICADO
(`pcrj_benef.db`) — não disputa lock com o sweep que escreve no pcrj.db.
"""
from __future__ import annotations

import logging
import csv
import io
import os
import re
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.nomes import normalizar

# Cada programa tem sua JANELA de vigência (competência ym = 'AAAAMM'). Fora dela o arquivo não
# existe — não adianta baixar. Portal da Transparência (download-de-dados segue 302 p/ o zip).
_BENEFICIOS = [
    {"nome": "BPC", "url": "https://portaldatransparencia.gov.br/download-de-dados/bpc/{ym}",
     "de": "200001", "ate": "999912"},
    {"nome": "Bolsa Família",
     "url": "https://portaldatransparencia.gov.br/download-de-dados/novo-bolsa-familia/{ym}",
     "de": "202303", "ate": "999912"},           # Novo Bolsa Família: mar/2023 em diante
    {"nome": "Auxílio Brasil",
     "url": "https://portaldatransparencia.gov.br/download-de-dados/auxilio-brasil/{ym}",
     "de": "202111", "ate": "202302"},           # substituiu o BF: nov/2021 a fev/2023
    {"nome": "Auxílio Emergencial",
     "url": "https://portaldatransparencia.gov.br/download-de-dados/auxilio-emergencial/{ym}",
     "de": "202004", "ate": "202110"},           # pandemia: abr/2020 a out/2021
    {"nome": "Gás do Povo",                        # (ex-Auxílio Gás) — só há download do relançamento
     "url": "https://portaldatransparencia.gov.br/download-de-dados/gas-do-povo/{ym}",
     "de": "202512", "ate": "999912"},           # dez/2025 em diante (meses sem pagamento vêm vazios)
]
_TMP = Path("/tmp/claude-1001/-home-ubuntu/b0a66c33-983b-415a-990a-72696e7566c0/scratchpad")
BENEF_DB = _db.DB_PATH.parent / "pcrj_benef.db"
RIO = "RIO DE JANEIRO"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pcrj_beneficio (
    nome_norm   TEXT NOT NULL,
    nome        TEXT,
    beneficio   TEXT NOT NULL,   -- Bolsa Família | BPC
    municipio   TEXT,
    uf          TEXT,
    valor       TEXT,
    cpf_frag    TEXT,            -- 6 dígitos do meio do CPF mascarado (desambiguador público)
    competencia TEXT,
    coletado_em TEXT,
    PRIMARY KEY (nome_norm, beneficio, cpf_frag, municipio, competencia)
);
CREATE INDEX IF NOT EXISTS ix_benef_nome ON pcrj_beneficio(nome_norm);
"""


logger = logging.getLogger(__name__)


def _find(header: list[str], nomes: list[str]) -> int:
    up = [c.strip().upper().strip('"') for c in header]
    for alvo in nomes:
        if alvo in up:
            return up.index(alvo)
    return -1


def _baixar(url: str, dest: Path) -> bool:
    import httpx
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        return dest.exists() and dest.stat().st_size > 1000
    except Exception as e:  # noqa: BLE001
        print(f"  download falhou: {e}", flush=True)
        return False


def _filtrar_zip(path: Path, beneficio: str, alvo: dict[str, str], ym: str) -> list[tuple]:
    """Stream do CSV; devolve (nome_norm, nome, beneficio, municipio, uf, valor, cpf_frag, ym)
    para linhas cujo NOME ∈ alvo. cpf_frag = os dígitos visíveis do CPF mascarado."""
    achados: list[tuple] = []
    with zipfile.ZipFile(path) as z:
        for nm in z.namelist():
            if not nm.lower().endswith(".csv"):
                continue
            with z.open(nm) as f:
                tw = io.TextIOWrapper(f, encoding="latin-1", errors="replace")
                rd = csv.reader(tw, delimiter=";")
                header = next(rd, None)
                if not header:
                    continue
                # nome do beneficiário: Emergencial usa "NOME BENEFICIARIO"/"NOME"; BF/BPC/Brasil "NOME FAVORECIDO"
                i_nome = _find(header, ["NOME FAVORECIDO", "NOME BENEFICIÁRIO", "NOME BENEFICIARIO",
                                        "NOME DO BENEFICIÁRIO", "NOME"])
                i_mun = _find(header, ["NOME MUNICÍPIO", "NOME MUNICIPIO", "MUNICÍPIO", "MUNICIPIO"])
                i_uf = _find(header, ["UF", "SIGLA UF"])
                i_val = _find(header, ["VALOR PARCELA", "VALOR DO BENEFÍCIO", "VALOR BENEFÍCIO",
                                       "VALOR BENEFICIO", "VALOR DA PARCELA", "VALOR"])
                i_cpf = _find(header, ["CPF FAVORECIDO", "CPF DO BENEFICIÁRIO", "CPF BENEFICIARIO",
                                       "CPF DO FAVORECIDO", "CPF"])
                if i_nome < 0:  # layout novo/desconhecido — mostra o cabeçalho p/ ajuste (não silencia)
                    print(f"  [aviso] {beneficio} {ym}: coluna de NOME não achada em {nm}. "
                          f"Cabeçalho: {[c.strip(chr(34)) for c in header][:14]}", flush=True)
                if i_nome < 0:
                    continue
                for row in rd:
                    if i_nome >= len(row):
                        continue
                    g = lambda i: row[i].strip('"') if 0 <= i < len(row) else ""  # noqa: E731
                    # TRAVA DE UF (escala + certeza): servidor municipal do Rio recebe no estado do
                    # Rio. Guardar só UF=RJ corta o país inteiro (Auxílio Emergencial nacional tem
                    # dezenas de milhões de linhas → estouraria a base e a RAM da VM) e já elimina o
                    # homônimo de outro estado. O recorte fino (município do Rio) é aplicado na análise.
                    if i_uf >= 0 and g(i_uf).strip().upper() not in ("RJ", "RIO DE JANEIRO"):
                        continue
                    nn = normalizar((row[i_nome] or "").strip('"'))
                    if nn not in alvo:
                        continue
                    cpf_frag = "".join(re.findall(r"\d", g(i_cpf)))[:9]
                    achados.append((nn, alvo[nn], beneficio, g(i_mun).upper(), g(i_uf),
                                    g(i_val), cpf_frag, ym))
    return achados


def _alvo_nomeados() -> dict[str, str]:
    """Nomeados a cruzar = Câmara (quadro completo) + Prefeitura (folha COMPLETA, ~200k
    servidores de pcrj_folha_pref: efetivos, comissionados, cedidos e aposentados/pensionistas).
    Chave = nome_norm; valor = nome legível. A folha da Prefeitura entrou em bloco via
    contrachequedoc (folha_pref.py); antes só havia o recorte de acúmulo (câmara×prefeitura)."""
    con = _db.conectar()
    alvo: dict[str, str] = {}
    for r in con.execute("SELECT DISTINCT nome_norm, nome FROM pcrj_camara_servidores"):
        if r["nome_norm"]:
            alvo[r["nome_norm"]] = r["nome"]
    # folha da Prefeitura (todas as competências carregadas — união de quem já foi servidor)
    try:
        for r in con.execute("SELECT DISTINCT nome_norm, nome FROM pcrj_folha_pref"):
            if r["nome_norm"]:
                alvo.setdefault(r["nome_norm"], r["nome"] or r["nome_norm"].title())
    except Exception:  # tabela ainda não existe (folha não coletada) — degrada p/ o acúmulo antigo
        for r in con.execute(
                "SELECT DISTINCT nome_norm, COALESCE(nome_pcrj, nome_norm) AS nome "
                "FROM pcrj_prefeitura_consulta WHERE encontrado=1"):
            alvo.setdefault(r["nome_norm"], (r["nome"] or r["nome_norm"]).title())
    # SÓCIOS de empresas fornecedoras do Estado/Prefeitura (QSA Receita) — para detectar dono de
    # fornecedor recebendo benefício assistencial. Banco separado (compliance.db); leitura best-effort.
    try:
        cc = _db.sqlite3.connect(f"file:{_db.DB_PATH.parent / 'compliance.db'}?mode=ro", uri=True)
        for tab, col in (("socios_receita", "nome_norm"), ("socios_fornecedor", "socio_nome_norm")):
            try:
                for (nn, nome) in cc.execute(
                        f"SELECT DISTINCT {col}, {col.replace('_norm','')} FROM {tab} WHERE {col}<>''"):
                    if nn:
                        alvo.setdefault(nn, nome or nn.title())
            except Exception:
                continue
        cc.close()
    except Exception as exc:
        logger.warning("carga de alvos da Câmara falhou (cruzamento pode sair incompleto): %s", exc)
    con.close()
    return alvo


def coletar(ym: str = "202605") -> dict:
    alvo = _alvo_nomeados()

    _TMP.mkdir(parents=True, exist_ok=True)
    todos: list[tuple] = []
    resumo: dict = {"competencia": ym, "por_beneficio": {}}
    for spec in _BENEFICIOS:
        beneficio = spec["nome"]
        if not (spec["de"] <= ym <= spec["ate"]):
            continue  # programa não vigente nesta competência
        dest = _TMP / f"benef_{beneficio.split()[0].lower()}_{ym}.zip"
        print(f"[benef] baixando {beneficio} {ym}…", flush=True)
        if not _baixar(spec["url"].format(ym=ym), dest):
            resumo["por_beneficio"][beneficio] = "download falhou"
            continue
        print(f"[benef] filtrando {beneficio} ({dest.stat().st_size // (1<<20)}MB)…", flush=True)
        achados = _filtrar_zip(dest, beneficio, alvo, ym)
        todos.extend(achados)
        resumo["por_beneficio"][beneficio] = len(achados)
        try:
            os.remove(dest)
        except OSError as exc:
            logger.debug("tmp %s não removido: %s", dest, exc)
        print(f"[benef] {beneficio}: {len(achados)} linhas brutas", flush=True)

    agora = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(str(BENEF_DB), timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_SCHEMA)
    # ACUMULA por competência — o dono quer a SÉRIE ("recebia DURANTE a nomeação? de quando a
    # quando?"), então cada mês coletado soma ao banco. Re-rodar o mesmo mês é idempotente:
    # limpa e regrava só aquela competência (o DROP antigo full-refresh matava o histórico).
    con.execute("DELETE FROM pcrj_beneficio WHERE competencia=?", (ym,))
    con.executemany(
        "INSERT OR IGNORE INTO pcrj_beneficio "
        "(nome_norm, nome, beneficio, municipio, uf, valor, cpf_frag, competencia, coletado_em) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [(*t, agora) for t in todos])
    con.commit()

    # ── estatística HONESTA: separa sinal de ruído ────────────────────────────
    # pessoas distintas por nome (por fragmento de CPF) — homônimo = muitos fragmentos
    por_nome: dict[str, set] = {}
    em_rio: set[str] = set()
    for nn, _nome, _ben, mun, _uf, _val, frag, _ym in todos:
        por_nome.setdefault(nn, set()).add(frag or "?")
        if mun == RIO:
            em_rio.add(nn)
    unicos = {nn for nn, frags in por_nome.items() if len(frags) == 1}
    unicos_rio = unicos & em_rio
    resumo.update({
        "nomes_com_algum_match": len(por_nome),
        "provavel_homonimo (≥3 pessoas p/ o nome)": sum(1 for f in por_nome.values() if len(f) >= 3),
        "candidatos_defensaveis (1 pessoa única)": len(unicos),
        "candidatos_defensaveis_no_rio": len(unicos_rio),
    })
    con.close()
    return resumo


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(coletar(sys.argv[1] if len(sys.argv) > 1 else "202605"),
                     ensure_ascii=False, indent=1))
