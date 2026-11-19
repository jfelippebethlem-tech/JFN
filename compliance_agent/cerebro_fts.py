# -*- coding: utf-8 -*-
"""Índice BM25 POR NOTA (SQLite FTS5) do segundo cérebro — UMA cópia, dois consumidores.

  VM-1  compliance_agent/cerebro_busca.py   (índice do vault local; comando `caso`)
  VM-2  ~/brain/brain_core.py               (índice das notas do jfn-brain; `brain_search` do MCP e /api/search)

Este arquivo vai para a VM-2 como está (deploy/vm2/brain/implantar.sh confere o md5). Só biblioteca padrão — não
importar nada do JFN aqui. Mudou a regra de busca? Muda aqui e reimplanta: as duas máquinas respondem igual.

Medido em 19/11/2026 (config/cerebro_bateria.yaml, 56 perguntas): ordenar por nota inteira com título ×6, nome do
arquivo ×8, resumo ×4 e corpo ×1 devolve a nota certa entre as 10 primeiras em 56 de 56 (jfn-brain antes: 33).
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

PESOS = (0, 6, 8, 4, 1)      # bm25 por coluna: chave (não indexada) · título · nome · resumo · corpo

_VAZIAS = set("""a o as os um uma uns umas de da do das dos em no na nos nas por para pra pro pela pelo pelas pelos com sem
sob sobre entre ate e ou mas que se como quando onde qual quais quem quanto quanta quantos quantas isso isto esse essa
esses essas este esta aquele aquela aquilo ja nao sim tambem so muito mais menos todo toda todos todas tudo cada
me mim te ele ela eles elas voce vc nos eu meu minha seu sua seus suas dele dela foi era ser sao esta estao estava
tem tinha ter teve ha vai vamos quero queremos veja ver acha achar procure favor mostra mostrar aquele tal algum
alguma alguns algumas mesmo mesma mesmos mesmas depois antes ao aos pra the ai la aqui ou seja porque pq""".split())

_RX_CNPJ = re.compile(r"(?<![\d.])\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
_RX_SEI = re.compile(r"(?<!\d)(\d{6})[/_](\d{6})[/_](\d{4})(?!\d)")
_RX_UG = re.compile(r"\b(?:ug|unidade gestora)\s*:?\s*\"?(\d{6})\b", re.I)
_RX_OB = re.compile(r"\b(20\d{2})OB(\d{5,6})\b")


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def termos(pergunta: str) -> list[str]:
    """Palavras de conteúdo da pergunta (sem acento, sem palavra vazia), na ordem, sem repetição."""
    out: list[str] = []
    for t in re.findall(r"[a-z0-9]+", sem_acento(pergunta.lower())):
        if (len(t) >= 3 or t.isdigit()) and t not in _VAZIAS and t not in out:
            out.append(t)
    return out


def cnpj_valido(d: str) -> bool:
    """Dígitos verificadores do CNPJ — barra nº de 14 dígitos que não é CNPJ (nº de contrato do PNCP, protocolo)."""
    if len(d) != 14 or not d.isdigit() or d == d[0] * 14:
        return False
    for n in (12, 13):
        pesos = list(range(n - 7, 1, -1)) + list(range(9, 1, -1))
        r = sum(int(a) * b for a, b in zip(d[:n], pesos)) % 11
        if int(d[n]) != (0 if r < 2 else 11 - r):
            return False
    return True


def entidades(texto: str) -> list[tuple[str, str]]:
    """Identificadores determinísticos no texto, sem repetição: ("cnpj", 14 dígitos) · ("processo", NNNNNN/NNNNNN/AAAA)
    · ("ug", 6 dígitos — só com "UG" escrito antes) · ("ob", AAAAOBNNNNN). CPF não é extraído, de propósito."""
    out: list[tuple[str, str]] = []
    for m in _RX_CNPJ.findall(texto):
        d = re.sub(r"\D", "", m)
        if cnpj_valido(d):
            out.append(("cnpj", d))
    out += [("processo", "/".join(m)) for m in _RX_SEI.findall(texto)]
    out += [("ug", m) for m in _RX_UG.findall(texto)]
    out += [("ob", f"{a}OB{n}") for a, n in _RX_OB.findall(texto)]
    return list(dict.fromkeys(out))


def grafias(tipo: str, chave: str) -> list[str]:
    """Como o identificador aparece escrito nas notas (para a busca por frase exata)."""
    if tipo == "cnpj" and len(chave) == 14:
        return [chave, f"{chave[:2]}.{chave[2:5]}.{chave[5:8]}/{chave[8:12]}-{chave[12:]}"]
    return [chave]


def partes(texto: str, stem: str) -> tuple[str, str, str]:
    """(título, resumo, corpo) de uma nota. Frontmatter lido por regex — há nota com YAML inválido no vault."""
    fm, corpo = "", texto
    if texto.startswith("---"):
        fim = texto.find("\n---", 3)
        if fim > 0:
            fm, corpo = texto[3:fim], texto[fim + 4:]

    def campo(nome: str) -> str:
        m = re.search(rf"^{nome}:\s*(.+)$", fm, re.M)
        return m.group(1).strip().strip("\"'") if m else ""
    h1 = re.search(r"^#\s+(.+)$", corpo, re.M)
    titulo = campo("title") or campo("name") or (h1.group(1).strip() if h1 else stem)
    resumo = " ".join(x for x in (campo("resumo"), campo("description"), campo("aliases"), campo("tags")) if x)
    return titulo, resumo, corpo


def abrir(caminho: Path) -> sqlite3.Connection:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS arq(chave TEXT PRIMARY KEY, assinatura TEXT, extra TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS nota USING fts5(chave UNINDEXED, titulo, nome, resumo, corpo, "
                "tokenize='unicode61 remove_diacritics 2')")
    return con


def conhecidos(con: sqlite3.Connection) -> dict[str, str]:
    return dict(con.execute("SELECT chave, assinatura FROM arq"))


def gravar_partes(con, chave: str, assinatura: str, titulo: str, nome: str, resumo: str, corpo: str,
                  extra: str = "") -> None:
    con.execute("DELETE FROM nota WHERE chave=?", (chave,))
    con.execute("INSERT INTO nota(chave,titulo,nome,resumo,corpo) VALUES (?,?,?,?,?)",
                (chave, titulo, nome, resumo, corpo))
    con.execute("INSERT OR REPLACE INTO arq VALUES (?,?,?)", (chave, assinatura, extra))


def gravar(con, chave: str, assinatura: str, texto: str, stem: str, extra: str = "") -> None:
    titulo, resumo, corpo = partes(texto, stem)
    gravar_partes(con, chave, assinatura, titulo, re.sub(r"[-_]+", " ", stem), resumo, corpo, extra)


def trecho_de(texto: str, tipo: str, chave: str, largura: int = 160) -> str:
    """Pedaço do texto em volta da primeira ocorrência do identificador — a prova de ONDE ele aparece."""
    for g in grafias(tipo, chave):
        i = texto.find(g)
        if i >= 0:
            return " ".join(texto[max(0, i - largura // 2): i + len(g) + largura // 2].split())
    return ""


def remover(con, chave: str) -> None:
    con.execute("DELETE FROM nota WHERE chave=?", (chave,))
    con.execute("DELETE FROM arq WHERE chave=?", (chave,))


def consultar(con, pergunta: str, n: int = 40) -> list[dict]:
    """Notas por BM25, palavras de conteúdo ligadas por OU. [{nota, titulo, trecho, extra}]"""
    ts = termos(pergunta)
    if not ts:
        return []
    linhas = con.execute(
        "SELECT nota.chave, titulo, snippet(nota, 4, '', '', ' … ', 28), extra FROM nota JOIN arq ON arq.chave=nota.chave "
        f"WHERE nota MATCH ? ORDER BY bm25(nota, {','.join(map(str, PESOS))}) LIMIT ?",
        (" OR ".join(f'"{t}"' for t in ts), n)).fetchall()
    return [{"nota": c, "titulo": t, "trecho": s, "extra": x} for c, t, s, x in linhas]


def por_identificador(con, tipo: str, chave: str, n: int = 20) -> list[dict]:
    """Notas que citam o identificador (frase exata, em qualquer grafia usual)."""
    out: list[dict] = []
    for g in grafias(tipo, chave):
        frase = '"' + " ".join(re.findall(r"[A-Za-z0-9]+", g)) + '"'
        for c, t, x in con.execute(
                "SELECT nota.chave, titulo, extra FROM nota JOIN arq ON arq.chave=nota.chave WHERE nota MATCH ? "
                f"ORDER BY bm25(nota, {','.join(map(str, PESOS))}) LIMIT ?", (frase, n)):
            out.append({"nota": c, "titulo": t, "trecho": f"{tipo} {g} citado na nota", "extra": x})
    return out
