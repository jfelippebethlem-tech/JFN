# -*- coding: utf-8 -*-
"""registro — versões IMUTÁVEIS da rubrica da perícia: candidato → (portão) → sombra → campeão, com rollback.

Uma versão é um JSON: {"tipo": "rubrica", "licoes": [ids de armadilha cuja lição entra no prompt],
"filtros": [ids de armadilha cujo padrão de indício rebaixa o laudo fraco], "nota": texto livre}. O conteúdo é
identificado pelo hash; registrar o mesmo conteúdo devolve a mesma chave e nunca o altera. Só as transições abaixo
existem, cada uma gravada em `evento_registro`. Promover a campeão é ato HUMANO (CLI `promover`), nunca do ciclo."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time

from . import armadilhas, config, ledger

_DDL = """
CREATE TABLE IF NOT EXISTS versao(
  chave TEXT PRIMARY KEY, n INTEGER NOT NULL, conteudo TEXT NOT NULL, hash TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK(status IN ('candidato','reprovado','sombra','campeao','aposentado')),
  validacao TEXT, origem TEXT, criado_em TEXT NOT NULL, sombra_desde TEXT, promovido_em TEXT, anterior TEXT, motivo TEXT);
CREATE TABLE IF NOT EXISTS evento_registro(
  id INTEGER PRIMARY KEY, chave TEXT NOT NULL, de TEXT, para TEXT NOT NULL, motivo TEXT, quem TEXT, em TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS laudo_sombra(
  id INTEGER PRIMARY KEY, chave TEXT NOT NULL, numero_sei TEXT NOT NULL, nota_campeao INTEGER, nota_desafiante INTEGER,
  laudo TEXT, em TEXT NOT NULL, UNIQUE(chave, numero_sei));
"""
_TRANSICOES = {("candidato", "reprovado"), ("candidato", "sombra"), ("sombra", "reprovado"), ("sombra", "campeao"),
               ("campeao", "aposentado"), ("aposentado", "campeao")}
BASE = {"tipo": "rubrica", "licoes": [], "filtros": [], "nota": "rubrica vigente em tools/lex_execucao.py (regras 1–9)"}


def _agora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def preparar(con: sqlite3.Connection) -> None:
    con.executescript(_DDL)
    if not con.execute("SELECT 1 FROM versao LIMIT 1").fetchone():
        ch = registrar(con, BASE, "semente")
        con.execute("UPDATE versao SET status='campeao', promovido_em=? WHERE chave=?", (_agora(), ch))
        _evento(con, ch, "candidato", "campeao", "versão de partida: o prompt que já estava em produção", "sistema")
        con.commit()


def abrir(caminho=None) -> sqlite3.Connection:
    """O ledger com o registro de versões pronto (semente do campeão incluída)."""
    con = ledger.conectar(caminho)
    preparar(con)
    return con


def _evento(con, chave, de, para, motivo, quem) -> None:
    con.execute("INSERT INTO evento_registro(chave,de,para,motivo,quem,em) VALUES(?,?,?,?,?,?)",
                (chave, de, para, (motivo or "")[:400], quem, _agora()))


def _canonico(conteudo: dict) -> str:
    c = {"tipo": conteudo.get("tipo", "rubrica"), "licoes": sorted(conteudo.get("licoes") or []),
         "filtros": sorted(conteudo.get("filtros") or []), "nota": conteudo.get("nota", "")}
    desconhecidas = [x for x in c["licoes"] + c["filtros"] if x not in armadilhas.POR_ID]
    if desconhecidas:
        raise ValueError(f"armadilha fora da taxonomia: {desconhecidas}")
    semfiltro = [x for x in c["filtros"] if armadilhas.POR_ID[x]["indicio"] is None]
    if semfiltro:
        raise ValueError(f"armadilha sem padrão de indício não pode ser filtro: {semfiltro}")
    return json.dumps(c, ensure_ascii=False, sort_keys=True)


def registrar(con: sqlite3.Connection, conteudo: dict, origem: str) -> str:
    con.executescript(_DDL)
    txt = _canonico(conteudo)
    h = hashlib.sha1(txt.encode()).hexdigest()
    r = con.execute("SELECT chave FROM versao WHERE hash=?", (h,)).fetchone()
    if r:
        return r[0]
    n = con.execute("SELECT COALESCE(MAX(n),0)+1 FROM versao").fetchone()[0]
    chave = f"rubrica_v{n}_{h[:8]}"
    con.execute("INSERT INTO versao(chave,n,conteudo,hash,status,origem,criado_em) VALUES(?,?,?,?, 'candidato',?,?)",
                (chave, n, txt, h, origem, _agora()))
    _evento(con, chave, None, "candidato", origem, "sistema")
    con.commit()
    return chave


def ler(con: sqlite3.Connection, chave: str) -> dict | None:
    r = con.execute("SELECT chave,n,conteudo,status,validacao,origem,criado_em,sombra_desde,promovido_em,anterior,motivo "
                    "FROM versao WHERE chave=?", (chave,)).fetchone()
    if not r:
        return None
    d = dict(zip(("chave", "n", "conteudo", "status", "validacao", "origem", "criado_em", "sombra_desde",
                  "promovido_em", "anterior", "motivo"), r))
    d["conteudo"] = json.loads(d["conteudo"])
    d["validacao"] = json.loads(d["validacao"]) if d["validacao"] else None
    return d


def campeao(con: sqlite3.Connection) -> dict | None:
    r = con.execute("SELECT chave FROM versao WHERE status='campeao'").fetchone()
    return ler(con, r[0]) if r else None


def mover(con: sqlite3.Connection, chave: str, para: str, motivo: str, quem: str = "sistema",
          validacao: dict | None = None) -> None:
    v = ler(con, chave)
    if v is None:
        raise KeyError(chave)
    if (v["status"], para) not in _TRANSICOES:
        raise ValueError(f"transição proibida: {v['status']} → {para}")
    extra = ", sombra_desde=?" if para == "sombra" else ""
    args = [para, motivo[:400]] + ([_agora()] if para == "sombra" else [])
    if validacao is not None:
        extra += ", validacao=?"
        args.append(json.dumps(validacao, ensure_ascii=False))
    con.execute(f"UPDATE versao SET status=?, motivo=?{extra} WHERE chave=?", (*args, chave))
    _evento(con, chave, v["status"], para, motivo, quem)
    con.commit()


def julgado(con: sqlite3.Connection, chave: str, veredito: dict) -> str:
    """Aplica o veredito do PORTÃO a um candidato: aprovado → sombra; reprovado → reprovado (não se repete). Falhar
    SÓ nas regras que dizem se o conjunto mede (portao.NAO_MEDE: amostra, verdadeiros, travas) é INCONCLUSIVO: segue
    candidato, com o veredito gravado — conjunto que não mede não refuta a lição. Perder alto verdadeiro (R3) reprova
    sempre. Devolve o status."""
    from .portao import NAO_MEDE
    falhas = "; ".join(f"{r['regra']}: {r['detalhe']}" for r in veredito["regras"] if not r["ok"])
    if not veredito.get("aprovado") and all(r["ok"] or r["regra"] in NAO_MEDE for r in veredito["regras"]):
        motivo = f"inconclusivo no portão (conjunto não mede) — {falhas}"
        con.execute("UPDATE versao SET motivo=?, validacao=? WHERE chave=? AND status='candidato'",
                    (motivo[:400], json.dumps(veredito, ensure_ascii=False), chave))
        _evento(con, chave, "candidato", "candidato", motivo, "portao")
        con.commit()
        return "candidato"
    para = "sombra" if veredito.get("aprovado") else "reprovado"
    mover(con, chave, para, "aprovado no portão — entra em sombra" if para == "sombra" else f"reprovado no portão — {falhas}",
          "portao", veredito)
    return para


def promover(con: sqlite3.Connection, chave: str, quem: str) -> None:
    """Sombra → campeão. Ato humano: exige `quem`, a amostra mínima de laudos em sombra e o kill desligado."""
    if not quem or quem in ("sistema", "portao", "ciclo"):
        raise PermissionError("promoção a campeão é ato humano: informe quem promove")
    if config.morto():
        raise PermissionError("kill switch ativo")
    n = con.execute("SELECT COUNT(*) FROM laudo_sombra WHERE chave=?", (chave,)).fetchone()[0]
    if n < config.SOMBRA_MIN_LAUDOS:
        raise PermissionError(f"só {n} laudo(s) em sombra (mínimo {config.SOMBRA_MIN_LAUDOS})")
    atual = campeao(con)
    if atual:
        mover(con, atual["chave"], "aposentado", f"substituído por {chave}", quem)
    mover(con, chave, "campeao", f"promovido por {quem}", quem)
    con.execute("UPDATE versao SET promovido_em=?, anterior=? WHERE chave=?", (_agora(), atual and atual["chave"], chave))
    con.commit()
    publicar(con)


def rollback(con: sqlite3.Connection, quem: str, motivo: str) -> str:
    """Um comando: aposenta o campeão e devolve o posto ao anterior. Devolve a chave que voltou."""
    atual = campeao(con)
    if not atual or not atual.get("anterior"):
        raise ValueError("não há campeão anterior para onde voltar")
    mover(con, atual["chave"], "aposentado", f"rollback: {motivo}", quem)
    mover(con, atual["anterior"], "campeao", f"rollback de {atual['chave']}: {motivo}", quem)
    publicar(con)
    return atual["anterior"]


def publicar(con: sqlite3.Connection) -> dict:
    """Grava `campeao.json` — o ÚNICO arquivo que a produção lê (`lex_execucao._regras_calibracao`)."""
    v = campeao(con)
    d = {"chave": v["chave"] if v else None,
         "licoes": [armadilhas.POR_ID[i]["licao"] for i in (v["conteudo"]["licoes"] if v else [])],
         "filtros": v["conteudo"]["filtros"] if v else [], "publicado_em": _agora()}
    (config.dados() / "campeao.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def licoes_do_campeao() -> list[str]:
    """Lições do campeão para o prompt. Kill switch ⇒ nenhuma (a produção volta à rubrica de partida)."""
    if config.morto():
        return []
    try:
        d = json.loads((config.dados() / "campeao.json").read_text(encoding="utf-8"))
        return [str(x) for x in d.get("licoes") or []][:config.ORCAMENTO["max_licoes_ativas"]]
    except (OSError, ValueError):
        return []
