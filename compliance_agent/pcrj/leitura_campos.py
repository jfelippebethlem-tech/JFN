# -*- coding: utf-8 -*-
"""Leitura ESTRUTURADA dos documentos municipais (CCON, conferência SEI): o texto vira campos.

Cada íntegra em ``pcrj_processo_doc`` passa por extratores pequenos e testados (nº do contrato,
partes/CNPJ, valor, prazo/vigência, fundamento legal, postos, assinantes "com senha", nº SEI e
verificador+CRC). O resultado vai para ``pcrj_doc_campos(numero_processo, seq, campo, valor, trecho)``
com o TRECHO de origem — o campo sem trecho não existe, e "não consta" fica registrado como tal.

    python -m compliance_agent.pcrj.leitura_campos            # roda em tudo que ainda não foi lido
    python -m compliance_agent.pcrj.leitura_campos --stats
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime

from compliance_agent.pcrj import db as pcrj_db

# padrões medidos nos autos reais de 13-15/09/2026 (SME × AGILE: contrato 145/2025, 167/2025, TA 119/2025, TR)
_RX = {
    "contrato_numero": re.compile(r"\bCONTRATO\s+N[ºo°.]?\s*(\d{1,5}/20\d{2})", re.I),
    "termo_aditivo": re.compile(r"(\d+)[ºo°]?\s*TERMO\s+ADITIVO\s+N[ºo°.]?\s*(\d{1,5}/20\d{2})", re.I),
    "cnpj": re.compile(r"CNPJ[^0-9]{0,25}(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})", re.I),
    # "O valor total do presente Contrato é de R$ …" · "O valor do presente termo aditivo é de R$ …" · "VALOR TOTAL DO TERMO ADITIVO: R$ …"
    "valor_total": re.compile(r"valor\s+(?:(?:total|global)\s+(?:do\s+(?:presente\s+)?(?:contrato|termo\s+aditivo|instrumento|acordo)\s*)?|do\s+(?:presente\s+)?(?:contrato|termo\s+aditivo|instrumento|acordo)\s*)(?::|(?:é|e)?\s*de)\s*R\$\s?([\d.]{1,15},\d{2})", re.I),
    # "pelo valor de R$ …", "no valor de R$ …" (cota, empenho, parcela): valor MENCIONADO, não o total do contrato
    "valor_mencionado": re.compile(r"(?:pelo|no|de|ao)\s+valor\s+de\s+R\$\s?([\d.]{1,15},\d{2})", re.I),
    "valor_mensal": re.compile(r"(?:despesa|valor)\s+mensal\s+(?:estimad[ao]\s+)?(?:de\s+)?R\$\s?([\d.]{1,15},\d{2})", re.I),
    "fundamento": re.compile(r"\b(art\.?\s*7[45],?\s*(?:inciso\s+)?[IVX]+|art\.?\s*2[45],?\s*(?:inciso\s+)?[IVX]+|art\.?\s*107|art\.?\s*12[45])[^.;\n]{0,60}?Lei\s+(?:Federal\s+)?n?[ºo°.]?\s*(1[34]\.\d{3}/20\d{2}|8\.666/93)", re.I),
    "prazo_vigencia": re.compile(r"(?:prazo|vig[êe]ncia)[^.\n]{0,60}?(\d{2}/\d{2}/20\d{2})\s*(?:a|até|ate|→)\s*(\d{2}/\d{2}/20\d{2})", re.I),
    # "410 postos" · "10 (dez) postos" — a 1ª versão aceitava 40 chars de qualquer coisa entre o número e a
    # palavra e casou "Rua Vinte e Quatro de Maio, 421 ( comercial…" e "EIS-PRO-2022/12888 …" (fabricava o sinal)
    "postos": re.compile(r"(?<![\d./-])(\d{1,4})\s*(?:\([a-záéíóú\s]{2,30}\)\s*)?postos?\b", re.I),
    "assinado_por": re.compile(r"Assinado\s+com\s+senha\s+por\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s]{6,80}?)\s*-\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9\s/]{2,40}?)\s*/\s*(\d{3,6})", re.I),
    "processo_sei": re.compile(r"\b(\d{6}\.\d{6}/20\d{2}-\d{2})\b"),
    "processo_legado": re.compile(r"\b([A-Z]{2,5}-[A-Z]{3}-20\d{2}/\d{5})\b"),
    "verificador_crc": re.compile(r"c[óo]digo\s+verificador\s*:?\s*(?:n[ºo°.]?\s*)?(\d{6,8})\s*(?:,|e)?\s*(?:o\s+)?c[óo]digo\s+CRC\s*:?\s*(?:n[ºo°.]?\s*)?([0-9A-F]{8})\b", re.I),
    "pregao": re.compile(r"Preg[ãa]o\s+(?:Eletr[ôo]nico\s+)?(?:n[ºo°.]?\s*)?(?:PE-RP-)?([A-Z-]*\d{3,6}/20\d{2})", re.I),
    "data_assinatura": re.compile(r"(?:Rio de Janeiro|Aos)\s*,?\s*(?:dias?\s+)?(\d{1,2})\s*(?:\(\w+\)\s*)?(?:dias?\s+)?(?:de|do\s+m[êe]s\s+de)\s+(janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+(?:de|do\s+ano\s+de)\s+(20\d{2})", re.I),
}
_MESES = {m: i for i, m in enumerate(("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
                                     "setembro", "outubro", "novembro", "dezembro"), 1)}
_MESES["marco"] = 3

DDL = """CREATE TABLE IF NOT EXISTS pcrj_doc_campos (
    numero_processo TEXT NOT NULL, seq INTEGER NOT NULL, campo TEXT NOT NULL, valor TEXT NOT NULL, trecho TEXT,
    lido_em TEXT, PRIMARY KEY (numero_processo, seq, campo, valor));
CREATE INDEX IF NOT EXISTS ix_pcrj_doc_campos_campo ON pcrj_doc_campos(campo, valor);
CREATE TABLE IF NOT EXISTS pcrj_doc_lido (numero_processo TEXT NOT NULL, seq INTEGER NOT NULL, n_campos INTEGER,
    lido_em TEXT, PRIMARY KEY (numero_processo, seq));"""


def _brl(s: str) -> str:
    return s.replace(".", "").replace(",", ".")


def _trecho(texto: str, m: re.Match, raio: int = 90) -> str:
    return re.sub(r"\s+", " ", texto[max(0, m.start() - raio):m.end() + raio]).strip()


_RX_PROC_QUALQUER = re.compile(r"\b(\d{6}\.\d{6}/20\d{2}-\d{2}|[A-Z]{2,5}-[A-Z]{3}-20\d{2}/\d{5})\b")
COLETIVO_A_PARTIR_DE = 4   # documento com ≥4 processos distintos = página coletiva do D.O. (extratos lado a lado)


def _normalizar(texto: str) -> str:
    t = re.sub(r"[ \t]+", " ", texto or "")
    t = re.sub(r"(-)\s*\n?\s*(20\d{2}/\d{5})", r"\1\2", t)          # "SME-PRO- 2025/38233" quebrado na linha
    return re.sub(r"(\d{6}\.\d{6}/)\s+(20\d{2}-\d{2})", r"\1\2", t)


def extrair(texto: str, processo: str | None = None, raio: int = 700) -> list[dict]:
    """→ [{campo, valor, trecho}], sem repetição de (campo, valor). Nunca inventa: só o que casou.
    Com `processo` informado e documento COLETIVO (≥4 processos distintos — página do D.O.), cada campo só
    vale se o nº de processo mais próximo do trecho for o próprio (medido 17/09: o art. 75, VIII do vizinho
    virava emergência nossa). O campo `processo` nunca é filtrado (é a âncora)."""
    t = _normalizar(texto)
    saida, vistos = [], set()
    alvo = (processo or "").upper()
    ancoras = [(pm.start(), pm.group(1).upper()) for pm in _RX_PROC_QUALQUER.finditer(t)]
    coletivo = bool(alvo) and len({a for _, a in ancoras}) >= COLETIVO_A_PARTIR_DE

    def _do_alvo(m) -> bool:
        if not coletivo:
            return True
        perto = [(abs(pos - m.start()), a) for pos, a in ancoras if abs(pos - m.start()) <= raio]
        return bool(perto) and min(perto)[1] == alvo

    def add(campo, valor, m):
        valor = str(valor).strip()
        if campo != "processo" and not _do_alvo(m):
            return
        if valor and (campo, valor) not in vistos:
            vistos.add((campo, valor))
            saida.append({"campo": campo, "valor": valor, "trecho": _trecho(t, m)})

    for m in _RX["contrato_numero"].finditer(t):
        add("contrato_numero", m.group(1), m)
    for m in _RX["termo_aditivo"].finditer(t):
        add("termo_aditivo", f"{m.group(1)}º TA {m.group(2)}", m)
    for m in _RX["cnpj"].finditer(t):
        add("cnpj", re.sub(r"\D", "", m.group(1)), m)
    for m in _RX["valor_total"].finditer(t):
        add("valor_total", _brl(m.group(1)), m)
    for m in _RX["valor_mensal"].finditer(t):
        add("valor_mensal", _brl(m.group(1)), m)
    for m in _RX["valor_mencionado"].finditer(t):
        add("valor_mencionado", _brl(m.group(1)), m)
    for m in _RX["fundamento"].finditer(t):
        add("fundamento", re.sub(r"\s+", " ", f"{m.group(1)} Lei {m.group(2)}"), m)
    for m in _RX["prazo_vigencia"].finditer(t):
        add("prazo_vigencia", f"{m.group(1)} a {m.group(2)}", m)
    for m in _RX["postos"].finditer(t):
        if int(m.group(1)) >= 3:
            add("postos", m.group(1), m)
    for m in _RX["assinado_por"].finditer(t):
        add("assinado_por", f"{m.group(1).strip().upper()} ({m.group(2).strip()} / {m.group(3)})", m)
    for m in _RX["processo_sei"].finditer(t):
        add("processo", m.group(1), m)
    for m in _RX["processo_legado"].finditer(t):
        add("processo", m.group(1), m)
    for m in _RX["verificador_crc"].finditer(t):
        add("verificador_crc", f"{m.group(1)}/{m.group(2).upper()}", m)
    for m in _RX["pregao"].finditer(t):
        add("pregao", m.group(1), m)
    for m in _RX["data_assinatura"].finditer(t):
        mes = _MESES.get(m.group(2).lower())
        if mes:
            add("data_assinatura", f"{m.group(3)}-{mes:02d}-{int(m.group(1)):02d}", m)
    return saida


def ler_pendentes(db_path=None, limite: int = 5000) -> dict:
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    con.executescript(DDL)
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n_docs = n_campos = 0
    try:
        rows = con.execute(
            "SELECT d.numero_processo, d.seq, d.texto FROM pcrj_processo_doc d LEFT JOIN pcrj_doc_lido l "
            "ON l.numero_processo=d.numero_processo AND l.seq=d.seq WHERE l.seq IS NULL AND d.texto IS NOT NULL "
            "AND length(d.texto) >= 40 LIMIT ?", (limite,)).fetchall()
        for numero, seq, texto in rows:
            campos = extrair(texto, numero)
            con.executemany("INSERT OR IGNORE INTO pcrj_doc_campos VALUES (?,?,?,?,?,?)",
                            [(numero, seq, c["campo"], c["valor"], c["trecho"], agora) for c in campos])
            con.execute("INSERT OR REPLACE INTO pcrj_doc_lido VALUES (?,?,?,?)", (numero, seq, len(campos), agora))
            n_docs += 1
            n_campos += len(campos)
        con.commit()
        tot = con.execute("SELECT count(*), count(DISTINCT numero_processo) FROM pcrj_doc_campos").fetchone()
    finally:
        con.close()
    return {"documentos_lidos": n_docs, "campos": n_campos, "total_campos": tot[0], "processos_com_campos": tot[1]}


def campos_do_processo(numero: str, db_path=None) -> dict[str, list[dict]]:
    """Campos agrupados por nome para um processo — insumo do LAI, do Lex e do painel."""
    con = pcrj_db.conectar(db_path)
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='pcrj_doc_campos'").fetchone():
            return {}
        saida: dict[str, list[dict]] = {}
        for seq, campo, valor, trecho in con.execute(
                "SELECT seq, campo, valor, trecho FROM pcrj_doc_campos WHERE upper(numero_processo)=upper(?) ORDER BY campo, seq",
                (numero,)):
            saida.setdefault(campo, []).append({"seq": seq, "valor": valor, "trecho": trecho})
        return saida
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--limite", type=int, default=5000)
    a = ap.parse_args()
    import json
    if a.stats:
        con = pcrj_db.conectar()
        for campo, n, nd in con.execute("SELECT campo, count(*), count(DISTINCT valor) FROM pcrj_doc_campos GROUP BY 1 ORDER BY 2 DESC"):
            print(f"{campo:18} {n:7,} ({nd:,} distintos)".replace(",", "."))
        return
    print(json.dumps(ler_pendentes(limite=a.limite), ensure_ascii=False))


if __name__ == "__main__":
    main()
