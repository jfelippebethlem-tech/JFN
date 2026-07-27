# -*- coding: utf-8 -*-
"""tcu_juris_index — índice LOCAL da jurisprudência REAL do TCU (dados abertos).

Complementa `knowledge/jurisprudencia.py` (base CURADA, escrita à mão, ~30 acórdãos). Aqui o
acervo é o oficial e completo: `jurisprudencia-selecionada.csv` (~116 MB, ~200k enunciados com
AREA/TEMA/SUBTEMA) e `sumula.csv` (~800 KB). Baixa uma vez, indexa em SQLite FTS5, consulta offline.

Duas funções que o resto do sistema não tinha:

  1. `verificar_citacao("Acórdão 1742/2026-Plenário")` — **anti-alucinação**. Todo acórdão que uma LLM
     citar num parecer passa por aqui antes de ir para o papel. Honesto: quem não está no acervo
     SELECIONADO volta `nao_confirmado` (≠ inexistente — a seleção é um subconjunto curado do TCU).
  2. `buscar_enunciados("atestado de capacidade técnica", area="Licitação")` — enunciado REAL, com
     número/ano/colegiado, para fundamentar um achado sem inventar ementa.

Fonte (verificada 2026-07-27, HTTP 200 da VM, sem auth):
  https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/jurisprudencia-selecionada/jurisprudencia-selecionada.csv
  https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/sumula/sumula.csv

CSV do TCU: delimitador `|`, aspas `"`, encoding utf-8-sig.
"""
from __future__ import annotations

import csv
import os
import re
import sqlite3
import sys
from pathlib import Path

import httpx

_BASE = "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos"
URL_SELECIONADA = f"{_BASE}/jurisprudencia-selecionada/jurisprudencia-selecionada.csv"
URL_SUMULA = f"{_BASE}/sumula/sumula.csv"

DB_PADRAO = Path(os.environ.get("JFN_TCU_JURIS_DB", Path.home() / "JFN" / "data" / "tcu_juris.db"))

# "Acórdão 1742/2026-Plenário", "AC 1.742/2026-P", "acórdão nº 2622/2013 - plenário"
_RE_CITACAO = re.compile(
    r"ac[óo]rd[ãa]o\s*(?:n[ºo°.]*\s*)?(\d{1,5}(?:\.\d{3})?)\s*/\s*(\d{4})"
    r"(?:\s*[-–—,]?\s*(plen[áa]rio|primeira\s+c[âa]mara|segunda\s+c[âa]mara|1[ªa]\s*c[âa]mara|2[ªa]\s*c[âa]mara|p|1c|2c))?",
    re.IGNORECASE,
)
_RE_SUMULA = re.compile(r"s[úu]mula\s*(?:tcu\s*)?(?:n[ºo°.]*\s*)?(\d{1,3})", re.IGNORECASE)

# Marcadores de que a citação é de OUTRA corte de contas. Este índice é do TCU: o teto de
# numeração e o acervo não valem para TCE-RJ. "Pleno"/"PLENV" é como o TCE-RJ nomeia o colegiado
# (o TCU escreve "Plenário") — confundir os dois produz falso positivo de citação fabricada.
_RE_OUTRA_CORTE = re.compile(r"\bTCE[- ]?[A-Z]{0,2}\b|\bPLENV\b|—\s*Pleno\b|\bTCM[- ]?[A-Z]{0,2}\b")

_COLEGIADO_CANON = {
    "plenario": "Plenário", "plenário": "Plenário", "p": "Plenário",
    "primeira camara": "Primeira Câmara", "primeira câmara": "Primeira Câmara",
    "1a camara": "Primeira Câmara", "1ª câmara": "Primeira Câmara", "1c": "Primeira Câmara",
    "segunda camara": "Segunda Câmara", "segunda câmara": "Segunda Câmara",
    "2a camara": "Segunda Câmara", "2ª câmara": "Segunda Câmara", "2c": "Segunda Câmara",
}

_TAG = re.compile(r"<[^>]+>")


def _limpar(html: str) -> str:
    """Enunciados do TCU vêm com HTML embutido (<p>, <b>, <a href=...>)."""
    return re.sub(r"\s+", " ", _TAG.sub(" ", html or "")).strip()


def _canon_colegiado(s: str | None) -> str | None:
    if not s:
        return None
    return _COLEGIADO_CANON.get(re.sub(r"\s+", " ", s.strip().lower()))


# ---------------------------------------------------------------- construção

def init_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS tcu_acordao (
            key TEXT PRIMARY KEY, numero INTEGER, ano INTEGER, colegiado TEXT,
            area TEXT, tema TEXT, subtema TEXT, enunciado TEXT, referencia_legal TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_acordao_num ON tcu_acordao(numero, ano);
        CREATE INDEX IF NOT EXISTS ix_acordao_area ON tcu_acordao(area, tema);
        CREATE TABLE IF NOT EXISTS tcu_sumula (
            numero INTEGER PRIMARY KEY, enunciado TEXT, area TEXT, tema TEXT, vigente TEXT
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS tcu_fts USING fts5(
            enunciado, area, tema, subtema, content='tcu_acordao', content_rowid='rowid'
        );
    """)
    con.commit()


def _linhas_csv(url: str, timeout: int = 300):
    """Streaming do CSV (o selecionada tem 116 MB — não cabe carregar inteiro na VM de 2 vCPU)."""
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as r:
        r.raise_for_status()
        resto = ""
        for bloco in r.iter_text(chunk_size=1 << 20):
            resto += bloco
            *prontas, resto = resto.split("\n")
            yield from prontas
        if resto:
            yield resto


def indexar_selecionada(con: sqlite3.Connection, url: str = URL_SELECIONADA,
                        limite: int | None = None) -> int:
    init_schema(con)
    leitor = csv.DictReader(_linhas_csv(url), delimiter="|", quotechar='"')
    n = 0
    lote: list[tuple] = []
    for row in leitor:
        num = (row.get("NUMACORDAO") or "").replace(".", "").strip()
        ano = (row.get("ANOACORDAO") or "").strip()
        if not num.isdigit() or not ano.isdigit():
            continue
        lote.append((
            row.get("KEY"), int(num), int(ano), (row.get("COLEGIADO") or "").strip(),
            row.get("AREA"), row.get("TEMA"), row.get("SUBTEMA"),
            _limpar(row.get("ENUNCIADO")), _limpar(row.get("REFERENCIALEGAL")),
        ))
        n += 1
        if len(lote) >= 2000:
            con.executemany("INSERT OR REPLACE INTO tcu_acordao VALUES (?,?,?,?,?,?,?,?,?)", lote)
            con.commit()
            lote.clear()
        if limite and n >= limite:
            break
    if lote:
        con.executemany("INSERT OR REPLACE INTO tcu_acordao VALUES (?,?,?,?,?,?,?,?,?)", lote)
    con.execute("INSERT INTO tcu_fts(tcu_fts) VALUES('rebuild')")
    con.commit()
    return n


def indexar_sumulas(con: sqlite3.Connection, url: str = URL_SUMULA) -> int:
    init_schema(con)
    leitor = csv.DictReader(_linhas_csv(url), delimiter="|", quotechar='"')
    n = 0
    for row in leitor:
        num = (row.get("NUMERO") or "").strip()
        if not num.isdigit():
            continue
        con.execute("INSERT OR REPLACE INTO tcu_sumula VALUES (?,?,?,?,?)", (
            int(num), _limpar(row.get("ENUNCIADO")), row.get("AREA"),
            row.get("TEMA"), (row.get("VIGENTE") or "").strip(),
        ))
        n += 1
    con.commit()
    return n


def abrir(db: str | Path | None = None) -> sqlite3.Connection | None:
    """Conexão só-leitura com o índice. `None` quando o índice ainda não foi construído."""
    caminho = Path(db or DB_PADRAO)
    if not caminho.exists():
        return None
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------- consulta

def teto_numeracao(colegiado: str | None, ano: int, db: str | Path | None = None) -> int | None:
    """Maior número de acórdão que aquele colegiado alcançou naquele ano, medido no acervo real.

    O TCU numera os acórdãos em série anual por colegiado. Medido em 2019-2026: o Plenário fecha o
    ano na casa dos 2.600-4.500; as Câmaras vão a dezenas de milhares. Aplica-se uma folga de 30%
    porque a Jurisprudência Selecionada é um recorte — o maior número REAL do ano é ≥ o daqui.
    """
    con = abrir(db)
    if con is None:
        return None
    if colegiado:
        linha = con.execute("SELECT MAX(numero) m FROM tcu_acordao WHERE colegiado=? AND ano=?",
                            (colegiado, ano)).fetchone()
    else:
        linha = con.execute("SELECT MAX(numero) m FROM tcu_acordao WHERE ano=?", (ano,)).fetchone()
    con.close()
    return int(linha["m"] * 1.3) if linha and linha["m"] else None


def implausivel(numero: int, colegiado: str | None, ano: int,
                db: str | Path | None = None) -> bool:
    """Citação numericamente impossível — independe de o índice estar completo.

    `nao_confirmado` só diz "não achei no recorte". Isto aqui diz "não pode existir": um
    'Acórdão 9.244/2024-Plenário' extrapola a série anual do Plenário. É o sinal forte de
    citação fabricada por LLM.
    """
    teto = teto_numeracao(colegiado, ano, db)
    return teto is not None and numero > teto


def verificar_citacao(texto: str, db: str | Path | None = None) -> list[dict]:
    """Extrai toda citação de acórdão/súmula do TCU em `texto` e confere contra o acervo real.

    Uso: guarda de saída de qualquer parecer gerado por LLM (Lex/Yoda) — citação inventada
    NÃO vai para o papel.

    status:
      `confirmado`     — número/ano existem no acervo (e o colegiado bate, quando citado)
      `colegiado_diverge` — o acórdão existe, mas em outro colegiado
      `numero_impossivel` — o número extrapola a série anual daquele colegiado. **Não existe.**
                          É a assinatura de citação fabricada por LLM. Barra o parecer.
      `nao_confirmado` — não está na Jurisprudência Selecionada. **Não é prova de inexistência**:
                          a Selecionada é um recorte curado. Trate como "citar só após conferir".
      `indice_ausente` — índice não construído (rode `indexar_selecionada`)
    """
    con = abrir(db)
    achados: list[dict] = []

    for m in _RE_CITACAO.finditer(texto or ""):
        num = int(m.group(1).replace(".", ""))
        ano = int(m.group(2))
        coleg = _canon_colegiado(m.group(3))
        item = {"tipo": "acordao", "citacao": m.group(0).strip(), "numero": num,
                "ano": ano, "colegiado_citado": coleg}
        # Janela de contexto: só o que é do TCU pode ser conferido contra este acervo.
        janela = (texto or "")[max(0, m.start() - 120):m.end() + 120]
        if _RE_OUTRA_CORTE.search(janela):
            item["status"] = "fora_do_escopo"
            item["observacao"] = "citação de outra corte de contas — este índice cobre só o TCU"
            achados.append(item)
            continue
        if con is None:
            item["status"] = "indice_ausente"
        else:
            linhas = con.execute(
                "SELECT colegiado, area, tema, enunciado FROM tcu_acordao WHERE numero=? AND ano=?",
                (num, ano)).fetchall()
            if not linhas:
                item["status"] = ("numero_impossivel" if implausivel(num, coleg, ano, db)
                                  else "nao_confirmado")
                if item["status"] == "numero_impossivel":
                    item["teto_do_ano"] = teto_numeracao(coleg, ano, db)
            elif coleg and not any(l["colegiado"] == coleg for l in linhas):
                item["status"] = "colegiado_diverge"
                item["colegiado_real"] = sorted({l["colegiado"] for l in linhas})
            else:
                item["status"] = "confirmado"
                escolhida = next((l for l in linhas if not coleg or l["colegiado"] == coleg), linhas[0])
                item["colegiado_real"] = escolhida["colegiado"]
                item["area"] = escolhida["area"]
                item["tema"] = escolhida["tema"]
                item["enunciado"] = escolhida["enunciado"]
        achados.append(item)

    for m in _RE_SUMULA.finditer(texto or ""):
        num = int(m.group(1))
        item = {"tipo": "sumula", "citacao": m.group(0).strip(), "numero": num}
        if con is None:
            item["status"] = "indice_ausente"
        else:
            linha = con.execute(
                "SELECT enunciado, vigente FROM tcu_sumula WHERE numero=?", (num,)).fetchone()
            if linha is None:
                item["status"] = "nao_confirmado"
            else:
                item["status"] = "confirmado"
                item["enunciado"] = linha["enunciado"]
                item["vigente"] = linha["vigente"]
        achados.append(item)

    if con is not None:
        con.close()
    return achados


def citacoes_suspeitas(texto: str, db: str | Path | None = None) -> list[dict]:
    """Só o que NÃO se confirmou — o que precisa sair do parecer ou ser conferido à mão."""
    return [c for c in verificar_citacao(texto, db)
            if c["status"] in ("nao_confirmado", "colegiado_diverge", "numero_impossivel")]


def buscar_enunciados(termo: str, area: str | None = None, limite: int = 5,
                      db: str | Path | None = None) -> list[dict]:
    """Enunciados REAIS do TCU por busca textual (FTS5) — fundamentação sem alucinação."""
    con = abrir(db)
    if con is None:
        return []
    # FTS5: o termo do usuário vira frase entre aspas (evita erro de sintaxe com hífen/acento)
    consulta = '"' + (termo or "").replace('"', " ").strip() + '"'
    if not consulta.strip('"'):
        con.close()
        return []
    sql = ("SELECT a.numero, a.ano, a.colegiado, a.area, a.tema, a.subtema, a.enunciado, "
           "a.referencia_legal FROM tcu_fts f JOIN tcu_acordao a ON a.rowid = f.rowid "
           "WHERE tcu_fts MATCH ?")
    params: list = [consulta]
    if area:
        sql += " AND a.area = ?"
        params.append(area)
    sql += " ORDER BY bm25(tcu_fts), a.ano DESC LIMIT ?"
    params.append(limite)
    try:
        linhas = con.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        linhas = []
    con.close()
    return [dict(l) for l in linhas]


def fundamentar(achado: str, area: str = "Licitação", limite: int = 3,
                db: str | Path | None = None) -> str:
    """Bloco de fundamentação pronto para o parecer, só com acórdão real e citável."""
    itens = buscar_enunciados(achado, area=area, limite=limite, db=db)
    if not itens:
        return ""
    linhas = [f"**Fundamentação jurisprudencial (TCU — Jurisprudência Selecionada, acervo oficial):**"]
    for i in itens:
        linhas.append(
            f"- **Acórdão {i['numero']}/{i['ano']}-{i['colegiado']}** "
            f"({i['area']} › {i['tema']}): {i['enunciado'][:400]}"
        )
    return "\n".join(linhas)


def status_indice(db: str | Path | None = None) -> dict:
    con = abrir(db)
    if con is None:
        return {"construido": False, "caminho": str(Path(db or DB_PADRAO))}
    ac = con.execute("SELECT COUNT(*) c, MIN(ano) a, MAX(ano) b FROM tcu_acordao").fetchone()
    su = con.execute("SELECT COUNT(*) c FROM tcu_sumula").fetchone()
    con.close()
    return {"construido": True, "caminho": str(Path(db or DB_PADRAO)),
            "acordaos": ac["c"], "ano_min": ac["a"], "ano_max": ac["b"], "sumulas": su["c"]}


if __name__ == "__main__":  # pragma: no cover
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "indexar":
        DB_PADRAO.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(DB_PADRAO)
        print("súmulas:", indexar_sumulas(con))
        lim = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print("acórdãos:", indexar_selecionada(con, limite=lim))
        con.close()
    elif cmd == "verificar":
        for c in verificar_citacao(" ".join(sys.argv[2:])):
            print(c["status"], "|", c["citacao"], "|", (c.get("enunciado") or "")[:120])
    elif cmd == "buscar":
        for i in buscar_enunciados(" ".join(sys.argv[2:])):
            print(f"Acórdão {i['numero']}/{i['ano']}-{i['colegiado']} :: {i['enunciado'][:200]}")
    else:
        print(status_indice())
