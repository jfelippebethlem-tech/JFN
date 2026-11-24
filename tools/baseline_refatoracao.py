#!/usr/bin/env python3
"""Linha de base da refatoração "Esteira Única" (O1.3 do plano mestre v2, §2 "Estado real medido").

Só leitura. Mede os números da §2 e grava UM JSON em que cada número traz a SQL ou o comando que o produz e o
estado: MEDIDO ou INDISPONIVEL (com motivo). **INDISPONÍVEL ≠ 0**: consulta que falhou, tabela que não existe ou
máquina que não respondeu NUNCA vira zero.

Universos:
  --universo snapshot   lê ~/snapshot-20261124/ (compliance.db, conferencia_opus.db, propagacao.db e
                        jfn_evidencias.dump) = universo de paridade da parada de obras. O "agora" das janelas de
                        7 dias é o início da cópia (estado.log), não o relógio — por isso duas execuções batem.
  --universo vivo       lê data/ e o PostgreSQL vigente; o "agora" é o relógio.

O que não está no snapshot (data/sei_arquivo/*/manifest.json, data/itcampo_rodadas.jsonl, filas em data/, o código
no HEAD do git, as fotos de ~/.config/jfn/backups/refatoracao-20261124/) é lido do lugar de sempre e marcado com a
origem; janelas de tempo são cortadas no "agora" do universo, então escrita posterior não muda o número.

Saída: ~/.local/share/jfn/baseline/<data>-<universo>.json. NÃO vai para data/baseline/: `data/` não é
gitignored por inteiro (169 arquivos versionados — ADR-011) e o repo é público.

Métricas `dinamico: true` (máquinas: carga, PSI, swap, disco, crontab de hoje) mudam entre execuções por natureza;
`--comparar A B` confere só as estáticas e sai 1 se alguma divergir.

Peso: roda sob `nice 15` + `ionice -c3`; só sqlite3 (nunca DuckDB na VM-1); o SQLite do snapshot abre `immutable`.
O dump do PostgreSQL é lido pelo `pg_restore` da VM-2 (stdin pelo ssh; a VM-1 não tem cliente PG).

Uso:
  python -m tools.baseline_refatoracao --universo snapshot
  python -m tools.baseline_refatoracao --universo vivo --sem-maquinas
  python -m tools.baseline_refatoracao --comparar A.json B.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
SNAPSHOT = Path.home() / "snapshot-20261124"
FOTOS = Path.home() / ".config" / "jfn" / "backups" / "refatoracao-20261124"
SAIDA_DIR = Path.home() / ".local" / "share" / "jfn" / "baseline"
MEDIDO, INDISPONIVEL = "MEDIDO", "INDISPONIVEL"
SSH_TIMEOUT = 20
CARGA_MAX = 10.0                   # carga 1 min acima disto na VM-1: não roda (conferir uptime antes de pesado)
TABELAS_CHAVE = ("ordens_bancarias", "ob_orcamentaria_siafe", "alertas", "pericia_integral", "lex_execucao",
                 "sei_fila_captura", "contratos_tcerj", "pcrj_contratos")
PROVEDORES_CASCATA = ("gemini", "openrouter")      # a "cascata grátis" da §2 (laudo sem Claude)

# fonte → (tabela, expressão do frescor). MAX cru da coluna de coleta; formatos mistos ficam visíveis no valor.
FRESCOR = {
    "tfe_ob": ("ordens_bancarias", "MAX(data_emissao)"),   # coletado_em/created_at/updated_at são todos NULL
    "siafe_ob": ("ob_orcamentaria_siafe", "MAX(coletado_em)"),
    "siafe_ne": ("ne_siafe", "MAX(coletado_em)"),
    "siafe_nl": ("nl_siafe", "MAX(coletado_em)"),
    "siafe_gd": ("gd_siafe", "MAX(coletado_em)"),
    "siafe_dea": ("dea_siafe", "MAX(coletado_em)"),
    "siafe_retencao": ("ob_retencao_siafe", "MAX(coletado_em)"),
    "siafe_bloqueio_judicial": ("bloqueio_judicial_siafe", "MAX(coletado_em)"),
    "tcerj_contratos": ("contratos_tcerj", "MAX(ingerido_em)"),
    "tcerj_compras_diretas": ("compras_diretas_tcerj", "MAX(ingerido_em)"),
    "tcerj_penalidades": ("penalidades_tcerj", "MAX(ingerido_em)"),
    "tcerj_licitante": ("tcerj_licitante", "MAX(coletado_em)"),
    "tce_decisoes": ("decisoes_tce", "MAX(created_at)"),
    "pncp_resultado": ("pncp_resultado", "MAX(coletado_em)"),
    "pncp_ente": ("pncp_ente", "MAX(coletado_em)"),
    "pcrj_contratos": ("pcrj_contratos", "MAX(coletado_em)"),
    "pcrj_despesa": ("pcrj_despesa", "MAX(coletado_em)"),
    "pcrj_despesa_dotacao": ("pcrj_despesa_dotacao", "MAX(coletado_em)"),
    "pcrj_licitacoes": ("pcrj_licitacoes", "MAX(coletado_em)"),
    "doerj_coleta": ("publicacoes_doerj", "MAX(created_at)"),
    "doerj_publicacao_min": ("publicacoes_doerj", "MIN(data_publicacao)"),
    "doerj_publicacao_max": ("publicacoes_doerj", "MAX(data_publicacao)"),
    "folha_alerj": ("alerj_folha", "MAX(ingerido_em)"),
    "folha_estado": ("registros_folha", "MAX(created_at)"),
    "sancoes_siga": ("siga_sancoes", "MAX(visto_em)"),
    "sancoes_federais_publicacao": ("sancoes_federais", "MAX(data_publicacao)"),
    "lista_suja_mte": ("lista_suja_mte", "MAX(visto_em)"),
    "siga_contratos": ("siga_contratos", "MAX(visto_em)"),
    "emendas": ("emendas", "MAX(coletado_em)"),
    "emenda_favorecidos": ("emenda_favorecidos", "MAX(coletado_em)"),
    "noticias_orgaos": ("noticias_orgaos", "MAX(visto_em)"),
    "edital_documento": ("edital_documento", "MAX(coletado_em)"),
    "contrato_aditivo": ("contrato_aditivo", "MAX(coletado_em)"),
    "socios_fornecedor": ("socios_fornecedor", "MAX(ingerido_em)"),
    "ckan_despesa_execucao": ("despesa_execucao", "MAX(CAST(exercicio AS TEXT) || ' ' || COALESCE(posicao, ''))"),
}


# ─── registro de métricas ────────────────────────────────────────────────────────────────────────────────────────
def metrica(mid: str, valor, *, consulta: str, grupo: str, descricao: str = "", origem: str = "",
            dinamico: bool = False, plano: str | None = None) -> dict:
    return {"id": mid, "grupo": grupo, "descricao": descricao, "estado": MEDIDO, "valor": valor,
            "consulta": consulta, "origem": origem, "dinamico": dinamico, **({"plano_s2": plano} if plano else {})}


def indisponivel(mid: str, motivo: str, *, consulta: str = "", grupo: str, descricao: str = "", origem: str = "",
                 dinamico: bool = False, plano: str | None = None, mover_para: str | None = None) -> dict:
    m = {"id": mid, "grupo": grupo, "descricao": descricao, "estado": INDISPONIVEL, "valor": None,
         "motivo": motivo, "consulta": consulta, "origem": origem, "dinamico": dinamico}
    if plano:
        m["plano_s2"] = plano
    if mover_para:
        m["mover_para"] = mover_para
    return m


def medir_sql(con: sqlite3.Connection | None, mid: str, sql: str, *, grupo: str, origem: str, descricao: str = "",
              params: tuple = (), forma: str = "escalar", plano: str | None = None) -> dict:
    """Roda `sql` e devolve a métrica. forma: escalar (1ª coluna da 1ª linha) | dict (2 colunas → {k: v}) |
    linha (1ª linha como lista). Falha de banco = INDISPONIVEL com o erro — nunca 0."""
    kw = dict(consulta=sql, grupo=grupo, origem=origem, descricao=descricao, plano=plano)
    if con is None:
        return indisponivel(mid, "banco do universo não abriu", **kw)
    try:
        cur = con.execute(sql, params)
        if forma == "dict":
            valor = {("∅" if k is None else str(k)): v for k, v in cur.fetchall()}
        elif forma == "linha":
            r = cur.fetchone()
            valor = list(r) if r else None
        else:
            r = cur.fetchone()
            valor = r[0] if r else None
    except sqlite3.Error as e:
        return indisponivel(mid, f"{type(e).__name__}: {e}", **kw)
    return metrica(mid, valor, **kw)


def abrir_sqlite(caminho: Path, *, imutavel: bool) -> sqlite3.Connection | None:
    if not caminho.exists():
        return None
    q = "mode=ro&immutable=1" if imutavel else "mode=ro"
    con = sqlite3.connect(f"file:{caminho}?{q}", uri=True, timeout=30)
    con.execute("PRAGMA query_only=1")
    return con


def razao(num, den) -> float | None:
    try:
        return round(float(num) / float(den), 4) if den else None
    except (TypeError, ValueError):
        return None


def derivada(mid: str, num: dict, den: dict, *, grupo: str, descricao: str, plano: str | None = None) -> dict:
    """num/den de duas métricas já medidas; se uma for INDISPONIVEL, a razão também é."""
    cons = f"{num['id']} / {den['id']}"
    if num["estado"] != MEDIDO or den["estado"] != MEDIDO or razao(num["valor"], den["valor"]) is None:
        return indisponivel(mid, "depende de métrica INDISPONIVEL ou denominador zero", consulta=cons, grupo=grupo,
                            descricao=descricao, origem="derivada", plano=plano)
    return metrica(mid, razao(num["valor"], den["valor"]), consulta=cons, grupo=grupo, descricao=descricao,
                   origem="derivada", plano=plano)


# ─── universo ────────────────────────────────────────────────────────────────────────────────────────────────────
def agora_do_snapshot(pasta: Path = SNAPSHOT) -> datetime | None:
    """Início da cópia congelada (1ª linha de estado.log: 'AAAA-MM-DD HH:MM:SS inicio')."""
    try:
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", (pasta / "estado.log").read_text().splitlines()[0])
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None
    except (OSError, IndexError, AttributeError):
        return None


def universo(nome: str) -> dict:
    if nome == "snapshot":
        agora = agora_do_snapshot()
        if agora is None:
            raise SystemExit(f"snapshot sem estado.log legível em {SNAPSHOT}")
        return {"nome": "snapshot", "agora": agora, "imutavel": True,
                "compliance": SNAPSHOT / "compliance.db", "opus": SNAPSHOT / "conferencia_opus.db",
                "propagacao": SNAPSHOT / "propagacao.db", "pg_dump": SNAPSHOT / "jfn_evidencias.dump"}
    return {"nome": "vivo", "agora": datetime.now().replace(microsecond=0), "imutavel": False,
            "compliance": DATA / "compliance.db", "opus": DATA / "conferencia_opus.db",
            "propagacao": DATA / "propagacao.db", "pg_dump": None}


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ─── compliance.db ───────────────────────────────────────────────────────────────────────────────────────────────
def medir_compliance(u: dict) -> list[dict]:
    g, org = "dados", f"{u['nome']}:compliance.db"
    out = []
    p = u["compliance"]
    if p.exists():
        out.append(metrica("dados.compliance_db_bytes", p.stat().st_size, consulta=f"stat {p.name}", grupo=g,
                           origem=org, plano="6,1 GB"))
    else:
        out.append(indisponivel("dados.compliance_db_bytes", f"{p} não existe", grupo=g, origem=org))
    con = abrir_sqlite(p, imutavel=u["imutavel"])
    s = lambda mid, sql, **kw: out.append(medir_sql(con, mid, sql, origem=org, **kw))  # noqa: E731
    s("dados.compliance_db_tabelas", "SELECT COUNT(*) FROM sqlite_master WHERE type='table'", grupo=g,
      plano="164 tabelas")
    for t in TABELAS_CHAVE:
        s(f"tabela.{t}.linhas", f"SELECT COUNT(*) FROM {t}", grupo="tabelas",
          plano="fila de 19.707" if t == "sei_fila_captura" else None)
    s("alertas.por_status", "SELECT status, COUNT(*) FROM alertas GROUP BY status ORDER BY status",
      grupo="tabelas", forma="dict")
    s("alertas.por_tipo", "SELECT tipo, COUNT(*) FROM alertas GROUP BY tipo ORDER BY tipo", grupo="tabelas",
      forma="dict")
    s("alertas.por_tipo_status", "SELECT tipo || '|' || COALESCE(status, '∅'), COUNT(*) FROM alertas "
      "GROUP BY tipo, status ORDER BY 1", grupo="tabelas", forma="dict")
    s("lex_execucao.ultima_em", "SELECT MAX(em) FROM lex_execucao", grupo="producao")
    s("triagem.ultima_em", "SELECT MAX(em) FROM alertas_triagem", grupo="producao",
      descricao="última triagem gravada", plano="triagem parada desde 21/11")
    # perícia integral: origem do modelo e conferência do Opus (laudo = linha eixo '_global')
    gp = "pericia"
    s("pericia.linhas", "SELECT COUNT(*) FROM pericia_integral", grupo=gp)
    s("pericia.processos", "SELECT COUNT(DISTINCT processo) FROM pericia_integral", grupo=gp)
    s("pericia.laudos", "SELECT COUNT(*) FROM pericia_integral WHERE eixo='_global'", grupo=gp)
    s("pericia.laudos_por_provedor", "SELECT provedor, COUNT(*) FROM pericia_integral WHERE eixo='_global' "
      "GROUP BY provedor ORDER BY provedor", grupo=gp, forma="dict")
    s("pericia.laudos_por_modelo", "SELECT modelo, COUNT(*) FROM pericia_integral WHERE eixo='_global' "
      "GROUP BY modelo ORDER BY modelo", grupo=gp, forma="dict")
    s("pericia.laudos_por_conferido_opus", "SELECT conferido_opus, COUNT(*) FROM pericia_integral "
      "WHERE eixo='_global' GROUP BY conferido_opus ORDER BY conferido_opus", grupo=gp, forma="dict",
      descricao="0 = não conferido, 1 = conferido pelo Opus, 2 = substituído pela conferência")
    marca = ",".join(f"'{p}'" for p in PROVEDORES_CASCATA)
    s("pericia.laudos_cascata", f"SELECT COUNT(*) FROM pericia_integral WHERE eixo='_global' "
      f"AND provedor IN ({marca})", grupo=gp)
    s("pericia.laudos_conferidos_opus", "SELECT COUNT(*) FROM pericia_integral WHERE eixo='_global' "
      "AND conferido_opus=1", grupo=gp)
    ult = ("SELECT p.* FROM pericia_integral p JOIN (SELECT processo, MAX(id) mid FROM pericia_integral "
           "WHERE eixo='_global' GROUP BY processo) u ON p.id=u.mid")
    s("pericia.ultimo_laudo_por_processo", f"SELECT COUNT(*), SUM(conferido_opus=1), "
      f"SUM(provedor IN ({marca})) FROM ({ult})", grupo=gp, forma="linha",
      descricao="[processos, último laudo conferido pelo Opus, último laudo da cascata]")
    idx = {m["id"]: m for m in out}
    out.append(derivada("pericia.frac_laudos_cascata", idx["pericia.laudos_cascata"], idx["pericia.laudos"],
                        grupo=gp, descricao="laudos sem Claude (gemini/openrouter) ÷ laudos", plano="72,6%"))
    out.append(derivada("pericia.frac_laudos_conferidos_opus", idx["pericia.laudos_conferidos_opus"],
                        idx["pericia.laudos"], grupo=gp, descricao="laudos com conferido_opus=1 ÷ laudos",
                        plano="9,9%"))
    # frescor por fonte
    for fonte, (tab, expr) in FRESCOR.items():
        m = medir_sql(con, f"frescor.{fonte}", f"SELECT {expr} FROM {tab}", grupo="frescor", origem=org)
        if m["estado"] == MEDIDO and m["valor"] is None:       # tabela vazia ou coluna toda NULL ≠ "fresco"
            m = indisponivel(m["id"], "coluna sem valor (tabela vazia ou coluna toda NULL)", consulta=m["consulta"],
                             grupo="frescor", origem=org)
        out.append(m)
    if con is not None:
        con.close()
    return out


def medir_analitico(u: dict) -> list[dict]:
    """compliance_analitico.db (cópia de defasagem desconhecida, §2): tamanho e frescor do SIAFE lá × no universo."""
    g, p = "dados", DATA / "compliance_analitico.db"
    if not p.exists():
        return [indisponivel("dados.analitico_bytes", f"{p.name} não existe", grupo=g, origem="data/")]
    out = [metrica("dados.analitico_bytes", p.stat().st_size, consulta=f"stat {p.name}", grupo=g, origem="data/",
                   plano="5,9 GB")]
    con = abrir_sqlite(p, imutavel=False)
    out.append(medir_sql(con, "dados.analitico_frescor_siafe_ob", "SELECT MAX(coletado_em) FROM ob_orcamentaria_siafe",
                         grupo=g, origem="data/compliance_analitico.db",
                         descricao="comparar com frescor.siafe_ob do universo = defasagem"))
    if con is not None:
        con.close()
    return out


# ─── fila do Opus ────────────────────────────────────────────────────────────────────────────────────────────────
def medir_opus(u: dict) -> list[dict]:
    g, org = "opus", f"{u['nome']}:conferencia_opus.db"
    con = abrir_sqlite(u["opus"], imutavel=u["imutavel"])
    desde, ate = iso(u["agora"] - timedelta(days=7)), iso(u["agora"])
    # as datas da fila são ISO com 'T' (memória timestamp-iso-com-T): normalizar antes de comparar
    norm = lambda c: f"REPLACE({c}, 'T', ' ')"  # noqa: E731
    out = [medir_sql(con, "opus.entradas_7d", f"SELECT COUNT(*) FROM fila WHERE {norm('criado_em')} >= ? "
                     f"AND {norm('criado_em')} <= ?", params=(desde, ate), grupo=g, origem=org, plano="~750/dia"),
           medir_sql(con, "opus.saidas_7d", f"SELECT COUNT(*) FROM fila WHERE {norm('conferido_em')} >= ? "
                     f"AND {norm('conferido_em')} <= ?", params=(desde, ate), grupo=g, origem=org, plano="~49/dia"),
           medir_sql(con, "opus.pendentes", "SELECT COUNT(*) FROM fila WHERE status='pendente'", grupo=g,
                     origem=org, plano="6.501"),
           medir_sql(con, "opus.por_status", "SELECT status, COUNT(*) FROM fila GROUP BY status ORDER BY status",
                     grupo=g, origem=org, forma="dict"),
           medir_sql(con, "opus.pendentes_por_tarefa", "SELECT tarefa, COUNT(*) FROM fila WHERE status='pendente' "
                     "GROUP BY tarefa ORDER BY tarefa", grupo=g, origem=org, forma="dict"),
           medir_sql(con, "opus.concorda", "SELECT SUM(concorda=1) FROM fila", grupo=g, origem=org),
           medir_sql(con, "opus.julgados", "SELECT COUNT(concorda) FROM fila", grupo=g, origem=org)]
    idx = {m["id"]: m for m in out}
    out.append(derivada("opus.concordancia", idx["opus.concorda"], idx["opus.julgados"], grupo=g,
                        descricao="concorda=1 ÷ pares julgados (todo o histórico)", plano="27%"))
    if con is not None:
        con.close()
    return out


# ─── PostgreSQL da leitura integral ──────────────────────────────────────────────────────────────────────────────
TABELAS_PG = ("fatos", "docs_lidos", "leituras", "tabelas_lidas", "jobs", "processos", "documentos", "versoes",
              "arvores")


def resumir_copy(linhas) -> dict:
    """Lê a saída de `pg_restore -a -f -` (blocos COPY) e devolve {tabela: {linhas, processos, max_em}}.
    `processos` = distintos da coluna `processo`; `max_em` = maior valor da coluna `em` (texto)."""
    res: dict[str, dict] = {}
    atual = cols = None
    vistos: set = set()
    for ln in linhas:
        ln = ln.rstrip("\n")
        if atual is None:
            m = re.match(r"COPY (?:\w+\.)?(\w+) \((.*)\) FROM stdin;", ln)
            if m:
                atual, cols, vistos = m.group(1), [c.strip().strip('"') for c in m.group(2).split(",")], set()
                res[atual] = {"linhas": 0, "processos": None, "max_em": None}
            continue
        if ln == "\\.":
            if "processo" in cols:
                res[atual]["processos"] = len(vistos)
            atual = None
            continue
        r = res[atual]
        r["linhas"] += 1
        campos = ln.split("\t")
        if "processo" in cols:
            vistos.add(campos[cols.index("processo")])
        if "em" in cols:
            v = campos[cols.index("em")]
            if v != "\\N" and (r["max_em"] is None or v > r["max_em"]):
                r["max_em"] = v
    return res


def _pg_do_dump(dump: Path) -> tuple[dict | None, str]:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={SSH_TIMEOUT}", "vm2-ts",
           "nice -n 15 pg_restore -a -f -"]
    try:
        with dump.open("rb") as f:
            r = subprocess.run(cmd, stdin=f, capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"pg_restore na VM-2 falhou: {type(e).__name__}"
    if r.returncode != 0:
        return None, f"pg_restore rc={r.returncode}: {r.stderr.decode(errors='replace')[:200]}"
    return resumir_copy(r.stdout.decode("utf-8", errors="replace").splitlines()), \
        "pg_restore -a -f - (VM-2, dump do snapshot por stdin)"


def _pg_vivo() -> tuple[dict | None, str]:
    try:
        sys.path.insert(0, str(RAIZ))
        from compliance_agent.evidencias import dsn_vigente
        import psycopg
    except ImportError as e:
        return None, f"sem cliente PG: {e}"
    dsn = dsn_vigente()
    if not dsn:
        return None, "DSN do PostgreSQL ausente (JFN_EVIDENCIAS_DSN)"
    res = {}
    try:
        with psycopg.connect(dsn, connect_timeout=SSH_TIMEOUT) as c:
            for t in TABELAS_PG:
                try:
                    cur = c.execute(f"SELECT COUNT(*) FROM public.{t}")
                    n = cur.fetchone()[0]
                    cols = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns "
                                                    "WHERE table_schema='public' AND table_name=%s", (t,))}
                    procs = c.execute(f"SELECT COUNT(DISTINCT processo) FROM public.{t}").fetchone()[0] \
                        if "processo" in cols else None
                    mx = c.execute(f"SELECT MAX(em) FROM public.{t}").fetchone()[0] if "em" in cols else None
                    res[t] = {"linhas": n, "processos": procs, "max_em": mx}
                except psycopg.Error:
                    c.rollback()
    except psycopg.Error as e:
        return None, f"PG não respondeu: {type(e).__name__}"
    return res, "SELECT COUNT(*) / COUNT(DISTINCT processo) / MAX(em) FROM public.<tabela> (PG vigente)"


def medir_pg(u: dict) -> list[dict]:
    g = "leitura_integral"
    if u["pg_dump"] is not None:
        res, como = _pg_do_dump(u["pg_dump"]) if u["pg_dump"].exists() else (None, "dump ausente")
        org = f"{u['nome']}:jfn_evidencias.dump"
    else:
        res, como = _pg_vivo()
        org = "vivo:PG jfn_evidencias"
    out = []
    planos = {"fatos": "133.750", "jobs": "vazio", "processos": "vazio", "documentos": "vazio", "versoes": "vazio",
              "arvores": "vazio"}
    for t in TABELAS_PG:
        if res is None or t not in res:
            out.append(indisponivel(f"pg.{t}.linhas", como if res is None else f"tabela {t} ausente no PG",
                                    consulta=como, grupo=g, origem=org))
            continue
        out.append(metrica(f"pg.{t}.linhas", res[t]["linhas"], consulta=como, grupo=g, origem=org,
                           plano=planos.get(t)))
    if res and "leituras" in res:
        out.append(metrica("pg.leituras.processos", res["leituras"]["processos"], consulta=como, grupo=g, origem=org,
                           plano="271 processos"))
        out.append(metrica("pg.leituras.ultima_em", res["leituras"]["max_em"], consulta=como, grupo=g, origem=org,
                           plano="parada desde 23/11 13:32"))
    else:
        for mid in ("pg.leituras.processos", "pg.leituras.ultima_em"):
            out.append(indisponivel(mid, como, consulta=como, grupo=g, origem=org))
    return out


# ─── despachante (propagacao.db + config/propagacao.yaml) ────────────────────────────────────────────────────────
def medir_despachante(u: dict) -> list[dict]:
    g, org = "orquestracao", f"{u['nome']}:propagacao.db + HEAD:config/propagacao.yaml"
    try:
        import yaml
        sys.path.insert(0, str(RAIZ))
        from compliance_agent.propagacao import _sujos, slo_s
        cfg = yaml.safe_load(git_show("config/propagacao.yaml")) or {}
    except Exception as e:  # noqa: BLE001 — qualquer falha de import/leitura = INDISPONIVEL, nunca 0
        return [indisponivel("despachante", f"config/propagacao indisponível: {e}", grupo=g, origem=org)]
    fontes, derivs = cfg.get("fontes") or {}, cfg.get("derivados") or {}
    out = [metrica("despachante.fontes", len(fontes), consulta="len(propagacao.yaml:fontes)", grupo=g, origem=org,
                   plano="36"),
           metrica("despachante.derivados", len(derivs), consulta="len(propagacao.yaml:derivados)", grupo=g,
                   origem=org, plano="43")]
    con = abrir_sqlite(u["propagacao"], imutavel=u["imutavel"])
    cons = "propagacao._sujos(con) + slo_s(derivado): sujo há mais que o SLO = ATRASADO, no 'agora' do universo"
    if con is None:
        return out + [indisponivel(f"despachante.{k}", "propagacao.db ausente", consulta=cons, grupo=g, origem=org)
                      for k in ("sujos", "atrasados", "maior_atraso_h")]
    try:
        sujos = {d: v for d, v in _sujos(con).items() if d in derivs}     # mesma regra de propagacao.estado()
    except sqlite3.Error as e:
        con.close()
        return out + [indisponivel("despachante.sujos", str(e), consulta=cons, grupo=g, origem=org)]
    con.close()
    agora = u["agora"].timestamp()
    atraso = {d: (agora - v["primeiro"]) / 3600 for d, v in sujos.items()}
    atrasados = sorted(d for d, h in atraso.items() if h * 3600 > slo_s(derivs.get(d) or {}, cfg))
    out += [metrica("despachante.sujos", len(sujos), consulta=cons, grupo=g, origem=org, plano="34"),
            metrica("despachante.atrasados", len(atrasados), consulta=cons, grupo=g, origem=org, plano="6"),
            metrica("despachante.atrasados_lista", atrasados, consulta=cons, grupo=g, origem=org),
            metrica("despachante.maior_atraso_h", round(max(atraso.values()), 1) if atraso else None, consulta=cons,
                    grupo=g, origem=org, plano="48,4 h")]
    return out


# ─── arquivos fora do snapshot ───────────────────────────────────────────────────────────────────────────────────
def medir_cobertura_pericia() -> list[dict]:
    """Reusa o sensor `plataforma` (tools/automelhoria_geral._cobertura_acervo): caracteres que a perícia integral
    alcança (teto por peça e por processo de compliance_agent/pericia_integral.py) ÷ caracteres do acervo."""
    g, org = "pericia", "data/sei_arquivo/*/manifest.json (fora do snapshot; congelado pela parada)"
    cons = "tools.automelhoria_geral._cobertura_acervo() — min(Σ min(chars, TETO_DOC), TETO_TEXTO) por processo"
    try:
        sys.path.insert(0, str(RAIZ))
        from tools.automelhoria_geral import _cobertura_acervo
        total, alc, procs, cortados = _cobertura_acervo()
    except Exception as e:  # noqa: BLE001
        return [indisponivel("pericia.cobertura_chars", f"{type(e).__name__}: {e}", consulta=cons, grupo=g,
                             origem=org)]
    if total <= 0:
        return [indisponivel("pericia.cobertura_chars", "nenhum manifesto com texto", consulta=cons, grupo=g,
                             origem=org)]
    return [metrica("pericia.acervo_chars", total, consulta=cons, grupo=g, origem=org),
            metrica("pericia.alcancavel_chars", alc, consulta=cons, grupo=g, origem=org),
            metrica("pericia.cobertura_chars", razao(alc, total), consulta=cons, grupo=g, origem=org, plano="17,3%"),
            metrica("pericia.processos_com_texto", procs, consulta=cons, grupo=g, origem=org),
            metrica("pericia.processos_cortados", cortados, consulta=cons, grupo=g, origem=org)]


def ler_rodadas(caminho: Path, ate: datetime) -> list[dict]:
    corte = iso(ate)
    out = []
    try:
        texto = caminho.read_text(errors="replace")
    except OSError:
        return []
    for ln in texto.splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("ts", "") <= corte:
            out.append(r)
    return out


def medir_captura_sei(u: dict, caminho: Path = DATA / "itcampo_rodadas.jsonl") -> list[dict]:
    """Rodadas de captura do it-campo (o log vive na VM-1). Janela = todo o log até o 'agora' do universo."""
    g, org = "captura_sei", f"data/{caminho.name} (fora do snapshot; cortado em {iso(u['agora'])})"
    rodadas = ler_rodadas(caminho, u["agora"])
    if not rodadas:
        return [indisponivel(f"captura.{k}", f"{caminho.name} ausente ou vazio", grupo=g, origem=org)
                for k in ("processos_distintos_por_dia", "frac_recaptura_igual", "frac_tempo_recaptura_igual")]
    sys.path.insert(0, str(RAIZ))
    from tools.automelhoria_geral import fracao_recaptura_igual
    dias, procs, ok = set(), set(), 0
    for r in rodadas:
        dias.add(r["ts"][:10])
        for p, d in (r.get("procs") or {}).items():
            procs.add(p)
            ok += d.get("status") == "ok"
    frac_t, n_igual = fracao_recaptura_igual(rodadas)
    return [metrica("captura.rodadas", len(rodadas), consulta="linhas JSON válidas com ts ≤ agora", grupo=g,
                    origem=org),
            metrica("captura.dias", len(dias), consulta="datas distintas de ts", grupo=g, origem=org),
            metrica("captura.processos_distintos_por_dia", round(len(procs) / len(dias), 1),
                    consulta="processos distintos em procs{} ÷ dias", grupo=g, origem=org, plano="874"),
            metrica("captura.frac_recaptura_igual", razao(n_igual, ok),
                    consulta="capturas ok com a MESMA árvore da anterior ÷ capturas ok", grupo=g, origem=org,
                    plano="16,9%"),
            metrica("captura.frac_tempo_recaptura_igual", round(frac_t, 4),
                    consulta="tools.automelhoria_geral.fracao_recaptura_igual (segundos)", grupo=g, origem=org,
                    plano="25,6% (definição do §2 não registrada; esta é a do sensor plataforma)")]


def medir_arquivos_data() -> list[dict]:
    g, org = "dados", "data/ (fora do snapshot)"
    jsons = sorted({p.name for p in DATA.glob("*.json")} | {p.name for p in DATA.glob(".*.json")})
    dbs = sorted(str(p.relative_to(DATA)) for p in DATA.rglob("*.db") if "sei_cache" not in p.parts)
    out = [metrica("dados.json_em_data", len(jsons), consulta="glob data/*.json + data/.*.json", grupo=g, origem=org,
                   plano="≥ 34 filas ou estados"),
           metrica("dados.sqlite_em_data", len(dbs), consulta="rglob data/**/*.db (fora sei_cache)", grupo=g,
                   origem=org, plano="30 bancos")]
    fila_ocr = DATA / "sei_ocr_gpu_fila.txt"
    if fila_ocr.exists():
        n = sum(1 for ln in fila_ocr.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip())
        out.append(metrica("ocr.fila_gpu", n, consulta="linhas não vazias de data/sei_ocr_gpu_fila.txt (última fila "
                           "gravada por tools/sei_ocr_gpu_fila.py)", grupo="captura_sei", origem=org, plano="9.837"))
    else:
        out.append(indisponivel("ocr.fila_gpu", "data/sei_ocr_gpu_fila.txt ausente", grupo="captura_sei",
                                origem=org))
    return out


# ─── código e detectores (sempre do HEAD do git: estável entre execuções) ────────────────────────────────────────
def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(RAIZ), *args], capture_output=True, text=True, timeout=120,
                          check=True).stdout


def git_show(caminho: str) -> str:
    return git("show", f"HEAD:{caminho}")


def avaliar_detectores(reg: dict) -> dict:
    det = (reg or {}).get("detectores") or {}
    manch = [k for k, v in det.items() if v.get("manchete")]
    return {"total": len(det),
            "sem_fp_medida": sum(1 for v in det.values() if v.get("fp_medida") is None),
            "manchetes": len(manch),
            "manchetes_sem_fp_medida": sum(1 for k in manch if det[k].get("fp_medida") is None),
            "sem_controle_positivo": sum(1 for v in det.values() if not v.get("controle_positivo")),
            "sem_controle_negativo": sum(1 for v in det.values() if not v.get("controle_negativo"))}


def medir_detectores() -> list[dict]:
    g, org, arq = "detectores", "HEAD:config/qualidade_detectores.yaml", "config/qualidade_detectores.yaml"
    planos = {"total": "149", "sem_fp_medida": "136", "manchetes": "47", "manchetes_sem_fp_medida": "41"}
    try:
        import yaml
        r = avaliar_detectores(yaml.safe_load(git_show(arq)))
    except Exception as e:  # noqa: BLE001
        return [indisponivel("detectores.total", f"{type(e).__name__}: {e}", grupo=g, origem=org)]
    return [metrica(f"detectores.{k}", v, consulta=f"yaml {arq}: detectores.* ({k})", grupo=g, origem=org,
                    plano=planos.get(k)) for k, v in r.items()]


ROTA = re.compile(r"@[a-z_]+\.(get|post|put|delete|patch|websocket|api_route)\(")


def medir_codigo() -> list[dict]:
    """Cada número isolado: um item que falha vira INDISPONIVEL sozinho, sem levar os outros."""
    g, org = "codigo", "HEAD do git"
    try:
        arqs = git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    except (subprocess.SubprocessError, OSError) as e:
        return [indisponivel("codigo.ls_tree", f"git falhou: {e}", grupo=g, origem=org)]
    conta = lambda rx: sum(1 for a in arqs if re.match(rx, a))  # noqa: E731
    out = [metrica("codigo.py_compliance_agent", conta(r"compliance_agent/.*\.py$"),
                   consulta="git ls-tree HEAD | compliance_agent/**/*.py", grupo=g, origem=org, plano="644"),
           metrica("codigo.py_compliance_agent_raiz", conta(r"compliance_agent/[^/]+\.py$"),
                   consulta="git ls-tree HEAD | compliance_agent/*.py", grupo=g, origem=org, plano="191"),
           metrica("codigo.py_tools", conta(r"tools/.*\.py$"), consulta="git ls-tree HEAD | tools/**/*.py",
                   grupo=g, origem=org, plano="381"),
           metrica("codigo.arquivos_teste", conta(r"tests/(.*/)?test_[^/]*\.py$"),
                   consulta="git ls-tree HEAD | tests/**/test_*.py", grupo=g, origem=org, plano="1.016"),
           metrica("seguranca.arquivos_versionados_data", conta(r"data/"),
                   consulta="git ls-tree -r HEAD | data/", grupo="seguranca", origem=org, plano="169")]
    itens = {
        "codigo.rotas": (lambda: len(git("grep", "-h", "-E", ROTA.pattern, "HEAD", "--", "server.py",
                                         "rotas").splitlines()),
                         f"git grep -E '{ROTA.pattern}' HEAD -- server.py rotas", "248"),
        "codigo.linhas_rotas_investigacao": (lambda: git_show("rotas/investigacao.py").count("\n"),
                                             "wc -l HEAD:rotas/investigacao.py", "3.121"),
        "codigo.ci_delta_falhas_toleradas": (
            lambda: sum(1 for f in ("tests/BASE-FALHAS-CI.txt", "tests/BASE-FALHAS-VM2.txt")
                        for ln in git_show(f).splitlines() if ln.strip() and not ln.lstrip().startswith("#")),
            "linhas não vazias de HEAD:tests/BASE-FALHAS-{CI,VM2}.txt", "194"),
    }
    for mid, (fn, cons, plano) in itens.items():
        try:
            out.append(metrica(mid, fn(), consulta=cons, grupo=g, origem=org, plano=plano))
        except (subprocess.SubprocessError, OSError) as e:
            out.append(indisponivel(mid, f"git falhou: {type(e).__name__}", consulta=cons, grupo=g, origem=org,
                                    plano=plano))
    uv = RAIZ / "uv.lock"
    if "uv.lock" in arqs:
        out.append(metrica("codigo.uv_lock_bytes", len(git_show("uv.lock").encode()), consulta="bytes de HEAD:uv.lock",
                           grupo=g, origem=org, plano="vazio"))
    elif uv.exists():
        out.append(metrica("codigo.uv_lock_bytes", uv.stat().st_size, consulta="stat uv.lock (NÃO versionado)",
                           grupo=g, origem="árvore de trabalho (uv.lock fora do git)", plano="vazio"))
    else:
        out.append(indisponivel("codigo.uv_lock_bytes", "uv.lock não existe", grupo=g, origem=org, plano="vazio"))
    return out


def medir_fotos_pre_parada() -> list[dict]:
    """Fotos O0.0 (antes da parada): o que rodava. Estáticas — o arquivo não muda mais."""
    g, org = "orquestracao", f"{FOTOS} (fotos O0.0)"
    out = []
    cron = FOTOS / "vm1" / "crontab_pre_parada.txt"
    if cron.exists():
        ativas = [ln for ln in cron.read_text(errors="replace").splitlines()
                  if ln.strip() and not ln.lstrip().startswith("#") and not re.match(r"[A-Za-z_]\w*=", ln)]
        out.append(metrica("pre_parada.vm1.crons_ativos", len(ativas), consulta="linhas não comentadas e não-env "
                           "de vm1/crontab_pre_parada.txt", grupo=g, origem=org, plano="114"))
        out.append(metrica("pre_parada.vm1.crons_com_semaforo", sum("pesado.sh" in ln for ln in ativas),
                           consulta="das ativas, as que passam por tools/pesado.sh", grupo=g, origem=org,
                           plano="4 de 114"))
    else:
        out.append(indisponivel("pre_parada.vm1.crons_ativos", "foto do crontab ausente", grupo=g, origem=org))
    for no, arq in (("vm1", FOTOS / "vm1" / "timers.txt"), ("vm2", FOTOS / "vm2" / "estado.txt")):
        if not arq.exists():
            out.append(indisponivel(f"pre_parada.{no}.timers", "foto ausente", grupo=g, origem=org))
            continue
        units = {m.group(0) for m in re.finditer(r"[\w@.-]+\.timer\b", arq.read_text(errors="replace"))}
        jfn = sorted(t for t in units if t.startswith(("jfn", "sei-")))
        out.append(metrica(f"pre_parada.{no}.timers_total", len(units), consulta=f"units *.timer distintas em {arq.name}",
                           grupo=g, origem=org, plano="17" if no == "vm1" else "16"))
        out.append(metrica(f"pre_parada.{no}.timers_jfn", len(jfn), consulta=f"units *.timer jfn*/sei-* em {arq.name}",
                           grupo=g, origem=org))
    return out


# ─── máquinas (dinâmicas, só leitura) ────────────────────────────────────────────────────────────────────────────
SCRIPT_LINUX = r"""
echo "NPROC $(nproc)"
echo "LOAD $(cut -d' ' -f1-3 /proc/loadavg)"
for r in cpu memory io; do echo "PSI_$r $(grep some /proc/pressure/$r | sed 's/.*avg300=\([0-9.]*\).*/\1/')"; done
free -m | awk '/Swap/{print "SWAP", $3, $2}'
df -P / | awk 'NR==2{gsub("%","",$5); print "DISCO", $5}'
echo "CRON_ATIVAS $(crontab -l 2>/dev/null | grep -v '^[[:space:]]*#' | grep -v '^[[:space:]]*$' | grep -vc '^[A-Za-z_][A-Za-z0-9_]*=')"
echo "CRON_ATIVAS_JFN $(crontab -l 2>/dev/null | grep -v '^[[:space:]]*#' | grep -c 'JFN')"
echo "CRON_PARADA $(crontab -l 2>/dev/null | grep -c '^#PARADA-20261124')"
echo "TIMERS_JFN_ATIVOS $(systemctl --user list-units --type=timer --state=active --no-legend 2>/dev/null | grep -cE 'jfn|sei-pcrj')"
echo "SERVICOS_JFN_RODANDO $(systemctl --user list-units --type=service --state=running --no-legend 2>/dev/null | grep -cE 'jfn|sei')"
echo "CHROMIUM $(pgrep -a -x 'chrome|chromium|chromium-browse' 2>/dev/null | grep -vc -- '--type=')"
"""


CHAVES_INT = {"NPROC", "CRON_ATIVAS", "CRON_ATIVAS_JFN", "CRON_PARADA", "TIMERS_JFN_ATIVOS", "SERVICOS_JFN_RODANDO",
              "CHROMIUM"}


def interpretar_linux(texto: str) -> dict:
    v: dict = {}
    for ln in texto.splitlines():
        partes = ln.split()
        if len(partes) < 2:
            continue
        k, resto = partes[0], partes[1:]
        try:
            if k == "LOAD":
                v["load"] = [float(x) for x in resto]
            elif k == "SWAP":
                v["swap_usado_mb"], v["swap_total_mb"] = int(resto[0]), int(resto[1])
            elif k.startswith("PSI_"):
                v[f"psi_{k[4:].lower()}_some_avg300"] = float(resto[0])
            elif k == "DISCO":
                v["disco_pct"] = float(resto[0])
            elif k in CHAVES_INT:
                v[k.lower()] = int(resto[0])
        except (ValueError, IndexError):
            continue
    return v


def _rodar(cmd: list[str], entrada: str | None = None) -> str | None:
    try:
        r = subprocess.run(cmd, input=entrada, capture_output=True, text=True, errors="replace",
                           timeout=SSH_TIMEOUT + 25)
        return r.stdout if r.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def _ps_itcampo() -> str:
    wsl = base64.b64encode(SCRIPT_LINUX.encode()).decode()
    ps = (f"$ErrorActionPreference='SilentlyContinue'\n"
          f"wsl -e sh -c \"echo {wsl} | base64 -d | sh\"\n"
          "Get-PSDrive -PSProvider FileSystem | ForEach-Object { 'DRIVE_' + $_.Name + ' ' + $_.Free + ' ' + $_.Used }\n"
          "Get-ScheduledTask -TaskName 'JFN*' | ForEach-Object { 'TASK ' + $_.TaskName + ' ' + $_.State }\n"
          "'CPU_WIN ' + (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum\n"
          "'RAM_WIN ' + (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory\n"
          "nvidia-smi --query-gpu=memory.total,utilization.gpu --format=csv,noheader,nounits | "
          "ForEach-Object { 'GPU ' + $_ }\n")
    return base64.b64encode(ps.encode("utf-16-le")).decode()


def medir_maquinas() -> list[dict]:
    out = []
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={SSH_TIMEOUT}"]
    fontes = {"vm1": (["bash", "-s"], SCRIPT_LINUX), "vm2": ([*ssh, "vm2-ts", "bash -s"], SCRIPT_LINUX),
              "itcampo": ([*ssh, "it-campo", f"powershell -NoProfile -EncodedCommand {_ps_itcampo()}"], None)}
    for no, (cmd, entrada) in fontes.items():
        g, cons = "maquinas", ("script linux de baseline_refatoracao.SCRIPT_LINUX" if no != "itcampo"
                               else "powershell: WSL (mesmo script) + Get-PSDrive + Get-ScheduledTask JFN* + nvidia-smi")
        org = f"{no} (ssh, timeout {SSH_TIMEOUT} s)" if no != "vm1" else "vm1 (local)"
        texto = _rodar(cmd, entrada)
        if texto is None:
            out.append(indisponivel(f"maq.{no}", "máquina não respondeu no prazo", consulta=cons, grupo=g, origem=org,
                                    dinamico=True))
            continue
        v = interpretar_linux(texto)
        if no == "itcampo":
            for ln in texto.splitlines():
                p = ln.split()
                if ln.startswith("DRIVE_") and len(p) >= 3 and p[1].isdigit():
                    v[f"drive_{p[0][6:].lower()}_livre_gb"] = round(int(p[1]) / 1e9, 1)
                elif ln.startswith("TASK ") and len(p) >= 3:
                    v.setdefault("tarefas_jfn", {})[p[1]] = p[2]
                elif ln.startswith("CPU_WIN ") and len(p) >= 2:
                    v["cpu_logicas_windows"] = int(p[1]) if p[1].isdigit() else None
                elif ln.startswith("RAM_WIN ") and len(p) >= 2 and p[1].isdigit():
                    v["ram_windows_gb"] = round(int(p[1]) / 2**30, 1)
                elif ln.startswith("GPU "):
                    g2 = [x.strip() for x in ln[4:].split(",")]
                    if len(g2) == 2 and g2[0].isdigit():
                        v["gpu_mem_mb"], v["gpu_util_pct"] = int(g2[0]), int(g2[1]) if g2[1].isdigit() else None
        if not v:
            out.append(indisponivel(f"maq.{no}", "resposta sem campos reconhecidos", consulta=cons, grupo=g,
                                    origem=org, dinamico=True))
            continue
        for k, val in sorted(v.items()):
            out.append(metrica(f"maq.{no}.{k}", val, consulta=cons, grupo=g, origem=org, dinamico=True))
    return out


# ─── o que a O1.3 pede e ainda não tem fonte ─────────────────────────────────────────────────────────────────────
def sem_fonte() -> list[dict]:
    g = "pendente"
    itens = {
        "seguranca.cpfs_no_historico": ("varrer `git log -p` do main inteiro é pesado para a VM-1 (2 vCPU)", "869",
                                        "VM-2: `git log -p main | tools/scanner de CPF com DV` (O0.4/O9.4)"),
        "painel.abas": ("definição de 'aba' do §2 não registrada (77); medir pelo inventário da O7.6", "77", None),
        "painel.contraste_reprovado": ("exige navegador (auditor de contraste mede pixel)", "2 textos a 4,37:1",
                                       "it-campo/VM-2 com o auditor de contraste"),
        "painel.saldo_higgsfield": ("saldo só pelo MCP do Higgsfield (não é chamável deste script)", "523,7", None),
        "o13.semaforo_ocioso": ("tools/pesado.sh não grava série de ocupação; nasce em fluxo.metricas (O8)", None, None),
        "o13.pushes_com_vm2_fora": ("o portão de pre-push não registra quando a VM-2 estava fora; nasce na O8", None,
                                    None),
        "o13.cpu_prewarm": ("prewarm parado pela parada de obras; medir na religação (O9.0) por cgroup do slice",
                            None, None),
        "o13.quem_detecta_primeiro": ("exige replay dos detectores sobre o snapshot (O5); sem série histórica", None,
                                      "VM-2 (replay sobre o snapshot)"),
    }
    return [indisponivel(mid, motivo, grupo=g, origem="—", plano=plano, mover_para=mover)
            for mid, (motivo, plano, mover) in itens.items()]


# ─── execução ────────────────────────────────────────────────────────────────────────────────────────────────────
def baixar_prioridade() -> None:
    try:
        os.nice(15)
    except OSError:
        pass
    try:
        subprocess.run(["ionice", "-c3", "-p", str(os.getpid())], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def medir_tudo(u: dict, *, maquinas: bool = True) -> dict:
    t0 = time.time()
    metricas = []
    for fn in (lambda: medir_compliance(u), lambda: medir_analitico(u), lambda: medir_opus(u), lambda: medir_pg(u),
               lambda: medir_despachante(u), medir_cobertura_pericia, lambda: medir_captura_sei(u),
               medir_arquivos_data, medir_detectores, medir_codigo, medir_fotos_pre_parada, sem_fonte):
        metricas += fn()
    if maquinas:
        metricas += medir_maquinas()
    try:
        head = git("rev-parse", "HEAD").strip()
    except (subprocess.SubprocessError, OSError):
        head = None
    ids = [m["id"] for m in metricas]
    duplicados = sorted({i for i in ids if ids.count(i) > 1})
    return {"meta": {"plano": "~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md §2", "item": "O1.3",
                     "universo": u["nome"], "agora_do_universo": iso(u["agora"]), "gerado_em": iso(datetime.now()),
                     "git_head": head, "carga_inicio": os.getloadavg()[0], "segundos": round(time.time() - t0, 1),
                     "medidas": sum(m["estado"] == MEDIDO for m in metricas),
                     "indisponiveis": sum(m["estado"] == INDISPONIVEL for m in metricas),
                     "ids_duplicados": duplicados},
            "metricas": metricas}


def comparar(a: dict, b: dict) -> list[str]:
    """Diferenças entre duas linhas de base nas métricas ESTÁTICAS (dinamico=false)."""
    ma = {m["id"]: m for m in a["metricas"] if not m.get("dinamico")}
    mb = {m["id"]: m for m in b["metricas"] if not m.get("dinamico")}
    dif = [f"só em A: {k}" for k in sorted(ma.keys() - mb.keys())] + \
          [f"só em B: {k}" for k in sorted(mb.keys() - ma.keys())]
    for k in sorted(ma.keys() & mb.keys()):
        if (ma[k]["estado"], ma[k]["valor"]) != (mb[k]["estado"], mb[k]["valor"]):
            dif.append(f"{k}: {ma[k]['estado']} {ma[k]['valor']!r} ≠ {mb[k]['estado']} {mb[k]['valor']!r}")
    return dif


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Linha de base da refatoração (O1.3) — só leitura")
    ap.add_argument("--universo", choices=("snapshot", "vivo"), default="snapshot")
    ap.add_argument("--saida", type=Path, help=f"arquivo de saída (padrão {SAIDA_DIR}/<data>-<universo>.json)")
    ap.add_argument("--sem-maquinas", action="store_true", help="não consulta as 3 máquinas")
    ap.add_argument("--comparar", nargs=2, type=Path, metavar=("A", "B"), help="compara as métricas estáticas")
    a = ap.parse_args(argv)
    if a.comparar:
        dif = comparar(*(json.loads(p.read_text(encoding="utf-8")) for p in a.comparar))
        print("\n".join(dif) if dif else "estáticas iguais")
        return 1 if dif else 0
    carga = os.getloadavg()[0]
    if carga > CARGA_MAX:
        print(f"carga {carga:.1f} > {CARGA_MAX}: não rodo agora (conferir uptime antes de pesado)", file=sys.stderr)
        return 2
    baixar_prioridade()
    u = universo(a.universo)
    res = medir_tudo(u, maquinas=not a.sem_maquinas)
    saida = a.saida or SAIDA_DIR / f"{u['agora']:%Y-%m-%d}-{u['nome']}.json"
    saida.parent.mkdir(parents=True, exist_ok=True)
    tmp = saida.with_suffix(".tmp")
    tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(saida)
    m = res["meta"]
    print(f"{saida}: {m['medidas']} MEDIDO · {m['indisponiveis']} INDISPONIVEL · {m['segundos']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
