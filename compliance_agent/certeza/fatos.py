# -*- coding: utf-8 -*-
"""fatos — o REGISTRO DE FATOS: cada número que a casa afirma tem identidade única, e existe em UM lugar.

Um fato é `familia:chave[:chave…]:medida` (ex.: `iss_nao_retido:00801512000157:180100:valor`). O registro
(`data/certeza/certeza.db`, tabela `fato_versao`) é SÓ ACRÉSCIMO — gatilhos do próprio banco recusam UPDATE de
conteúdo e DELETE: uma medição nova é uma versão nova; a anterior continua lá, com a data em que valia (é o que
permite acusar o texto que ainda repete o número antigo). Cada versão carrega valor, unidade, estado, nível de
prova, natureza/base (o STATUS ao lado do valor), confiança, e a proveniência: fonte, consulta, data de referência
e hash da fonte. Nada entra sem passar por `portoes.julgar_fato`; o que o portão recusa fica em `recusa`.

Quem produz fato não é código novo: é a declaração `fatos:` de cada nó de `config/propagacao.yaml` (o mesmo mapa
que o despachante usa), lida por `extrair`. O derivado continua sendo calculado por quem já o calculava.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from . import config, portoes

DDL = """
CREATE TABLE IF NOT EXISTS fato_versao(
  id INTEGER PRIMARY KEY, fato_id TEXT NOT NULL, valor REAL, unidade TEXT NOT NULL, estado TEXT NOT NULL,
  nivel_prova INTEGER NOT NULL, natureza TEXT, base TEXT, graduacao TEXT, confianca REAL, confianca_texto TEXT,
  rotulo TEXT, meta TEXT, no TEXT, fonte TEXT NOT NULL, consulta TEXT NOT NULL, data_ref TEXT NOT NULL,
  hash_fonte TEXT NOT NULL, produtor TEXT NOT NULL, anterior_id INTEGER, hash_versao TEXT NOT NULL,
  registrado_em REAL NOT NULL, confirmado_em REAL NOT NULL, hash_fonte_confirmado TEXT);
CREATE INDEX IF NOT EXISTS ix_fato ON fato_versao(fato_id, id);
CREATE TRIGGER IF NOT EXISTS fato_so_acrescimo BEFORE UPDATE OF fato_id, valor, unidade, estado, nivel_prova, natureza,
  base, graduacao, fonte, consulta, data_ref, hash_fonte, produtor, anterior_id, hash_versao, registrado_em ON fato_versao
  BEGIN SELECT RAISE(ABORT, 'fato_versao é só acréscimo: registre uma versão nova'); END;
CREATE TRIGGER IF NOT EXISTS fato_nao_apaga BEFORE DELETE ON fato_versao
  BEGIN SELECT RAISE(ABORT, 'fato_versao é só acréscimo: nada é apagado'); END;
CREATE TABLE IF NOT EXISTS recusa(id INTEGER PRIMARY KEY, fato_id TEXT, em REAL, produtor TEXT, regras TEXT, proposta TEXT);
CREATE TABLE IF NOT EXISTS medida(nome TEXT, em REAL, valor REAL);
CREATE TABLE IF NOT EXISTS extracao(no TEXT, bloco TEXT, em REAL, n INTEGER, erro TEXT, PRIMARY KEY(no, bloco));
"""
_COLS = ("fato_id", "valor", "unidade", "estado", "nivel_prova", "natureza", "base", "graduacao", "confianca",
         "confianca_texto", "rotulo", "meta", "no", "fonte", "consulta", "data_ref", "hash_fonte", "produtor")


def conectar(caminho: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(caminho or config.banco(), timeout=30, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(DDL + portoes.DDL_FOTO)
    return con


def _arred(v, unidade):
    if v is None:
        return None
    return int(round(v)) if unidade == "contagem" else round(float(v), 2 if unidade == "BRL" else 4)


def hash_versao(f: dict) -> str:
    """Identidade do CONTEÚDO de uma versão (o que o fato afirma). A proveniência fica fora: reler a mesma fonte e
    achar o mesmo valor confirma a versão, não cria outra."""
    return portoes.versao({k: (_arred(f.get(k), f.get("unidade")) if k == "valor" else f.get(k))
                           for k in ("valor", "unidade", "estado", "nivel_prova", "natureza", "base", "graduacao")})


def _dic(cur, lin) -> dict | None:
    return dict(zip([c[0] for c in cur.description], lin)) if lin else None


def vigente(con: sqlite3.Connection, fato_id: str) -> dict | None:
    cur = con.execute("SELECT * FROM fato_versao WHERE fato_id=? ORDER BY id DESC LIMIT 1", (fato_id,))
    return _dic(cur, cur.fetchone())


def historico(con: sqlite3.Connection, fato_id: str) -> list[dict]:
    cur = con.execute("SELECT * FROM fato_versao WHERE fato_id=? ORDER BY id", (fato_id,))
    return [_dic(cur, r) for r in cur.fetchall()]


def vigentes(con: sqlite3.Connection) -> list[dict]:
    cur = con.execute("SELECT * FROM fato_versao WHERE id IN (SELECT MAX(id) FROM fato_versao GROUP BY fato_id) ORDER BY fato_id")
    return [_dic(cur, r) for r in cur.fetchall()]


def registrar(con: sqlite3.Connection, fato: dict, lido: str | None, agora: float | None = None) -> dict:
    """Registra uma versão do fato se o portão aprovar. `lido` = `hash_versao` da versão vigente que o produtor leu
    (None se não havia). Devolve {status: novo|atualizado|igual|recusado, regras}. A leitura de conferência e a
    gravação estão na MESMA transação de escrita: entre julgar e gravar ninguém muda o fato."""
    agora = agora or time.time()
    f = {**fato, "valor": _arred(fato.get("valor"), fato.get("unidade"))}
    if isinstance(f.get("meta"), (dict, list)):
        f["meta"] = json.dumps(f["meta"], ensure_ascii=False, sort_keys=True)
    con.execute("BEGIN IMMEDIATE")
    fechou = False
    try:
        vig = vigente(con, str(f.get("fato_id")))
        ver = portoes.julgar_fato(f, vig, lido)
        h = hash_versao(f)
        if not ver["aprovado"]:
            con.execute("INSERT INTO recusa(fato_id, em, produtor, regras, proposta) VALUES (?,?,?,?,?)",
                        (str(f.get("fato_id")), agora, f.get("produtor"),
                         json.dumps([r for r in ver["regras"] if not r["ok"]], ensure_ascii=False),
                         json.dumps(f, ensure_ascii=False, default=str)))
            status = "recusado"
        elif vig and vig["hash_versao"] == h:
            con.execute("UPDATE fato_versao SET confirmado_em=?, hash_fonte_confirmado=? WHERE id=?",
                        (agora, f.get("hash_fonte"), vig["id"]))
            status = "igual"
        else:
            con.execute(f"INSERT INTO fato_versao({','.join(_COLS)}, anterior_id, hash_versao, registrado_em, confirmado_em, "
                        f"hash_fonte_confirmado) VALUES ({','.join('?' * len(_COLS))},?,?,?,?,?)",
                        [f.get(c) for c in _COLS] + [vig["id"] if vig else None, h, agora, agora, f.get("hash_fonte")])
            status = "atualizado" if vig else "novo"
        con.execute("COMMIT")
        fechou = True
    finally:
        if not fechou:
            con.execute("ROLLBACK")
    return {"status": status, "fato_id": f.get("fato_id"), "regras": ver["regras"],
            "antes": vig["valor"] if vig else None, "depois": f.get("valor")}


def registrar_lote(con: sqlite3.Connection, propostas: list[dict], agora: float | None = None) -> dict:
    """Registra o que `extrair` produziu. O produtor em lote LÊ a versão vigente imediatamente antes de cada escrita
    (é a ficha que ele apresenta ao portão)."""
    res = {"novo": 0, "atualizado": 0, "igual": 0, "recusado": 0, "mudancas": [], "recusas": [], "novos": []}
    for p in propostas:
        vig = vigente(con, p["fato_id"])
        r = registrar(con, p, vig["hash_versao"] if vig else None, agora)
        res[r["status"]] += 1
        if r["status"] == "novo":
            res["novos"].append(r["fato_id"])
        elif r["status"] == "atualizado":
            res["mudancas"].append({"fato_id": r["fato_id"], "antes": r["antes"], "depois": r["depois"]})
        elif r["status"] == "recusado":
            res["recusas"].append({"fato_id": r["fato_id"], "regras": [x for x in r["regras"] if not x["ok"]]})
    return res


# ───────────────────────────── formatação (a mesma em todo lugar) ─────────────────────────────
def brl(v: float) -> str:
    return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def formatar(valor, unidade: str) -> str:
    if valor is None:
        return "INDISPONÍVEL"
    if unidade == "BRL":
        return brl(valor)
    if unidade == "contagem":
        return f"{int(round(valor)):,}".replace(",", ".")
    if unidade == "percentual":
        return f"{float(valor):.1f}%".replace(".", ",")
    return f"{float(valor):g}".replace(".", ",")


# ───────────────────────────── extração (declaração `fatos:` do mapa) ─────────────────────────────
def slug(v) -> str:
    s = unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9.\-]+", "_", s).strip("_") or "vazio"


def _caminho(obj, caminho: str):
    for p in caminho.split("."):
        obj = obj[p] if isinstance(obj, dict) else obj[int(p)]
    return obj


def _por(bloco: dict, spec: dict, nome: str, item: dict, padrao=None):
    """Campo fixo (`estado: X`) ou por valor do item (`estado_por: {campo, mapa, padrao}`); a medida vence o bloco."""
    for d in (spec, bloco):
        if nome in d:
            return d[nome]
        if f"{nome}_por" in d:
            m = d[f"{nome}_por"]
            return m.get("mapa", {}).get(item.get(m["campo"]), m.get("padrao", padrao))
    return padrao


class _Formato(dict):
    def __missing__(self, k):
        raise KeyError(k)


def _itens(bloco: dict, raiz: Path, ro) -> tuple[list[dict], dict, str, str]:
    """(itens, raiz do documento, hash da fonte, data de referência)."""
    if "sql" in bloco:
        if ro is None:
            raise OSError("fato por SQL sem conexão com o banco")
        cur = ro.execute(bloco["sql"])
        nomes = [c[0] for c in cur.description]
        itens = [dict(zip(nomes, r)) for r in cur.fetchall()]
        h = hashlib.sha1(json.dumps(itens, sort_keys=True, default=str).encode()).hexdigest()
        return itens, {}, h, datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    arq = raiz / bloco["arquivo"]
    bruto = arq.read_bytes()
    doc = json.loads(bruto)
    itens = _caminho(doc, bloco["lista"]) if bloco.get("lista") else [doc]
    ref = bloco.get("data_ref")
    data_ref = str(_caminho(doc, ref)) if ref else datetime.fromtimestamp(arq.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
    return list(itens), doc, hashlib.sha1(bruto).hexdigest(), data_ref


def blocos(cfg: dict):
    """(nó, índice, bloco) de todo `fatos:` do mapa — fontes, derivados e externos."""
    for secao in ("fontes", "derivados", "externos"):
        for nid, n in (cfg.get(secao) or {}).items():
            for i, b in enumerate(n.get("fatos") or []):
                yield nid, i, b


def extrair(cfg: dict, ro=None, raiz: Path | None = None, cz: sqlite3.Connection | None = None,
            agora: float | None = None) -> tuple[list[dict], list[dict]]:
    """Lê as declarações `fatos:` e devolve (propostas, erros). Fonte ausente ou ilegível é ERRO DECLARADO do bloco —
    nunca fato com valor zero, nunca 'sem fato'. Com `cz`, registra a extração de cada bloco (frescor)."""
    raiz, agora = raiz or config.REPO, agora or time.time()
    props, erros = [], []
    for nid, i, b in blocos(cfg):
        try:
            itens, doc, h, data_ref = _itens(b, raiz, ro)
            onde = b.get("sql") or b["arquivo"]
            n = 0
            fl = b.get("filtro")
            for item in itens:
                if fl and not (item.get(fl["campo"]) or 0) >= fl["min"]:
                    continue
                ctx = _Formato({k: v for k, v in item.items() if isinstance(v, (str, int, float))})
                base_id = b["id"].format_map(_Formato({k: slug(v) for k, v in ctx.items()}))
                sufixo = base_id.split(":", 1)[1] if ":" in base_id else ""
                for medida, spec in b["medidas"].items():
                    valor = _caminho(item, spec["campo"])
                    estado = _por(b, spec, "estado", item)
                    meta = {"apelidos": [a.format_map(ctx) for a in b.get("apelidos", [])] + list((b.get("apelidos_por") or {}).get(sufixo, [])),
                            "termos": spec.get("termos", b.get("termos", [])),
                            "superados": [s[medida] for s in ([(b.get("superados") or {}).get(sufixo)] if sufixo else [])
                                          if s and medida in s],
                            "grupo": base_id, "medida": medida}
                    props.append({
                        "fato_id": f"{base_id}:{medida}", "valor": None if estado == "INDISPONIVEL" else valor,
                        "unidade": spec["unidade"], "estado": estado, "nivel_prova": _por(b, spec, "nivel_prova", item),
                        "natureza": _por(b, spec, "natureza", item), "base": _por(b, spec, "base", item),
                        "graduacao": _por(b, spec, "graduacao", item),
                        "confianca": spec.get("confianca"), "confianca_texto": spec.get("confianca_texto", b.get("confianca_texto")),
                        "rotulo": (spec.get("rotulo") or b.get("rotulo") or base_id).format_map(ctx), "meta": meta, "no": nid,
                        "fonte": b["fonte"], "consulta": f"{onde} › {b.get('lista') or '(raiz)'} › {spec['campo']}",
                        "data_ref": data_ref, "hash_fonte": h, "produtor": f"propagacao.yaml:{nid}.fatos[{i}]",
                        "_reconcilia": _reconciliar(b, doc, item, medida) if b.get("reconcilia") else None})
                    n += 1
            if cz is not None:
                cz.execute("INSERT OR REPLACE INTO extracao VALUES (?,?,?,?,NULL)", (nid, str(i), agora, n))
        except (OSError, ValueError, KeyError, IndexError, TypeError, sqlite3.Error) as e:
            erros.append({"no": nid, "bloco": i, "erro": f"{type(e).__name__}: {e}"})
            if cz is not None:
                cz.execute("INSERT OR REPLACE INTO extracao VALUES (?,?,?,?,?)", (nid, str(i), agora, None, f"{type(e).__name__}: {e}"))
    return props, erros


def _reconciliar(b: dict, doc: dict, item: dict, medida: str) -> dict | None:
    """Recalcula a medida por OUTRO caminho do mesmo documento (as linhas de detalhe) — o agregado publicado tem de
    bater com a soma do que o sustenta. Devolve {esperado, caminho} ou None se a medida não tem reconciliação."""
    rc = b["reconcilia"]
    como = (rc.get("medidas") or {}).get(medida)
    if not como:
        return None
    linhas = [x for x in _caminho(doc, rc["lista"])
              if all(x.get(k) == (item.get(v[1:]) if isinstance(v, str) and v.startswith("$") else v)
                     for k, v in rc.get("onde", {}).items())]
    if "soma" in como:
        v = round(sum(float(x.get(como["soma"]) or 0) for x in linhas), 2)
    else:
        v = len({x.get(como["distintos"]) for x in linhas})
    return {"esperado": v, "caminho": f"{b['arquivo']} › {rc['lista']} ({len(linhas)} linha(s))"}
