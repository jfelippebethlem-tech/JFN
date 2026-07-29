#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""socios_serie_historica — constrói a SÉRIE de snapshots de sócios, para saber quem SAIU e quando.

O PROBLEMA. A base tinha um snapshot único (`socios_receita.fonte_mes = '2026-05'`), com data de
entrada e nenhuma data de saída. "Fulano já era sócio no dia do certame?" era inverificável — e a
ausência era silenciosa, o que é pior, porque silêncio se lê como "não há vínculo".

A DESCOBERTA QUE TORNOU ISTO BARATO. Os caminhos oficiais da Receita estão quebrados desde
janeiro/2026 (404 em cinco variações de path; a página institucional redireciona para login). Mas o
espelho público `dados-abertos-rf-cnpj.casadosdados.com.br` guarda **41 snapshots mensais, de
2023-03 a 2026-07** — sem chave, sem cobrança, com `accept-ranges`. A série histórica não precisa
"começar agora": ela já existe e é retroativa em mais de três anos. Isso substitui, com vantagem, o
caminho por BigQuery/Base dos Dados que o dono vetou por exigir billing.

CUSTO, MEDIDO E RESPEITADO. Cada snapshot são ~600 MB em dez `Socios*.zip`. Baixar e guardar os 41
seriam ~25 GB. Não é o que este script faz: ele baixa **um zip por vez**, filtra por STREAMING para
as nossas raízes-alvo (~36 mil de 27 milhões de sócios), grava só o que interessa e **apaga o zip**.
O que fica em disco é a série filtrada, não o dump. Herda de `socios_dump_sweep` o guarda de
load/memória — a VM tem 2 vCPU e já caiu quatro vezes por trabalho pesado concorrente.

Uso:
  PYTHONPATH=. .venv/bin/python -m tools.socios_serie_historica --listar
  PYTHONPATH=. .venv/bin/python -m tools.socios_serie_historica --mes 2026-07 --mes 2026-05
  PYTHONPATH=. .venv/bin/python -m tools.socios_serie_historica --ultimos 6      # os 6 mais recentes
  PYTHONPATH=. .venv/bin/python -m tools.socios_serie_historica --diff           # só recalcula
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from compliance_agent.osint.historico_societario import (  # noqa: E402
    criar_schema,
    diff_snapshots,
    snapshots_ingeridos,
)
from tools.socios_dump_sweep import (  # noqa: E402
    _carregar_qualif,
    _carregar_raizes,
    _conectar,
    _guarda_recursos,
    _norm,
)

_ESPELHO = "http://dados-abertos-rf-cnpj.casadosdados.com.br/arquivos/"
_RE_PASTA = re.compile(r'<a href="(\d{4}-\d{2}-\d{2})/"')
_UA = {"User-Agent": "controle-externo-rj/1.0 (auditoria; fonte aberta)"}
_BATCH = 5000


def listar_snapshots() -> list[str]:
    """Datas de snapshot disponíveis no espelho, mais recente por último."""
    req = urllib.request.Request(_ESPELHO, headers=_UA)
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 — host fixo e público
        html = r.read().decode("utf-8", "ignore")
    return sorted(set(_RE_PASTA.findall(html)))


def _mes(data_pasta: str) -> str:
    return data_pasta[:7]


def _baixar(url: str, destino: Path) -> int:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=600) as r, open(destino, "wb") as f:  # noqa: S310
        n = 0
        while True:
            bloco = r.read(1 << 20)
            if not bloco:
                break
            f.write(bloco)
            n += len(bloco)
    return n


def _gravar_com_espera(con, sql: str, buf: list[tuple], *, tentativas: int = 8) -> None:
    """Grava o lote esperando o escritor concorrente sair.

    O `busy_timeout=60000` do `_conectar` não bastou: a primeira execução deste backfill morreu com
    `database is locked` no 7º de 17 snapshots, porque outra sessão manteve transação de escrita
    aberta por mais de um minuto (o `compliance.db` é compartilhado com sweeps e com o enxame). Meia
    hora de download perdida por não haver espera aqui.

    Espera crescente até ~4 min no total; se nem assim, propaga — perder o lote em silêncio seria
    produzir uma série com buraco que ninguém veria, e buraco não observado vira falsa "saída".
    """
    import time

    espera = 2.0
    for tentativa in range(1, tentativas + 1):
        try:
            con.executemany(sql, buf)
            con.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            if tentativa == tentativas:
                raise
            print(f"[serie] base ocupada (tentativa {tentativa}/{tentativas}); "
                  f"aguardando {espera:.0f}s", flush=True)
            time.sleep(espera)
            espera = min(espera * 1.8, 60.0)


def _stream_para_snapshot(zf: Path, raizes: set[str], qualif: dict, con, mes: str) -> tuple[int, int]:
    """Lê o ZIP linha-a-linha e grava em `socio_snapshot` só as raízes-alvo.

    Mesma técnica do `socios_dump_sweep`: `unzip -p` num pipe, checagem barata da raiz nos bytes 1..9
    antes de decodificar a linha inteira. 27 milhões de linhas não cabem na memória desta VM.
    """
    proc = subprocess.Popen(["unzip", "-p", str(zf)], stdout=subprocess.PIPE, bufsize=1 << 20)
    sql = ("INSERT OR REPLACE INTO socio_snapshot "
           "(fonte_mes, cnpj_basico, doc_socio, nome_norm, ident, qualificacao, data_entrada) "
           "VALUES (?,?,?,?,?,?,?)")
    lidas = casadas = 0
    buf: list[tuple] = []
    try:
        for raw in proc.stdout:
            lidas += 1
            if raw[:1] != b'"':
                continue
            if raw[1:9].decode("latin1", "ignore") not in raizes:
                continue
            p = [c.strip('"') for c in raw.decode("latin1", "ignore").rstrip("\r\n").split(";")]
            if len(p) < 6:
                continue
            cod = (p[4] or "").zfill(2) if p[4] else ""
            buf.append((mes, p[0], p[3], _norm(p[2]), p[1], qualif.get(cod, cod), p[5]))
            casadas += 1
            if len(buf) >= _BATCH:
                _gravar_com_espera(con, sql, buf); buf.clear()
        if buf:
            _gravar_com_espera(con, sql, buf)
    finally:
        proc.stdout.close()
        proc.wait()
    return lidas, casadas


def ingerir_snapshot(data_pasta: str, *, con=None, manter_zip: bool = False) -> dict:
    """Baixa, filtra e grava UM snapshot. O zip é apagado depois — o que fica é a série filtrada."""
    mes = _mes(data_pasta)
    raizes = _carregar_raizes()
    qualif = _carregar_qualif()
    fechar = con is None
    con = con or _conectar()
    criar_schema(con)
    lidas = casadas = 0
    tmp = Path(tempfile.mkdtemp(prefix="socios_", dir="/tmp"))
    try:
        for i in range(10):
            _guarda_recursos()
            url = f"{_ESPELHO}{data_pasta}/Socios{i}.zip"
            alvo = tmp / f"Socios{i}.zip"
            try:
                tam = _baixar(url, alvo)
            except Exception as e:  # noqa: BLE001 — snapshot antigo pode ter outro conjunto
                print(f"[serie] {data_pasta} Socios{i}.zip indisponível: {str(e)[:80]}", flush=True)
                continue
            a, b = _stream_para_snapshot(alvo, raizes, qualif, con, mes)
            lidas += a; casadas += b
            print(f"[serie] {mes} Socios{i}.zip {tam / 1e6:.0f}MB → {b} linhas nossas "
                  f"(de {a} lidas)", flush=True)
            if not manter_zip:
                alvo.unlink(missing_ok=True)
    finally:
        if not manter_zip:
            for f in tmp.glob("*"):
                f.unlink(missing_ok=True)
            tmp.rmdir()
    n_raizes = con.execute(
        "SELECT COUNT(DISTINCT cnpj_basico) FROM socio_snapshot WHERE fonte_mes=?", (mes,)
    ).fetchone()[0]
    con.execute(
        "INSERT OR REPLACE INTO socio_snapshot_meta "
        "(fonte_mes, origem, ingerido_em, n_linhas, n_raizes, escopo) "
        "VALUES (?,?,datetime('now'),?,?,'raizes-alvo')",
        (mes, f"espelho casadosdados {data_pasta}", casadas, n_raizes))
    con.commit()
    if fechar:
        con.close()
    return {"mes": mes, "linhas_lidas": lidas, "linhas_nossas": casadas, "raizes": n_raizes}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listar", action="store_true", help="lista os snapshots do espelho e sai")
    ap.add_argument("--mes", action="append", default=[], help="data de pasta (AAAA-MM-DD), repetível")
    ap.add_argument("--ultimos", type=int, default=0, help="ingere os N snapshots mais recentes")
    ap.add_argument("--diff", action="store_true", help="só recalcula socio_historico")
    ap.add_argument("--manter-zip", action="store_true", help="não apaga os zips (depuração)")
    a = ap.parse_args(argv)

    if a.listar:
        disp = listar_snapshots()
        con = _conectar(); criar_schema(con)
        ja = set(snapshots_ingeridos(con)); con.close()
        print(f"{len(disp)} snapshots no espelho ({disp[0]} a {disp[-1]}):")
        for d in disp:
            print(f"  {d}  {'JÁ INGERIDO' if _mes(d) in ja else ''}")
        return 0

    con = _conectar()
    criar_schema(con)
    try:
        alvos = list(a.mes)
        if a.ultimos:
            alvos = listar_snapshots()[-a.ultimos:]
        for d in alvos:
            print(f"[serie] ingerindo {d} …", flush=True)
            print("[serie]", ingerir_snapshot(d, con=con, manter_zip=a.manter_zip), flush=True)
        if alvos or a.diff:
            r = diff_snapshots(con)
            print(f"[serie] histórico recalculado: {r}", flush=True)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
