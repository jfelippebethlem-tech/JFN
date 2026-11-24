# -*- coding: utf-8 -*-
"""Aplica e verifica o schema do motor de fluxo (deploy/vm2/postgres/fluxo_*.sql; ADR-012).

O SQL é o mesmo para produção (`fluxo`) e para os testes (esquema temporário criado e apagado no teste): o arquivo
usa a variável psql `:"esquema"` e aqui ela vira o identificador citado. `verificar` abre a sessão em SOMENTE
LEITURA — pode rodar contra o banco real sem risco (23/11/2026: a suíte antiga esvaziava a tabela real).

CLI:
    python -m compliance_agent.fluxo.schema verificar [--esquema fluxo]    # só leitura; sai 1 se faltar algo
    python -m compliance_agent.fluxo.schema aplicar   [--esquema fluxo]    # idempotente
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from compliance_agent.evidencias import dsn_vigente

RAIZ = Path(__file__).resolve().parents[2]
PASTA_SQL = RAIZ / "deploy" / "vm2" / "postgres"
ESQUEMA_PADRAO = "fluxo"
_RX_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# o que a O1.7/O2.3 prometem: tabela → colunas obrigatórias (verificar confere uma a uma)
TABELAS = {
    "jobs": ("id", "tipo", "chave", "estado", "prioridade", "recursos", "dono", "prazo", "ficha", "heartbeat_em",
             "tentativas", "max_tentativas", "disponivel_em", "erro_tipo", "erro_resumo", "correlation_id",
             "no_preferido", "volta", "payload", "efeito", "criado_em", "iniciado_em", "concluido_em"),
    "eventos": ("id", "fonte", "chave", "tipo", "detalhe", "quando", "processado_em"),
    "agenda": ("id", "cron_expr", "proximo", "tipo_job", "payload", "ativo", "dono"),
    "nos": ("no", "capacidades", "slots", "psi", "versao_codigo", "heartbeat_em"),
    "metricas": ("no", "nome", "valor", "quando", "rotulos"),
    "jobs_arquivo": ("id", "chave", "estado"),
    "migracoes": ("versao", "aplicada_em"),
    "liberacao": ("estagio", "liberado_em", "por", "nota"),                       # fluxo_002 (O9.0)
    "eventos_arquivo": ("id", "fonte", "tipo", "quando", "processado_em"),         # fluxo_002 (histórico)
}


def validar_esquema(esquema: str) -> str:
    """O nome entra no SQL como identificador: só minúsculas, dígitos e `_` (nada de injeção por nome)."""
    if not _RX_IDENT.match(esquema or ""):
        raise ValueError(f"nome de esquema inválido: {esquema!r}")
    return esquema


def migracoes() -> list[Path]:
    return sorted(PASTA_SQL.glob("fluxo_[0-9][0-9][0-9].sql"))


def renderizar(sql: str, esquema: str) -> str:
    return sql.replace(':"esquema"', f'"{validar_esquema(esquema)}"')


def aplicar(con, esquema: str = ESQUEMA_PADRAO) -> list[str]:
    """Roda todas as migrações em ordem numa conexão psycopg em autocommit (cada arquivo tem o seu BEGIN/COMMIT e
    a sua trava de DDL). Devolve as versões aplicadas nesta chamada (vazia = já estava tudo)."""
    validar_esquema(esquema)
    antes = set(_versoes(con, esquema))
    for arq in migracoes():
        con.execute(renderizar(arq.read_text(encoding="utf-8"), esquema))
    return sorted(set(_versoes(con, esquema)) - antes)


def _versoes(con, esquema: str) -> list[str]:
    existe = con.execute("SELECT to_regclass(%s)", (f'"{esquema}".migracoes',)).fetchone()[0]
    if not existe:
        return []
    return [r[0] for r in con.execute(f'SELECT versao FROM "{esquema}".migracoes')]


def verificar(con, esquema: str = ESQUEMA_PADRAO) -> dict:
    """Confere, só com SELECT no catálogo, se o schema está completo. `faltando` vazio = ok."""
    validar_esquema(esquema)
    faltando: list[str] = []
    cols: dict[str, set] = {}
    for tabela, coluna in con.execute("SELECT table_name, column_name FROM information_schema.columns "
                                      "WHERE table_schema = %s", (esquema,)):
        cols.setdefault(tabela, set()).add(coluna)
    for tabela, obrigatorias in TABELAS.items():
        if tabela not in cols:
            faltando.append(f"tabela {tabela}")
            continue
        faltando += [f"coluna {tabela}.{c}" for c in obrigatorias if c not in cols[tabela]]
    indices = {r[0]: r[1] for r in con.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = %s",
                                               (esquema,))}
    if "estado = 'fila'" not in indices.get("jobs_fila_ix", ""):
        faltando.append("índice parcial jobs_fila_ix WHERE estado='fila'")
    if not any("UNIQUE" in d and "(chave)" in d for d in indices.values()):
        faltando.append("UNIQUE(chave) em jobs")
    gatilho = con.execute("SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n "
                          "ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relname = 'jobs' "
                          "AND t.tgname = 'jobs_notificar'", (esquema,)).fetchone()
    if not gatilho:
        faltando.append("gatilho jobs_notificar (NOTIFY jfn_jobs)")
    opcoes = con.execute("SELECT c.reloptions FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                         "WHERE n.nspname = %s AND c.relname = 'jobs'", (esquema,)).fetchone()
    if not opcoes or not any(str(o).startswith("autovacuum_vacuum_scale_factor=") for o in (opcoes[0] or [])):
        faltando.append("autovacuum agressivo em jobs")
    versoes = _versoes(con, esquema) if "migracoes" in cols else []
    esperadas = [p.stem for p in migracoes()]
    faltando += [f"migração {v}" for v in esperadas if v not in versoes]
    return {"esquema": esquema, "ok": not faltando, "faltando": faltando, "versoes": versoes}


def conectar_leitura(dsn: str):
    """Sessão em que o próprio servidor recusa escrita (garantia de que `verificar` não altera nada)."""
    import psycopg
    con = psycopg.connect(dsn, autocommit=True)
    con.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    return con


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="schema do motor de fluxo")
    ap.add_argument("acao", choices=("verificar", "aplicar"))
    ap.add_argument("--esquema", default=ESQUEMA_PADRAO)
    a = ap.parse_args(argv)
    dsn = dsn_vigente()
    if not dsn:
        print("sem JFN_EVIDENCIAS_DSN (nem ~/.config/jfn/pg_evidencias.env)", file=sys.stderr)
        return 2
    if a.acao == "verificar":
        con = conectar_leitura(dsn)
        r = verificar(con, a.esquema)
    else:
        import psycopg
        con = psycopg.connect(dsn, autocommit=True)
        r = {"aplicadas": aplicar(con, a.esquema), **verificar(con, a.esquema)}
    con.close()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
