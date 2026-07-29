#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tcu_indice_existencia — índice de EXISTÊNCIA de acórdãos do TCU, sem guardar o texto integral.

O PROBLEMA QUE RESOLVE. `knowledge/tcu_juris_index.verificar_citacao` confere citações contra a
**Jurisprudência Selecionada** (17.510 acórdãos), que é um recorte CURADO. Acórdão fora dela volta
como `nao_confirmado` — e `nao_confirmado` não é prova de inexistência, é "não sei". Medido em
2026-07-29, a base curada da casa tem 8 citações nesse limbo, todas aritmeticamente plausíveis.

POR QUE NÃO BAIXAR O ACERVO COMPLETO. O `acordao-completo-AAAA.csv` do TCU tem 146 a 501 MB POR
ANO — 2,2 GB só para os seis anos das citações pendentes, e muitos GB para a série inteira. Mas o
que a verificação precisa não é o texto: é saber se o par (número, ano, colegiado) EXISTE. Este
ingestor faz o streaming do CSV pela rede e guarda **onze colunas de cabeçalho**, descartando
sumário, relatório, voto e decisão à medida que passam. Nada do arquivo toca o disco.

CUIDADOS DE VM (2 vCPU, sem folga):
  · leitura em fluxo com `csv.reader` sobre a resposta HTTP — os campos do TCU têm quebra de linha
    DENTRO das aspas, e um filtro por linha (grep/awk) partiria registro no meio;
  · commit em lotes, guarda de load/memória entre anos, `nice` no processo;
  · RESUMÍVEL por ano: ano já ingerido é pulado, então a série pode ser completada aos poucos.

HTTP 200 COM CORPO DE ERRO é falha, não sucesso — a armadilha que já matou o Querido Diário em
silêncio, e que a API `contas.tcu.gov.br` desta mesma casa devolve hoje. O ingestor exige que o
cabeçalho do CSV traga as colunas esperadas antes de gravar qualquer linha.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.tcu_indice_existencia --anos 2007,2012,2019
    PYTHONPATH=. .venv/bin/python -m tools.tcu_indice_existencia --anos 2000-2026
    PYTHONPATH=. .venv/bin/python -m tools.tcu_indice_existencia --conferir "3.243/2020-Plenário"
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DB = _REPO / "data" / "tcu_juris.db"
_BASE = "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/acordao-completo"

# O que guardamos — cabeçalho, nunca corpo. O resto do registro é descartado em fluxo.
# O ESQUEMA VARIA POR ANO: os arquivos antigos (medido em 2007) não têm a coluna `KEY`, que só
# aparece nos recentes. Exigir todas as colunas fazia o ingestor recusar o acervo antigo INTEIRO
# acusando "200 com corpo de erro" — o alarme certo disparando pelo motivo errado. O contrato é o
# mínimo que identifica um acórdão; o resto entra quando existe.
_COLS_OBRIGATORIAS = ("NUMACORDAO", "ANOACORDAO", "COLEGIADO")
_COLS_OPCIONAIS = ("KEY", "TIPO", "TITULO", "NUMATA", "DATASESSAO", "RELATOR", "SITUACAO", "PROC")

_DDL = """
CREATE TABLE IF NOT EXISTS tcu_acordao_existencia (
    key         TEXT PRIMARY KEY,
    numero      INTEGER,
    ano         INTEGER,
    colegiado   TEXT,
    tipo        TEXT,
    titulo      TEXT,
    ata         TEXT,
    data_sessao TEXT,
    relator     TEXT,
    situacao    TEXT,
    processo    TEXT
)
"""
_IDX = [
    "CREATE INDEX IF NOT EXISTS ix_tcuex_num ON tcu_acordao_existencia(ano, numero)",
    "CREATE INDEX IF NOT EXISTS ix_tcuex_col ON tcu_acordao_existencia(ano, numero, colegiado)",
]
# Quais anos já entraram, e com quantas linhas — sem isto o resumo não sabe onde parou.
_DDL_CTRL = """
CREATE TABLE IF NOT EXISTS tcu_existencia_cobertura (
    ano INTEGER PRIMARY KEY, linhas INTEGER, bytes INTEGER, ingerido_em TEXT
)
"""

LOTE = 5000
# O voto e o relatório de um acórdão passam de 1 MB; o limite padrão do módulo `csv` é 128 KB e
# levanta `field larger than field limit` no meio do fluxo. Subir para 16 MB não bastou: o acervo
# de 2020 estourou até isso. O idioma correto é pedir o máximo da plataforma e recuar até caber —
# o campo é lido e DESCARTADO na mesma linha, então o teto não custa memória acumulada.
def _maior_campo_possivel() -> int:
    limite = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limite)
            return limite
        except OverflowError:
            limite //= 2


_maior_campo_possivel()


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(_DB)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(_DDL)
    con.execute(_DDL_CTRL)
    for s in _IDX:
        con.execute(s)
    con.commit()
    return con


def _guarda() -> None:
    """Pausa enquanto a VM estiver apertada. Mesma régua de `socios_dump_sweep`."""
    for _ in range(180):
        try:
            load = float(open("/proc/loadavg").read().split()[0])
            free_mb = int(subprocess.run(["free", "-m"], capture_output=True)
                          .stdout.decode().splitlines()[1].split()[6])
        except (OSError, ValueError, IndexError):
            return
        if load < 4 and free_mb >= 800:
            return
        print(f"[tcu-ex] pausa: load={load:.1f} free={free_mb}MB", flush=True)
        time.sleep(20)


def _num(s: str) -> int | None:
    d = re.sub(r"\D", "", str(s or ""))
    return int(d) if d else None


def ingerir_ano(ano: int, con: sqlite3.Connection, *, forcar: bool = False,
                timeout: float = 120.0, tentativas: int = 3) -> dict:
    """Baixa em fluxo o CSV do ano e grava só o cabeçalho de cada acórdão.

    RETENTA a conexão: medido em 2026-07-29, o servidor do TCU fechou o socket no meio de um
    arquivo de 335 MB (recebidos 180 MB). Uma leitura parcial não pode virar cobertura — o ano só
    entra em `tcu_existencia_cobertura` depois que o fluxo termina inteiro, e é isso que impede a
    lacuna de virar `inexistente`. As linhas já gravadas ficam (são verdadeiras) e a retentativa
    as reencontra com `INSERT OR IGNORE`.
    """
    import httpx as _hx

    ultimo = ""
    for tentativa in range(1, max(1, tentativas) + 1):
        try:
            return _ingerir_ano_uma_vez(ano, con, forcar=forcar, timeout=timeout)
        except (_hx.RemoteProtocolError, _hx.ReadError, _hx.ReadTimeout,
                _hx.ConnectError, _hx.ConnectTimeout) as exc:
            ultimo = f"{type(exc).__name__}: {str(exc)[:120]}"
            print(f"[tcu-ex] {ano}: conexão caiu ({ultimo}) — tentativa {tentativa}/{tentativas}",
                  flush=True)
            _guarda()
            time.sleep(5 * tentativa)
    return {"ano": ano, "erro": f"conexão instável após {tentativas} tentativas — {ultimo}",
            "parcial": True}


def _ingerir_ano_uma_vez(ano: int, con: sqlite3.Connection, *, forcar: bool = False,
                         timeout: float = 120.0) -> dict:
    ja = con.execute("SELECT linhas FROM tcu_existencia_cobertura WHERE ano=?", (ano,)).fetchone()
    if ja and not forcar:
        return {"ano": ano, "pulado": True, "linhas": ja[0]}

    import httpx

    url = f"{_BASE}/acordao-completo-{ano}.csv"
    t0 = time.time()
    inseridas = lidas = 0
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"}) as r:
        if r.status_code != 200:
            return {"ano": ano, "erro": f"HTTP {r.status_code}"}
        bruto = io.TextIOWrapper(_FluxoBytes(r), encoding="utf-8", errors="replace",
                                 newline="")
        leitor = csv.reader(bruto, delimiter="|", quotechar='"')
        try:
            cab = next(leitor)
        except StopIteration:
            return {"ano": ano, "erro": "corpo vazio"}
        # HTTP 200 com corpo de erro é falha: se o cabeçalho não é o do CSV, não grava nada.
        if not set(_COLS_OBRIGATORIAS).issubset({c.strip().upper() for c in cab}):
            return {"ano": ano, "erro": f"cabeçalho inesperado ({cab[:3]}) — 200 com corpo de erro?"}
        pos = {c.strip().upper(): i for i, c in enumerate(cab)}

        buf, sql = [], (
            "INSERT OR IGNORE INTO tcu_acordao_existencia"
            "(key,numero,ano,colegiado,tipo,titulo,ata,data_sessao,relator,situacao,processo)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)")
        def g_de(linha):
            def g(c):
                i = pos.get(c)
                return (linha[i] or "").strip() if i is not None and i < len(linha) else ""
            return g

        for linha in leitor:
            lidas += 1
            if len(linha) <= pos["COLEGIADO"]:
                continue
            g = g_de(linha)
            # Sem `KEY` (acervo antigo), a chave é o próprio identificador do acórdão.
            chave = g("KEY") or f"{ano}-{g('NUMACORDAO')}-{g('COLEGIADO')}-{g('NUMATA')}"
            buf.append((chave, _num(g("NUMACORDAO")), _num(g("ANOACORDAO")) or ano,
                        g("COLEGIADO"), g("TIPO"), g("TITULO")[:300], g("NUMATA"),
                        g("DATASESSAO"), g("RELATOR"), g("SITUACAO"), g("PROC")))
            if len(buf) >= LOTE:
                con.executemany(sql, buf)
                con.commit()
                inseridas += len(buf)
                buf.clear()
                _guarda()
        if buf:
            con.executemany(sql, buf)
            con.commit()
            inseridas += len(buf)

    con.execute("INSERT OR REPLACE INTO tcu_existencia_cobertura(ano,linhas,bytes,ingerido_em)"
                " VALUES(?,?,?,datetime('now'))", (ano, lidas, 0))
    con.commit()
    return {"ano": ano, "lidas": lidas, "gravadas": inseridas, "segundos": round(time.time() - t0)}


class _FluxoBytes(io.RawIOBase):
    """Adapta o `iter_bytes` do httpx a um objeto binário legível — o CSV é lido em fluxo."""

    def __init__(self, resposta):
        self._it = resposta.iter_bytes()
        self._resto = b""

    def readable(self) -> bool:
        return True

    def readinto(self, alvo) -> int:
        while not self._resto:
            try:
                self._resto = next(self._it)
            except StopIteration:
                return 0
        n = min(len(alvo), len(self._resto))
        alvo[:n] = self._resto[:n]
        self._resto = self._resto[n:]
        return n


def conferir(citacao: str, con: sqlite3.Connection | None = None) -> dict:
    """O par (número, ano) existe? E o colegiado bate?

    Devolve `confirmado` / `colegiado_diverge` / `inexistente_no_ano` / `ano_nao_indexado`. O
    último NÃO é negativa: é o ano que ainda não foi ingerido, e confundir os dois transformaria
    lacuna de cobertura em afirmação de que o acórdão não existe.
    """
    fechar = con is None
    con = con or _conectar()
    try:
        m = re.search(r"(\d[\d.]*)\s*/\s*((?:19|20)\d{2})", citacao or "")
        if not m:
            return {"citacao": citacao, "status": "ilegivel"}
        numero, ano = _num(m.group(1)), int(m.group(2))
        col = ""
        mc = re.search(r"(Plen[áa]rio|1[ªa]\s*C[âa]mara|2[ªa]\s*C[âa]mara)", citacao or "", re.I)
        if mc:
            col = mc.group(1)
        if not con.execute("SELECT 1 FROM tcu_existencia_cobertura WHERE ano=?", (ano,)).fetchone():
            return {"citacao": citacao, "numero": numero, "ano": ano, "status": "ano_nao_indexado",
                    "nota": "ano ainda não ingerido — lacuna de cobertura, NÃO negativa"}
        linhas = con.execute("SELECT colegiado, tipo, data_sessao, relator, processo "
                             "FROM tcu_acordao_existencia WHERE ano=? AND numero=?",
                             (ano, numero)).fetchall()
        if not linhas:
            return {"citacao": citacao, "numero": numero, "ano": ano, "status": "inexistente_no_ano",
                    "nota": "o ano está indexado e o número não consta — assinatura de citação fabricada"}
        cols = {(r[0] or "").strip() for r in linhas}
        if col and not any(_norm_col(col) == _norm_col(c) for c in cols):
            return {"citacao": citacao, "numero": numero, "ano": ano,
                    "status": "colegiado_diverge", "colegiados_reais": sorted(cols)}
        r = linhas[0]
        return {"citacao": citacao, "numero": numero, "ano": ano, "status": "confirmado",
                "colegiado": r[0], "tipo": r[1], "data_sessao": r[2], "relator": r[3],
                "processo": r[4]}
    finally:
        if fechar:
            con.close()


def _norm_col(s: str) -> str:
    t = re.sub(r"[^a-z0-9]", "", (s or "").lower()
               .replace("á", "a").replace("â", "a").replace("ª", "a"))
    return t


def _anos(spec: str) -> list[int]:
    fora: list[int] = []
    for parte in (spec or "").split(","):
        parte = parte.strip()
        if not parte:
            continue
        if "-" in parte:
            a, b = parte.split("-", 1)
            fora.extend(range(int(a), int(b) + 1))
        else:
            fora.append(int(parte))
    return sorted(set(fora))


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(description="Índice de existência de acórdãos do TCU")
    ap.add_argument("--anos", help="ex.: 2007,2012 ou 2000-2026")
    ap.add_argument("--conferir", help="citação, ex.: '3.243/2020-Plenário'")
    ap.add_argument("--cobertura", action="store_true")
    ap.add_argument("--forcar", action="store_true")
    a = ap.parse_args(argv)
    os.nice(10)
    con = _conectar()
    try:
        if a.conferir:
            import json
            print(json.dumps(conferir(a.conferir, con), ensure_ascii=False, indent=2))
            return 0
        if a.cobertura or not a.anos:
            linhas = con.execute("SELECT ano, linhas, ingerido_em FROM tcu_existencia_cobertura "
                                 "ORDER BY ano").fetchall()
            tot = con.execute("SELECT COUNT(*) FROM tcu_acordao_existencia").fetchone()[0]
            print(f"anos indexados: {len(linhas)} | acórdãos: {tot}")
            for ano, n, quando in linhas:
                print(f"  {ano}: {n:>8} linhas  ({quando})")
            return 0
        falhos: list[int] = []
        for ano in _anos(a.anos):
            _guarda()
            try:
                r = ingerir_ano(ano, con, forcar=a.forcar)
            except (csv.Error, sqlite3.Error, OSError, ValueError) as exc:
                r = {"ano": ano, "erro": f"{type(exc).__name__}: {str(exc)[:120]}"}
            print(f"[tcu-ex] {r}", flush=True)
            if r.get("erro"):
                # Ano com erro NÃO entra na cobertura e a série continua: abortar deixaria os
                # anos seguintes sem indexar por causa de um servidor instável num só arquivo.
                falhos.append(ano)
        if falhos:
            print(f"[tcu-ex] anos NÃO indexados (repetir depois): {falhos}", file=sys.stderr)
            return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
