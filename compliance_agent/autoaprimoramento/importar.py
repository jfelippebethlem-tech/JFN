# -*- coding: utf-8 -*-
"""importar — reconstrói a verdade de chão a partir do que a casa JÁ gravou (só leitura nas fontes).

Fontes, em ordem de riqueza:
  1. `data/conferencia_opus.db` (fila conferida): laudo do motor fraco (`resposta`) × laudo do Opus (`resposta_opus`);
  2. `data/compliance.db` (`lex_execucao`): o laudo vigente de cada processo, com a proveniência no campo `modelo`;
  3. `data/cruzamento_motores.db`: qual motor fraco deu qual nota (quando o texto do laudo não sobrou);
  4. logs de lote (`data/conferir_85.log`): só a nota antes/depois — vira versão SEM texto de indício;
  5. JSONs de laudo escritos por agentes na fonte primária: entram se o processo for identificável SEM adivinhar
     (arquivo `.ns` ao lado, resumo idêntico ao gravado, ou OB+NL citadas que o SIAFE liga a um único processo).
Tudo idempotente: rodar de novo não duplica."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from . import config, ledger

_RE_NOTA = re.compile(r"nota (\d+)")
_RE_OB = re.compile(r"\b(20\d\dOB\d{4,6})\b")
_RE_NL = re.compile(r"\b(20\d\dNL\d{4,6})\b")
_TIPOS = (("fundo_a_fundo", r"fundo a fundo|transfer[eê]ncia (financeira|volunt)|repasse"),
          ("diaria_adiantamento", r"di[aá]ria|adiantamento|suprimento de fundos"),
          ("aditivo", r"aditivo|prorroga[çc]|apostilamento|reajuste"),
          ("licitacao", r"preg[aã]o|licita[çc]|dispensa|inexigibilidade|ades[aã]o [aà] ata"),
          ("obra", r"\bobra|reforma|constru[çc]|pavimenta|medi[çc][aã]o"),
          ("servico_continuo", r"presta[çc][aã]o de servi|loca[çc][aã]o|manuten[çc]|limpeza|vigil[aâ]ncia|terceiriz"),
          ("aquisicao", r"aquisi[çc]|fornecimento|compra|material|medicamento|equipamento"))


def tipo_de(objeto: str | None) -> str:
    for nome, rx in _TIPOS:
        if re.search(rx, objeto or "", re.I):
            return nome
    return "outro"


def _ro(caminho: Path) -> sqlite3.Connection | None:
    if not Path(caminho).exists():
        return None
    return sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=60)


def _json(txt) -> dict | None:
    txt = (txt or "").strip()
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j < 0:
        return None
    try:
        d = json.loads(txt[i:j + 1])
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def da_fila(con, fila_db: Path) -> int:
    f = _ro(fila_db)
    if f is None:
        return 0
    n = 0
    try:
        for item, motor, resp, criado, modelo_opus, resp_opus, conferido in f.execute(
                "SELECT item,motor,resposta,criado_em,modelo_opus,resposta_opus,conferido_em FROM fila "
                "WHERE tarefa='pericia_execucao' AND status='conferido' AND item LIKE 'sei:%'"):
            ns = item[4:]
            a, d = _json(resp), _json(resp_opus)
            if a and ledger.registrar_versao(con, ns, a, motor, "fila:resposta", criado) is not None:
                n += 1
            if d:
                # o modelo do Opus na fila vem sem o prefixo 'claude:' — a proveniência é a da própria fila
                ledger.registrar_versao(con, ns, d, f"claude:{modelo_opus} (conferência; antes {motor})",
                                        "fila:resposta_opus", conferido)
    finally:
        f.close()
    con.commit()
    return n


def do_lex(con, compliance_db: Path) -> int:
    c = _ro(compliance_db)
    if c is None:
        return 0
    n = 0
    try:
        for ns, ex, co, nota, ind, duv, res, modelo, em in c.execute(
                "SELECT numero_sei,execucao_comprovada,coerencia,nota_risco,indicios,duvidas,resumo,modelo,em "
                "FROM lex_execucao WHERE nota_risco IS NOT NULL"):
            if ledger.registrar_versao(con, ns, {"execucao_comprovada": ex, "coerencia": co, "nota_risco": nota,
                                                 "indicios": ind, "duvidas": duv, "resumo": res},
                                       modelo, "lex_execucao", em) is not None:
                n += 1
    finally:
        c.close()
    con.commit()
    return n


def _motores_fracos(cruz_db: Path) -> dict[tuple[str, int], str]:
    """(numero_sei, nota) → modelo fraco que deu essa nota, pelo cruzamento de motores."""
    x = _ro(cruz_db)
    out: dict[tuple[str, int], str] = {}
    if x is None:
        return out
    try:
        for item, modelo, ver in x.execute("SELECT item,modelo,veredito FROM veredito WHERE tarefa='pericia_execucao' "
                                           "AND motor<>'claude' AND item LIKE 'sei:%' AND veredito IS NOT NULL"):
            m = _RE_NOTA.search(ver or "")
            if m and modelo:
                out.setdefault((item[4:], int(m.group(1))), modelo)
    finally:
        x.close()
    return out


def do_log_lote(con, log: Path, cruz_db: Path, modelo_lote: str) -> int:
    """Log do lote do Opus de 18/11 (`conferir_85`): {ns, antes, depois}. Só a NOTA sobrou do laudo anterior."""
    if not Path(log).exists():
        return 0
    motores = _motores_fracos(cruz_db)
    n = 0
    for linha in Path(log).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(linha)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("depois") is None or d.get("antes") is None or not d.get("ns"):
            continue
        ns, t = d["ns"], d.get("t")
        fraco = motores.get((ns, int(d["antes"])), "desconhecido")
        if ledger.registrar_versao(con, ns, {"nota_risco": d["antes"]}, fraco, "log:conferir_85", None) is None:
            continue
        ledger.registrar_versao(con, ns, {"nota_risco": d["depois"], "execucao_comprovada": d.get("exec")},
                                modelo_lote, "log:conferir_85", t)
        n += 1
    con.commit()
    return n


def _processo_por_ob(c: sqlite3.Connection, texto: str) -> str | None:
    """OB (+NL) citadas no laudo → o ÚNICO processo que o SIAFE liga a elas; ambíguo ou vazio ⇒ None."""
    obs, nls = set(_RE_OB.findall(texto)), set(_RE_NL.findall(texto))
    if not obs:
        return None
    from compliance_agent.cruzamentos_intel import _ob_paga
    q = (f"SELECT DISTINCT processo, nl FROM ob_orcamentaria_siafe WHERE {_ob_paga(c)} AND "
         f"numero_ob IN ({','.join('?' * len(obs))})")
    linhas = [(p, nl) for p, nl in c.execute(q, tuple(obs)) if p and "/" in p]
    if nls:
        linhas = [(p, nl) for p, nl in linhas if nl in nls]
    procs = {p for p, _ in linhas}
    return procs.pop() if len(procs) == 1 else None


def dos_agentes(con, pastas: list[Path], compliance_db: Path, modelo: str) -> dict:
    """Laudos de agente na fonte primária que ficaram só em arquivo. Devolve {importados, sem_processo, sobrescritos}:
    `sobrescritos` = processos cujo laudo vigente tem nível de prova MENOR que o do arquivo (fonte primária perdida)."""
    c = _ro(compliance_db)
    out = {"importados": 0, "sem_processo": [], "sobrescritos": []}
    if c is None:
        return out
    try:
        por_resumo = {r[1]: r[0] for r in c.execute("SELECT numero_sei,resumo FROM lex_execucao WHERE resumo IS NOT NULL")}
        from tools.lex_execucao import _chave_processo
        chave_ns = {_chave_processo(r[0]): r[0] for r in c.execute("SELECT numero_sei FROM lex_execucao")}
        for pasta in pastas:
            for arq in sorted(Path(pasta).glob("*.json")):
                try:
                    d = json.loads(arq.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    continue
                if not isinstance(d, dict) or "resumo" not in d or "nota_risco_execucao" not in d:
                    continue
                ns_arq = arq.with_name(arq.stem.replace("_v", "") + ".ns")
                ns = ns_arq.read_text().strip() if ns_arq.exists() else por_resumo.get(d["resumo"])
                if not ns:
                    proc = _processo_por_ob(c, json.dumps(d, ensure_ascii=False))
                    ns = chave_ns.get(_chave_processo(proc)) if proc else None
                if not ns:
                    out["sem_processo"].append(str(arq))
                    continue
                if ledger.registrar_versao(con, ns, d, modelo, f"agente:{arq.parent.name}/{arq.name}") is not None:
                    out["importados"] += 1
                atual = c.execute("SELECT modelo FROM lex_execucao WHERE numero_sei=?", (ns,)).fetchone()
                if atual and 0 <= ledger.nivel_gravado(atual[0]) < config.NIVEL_FONTE:
                    out["sobrescritos"].append(ns)
    finally:
        c.close()
    con.commit()
    out["sobrescritos"] = sorted(set(out["sobrescritos"]))
    return out


def valores_e_tipos(compliance_db: Path, processos: list[str]) -> tuple[dict, dict]:
    """{numero_sei: total pago no SIAFE (OB contabilizada, sem devolvida)} e {numero_sei: tipo de processo}."""
    c = _ro(compliance_db)
    if c is None:
        return {}, {}
    try:
        from tools.lex_execucao import _chave_processo, mapa_obs_siafe
        obs = mapa_obs_siafe(c, processos)
        valores = {ns: obs[_chave_processo(ns)]["total"] for ns in processos if _chave_processo(ns) in obs}
        tipos = {}
        for i in range(0, len(processos), 500):
            lote = processos[i:i + 500]
            for ns, obj in c.execute(f"SELECT numero_sei, objeto FROM lex_execucao WHERE numero_sei IN "
                                     f"({','.join('?' * len(lote))})", lote):
                tipos[ns] = tipo_de(obj)
        return valores, tipos
    finally:
        c.close()


def tudo(con, *, compliance_db: Path | None = None, fila_db: Path | None = None, cruz_db: Path | None = None,
         log_lote: Path | None = None, pastas_agentes: list[Path] | None = None) -> dict:
    d = config.CASA
    compliance_db, fila_db = config.compliance_db(compliance_db), fila_db or d / "conferencia_opus.db"
    cruz_db, log_lote = cruz_db or d / "cruzamento_motores.db", log_lote or d / "conferir_85.log"
    r = {"fila": da_fila(con, fila_db), "lex": do_lex(con, compliance_db),
         "log_lote": do_log_lote(con, log_lote, cruz_db, "claude-opus-5-5 (conferência Opus 18/11, lote até 85%)")}
    r["agentes"] = dos_agentes(con, pastas_agentes or [], compliance_db,
                               "claude-opus-5-5 (agente Claude Code, conferência na fonte primária 18/11)")
    procs = [x[0] for x in con.execute("SELECT DISTINCT numero_sei FROM laudo_versao")]
    valores, tipos = valores_e_tipos(compliance_db, procs)
    r.update(ledger.conciliar(con, valores, tipos))
    r["pares"] = con.execute("SELECT COUNT(*) FROM conferencia").fetchone()[0]
    return r
