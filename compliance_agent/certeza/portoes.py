# -*- coding: utf-8 -*-
"""portoes — o portão determinístico de TODA escrita de fato ou de achado.

Mesma regra de ouro do portão do autoaprimoramento (`autoaprimoramento/portao.py`): quem aprova é código, com o
motivo de cada regra. Aqui o que se julga não é uma mudança de prompt, é uma ESCRITA:

  P1 identidade       o fato tem id estável (`familia:chave[:chave…]:medida`)
  P2 tipo e faixa     valor finito, unidade conhecida, dentro da faixa; valor monetário nunca é sentinela (1e12)
  P3 proveniência     fonte, consulta, data de referência e hash da fonte — sem os quatro não entra
  P4 estado           estado da casa; INDISPONÍVEL não carrega valor (INDISPONÍVEL ≠ 0)
  P5 prova primária   VERIFICADO (e toda graduação 🔴/🟡) exige nível de prova 2
  P6 pagamento        "pago" VERIFICADO exige base = OB contabilizada com envio CONFIRMADO (status ao lado do valor)
  P7 não regride      nível de prova menor não substitui nível maior (fica arquivado como recusa)
  P8 leu antes        quem regrava apresenta a versão que LEU; se o registro mudou desde então, a escrita é recusada

Os mesmos contratos servem a três usos: `julgar_fato` (registro de fatos), `escrever` (upsert guardado de linha
em tabela de achado — para código novo) e `auditar`/`fotografar` (controle DETECTIVO sobre as tabelas que já
existem, sem tocar em quem escreve). `ddl_gatilhos` gera o controle PREVENTIVO de faixa no próprio banco.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
import sqlite3
import time

from . import config

RE_ID = re.compile(r"^[a-z][a-z0-9_]*(:[A-Za-z0-9_.\-]+)+$")
RE_NOME_SQL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sentinela(v: float) -> bool:
    """Valor monetário que não é dado: acima do teto plausível, ou potência de dez ≥ R$ 1 bi (1e9, 1e10, 1e12…)."""
    v = abs(float(v))
    if v > config.BRL_MAX:
        return True
    return v >= 1e9 and math.log10(v) == int(math.log10(v))


def _r(regra: str, ok: bool, detalhe: str) -> dict:
    return {"regra": regra, "ok": bool(ok), "detalhe": detalhe}


def versao(linha: dict | None) -> str:
    """Ficha de leitura de uma linha (ou fato): quem regrava devolve esta ficha para provar que leu o estado atual."""
    if linha is None:
        return "ausente"
    return hashlib.sha1(json.dumps(linha, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def _faixa(nome: str, v, regra: dict) -> str | None:
    """Motivo da violação de tipo/faixa de um valor, ou None."""
    if v is None:
        return None if regra.get("nulo", True) else f"{nome}: vazio (obrigatório)"
    if "dominio" in regra:
        return None if v in regra["dominio"] else f"{nome}: {v!r} fora do domínio"
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return f"{nome}: {v!r} não é número"
    if not math.isfinite(v):
        return f"{nome}: valor não finito"
    if regra.get("tipo") == "int" and float(v) != int(v):
        return f"{nome}: {v} não é inteiro"
    if regra.get("min") is not None and v < regra["min"]:
        return f"{nome}: {v} abaixo do mínimo {regra['min']}"
    if regra.get("max") is not None and v > regra["max"]:
        return f"{nome}: {v} acima do máximo {regra['max']}"
    if regra.get("monetaria") and sentinela(v):
        return f"{nome}: {v:.2f} é sentinela, não valor com proveniência"
    return None


# ───────────────────────────── fatos ─────────────────────────────
def julgar_fato(novo: dict, vigente: dict | None, lido: str | None) -> dict:
    """{aprovado, regras}. `vigente` = versão vigente do mesmo fato (ou None); `lido` = `versao_fato` que o produtor
    leu antes de calcular. Não altera nada."""
    v, un = novo.get("valor"), novo.get("unidade")
    faixa = {"BRL": {"monetaria": True, "min": novo.get("min"), "max": novo.get("max")},
             "contagem": {"tipo": "int", "min": 0, "max": novo.get("max")},
             "percentual": {"min": 0, "max": 100}, "indice": {"min": novo.get("min"), "max": novo.get("max")}}
    prov = [k for k in ("fonte", "consulta", "data_ref", "hash_fonte", "produtor") if not str(novo.get(k) or "").strip()]
    est, niv = novo.get("estado"), novo.get("nivel_prova")
    pago = novo.get("natureza") == "pago"
    r = [
        _r("P1 identidade", bool(RE_ID.match(str(novo.get("fato_id") or ""))), f"id {novo.get('fato_id')!r}"),
        _r("P2 tipo e faixa", un in config.UNIDADES and (_faixa("valor", v, faixa.get(un, {})) is None),
           f"unidade {un!r}" if un not in config.UNIDADES else (_faixa("valor", v, faixa[un]) or f"{v} {un}")),
        _r("P3 proveniência", not prov, "completa" if not prov else "falta " + ", ".join(prov)),
        _r("P4 estado", est in config.ESTADOS and niv in (0, 1, 2) and ((v is None) == (est == "INDISPONIVEL")),
           f"estado {est!r}, nível {niv!r}, valor {'ausente' if v is None else 'presente'}"),
        _r("P5 prova primária", not (est == "VERIFICADO" or novo.get("graduacao")) or niv == config.NIVEL_FONTE,
           f"estado {est!r}, graduação {novo.get('graduacao')!r}, nível de prova {niv!r}"),
        _r("P6 pagamento", not (pago and est == "VERIFICADO") or novo.get("base") == config.BASE_PAGO_CONFIRMADO,
           f"natureza {novo.get('natureza')!r}, base {novo.get('base')!r}"),
        _r("P7 não regride", vigente is None or niv is None or niv >= vigente["nivel_prova"],
           "sem versão anterior" if vigente is None else f"nível {vigente['nivel_prova']} → {niv}"),
        _r("P8 leu antes", vigente is None or lido == vigente["hash_versao"],
           "sem versão anterior" if vigente is None else
           ("leu a versão vigente" if lido == vigente["hash_versao"] else
            f"leu {lido or 'nada'}; vigente é {vigente['hash_versao']} (o fato mudou desde a leitura)")),
    ]
    return {"aprovado": all(x["ok"] for x in r), "regras": r}


# ───────────────────────────── contratos de tabela ─────────────────────────────
def _nivel_py(contrato: dict):
    ref = (contrato.get("nivel_prova") or {}).get("funcao")
    if not ref:
        return None
    mod, _, nome = ref.partition(":")
    return getattr(importlib.import_module(mod), nome)


def nivel_da_linha(contrato: dict, linha: dict) -> int | None:
    """Nível de prova de uma linha pelo contrato: `funcao` (módulo:função sobre a `coluna`) ou `casos` (lista de
    [nível, {coluna: valor | "*"}] — o primeiro que casa vale; "*" = não vazio)."""
    np_ = contrato.get("nivel_prova")
    if not np_:
        return None
    fn = _nivel_py(contrato)
    if fn:
        n = int(fn(linha.get(np_["coluna"])))
        return n if n >= 0 else None            # negativo = "não é juízo" (regra determinística): fora da hierarquia
    for nivel, cond in np_.get("casos", []):
        if all((linha.get(c) not in (None, "")) if v == "*" else (linha.get(c) == v) for c, v in cond.items()):
            return int(nivel)
    return int(np_.get("padrao", 0))


def julgar_linha(contrato: dict, vigente: dict | None, nova: dict, lido: str | None) -> dict:
    """Portão de uma linha de tabela de achado: faixa (P2), proveniência (P3), não regride (P7), leu antes (P8)."""
    viol = [m for c, regra in (contrato.get("colunas") or {}).items() if (m := _faixa(c, nova.get(c), regra))]
    falta = [c for c in contrato.get("proveniencia", []) if nova.get(c) in (None, "")]
    n_novo, n_vig = nivel_da_linha(contrato, nova), (nivel_da_linha(contrato, vigente) if vigente else None)
    r = [
        _r("P2 tipo e faixa", not viol, "; ".join(viol) or "dentro da faixa"),
        _r("P3 proveniência", not falta, "completa" if not falta else "falta " + ", ".join(falta)),
        _r("P7 não regride", vigente is None or n_novo is None or n_vig is None or n_novo >= n_vig,
           "sem linha anterior" if vigente is None else f"nível {n_vig} → {n_novo}"),
        _r("P8 leu antes", vigente is None or lido == versao(vigente),
           "sem linha anterior" if vigente is None else
           ("leu a linha vigente" if lido == versao(vigente) else "a linha mudou desde a leitura (ou não foi lida)")),
    ]
    return {"aprovado": all(x["ok"] for x in r), "regras": r}


def _nomes(contrato: dict) -> tuple[str, list[str]]:
    tab, chave = contrato["tabela"], list(contrato["chave"])
    for n in [tab, *chave]:
        if not RE_NOME_SQL.match(n):
            raise ValueError(f"nome inválido no contrato: {n!r}")
    return tab, chave


def ler(con: sqlite3.Connection, contrato: dict, chave: dict) -> tuple[dict | None, str]:
    """(linha vigente, ficha de leitura). A ficha volta em `escrever(…, lido=ficha)`."""
    tab, ch = _nomes(contrato)
    cur = con.execute(f"SELECT * FROM {tab} WHERE " + " AND ".join(f"{c}=?" for c in ch), [chave[c] for c in ch])
    lin = cur.fetchone()
    d = dict(zip([x[0] for x in cur.description], lin)) if lin else None
    return d, versao(d)


def escrever(con: sqlite3.Connection, contrato: dict, nova: dict, lido: str | None, recusas=None) -> dict:
    """Upsert GUARDADO: relê a linha dentro da transação de escrita, julga, e só então grava. Recusa não levanta —
    devolve o veredito (e chama `recusas(veredito)` para o registro). Para código novo; os escritores antigos são
    cobertos pelo controle detectivo (`fotografar`)."""
    tab, ch = _nomes(contrato)
    cols = list(nova)
    for c in cols:
        if not RE_NOME_SQL.match(c):
            raise ValueError(f"coluna inválida: {c!r}")
    con.execute("BEGIN IMMEDIATE")
    fechou = False
    try:
        vigente, _ = ler(con, contrato, nova)
        ver = julgar_linha(contrato, vigente, nova, lido)
        if ver["aprovado"]:
            con.execute(f"INSERT OR REPLACE INTO {tab} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [nova[c] for c in cols])
        con.execute("COMMIT")
        fechou = True
    finally:
        if not fechou:
            con.execute("ROLLBACK")
    ver["gravado"] = ver["aprovado"]
    if not ver["aprovado"] and recusas:
        recusas({"contrato": tab, "chave": {c: nova.get(c) for c in ch}, "veredito": ver})
    return ver


def ddl_gatilhos(cid: str, contrato: dict) -> list[str]:
    """Gatilhos de FAIXA (SQL puro, sem função Python: valem para qualquer processo que escreva). Só colunas com
    min/max/monetária. Regra de nível de prova não vira gatilho — depende de texto e fica no portão e na fotografia."""
    tab, _ = _nomes(contrato)
    conds = []
    for c, regra in (contrato.get("colunas") or {}).items():
        if not RE_NOME_SQL.match(c):
            raise ValueError(f"coluna inválida: {c!r}")
        lo = regra.get("min")
        hi = regra.get("max", config.BRL_MAX if regra.get("monetaria") else None)
        partes = ([f"NEW.{c} < {float(lo)!r}"] if lo is not None else []) + ([f"NEW.{c} > {float(hi)!r}"] if hi is not None else [])
        if partes:
            conds.append(f"(NEW.{c} IS NOT NULL AND ({' OR '.join(partes)}))")
    if not conds:
        return []
    cond, msg = " OR ".join(conds), f"certeza: {tab} fora do contrato ({cid}) — valor sem faixa plausível"
    return [f"CREATE TRIGGER IF NOT EXISTS certeza_{cid}_{ev[:3].lower()} BEFORE {ev} ON {tab} WHEN {cond} "
            f"BEGIN SELECT RAISE(ABORT, '{msg}'); END" for ev in ("INSERT", "UPDATE")]


# ───────────────────────────── controle detectivo ─────────────────────────────
def auditar(ro: sqlite3.Connection, contratos: dict, amostra: int = 5) -> list[dict]:
    """Violações de faixa e de proveniência nas tabelas COMO ESTÃO (só leitura). Tabela ou coluna ausente = erro
    declarado do contrato, nunca 'sem violação'."""
    out = []
    for cid, c in contratos.items():
        tab, ch = _nomes(c)
        try:
            cols = {r[1] for r in ro.execute(f"PRAGMA table_info({tab})")}
            if not cols:
                out.append({"contrato": cid, "regra": "contrato", "n": None, "detalhe": f"tabela {tab} não existe"})
                continue
            total = ro.execute(f"SELECT COUNT(*) FROM {tab}").fetchone()[0]
            for col, regra in (c.get("colunas") or {}).items():
                if col not in cols:
                    out.append({"contrato": cid, "regra": "contrato", "n": None, "detalhe": f"coluna {tab}.{col} não existe"})
                    continue
                if "dominio" in regra:
                    marcas = ",".join("?" * len(regra["dominio"]))
                    n = ro.execute(f"SELECT COUNT(*) FROM {tab} WHERE COALESCE({col},'') NOT IN ({marcas})", regra["dominio"]).fetchone()[0]
                    if n:
                        ex = ro.execute(f"SELECT DISTINCT {col} FROM {tab} WHERE COALESCE({col},'') NOT IN ({marcas}) LIMIT ?",
                                        [*regra["dominio"], amostra]).fetchall()
                        out.append({"contrato": cid, "regra": "P2 tipo e faixa", "n": n, "de": total,
                                    "detalhe": f"{tab}.{col} fora do domínio declarado", "exemplos": [str(e[0]) for e in ex]})
                    continue
                hi = regra.get("max", config.BRL_MAX if regra.get("monetaria") else None)
                partes = ([f"{col} < {float(regra['min'])!r}"] if regra.get("min") is not None else []) + \
                         ([f"{col} > {float(hi)!r}"] if hi is not None else []) + \
                         ([f"{col} IN (1e9,1e10,1e11,1e12,1e13,1e14,1e15)"] if regra.get("monetaria") else []) + \
                         ([] if regra.get("nulo", True) else [f"{col} IS NULL"])
                if not partes:
                    continue
                onde = " OR ".join(partes)
                n = ro.execute(f"SELECT COUNT(*) FROM {tab} WHERE {onde}").fetchone()[0]
                if n:
                    ex = ro.execute(f"SELECT {','.join(ch)}, {col} FROM {tab} WHERE {onde} LIMIT ?", (amostra,)).fetchall()
                    out.append({"contrato": cid, "regra": "P2 tipo e faixa", "n": n, "de": total,
                                "detalhe": f"{tab}.{col} fora da faixa", "exemplos": [list(map(str, e)) for e in ex]})
            for col in c.get("proveniencia", []):
                if col not in cols:
                    out.append({"contrato": cid, "regra": "contrato", "n": None, "detalhe": f"coluna {tab}.{col} não existe"})
                    continue
                n = ro.execute(f"SELECT COUNT(*) FROM {tab} WHERE COALESCE({col},'')=''").fetchone()[0]
                if n:
                    out.append({"contrato": cid, "regra": "P3 proveniência", "n": n, "de": total,
                                "detalhe": f"{tab}.{col} vazio (linha sem proveniência)"})
        except sqlite3.Error as e:
            out.append({"contrato": cid, "regra": "contrato", "n": None, "detalhe": f"{type(e).__name__}: {e}"})
    return out


DDL_FOTO = """
CREATE TABLE IF NOT EXISTS linha_vista(contrato TEXT, chave TEXT, nivel INTEGER, hash TEXT, visto_em REAL,
  conteudo TEXT, PRIMARY KEY(contrato, chave));
CREATE TABLE IF NOT EXISTS regressao(id INTEGER PRIMARY KEY, contrato TEXT, chave TEXT, nivel_antes INTEGER,
  nivel_depois INTEGER, em REAL, conteudo_antes TEXT, sumiu INTEGER DEFAULT 0, resolvida_em REAL);
"""


def fotografar(ro: sqlite3.Connection, cz: sqlite3.Connection, contratos: dict, agora: float | None = None) -> dict:
    """Controle detectivo de P7 para QUALQUER escritor: guarda (chave, nível, hash) de cada linha das tabelas com
    `nivel_prova` e acusa a linha que REGREDIU de nível (ou sumiu sendo prova primária) desde a fotografia anterior.
    O conteúdo da linha de nível 2 fica guardado: o laudo regravado é recuperável."""
    agora = agora or time.time()
    cz.executescript(DDL_FOTO)
    if not cz.in_transaction:
        cz.execute("BEGIN")
    res = {}
    for cid, c in contratos.items():
        if not c.get("nivel_prova"):
            continue
        tab, ch = _nomes(c)
        try:
            cur = ro.execute(f"SELECT * FROM {tab}")
            nomes = [x[0] for x in cur.description]
            atuais = {}
            for lin in cur:
                d = dict(zip(nomes, lin))
                atuais["|".join(str(d[k]) for k in ch)] = (nivel_da_linha(c, d), versao(d), d)
        except sqlite3.Error as e:
            res[cid] = {"erro": f"{type(e).__name__}: {e}"}
            continue
        antes = {k: (n, h, ct) for k, n, h, ct in
                 cz.execute("SELECT chave, nivel, hash, conteudo FROM linha_vista WHERE contrato=?", (cid,))}
        regrediu = sumiu = 0
        for k, (n0, _h0, ct0) in antes.items():
            at = atuais.get(k)
            if at is None and n0 == config.NIVEL_FONTE:
                cz.execute("INSERT INTO regressao(contrato,chave,nivel_antes,nivel_depois,em,conteudo_antes,sumiu) "
                           "VALUES (?,?,?,?,?,?,1)", (cid, k, n0, None, agora, ct0))
                sumiu += 1
            elif at is not None and n0 is not None and at[0] is not None and at[0] < n0:
                cz.execute("INSERT INTO regressao(contrato,chave,nivel_antes,nivel_depois,em,conteudo_antes) "
                           "VALUES (?,?,?,?,?,?)", (cid, k, n0, at[0], agora, ct0))
                regrediu += 1
        # regressão curada: a linha voltou ao nível que tinha
        for rid, k, n0 in cz.execute("SELECT id, chave, nivel_antes FROM regressao WHERE contrato=? AND resolvida_em IS NULL",
                                     (cid,)).fetchall():
            at = atuais.get(k)
            if at is not None and at[0] is not None and at[0] >= n0:
                cz.execute("UPDATE regressao SET resolvida_em=? WHERE id=?", (agora, rid))
        cz.execute("DELETE FROM linha_vista WHERE contrato=?", (cid,))
        cz.executemany("INSERT INTO linha_vista VALUES (?,?,?,?,?,?)",
                       [(cid, k, n, h, agora, json.dumps(d, ensure_ascii=False, default=str) if n == config.NIVEL_FONTE else None)
                        for k, (n, h, d) in atuais.items()])
        abertas = cz.execute("SELECT COUNT(*) FROM regressao WHERE contrato=? AND resolvida_em IS NULL", (cid,)).fetchone()[0]
        res[cid] = {"linhas": len(atuais), "por_nivel": _conta(n for n, _, _ in atuais.values()),
                    "regrediram_agora": regrediu, "sumiram_agora": sumiu, "regressoes_abertas": abertas}
    cz.commit()
    return res


def _conta(it) -> dict:
    d: dict = {}
    for x in it:
        d[str(x)] = d.get(str(x), 0) + 1
    return d
