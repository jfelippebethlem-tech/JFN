#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tse_cpf_corpus — baixa dos dados abertos do TSE os conjuntos com CPF COMPLETO e ingere em `cpf_corpus`.

Fonte: cdn.tse.jus.br/estatistica/sead/odsele (dados abertos oficiais; Lei 9.504/97 art. 11 e 28).
  • candidatos (Brasil inteiro): consulta_cand_{ano}_BRASIL.csv — 2016, 2018, 2020, 2022, 2026;
    2024 sem CPF publicado → ponte pelo título de eleitor + nome (`cpf_corpus.ponte_titulo`);
  • prestação de contas (RJ): receitas (doador), doador originário e despesas contratadas (fornecedor PF).

Lê só os membros necessários de cada zip por HTTP Range (o zip de 2020 tem 1,4 GB; o membro do RJ, dezenas
de MB) — nada de zip inteiro em disco. Um arquivo por vez, sequencial (volume baixo para o CDN).
Bloqueio a datacenter (403 Akamai, visto em 28/09/2026): a ferramenta PARA com erro visível — a saída é
rodar o mesmo comando numa máquina fora da nuvem (it-campo) com `--banco` apontando para um SQLite local e
trazer o arquivo com md5 conferido. Em 19/11/2026 o CDN respondeu 200/206 à VM-1.

LGPD: só contagens vão para a tela/log; o CPF completo fica só no banco (uso interno).
Uso: PYTHONPATH=. .venv/bin/python -m tools.tse_cpf_corpus [--anos 2016 2018 ...] [--so-candidatos] [--medir]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compliance_agent import cpf_corpus as cc  # noqa: E402

BASE = "https://cdn.tse.jus.br/estatistica/sead/odsele/"
ANOS = (2016, 2018, 2020, 2022, 2024, 2026)
_DB = Path("data") / "compliance.db"
_LOG = Path("data") / "tse_cpf_corpus.jsonl"
csv.field_size_limit(10_000_000)


class TSEIndisponivel(RuntimeError):
    pass


class _RangeFile(io.RawIOBase):
    """Arquivo remoto só-leitura com seek, por HTTP Range — o zipfile lê o diretório central e o membro pedido."""

    def __init__(self, url: str):
        self.url = url
        self.cli = httpx.Client(timeout=180, follow_redirects=True, headers={"User-Agent": "JFN-controle-externo/1.0"})
        h = self.cli.head(url)
        if h.status_code != 200:
            raise TSEIndisponivel(f"HTTP {h.status_code} em {url}")
        self.size = int(h.headers["content-length"])
        self.pos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        fim = min(self.size, self.pos + len(b)) - 1
        for tent in range(4):
            try:
                r = self.cli.get(self.url, headers={"Range": f"bytes={self.pos}-{fim}"})
                if r.status_code == 206:
                    break
                raise TSEIndisponivel(f"HTTP {r.status_code} (range) em {self.url}")
            except httpx.TransportError:
                if tent == 3:
                    raise
                time.sleep(5 * (tent + 1))
        n = len(r.content)
        b[:n] = r.content
        self.pos += n
        return n


def _abrir_zip(caminho: str) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BufferedReader(_RangeFile(BASE + caminho), 8 << 20))


def _linhas(z: zipfile.ZipFile, membro: str):
    with z.open(membro) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="latin-1", newline=""), delimiter=";")


def _membros_cand(z: zipfile.ZipFile) -> list[str]:
    nomes = [n for n in z.namelist() if n.lower().endswith((".csv", ".txt"))]
    br = [n for n in nomes if "BRASIL" in n.upper()]
    return br or nomes


def _membros_prestacao(z: zipfile.ZipFile, ano: int) -> list[str]:
    alvo = ("receitas_candidatos", "despesas_contratadas_candidatos", "despesas_candidatos_prestacao")
    return [n for n in z.namelist() if n.endswith(("_RJ.csv", "_RJ.txt")) and n.startswith(alvo)]


def _registrar(evento: dict) -> None:
    evento["em"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _LOG.open("a", encoding="utf-8") as f:
        f.write(cc.sem_cpf(json.dumps(evento, ensure_ascii=False)) + "\n")


def ingerir(con: sqlite3.Connection, anos, so_candidatos: bool = False) -> None:
    titulos: dict = {}
    for ano in sorted(a for a in anos if a != 2024):
        z = _abrir_zip(f"consulta_cand/consulta_cand_{ano}.zip")
        for m in _membros_cand(z):
            cont = [0]

            def _indexando(it, cont=cont):   # uma passada só: indexa o título e entrega a linha (sem lista em RAM)
                for row in it:
                    cont[0] += 1
                    cc.indexar_titulos((row,), titulos)
                    yield row
            n = cc.gravar(con, cc.pares_de_linhas(_indexando(_linhas(z, m))), "tse_candidatos", ano)
            print(f"candidatos {ano} {m}: {cont[0]} linhas → {n} pares novos", flush=True)
            _registrar({"fonte": "tse_candidatos", "ano": ano, "membro": m, "linhas": cont[0], "novos": n})
    if 2024 in anos:
        z = _abrir_zip("consulta_cand/consulta_cand_2024.zip")
        for m in _membros_cand(z):
            direto = cc.gravar(con, cc.pares_de_linhas(_linhas(z, m)), "tse_candidatos", 2024)
            ponte = cc.gravar(con, cc.ponte_titulo(_linhas(z, m), titulos), "tse_candidatos_titulo", 2024)
            print(f"candidatos 2024 {m}: {direto} com CPF publicado, "
                  f"{ponte} pelo título de eleitor ({len(titulos)} títulos conhecidos)", flush=True)
            _registrar({"fonte": "tse_candidatos_titulo", "ano": 2024, "membro": m,
                        "novos_direto": direto, "novos_ponte": ponte})
    if so_candidatos:
        return
    for ano in sorted(anos):
        arq = ("prestacao_contas/prestacao_contas_final_2016.zip" if ano == 2016
               else f"prestacao_contas/prestacao_de_contas_eleitorais_candidatos_{ano}.zip")
        try:
            z = _abrir_zip(arq)
        except TSEIndisponivel as e:
            print(f"prestação {ano}: INDISPONÍVEL ({e})", flush=True)
            _registrar({"fonte": "tse_prestacao", "ano": ano, "erro": str(e)})
            continue
        for m in _membros_prestacao(z, ano):
            n_lin = 0

            def _cont(it):
                nonlocal n_lin
                for row in it:
                    n_lin += 1
                    yield row
            n = cc.gravar(con, cc.pares_de_linhas(_cont(_linhas(z, m))), "tse_prestacao_rj", ano)
            print(f"prestação {ano} {m}: {n_lin} linhas → {n} pares novos", flush=True)
            _registrar({"fonte": "tse_prestacao_rj", "ano": ano, "membro": m, "linhas": n_lin, "novos": n})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anos", type=int, nargs="*", default=list(ANOS))
    ap.add_argument("--so-candidatos", action="store_true")
    ap.add_argument("--medir", action="store_true", help="só imprime as contagens do corpus")
    ap.add_argument("--banco", default=str(_DB))
    a = ap.parse_args()
    con = sqlite3.connect(a.banco, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cc.garantir_tabela(con)
    con.commit()
    if not a.medir:
        try:
            ingerir(con, a.anos, a.so_candidatos)
        except TSEIndisponivel as e:
            print(f"TSE INDISPONÍVEL desta máquina: {e} — rodar no it-campo com --banco local", flush=True)
            return 2
    print(json.dumps(cc.medir(con), ensure_ascii=False, indent=1))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
