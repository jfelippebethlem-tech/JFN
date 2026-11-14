# -*- coding: utf-8 -*-
"""Sweep de CPF nos documentos do SEI (habilitação/contrato social/procuração) — a fonte AUTORITATIVA de
CPF completo de sócio. Varre o `conteudo_documentos` já capturado em `data/sei_cache/*.json` (e processos
futuros), extrai CPF+nome VÁLIDOS (`compliance_agent.sei.extrair_cpf`, dígito verificador conferido) e grava
em `sei_cpf` — que vira 3ª fonte do resolver de CPF (favorecidos PF + TSE + **SEI**).

Base legal: contratação pública é aberta; dever de fiscalização do Deputado (CF art. 70-71; LGPD art. 7º,II/23).
Honesto: só CPF com DV válido; cada par guarda o contexto p/ conferência; resolução por nome+6 díg = 1:1.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

from compliance_agent.sei.cache_arquivo import glob_cache, ler_json
from compliance_agent.sei.extrair_cpf import extrair_cpfs

_DB = Path("data") / "compliance.db"
_CACHE = Path("data") / "sei_cache"


def _norm(s: str) -> str:
    s = (s or "").upper().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS sei_cpf (
            cpf TEXT NOT NULL, nome TEXT, nome_norm TEXT, middle6 TEXT,
            numero_sei TEXT, contexto TEXT, extraido_em TEXT,
            PRIMARY KEY (cpf, numero_sei)
        )""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_sei_cpf_nm6 ON sei_cpf(nome_norm, middle6)")
    con.commit()


def _texto_do_arquivo(d: dict) -> str:
    """Concatena texto + conteudo_documentos de um cdp_SEI.json."""
    partes = [str(d.get("texto") or "")]
    for doc in (d.get("conteudo_documentos") or []):
        if isinstance(doc, dict):
            partes.append(str(doc.get("conteudo") or ""))
    return "\n".join(partes)


def varrer_cache(db_path: str | Path | None = None, cache_dir: str | Path | None = None) -> dict:
    """Varre os JSON do sei_cache, extrai CPFs válidos e grava em sei_cpf. Resumível (PK cpf+numero_sei)."""
    con = sqlite3.connect(Path(db_path or _DB))
    try:
        ensure_schema(con)
        # `glob_cache`/`ler_json`: 8.496 de 9.260 blobs estão em `.json.zst` (14/11/2026) — o glob antigo via 764.
        files = list(glob_cache(Path(cache_dir or _CACHE), "cdp_SEI_*.json"))
        n_arq = n_cpf = 0
        for f in files:
            d = ler_json(f)
            if not isinstance(d, dict):
                continue
            n_arq += 1
            numero = d.get("numero") or os.path.basename(f)
            for par in extrair_cpfs(_texto_do_arquivo(d)):
                cpf = par["cpf"]
                con.execute(
                    "INSERT OR IGNORE INTO sei_cpf (cpf,nome,nome_norm,middle6,numero_sei,contexto,extraido_em) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (cpf, par["nome"], _norm(par["nome"]), cpf[3:9], str(numero),
                     par["contexto"][:200], datetime.now().isoformat(timespec="seconds")))
                n_cpf += 1
        con.commit()
        total = con.execute("SELECT COUNT(*), COUNT(DISTINCT cpf) FROM sei_cpf").fetchone()
        return {"arquivos": n_arq, "cpfs_gravados": n_cpf, "total_sei_cpf": total[0], "cpfs_distintos": total[1]}
    finally:
        con.close()


MARCA_ACERVO = Path("data") / ".sei_cpf_acervo_vistos.json"


def varrer_acervo(db_path: str | Path | None = None, acervo: str | Path | None = None,
                  limite: int = 0, marca: str | Path | None = None) -> dict:
    """Varre o ACERVO (`data/sei_arquivo/*/texto/*.txt`), não só o cache — é 7× mais texto.

    POR QUE ISTO FALTAVA. `varrer_cache` lê os `cdp_SEI_*.json` do `sei_cache`: 557 arquivos,
    0,04 GB. O acervo, que é o produto do `sei_arquivar` e do sweep, tem **2.351 processos e 48.983
    arquivos de texto, 0,29 GB** — o mesmo dado, extraído e já OCRizado, sete vezes maior. O índice
    de CPF do SEI é o menor dos três corpora do resolver (14.075 chaves contra 62.439 dos
    favorecidos-PF e 434.815 do TSE), e é o único que cresce com a captura que já roda todo dia.

    FONTE LEGÍTIMA, e vale dizer por quê: o CPF completo aparece aqui em contrato social, procuração
    e documento de habilitação juntados ao processo administrativo — peça pública de contratação
    pública. Não há base vazada envolvida; o que a Receita publica mascarado (o QSA) continua sendo
    usado apenas como máscara, e serve de checksum anti-homônimo.

    Resumível e idempotente: a PK é (cpf, numero_sei) e a inserção é `INSERT OR IGNORE`, então
    rodar duas vezes não duplica nem apaga o que veio do cache — o índice só cresce.
    """
    con = sqlite3.connect(Path(db_path or _DB))
    con.execute("PRAGMA busy_timeout=60000")
    try:
        ensure_schema(con)
        raiz = Path(acervo or (Path(_DB).parent / "sei_arquivo"))
        pastas = sorted(d for d in raiz.iterdir() if d.is_dir()) if raiz.is_dir() else []
        if limite:
            pastas = pastas[:limite]
        # INCREMENTAL (14/11/2026): a captura dos nós entrega dezenas de processos por hora e a varredura
        # inteira relê 6 mil pastas. A marca guarda, por pasta, a assinatura do `texto/` (nº de arquivos +
        # bytes); pasta igual à da última passada é pulada. Pasta VARRIDA sem CPF também fica marcada — é o
        # que distingue "não tem CPF" (medido) de "nunca foi lida" (INDISPONÍVEL).
        marca_arq = Path(marca) if marca else None
        vistos = {}
        if marca_arq and marca_arq.is_file():
            try:
                vistos = json.loads(marca_arq.read_text("utf-8"))
            except (OSError, ValueError):
                vistos = {}
        n_pulados = 0
        n_proc = n_arq = n_cpf = 0
        agora = datetime.now().isoformat(timespec="seconds")
        for pasta in pastas:
            tdir = pasta / "texto"
            if not tdir.is_dir():
                continue
            # o número do processo vem do NOME da pasta (030001_075841_2024 → SEI-030001/075841/2024)
            partes = pasta.name.split("_")
            numero = (f"SEI-{partes[0]}/{partes[1]}/{partes[2]}"
                      if len(partes) >= 3 else pasta.name)
            txts = sorted(tdir.glob("*.txt"))
            assinatura = f"{len(txts)}:{sum(f.stat().st_size for f in txts)}"
            if marca_arq and vistos.get(pasta.name, {}).get("a") == assinatura:
                n_pulados += 1
                continue
            n_proc += 1
            antes = n_cpf
            for f in txts:
                try:
                    txt = f.read_text("utf-8", errors="ignore")
                except OSError:
                    continue
                n_arq += 1
                for par in extrair_cpfs(txt):
                    cpf = par["cpf"]
                    con.execute(
                        "INSERT OR IGNORE INTO sei_cpf "
                        "(cpf,nome,nome_norm,middle6,numero_sei,contexto,extraido_em) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (cpf, par["nome"], _norm(par["nome"]), cpf[3:9], numero,
                         par["contexto"][:200], agora))
                    n_cpf += 1
            if marca_arq:
                vistos[pasta.name] = {"a": assinatura, "cpfs": n_cpf - antes, "em": agora}
            # COMMIT CURTO: a cada 200 pastas a trava de escrita do compliance.db ficava ~1 min com este
            # processo, e o lex_execucao (busy_timeout 30 s) perdeu 9 pareceres já pagos em 14/11/2026.
            if n_proc % 20 == 0:
                con.commit()
                if marca_arq:
                    marca_arq.write_text(json.dumps(vistos), "utf-8")
            if n_proc % 200 == 0:
                print(f"  …{n_proc} processos · {n_arq} arquivos · {n_cpf} pares", flush=True)
        con.commit()
        if marca_arq:
            marca_arq.write_text(json.dumps(vistos), "utf-8")
        tot = con.execute("SELECT COUNT(*), COUNT(DISTINCT cpf) FROM sei_cpf").fetchone()
        return {"processos": n_proc, "pulados_sem_mudanca": n_pulados, "varridos_total": len(vistos), "arquivos": n_arq, "pares_vistos": n_cpf,
                "total_sei_cpf": tot[0], "cpfs_distintos": tot[1]}
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Sweep de CPF nos documentos do SEI (fonte autoritativa)")
    ap.add_argument("--cache", default=str(_CACHE))
    ap.add_argument("--acervo", action="store_true",
                    help="varre data/sei_arquivo/*/texto/*.txt (7× mais texto que o cache)")
    ap.add_argument("--limite", type=int, default=0, help="só os N primeiros processos do acervo")
    a = ap.parse_args()
    if a.acervo:
        r = varrer_acervo(limite=a.limite, marca=MARCA_ACERVO)
        print(f"[sei_cpf_sweep] ACERVO: {r['processos']} processos lidos · {r['pulados_sem_mudanca']} sem mudança · "
              f"{r['varridos_total']} pastas varridas no total · {r['arquivos']} arquivos · "
              f"{r['cpfs_distintos']} CPFs distintos em sei_cpf ({r['total_sei_cpf']} pares)")
        return
    r = varrer_cache(cache_dir=a.cache)
    print(f"[sei_cpf_sweep] {r['arquivos']} arquivos · {r['cpfs_distintos']} CPFs distintos válidos em sei_cpf "
          f"({r['total_sei_cpf']} pares cpf×processo)")


if __name__ == "__main__":
    main()
