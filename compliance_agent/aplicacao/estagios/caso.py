# -*- coding: utf-8 -*-
"""E14 `caso:<chave>` — CASO com achados relacionados, hipóteses inocentes, lacunas e contestações (plano mestre v2
§3.2 E14, §8 "Contestação", §3.11 "RBAC e trilha"; O7.4). Absorve `processo_360`, `dossie_mestre`, `vault_casos` e
`vault_retratos` como DERIVADOS de um caso versionado — a montagem não julga nada novo, só junta o que E10/E11 e as
decisões humanas já gravaram.

CHAVE do caso (`analisar_chave`): `processo:<nº SEI>` (canônica de `dominio/processo_id`), `cnpj:<14 dígitos>`,
`ug:<6 dígitos>` ou `lista:<id,id,…>` (achados escolhidos à mão). O critério de cada achado fica gravado.

RELACIONADOS (`relacionados`) — no esquema dos achados do E10 (`sombra` por padrão), por IGUALDADE de valor, nunca por
substring do JSON cru (memória casar-palavra-no-json-cru-pega-o-nome-do-campo):
  · processo: `execucao_regra.processo` ou qualquer campo `processo` do resultado, comparados pela chave canônica;
  · cnpj: qualquer valor do resultado igual ao CNPJ (14 dígitos ou formatado) — campo `cnpj`, `credor`, …;
  · ug: campos `ug`/`ug_emitente` do resultado iguais ao código.

DERIVADO (`derivar`, determinístico — mesmo estado do banco ⇒ mesmo sha256): achados com status EFETIVO (a última
`decisao_humana`; o achado da regra nunca muda), hipóteses inocentes (do achado e do registro, com `excluida_por`),
lacunas (estado INDISPONIVEL/INCERTO/ABSTEVE, fato incerto/indisponível, peças não lidas do laudo E11 vigente),
contraevidências (fato de papel `contradicao`, contestação acolhida), diligências (o que sanearia cada lacuna e cada
contestação pendente — mecânico, sem inventar providência) e histórico (decisões, contestações e desfechos).
VERSIONADO em `caso_versao`: chave nova ⇒ versão n+1 com `supersedes`; a anterior fica, `vigente = false`.

CONTESTAÇÃO = EVENTO (argumento, anexo com sha256, autor) + DESFECHO (revisor ≠ autor, `acolhida` |
`parcialmente_acolhida` | `rejeitada`, fundamentação). O desfecho REVISA os derivados: acolhida ⇒ `decisao_humana`
refutado; parcial ⇒ `em_revisao`; rejeitada ⇒ só o registro. Cada evento gera nova versão do caso. Nada se apaga:
`contestacao`, `contestacao_desfecho`, `caso_achado` e `acesso_log` são append-only NO BANCO (gatilho).

RBAC (`dominio/acesso`): toda ação passa por `autorizar`, que grava a tentativa — permitida ou negada — em
`acesso_log` ANTES de seguir. Ler caso de classe pessoal/restrito/segredo é abrir restrito e exige justificativa.

Efeito conferido (`_efeito`, outro processo): todo achado que a regra de relação acha HOJE está no caso; a versão
vigente tem a chave declarada e ela é igual ao sha256 do derivado RECALCULADO do banco; a cadeia de versões fecha; a
montagem está no `acesso_log`.

CLI:
    python -m compliance_agent.aplicacao.estagios.caso schema aplicar
    python -m compliance_agent.aplicacao.estagios.caso montar --chave processo:SEI-480002/003703/2024
    python -m compliance_agent.aplicacao.estagios.caso ler --chave … [--justificativa "…"]
    python -m compliance_agent.aplicacao.estagios.caso contestar --chave … --argumento "…" [--achado 12] [--anexo f.pdf]
    python -m compliance_agent.aplicacao.estagios.caso desfecho --contestacao 3 --desfecho acolhida --fundamentacao "…"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.dominio import acesso as AC
from compliance_agent.dominio import processo_id as PID
from compliance_agent.dominio.achado import DecisaoHumana, StatusAchado
from compliance_agent.dominio.digitos import so_digitos
from compliance_agent.fluxo.fila import Resultado

VERSAO = "e14-1"
ESQUEMA_PADRAO = "sombra"
ENV_ESQUEMA = "JFN_E14_ESQUEMA"
RAIZ = Path(__file__).resolve().parents[3]
SQL_ACHADOS = RAIZ / "deploy" / "vm2" / "postgres" / "achados_001.sql"
SQL_CASOS = RAIZ / "deploy" / "vm2" / "postgres" / "casos_001.sql"
DESFECHOS = ("acolhida", "parcialmente_acolhida", "rejeitada")
EFEITO_DO_DESFECHO = {"acolhida": StatusAchado.REFUTADO, "parcialmente_acolhida": StatusAchado.EM_REVISAO}
ESTADOS_LACUNA = ("INDISPONIVEL", "INCERTO", "ABSTEVE")
FATOS_LACUNA = ("incerto", "indisponivel")
ANEXO_MAX = 20 * 1024 * 1024
_ORDEM_CLASSE = {c: i for i, c in enumerate(AC.CLASSES)}


# ══ 1. conexão e schema ═════════════════════════════════════════════════════════════════════════════════════════
def esquema_vigente(payload: dict | None = None) -> str:
    from compliance_agent.fluxo.schema import validar_esquema
    return validar_esquema((payload or {}).get("esquema") or os.environ.get(ENV_ESQUEMA) or ESQUEMA_PADRAO)


def conectar(payload: dict | None = None):
    import psycopg

    from compliance_agent.evidencias import dsn_vigente
    dsn = (payload or {}).get("dsn") or dsn_vigente()
    if not str(dsn or "").startswith(("postgresql://", "postgres://")):
        raise RuntimeError("sem DSN do PostgreSQL (JFN_EVIDENCIAS_DSN)")
    con = psycopg.connect(dsn, autocommit=True)
    con.execute(f'SET search_path TO "{esquema_vigente(payload)}"')
    return con


def aplicar_schema(con, esquema: str) -> None:
    """achados_001 (achado, decisao_humana) e casos_001, nesta ordem, no MESMO esquema (idempotente)."""
    from compliance_agent.fluxo.schema import renderizar, validar_esquema
    s = validar_esquema(esquema)
    con.execute(f'CREATE SCHEMA IF NOT EXISTS "{s}"')
    for arq in (SQL_ACHADOS, SQL_CASOS):
        con.execute(renderizar(arq.read_text(encoding="utf-8"), s))
    con.execute(f'SET search_path TO "{s}"')


# ══ 2. RBAC + trilha append-only ════════════════════════════════════════════════════════════════════════════════
def principal_atual() -> AC.Principal:
    """Quem roda este processo, sem credencial nova: terminal interativo do dono do repositório → dono; o resto →
    serviço (o filho do fluxo, cron, ssh não interativo)."""
    try:
        interativo = sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        interativo = False
    return AC.principal_do_processo(interativo=interativo, dono_do_repo=os.getuid() == RAIZ.stat().st_uid,
                                    no=os.environ.get("JFN_NO") or socket.gethostname())


def autorizar(con, principal: AC.Principal, acao: AC.Acao, recurso: str, *, justificativa: str = "",
              classe: str = "interno", detalhe: dict | None = None) -> AC.Decisao:
    """Decide (dominio/acesso), GRAVA a tentativa em `acesso_log` e só então devolve; negado ⇒ `AcessoNegado`."""
    from psycopg.types.json import Jsonb
    d = AC.decidir(principal, acao, justificativa=justificativa, classe=classe)
    con.execute("INSERT INTO acesso_log(principal, papel, acao, recurso, classe, justificativa, permitido, motivo, "
                "detalhe) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (principal.id, principal.papel.value, acao.value, recurso, classe, str(justificativa or ""),
                 d.permitido, d.motivo, Jsonb({**(detalhe or {}), "exigidas": list(d.exigidas)})))
    if not d.permitido:
        raise AC.AcessoNegado(d)
    return d


# ══ 3. chave e achados relacionados ═════════════════════════════════════════════════════════════════════════════
def analisar_chave(chave: str) -> tuple[str, str, str]:
    """(tipo, valor, chave canônica). Chave que não identifica UMA coisa sem palpite ⇒ ErroPermanente."""
    tipo, _, bruto = str(chave or "").partition(":")
    tipo = tipo.strip().lower()
    if tipo == "processo":
        v = PID.chave_processo(bruto)
    elif tipo == "cnpj":
        v = so_digitos(bruto)
        v = v if len(v) == 14 else None
    elif tipo == "ug":
        v = so_digitos(bruto)
        v = v if len(v) == 6 else None
    elif tipo == "lista":
        ids = sorted({int(x) for x in re.findall(r"\d+", bruto)})
        v = ",".join(map(str, ids)) if ids and re.fullmatch(r"[\d,\s]+", bruto.strip()) else None
    else:
        raise ErroPermanente(f"tipo de caso inválido: {tipo!r} (processo|cnpj|ug|lista)")
    if not v:
        raise ErroPermanente(f"chave de caso não identifica um {tipo}: {bruto!r}")
    return tipo, v, f"{tipo}:{v}"


def _cnpj_formatado(c: str) -> str:
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def relacionados(con, tipo: str, valor: str) -> dict[int, str]:
    """achado_id → critério. Igualdade de valor (jsonpath), nunca substring do JSON."""
    if tipo == "lista":
        ids = [int(x) for x in valor.split(",")]
        return {r[0]: "lista" for r in con.execute("SELECT id FROM achado WHERE id = ANY(%s)", (ids,))}
    if tipo == "cnpj":
        sql = ("SELECT a.id FROM achado a JOIN execucao_regra e ON e.id = a.execucao_regra_id "
               "WHERE jsonb_path_exists(e.resultado, '$.** ? (@ == $c || @ == $f)', %s) "
               "OR EXISTS (SELECT 1 FROM achado_evidencia v WHERE v.achado_id = a.id "
               "AND jsonb_path_exists(v.fato, '$.** ? (@ == $c || @ == $f)', %s))")
        var = json.dumps({"c": valor, "f": _cnpj_formatado(valor)})
        return {r[0]: "cnpj" for r in con.execute(sql, (var, var))}
    if tipo == "ug":
        cond = "'$.** ? (@.ug == $u || @.ug == $n || @.ug_emitente == $u || @.ug_emitente == $n)'"
        sql = ("SELECT a.id FROM achado a JOIN execucao_regra e ON e.id = a.execucao_regra_id "
               f"WHERE jsonb_path_exists(e.resultado, {cond}, %s) OR EXISTS (SELECT 1 FROM achado_evidencia v "
               f"WHERE v.achado_id = a.id AND jsonb_path_exists(v.fato, {cond}, %s))")
        var = json.dumps({"u": valor, "n": int(valor)})
        return {r[0]: "ug" for r in con.execute(sql, (var, var))}
    # processo: candidatos pelo sequencial (pré-filtro barato), decisão pela chave canônica de CADA valor
    p = PID.analisar(valor)
    seq = str(p.sequencial) if p else ""
    out: dict[int, str] = {}
    sql = ("SELECT a.id, e.processo, jsonb_path_query_array(e.resultado, '$.**.processo') FROM achado a "
           "JOIN execucao_regra e ON e.id = a.execucao_regra_id WHERE e.processo LIKE %s OR "
           "e.resultado::text LIKE %s")
    for aid, proc, outros in con.execute(sql, (f"%{seq}%", f"%{seq}%")):
        valores = [proc, *(outros or [])]
        if any(isinstance(x, str) and PID.chave_processo(x) == valor for x in valores):
            out[aid] = "processo"
    return out


# ══ 4. derivado determinístico ══════════════════════════════════════════════════════════════════════════════════
def _iso(v) -> str | None:
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    return None if v is None else str(v)


def chave_derivado(derivado: dict) -> str:
    txt = json.dumps(derivado, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()


def _registro() -> dict:
    from compliance_agent.qualidade import detectores as REG
    return REG.carregar()


def _laudos_e11(con, processos: list[str]) -> dict[str, dict]:
    """Laudo v2 VIGENTE do E11 de cada processo (peças não lidas e lacunas por eixo) — {} se o E11 não gravou."""
    if not processos:
        return {}
    from compliance_agent.aplicacao.estagios import periciar as E11
    esq = E11.esquema_vigente()
    if con.execute("SELECT to_regclass(%s)", (f'"{esq}".laudos_v2',)).fetchone()[0] is None:
        return {}
    out = {}
    for proc, versao, pecas, eixos in con.execute(
            f'SELECT processo, versao, laudo -> \'pecas_nao_lidas\', laudo -> \'eixos\' FROM "{esq}".laudos_v2 '
            "WHERE vigente AND processo = ANY(%s)", (processos,)):
        out[proc] = {"versao": versao, "pecas_nao_lidas": pecas or [], "eixos": eixos or {}}
    return out


def _caso(con, chave: str) -> dict | None:
    r = con.execute("SELECT id, chave, tipo, valor, titulo, classe FROM caso WHERE chave = %s", (chave,)).fetchone()
    return None if r is None else dict(zip(("id", "chave", "tipo", "valor", "titulo", "classe"), r))


def derivar(con, caso_id: int, registro: dict | None = None) -> dict:
    """O caso inteiro, montado SÓ do banco (achados, evidências, decisões, contestações, laudos E11) e do registro."""
    reg = registro if registro is not None else _registro()
    c = con.execute("SELECT chave, tipo, valor, titulo, classe FROM caso WHERE id = %s", (caso_id,)).fetchone()
    if c is None:
        raise ErroPermanente(f"caso {caso_id} inexistente")
    linhas = con.execute(
        "SELECT a.id, e.regra_id, e.regra_versao, e.processo, e.entradas_hash, e.origem, a.status, a.estado, "
        "a.motivo_estado, a.observacao, a.inferencia, a.qualificacao, a.hipotese, a.hipoteses_alternativas, "
        "ca.criterio, e.resultado -> 'valores' FROM caso_achado ca JOIN achado a ON a.id = ca.achado_id "
        "JOIN execucao_regra e ON e.id = a.execucao_regra_id WHERE ca.caso_id = %s ORDER BY a.id",
        (caso_id,)).fetchall()
    ids = [r[0] for r in linhas]
    evid: dict[int, list] = {}
    for aid, ordem, papel, fato in con.execute("SELECT achado_id, ordem, papel, fato FROM achado_evidencia "
                                               "WHERE achado_id = ANY(%s) ORDER BY achado_id, ordem", (ids,)):
        evid.setdefault(aid, []).append({"ordem": ordem, "papel": papel, "fato": fato})
    decis: dict[int, list] = {}
    for did, aid, autor, st, just, enc, em in con.execute(
            "SELECT id, achado_id, autor, status, justificativa, encaminhamento, decidido_em FROM decisao_humana "
            "WHERE achado_id = ANY(%s) ORDER BY decidido_em, id", (ids,)):
        decis.setdefault(aid, []).append({"id": did, "autor": autor, "status": st, "justificativa": just,
                                          "encaminhamento": enc, "em": _iso(em)})
    contest = []
    for (cid, aid, arg, anome, asha, autor, papel, em, did, rev, desf, fund, dhid, dem) in con.execute(
            "SELECT c.id, c.achado_id, c.argumento, c.anexo_nome, c.anexo_sha256, c.autor, c.papel, c.registrada_em, "
            "d.id, d.revisor, d.desfecho, d.fundamentacao, d.decisao_humana_id, d.decidido_em FROM contestacao c "
            "LEFT JOIN contestacao_desfecho d ON d.contestacao_id = c.id WHERE c.caso_id = %s ORDER BY c.id",
            (caso_id,)):
        contest.append({"id": cid, "achado_id": aid, "argumento": arg, "anexo_nome": anome, "anexo_sha256": asha,
                        "autor": autor, "papel": papel, "registrada_em": _iso(em),
                        "desfecho": None if did is None else {"id": did, "revisor": rev, "desfecho": desf,
                                                               "fundamentacao": fund, "decisao_humana_id": dhid,
                                                               "em": _iso(dem)}})
    pendentes = {x["achado_id"] for x in contest if x["desfecho"] is None and x["achado_id"] is not None}
    achados, hipoteses, lacunas, contra, diligencias = [], [], [], [], []
    processos = sorted({PID.chave_processo(r[3]) for r in linhas if r[3] and PID.chave_processo(r[3])})
    for (aid, rid, rver, proc, eh, orig, st, estado, mot, obs, inf, qual, hip, alts, crit, valores) in linhas:
        e = reg.get(rid) or {}
        ds = decis.get(aid, [])
        achados.append({"id": aid, "regra_id": rid, "regra_versao": rver, "tier": e.get("tier"),
                        "processo": PID.chave_processo(proc) if proc else None, "entradas_hash": eh.strip(),
                        "origem": orig, "criterio": crit, "status_regra": st,
                        "status_efetivo": ds[-1]["status"] if ds else st, "estado": estado, "motivo_estado": mot,
                        "observacao": obs, "inferencia": inf, "qualificacao": qual, "hipotese": hip,
                        "valores": valores or {}, "evidencias": evid.get(aid, []), "decisoes": ds,
                        "contestacao_pendente": aid in pendentes})
        vistos = set()
        for h in alts or []:
            vistos.add(h)
            hipoteses.append({"achado_id": aid, "regra_id": rid, "hipotese": h, "origem": "achado",
                              "excluida_por": None})
        for h in e.get("hipoteses_inocentes") or []:
            if h.get("hipotese") and h["hipotese"] not in vistos:
                hipoteses.append({"achado_id": aid, "regra_id": rid, "hipotese": h["hipotese"], "origem": "registro",
                                  "excluida_por": h.get("excluida_por")})
        if estado in ESTADOS_LACUNA:
            lacunas.append({"achado_id": aid, "tipo": f"estado {estado}", "motivo": mot or estado})
        for v in evid.get(aid, []):
            f = v["fato"] or {}
            if f.get("estado") in FATOS_LACUNA:
                lacunas.append({"achado_id": aid, "tipo": f"fato {f.get('estado')}",
                                "motivo": f"{f.get('tipo')} {f.get('referencia') or ''} em {f.get('fonte')}".strip()})
            if v["papel"] == "contradicao":
                contra.append({"achado_id": aid, "origem": "evidencia", "descricao": f.get("descricao") or "",
                               "fonte": f.get("fonte"), "referencia": f.get("referencia")})
    for proc, laudo in sorted(_laudos_e11(con, processos).items()):
        for p in laudo["pecas_nao_lidas"]:
            lacunas.append({"achado_id": None, "processo": proc, "tipo": "peça não lida (E11)",
                            "motivo": f"{p.get('doc_id') or p.get('titulo') or '?'}: {p.get('motivo') or '?'}"})
        for nome, ex in sorted((laudo["eixos"] or {}).items()):
            for lac in ex.get("lacunas") or []:
                lacunas.append({"achado_id": None, "processo": proc, "tipo": f"lacuna do eixo {nome} (E11)",
                                "motivo": str(lac.get("descricao") if isinstance(lac, dict) else lac)})
    for x in contest:
        d = x["desfecho"]
        if d and d["desfecho"] in EFEITO_DO_DESFECHO:
            contra.append({"achado_id": x["achado_id"], "origem": f"contestacao:{x['id']}",
                           "descricao": x["argumento"], "fonte": "contestação", "referencia": x["anexo_sha256"]})
        if d is None:
            diligencias.append({"origem": f"contestacao:{x['id']}",
                                "texto": f"decidir a contestação {x['id']} (revisor diferente do autor)"})
    for lac in lacunas:
        alvo = f"achado {lac['achado_id']}" if lac.get("achado_id") else f"processo {lac.get('processo')}"
        diligencias.append({"origem": "lacuna", "texto": f"sanear {lac['tipo']} — {alvo}: {lac['motivo']}"})
    for a in achados:
        if a["status_efetivo"] == "triagem" and a["estado"] == "INDICIO":
            diligencias.append({"origem": f"achado:{a['id']}",
                                "texto": f"conferência humana do achado {a['id']} ({a['regra_id']}), hoje em triagem"})
    historico = sorted(
        [{"em": d["em"], "evento": "decisao", "achado_id": a["id"], "detalhe": f"{d['status']} por {d['autor']}"}
         for a in achados for d in a["decisoes"]]
        + [{"em": x["registrada_em"], "evento": "contestacao", "achado_id": x["achado_id"],
            "detalhe": f"contestação {x['id']} por {x['autor']}"} for x in contest]
        + [{"em": x["desfecho"]["em"], "evento": "desfecho", "achado_id": x["achado_id"],
            "detalhe": f"contestação {x['id']}: {x['desfecho']['desfecho']} por {x['desfecho']['revisor']}"}
           for x in contest if x["desfecho"]],
        key=lambda h: (h["em"] or "", h["evento"], h["achado_id"] or 0, h["detalhe"]))
    return {"versao_estagio": VERSAO, "caso": dict(zip(("chave", "tipo", "valor", "titulo", "classe"), c)),
            "achados": achados, "hipoteses_inocentes": hipoteses, "lacunas": lacunas,
            "contraevidencias": contra, "diligencias": diligencias, "contestacoes": contest,
            "historico": historico, "processos": processos}


def classe_minima(derivado: dict) -> str:
    """Caso com pessoa física (campo `cpf` em evidência ou valores) é ao menos `pessoal`."""
    def tem_cpf(o) -> bool:
        if isinstance(o, dict):
            return any(k == "cpf" and v for k, v in o.items()) or any(tem_cpf(v) for v in o.values())
        return isinstance(o, list) and any(tem_cpf(v) for v in o)
    return "pessoal" if any(tem_cpf(a["evidencias"]) or tem_cpf(a["valores"]) for a in derivado["achados"]) \
        else "interno"


def vigente(con, caso_id: int) -> dict | None:
    r = con.execute("SELECT id, versao, chave, supersedes, derivado, motivo FROM caso_versao WHERE caso_id = %s "
                    "AND vigente", (caso_id,)).fetchone()
    return None if r is None else dict(zip(("id", "versao", "chave", "supersedes", "derivado", "motivo"), r))


def versionar(con, caso_id: int, derivado: dict, motivo: str) -> dict:
    """Mesma chave da vigente ⇒ nada (idempotente); chave nova ⇒ n+1 com `supersedes` (a anterior só deixa de ser
    vigente)."""
    from psycopg.types.json import Jsonb
    ch = chave_derivado(derivado)
    with con.transaction():
        con.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"caso:{caso_id}",))
        v = vigente(con, caso_id)
        if v and v["chave"].strip() == ch:
            return {"id": v["id"], "versao": v["versao"], "chave": ch, "nova": False}
        n = 1 + (con.execute("SELECT COALESCE(MAX(versao), 0) FROM caso_versao WHERE caso_id = %s",
                             (caso_id,)).fetchone()[0])
        if v:
            con.execute("UPDATE caso_versao SET vigente = false WHERE id = %s", (v["id"],))
        rid = con.execute("INSERT INTO caso_versao(caso_id, versao, chave, supersedes, vigente, motivo, derivado) "
                          "VALUES (%s,%s,%s,%s,true,%s,%s) RETURNING id",
                          (caso_id, n, ch, v["id"] if v else None, motivo, Jsonb(derivado))).fetchone()[0]
    return {"id": rid, "versao": n, "chave": ch, "nova": True}


# ══ 5. operações (todas autorizadas e trilhadas) ════════════════════════════════════════════════════════════════
def montar(con, chave: str, principal: AC.Principal, *, titulo: str = "", classe: str | None = None) -> dict:
    tipo, valor, ch = analisar_chave(chave)
    if classe is not None and classe not in AC.CLASSES:
        raise ErroPermanente(f"classe inválida: {classe!r}")
    c = _caso(con, ch)
    autorizar(con, principal, AC.Acao.MONTAR_CASO, f"caso:{ch}", classe=(c or {}).get("classe") or "interno")
    if c is None:
        con.execute("INSERT INTO caso(chave, tipo, valor, titulo, classe, criado_por) VALUES (%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (chave) DO NOTHING", (ch, tipo, valor, titulo, classe or "interno", principal.id))
        c = _caso(con, ch)
    rel = relacionados(con, tipo, valor)
    for aid, crit in sorted(rel.items()):
        con.execute("INSERT INTO caso_achado(caso_id, achado_id, criterio) VALUES (%s,%s,%s) "
                    "ON CONFLICT (caso_id, achado_id) DO NOTHING", (c["id"], aid, crit))
    der = derivar(con, c["id"])
    alvo = max((classe or c["classe"], classe_minima(der)), key=_ORDEM_CLASSE.get)
    if _ORDEM_CLASSE[alvo] > _ORDEM_CLASSE[c["classe"]]:          # classe só SOBE (nunca afrouxa sozinha)
        con.execute("UPDATE caso SET classe = %s WHERE id = %s", (alvo, c["id"]))
        der = derivar(con, c["id"])
    v = versionar(con, c["id"], der, "montagem")
    return {"caso_id": c["id"], "chave": ch, "achados": len(der["achados"]), "classe": der["caso"]["classe"], **{
        f"versao_{k}": x for k, x in v.items()}}


def ler(con, chave: str, principal: AC.Principal, *, justificativa: str = "") -> dict:
    _t, _v, ch = analisar_chave(chave)
    c = _caso(con, ch)
    if c is None:
        raise ErroPermanente(f"caso inexistente: {ch}")
    autorizar(con, principal, AC.Acao.LER_CASO, f"caso:{ch}", justificativa=justificativa, classe=c["classe"])
    v = vigente(con, c["id"])
    return {"caso_id": c["id"], **(v or {})}


def contestar(con, chave: str, principal: AC.Principal, argumento: str, *, achado_id: int | None = None,
              anexo: Path | None = None) -> dict:
    _t, _v, ch = analisar_chave(chave)
    c = _caso(con, ch)
    if c is None:
        raise ErroPermanente(f"caso inexistente: {ch}")
    autorizar(con, principal, AC.Acao.CONTESTAR, f"caso:{ch}", classe=c["classe"],
              detalhe={"achado_id": achado_id})
    if not str(argumento or "").strip():
        raise ErroPermanente("contestação sem argumento")
    if achado_id is not None and con.execute("SELECT 1 FROM caso_achado WHERE caso_id = %s AND achado_id = %s",
                                             (c["id"], achado_id)).fetchone() is None:
        raise ErroPermanente(f"o achado {achado_id} não é do caso {ch}")
    nome = sha = dados = None
    if anexo is not None:
        dados = Path(anexo).read_bytes()
        if len(dados) > ANEXO_MAX:
            raise ErroPermanente(f"anexo de {len(dados)} bytes acima de {ANEXO_MAX}")
        nome, sha = Path(anexo).name, hashlib.sha256(dados).hexdigest()
    cid = con.execute("INSERT INTO contestacao(caso_id, achado_id, argumento, anexo_nome, anexo_sha256, anexo, autor, "
                      "papel) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                      (c["id"], achado_id, argumento, nome, sha, dados, principal.id,
                       principal.papel.value)).fetchone()[0]
    v = versionar(con, c["id"], derivar(con, c["id"]), f"contestacao:{cid}")
    return {"contestacao_id": cid, "anexo_sha256": sha, **{f"versao_{k}": x for k, x in v.items()}}


def decidir_contestacao(con, contestacao_id: int, principal: AC.Principal, desfecho: str, fundamentacao: str) -> dict:
    """Desfecho de quem não é o autor; acolhida/parcial viram `decisao_humana` (o achado da regra não muda)."""
    if desfecho not in DESFECHOS:
        raise ErroPermanente(f"desfecho inválido: {desfecho!r} ({'|'.join(DESFECHOS)})")
    r = con.execute("SELECT c.caso_id, c.achado_id, c.autor, k.chave, k.classe FROM contestacao c JOIN caso k "
                    "ON k.id = c.caso_id WHERE c.id = %s", (contestacao_id,)).fetchone()
    if r is None:
        raise ErroPermanente(f"contestação {contestacao_id} inexistente")
    caso_id, achado_id, autor, ch, classe = r
    autorizar(con, principal, AC.Acao.REVISAR_CONTESTACAO, f"caso:{ch}", classe=classe,
              detalhe={"contestacao_id": contestacao_id, "desfecho": desfecho})
    if principal.id.strip().lower() == autor.strip().lower():
        raise ErroPermanente("o revisor não pode ser o autor da contestação")
    if not str(fundamentacao or "").strip():
        raise ErroPermanente("desfecho sem fundamentação")
    with con.transaction():
        dh = None
        st = EFEITO_DO_DESFECHO.get(desfecho)
        if st is not None and achado_id is not None:
            dec = DecisaoHumana(autor=principal.id, status=st, justificativa=fundamentacao,
                                decidido_em=datetime.now(timezone.utc),
                                encaminhamento=f"contestacao:{contestacao_id}:{desfecho}")
            dh = con.execute("INSERT INTO decisao_humana(achado_id, autor, status, justificativa, encaminhamento, "
                             "decidido_em) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                             (achado_id, dec.autor, dec.status.value, dec.justificativa, dec.encaminhamento,
                              dec.decidido_em)).fetchone()[0]
        did = con.execute("INSERT INTO contestacao_desfecho(contestacao_id, revisor, papel, desfecho, fundamentacao, "
                          "decisao_humana_id) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                          (contestacao_id, principal.id, principal.papel.value, desfecho, fundamentacao,
                           dh)).fetchone()[0]
    v = versionar(con, caso_id, derivar(con, caso_id), f"desfecho:{did}")
    return {"desfecho_id": did, "decisao_humana_id": dh, **{f"versao_{k}": x for k, x in v.items()}}


# ══ 6. estágio (contrato do §3.2) ═══════════════════════════════════════════════════════════════════════════════
def _chave_payload(payload: dict, ctx: Contexto | None) -> str:
    ch = payload.get("chave") or (ctx.tipo.split(":", 1)[1] if ctx and ":" in ctx.tipo else "")
    return analisar_chave(ch)[2]


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    ch = _chave_payload(payload, ctx)
    con = conectar(payload)
    try:
        aplicar_schema(con, esquema_vigente(payload))
        r = montar(con, ch, AC.Principal(f"servico:fluxo@{ctx.no}", AC.Papel.SERVICO),
                   titulo=str(payload.get("titulo") or ""), classe=payload.get("classe"))
    finally:
        con.close()
    return Resultado(efeito={**r, "esquema": esquema_vigente(payload)},
                     eventos=[{"fonte": "caso", "tipo": "versao", "chave": ch}] if r["versao_nova"] else [])


def conferir(con, efeito: dict) -> dict:
    """Relê o banco: relação de hoje ⊆ caso; vigente = declarada = sha do derivado recalculado; cadeia; trilha."""
    out = {"relacao_completa": False, "vigente_ok": False, "recalculo_ok": False, "cadeia_ok": False, "trilha": 0}
    c = _caso(con, efeito.get("chave") or "")
    if c is None:
        return out
    tipo, valor, _ = analisar_chave(c["chave"])
    no_caso = {r[0] for r in con.execute("SELECT achado_id FROM caso_achado WHERE caso_id = %s", (c["id"],))}
    out["relacao_completa"] = set(relacionados(con, tipo, valor)) <= no_caso
    v = vigente(con, c["id"])
    out["vigente_ok"] = v is not None and v["chave"].strip() == efeito.get("versao_chave")
    if v is not None:
        recalc = chave_derivado(derivar(con, c["id"]))
        out["recalculo_ok"] = recalc == v["chave"].strip() == chave_derivado(v["derivado"])
        ant = con.execute("SELECT versao FROM caso_versao WHERE id = %s", (v["supersedes"],)).fetchone() \
            if v["supersedes"] else None
        out["cadeia_ok"] = (v["versao"] == 1 and ant is None) or (ant is not None and ant[0] < v["versao"])
    out["trilha"] = con.execute("SELECT count(*) FROM acesso_log WHERE recurso = %s AND acao = 'montar_caso' "
                                "AND permitido", (f"caso:{c['chave']}",)).fetchone()[0]
    return out


def efeito_ok(c: dict) -> bool:
    return c["relacao_completa"] and c["vigente_ok"] and c["recalculo_ok"] and c["cadeia_ok"] and c["trilha"] > 0


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    ef = resultado.efeito or {}
    if ef.get("chave") != _chave_payload(payload, ctx):
        return False
    con = conectar(payload)
    try:
        c = conferir(con, ef)
    finally:
        con.close()
    ef["conferencia"] = c
    return efeito_ok(c)


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["cpu_leve"], prioridade=60)


# ══ 7. CLI ══════════════════════════════════════════════════════════════════════════════════════════════════════
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E14 caso (O7.4)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("schema")
    s.add_argument("acao", choices=("aplicar",))
    m = sub.add_parser("montar")
    m.add_argument("--chave", required=True)
    m.add_argument("--titulo", default="")
    m.add_argument("--classe", choices=AC.CLASSES)
    le = sub.add_parser("ler")
    le.add_argument("--chave", required=True)
    le.add_argument("--justificativa", default="")
    c = sub.add_parser("contestar")
    c.add_argument("--chave", required=True)
    c.add_argument("--argumento", required=True)
    c.add_argument("--achado", type=int)
    c.add_argument("--anexo", type=Path)
    d = sub.add_parser("desfecho")
    d.add_argument("--contestacao", type=int, required=True)
    d.add_argument("--desfecho", choices=DESFECHOS, required=True)
    d.add_argument("--fundamentacao", required=True)
    a = ap.parse_args(argv)
    con = conectar({})
    try:
        if a.cmd == "schema":
            aplicar_schema(con, esquema_vigente())
            out = {"esquema": esquema_vigente(), "ok": True}
        else:
            p = principal_atual()
            if a.cmd == "montar":
                out = montar(con, a.chave, p, titulo=a.titulo, classe=a.classe)
            elif a.cmd == "ler":
                out = ler(con, a.chave, p, justificativa=a.justificativa)
            elif a.cmd == "contestar":
                out = contestar(con, a.chave, p, a.argumento, achado_id=a.achado, anexo=a.anexo)
            else:
                out = decidir_contestacao(con, a.contestacao, p, a.desfecho, a.fundamentacao)
    except AC.AcessoNegado as e:
        print(f"caso: ACESSO NEGADO — {e.decisao.motivo} (registrado em acesso_log)", file=sys.stderr)
        return 2
    finally:
        con.close()
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
