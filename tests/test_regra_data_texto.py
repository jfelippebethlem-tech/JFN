# -*- coding: utf-8 -*-
"""Catraca O4.3 (Esteira Única, 24/11/2026): data do SIAFE em TEXTO 'DD/MM/AAAA' não se ordena crua.

`ORDER BY`/`MIN`/`MAX`/`<`/`>`/`BETWEEN` sobre o texto comparam o DIA primeiro: '31/12/2025' > '02/01/2026'.
Medido no snapshot de 24/11: `MAX(data_emissao)` de `ob_orcamentaria_siafe` devolve '31/12/2025'; a última OB
de verdade é de 23/11/2026. Remédio: `<col>_iso` (coluna gerada + índice, revisão `0002_datas_iso`) ou
`datas_iso.expr_iso(col)` nas tabelas pequenas sem a coluna.

Aqui também: paridade da expressão congelada da migração × `datas_iso`, ensaio em miniatura de
upgrade/downgrade, e paridade de cada consumidor trocado (a ordem certa, não só "não quebra").
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sqlite3
from pathlib import Path

import pytest

from compliance_agent.database import datas_iso, migrar, models

RAIZ = Path(__file__).resolve().parents[1]
REVISAO = migrar.PASTA_ALEMBIC / "versions" / "0002_datas_iso.py"

# Colunas texto 'DD/MM/AAAA' medidas no snapshot ~/snapshot-20261124/compliance.db (100% no formato).
COLUNAS_TEXTO = {
    "ob_orcamentaria_siafe": ("data_emissao",), "ne_siafe": ("data_emissao",), "nl_siafe": ("data_emissao",),
    "gd_siafe": ("data_emissao",), "ob_retencao_siafe": ("data_emissao",), "ob_status_recoleta": ("data_emissao",),
    "bloqueio_judicial_siafe": ("data_bloqueio", "data_desbloqueio"), "siga_contratos": ("data",),
    "doerj_tac": ("data_assinatura",), "siga_pca_itens": ("data_desejada",), "siga_sancoes": ("data_efetivacao",),
}
PASTAS = ("compliance_agent", "tools", "rotas")
ARQUIVOS_SOLTOS = ("server.py",)

# Exceções justificadas (caminho relativo → motivo). Crescer esta lista pede motivo escrito.
EXCECOES = {
    "tools/_arquivo/": "arquivo morto (relatório ITERJ×MGS 2021 já entregue); não roda em cron nem rota",
}

_PALAVRAS_SQL = {"where", "on", "join", "left", "inner", "group", "order", "limit", "using", "cross",
                 "natural", "union", "set", "values", "select"}


def _strings(arvore):
    for n in ast.walk(arvore):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.lineno, n.value
        elif isinstance(n, ast.JoinedStr):
            yield n.lineno, "".join(v.value if isinstance(v, ast.Constant) else "{X}" for v in n.values)


def _termos_order_by(baixo: str):
    """Termos de cada ORDER BY (vírgula de nível zero), sem ASC/DESC/NULLS; para no LIMIT/`)` que fecha."""
    for m in re.finditer(r"\border\s+by\b", baixo):
        prof, atual, i = 0, "", m.end()
        while i < len(baixo):
            ch = baixo[i]
            if ch == "(":
                prof += 1
            elif ch == ")":
                if prof == 0:
                    break
                prof -= 1
            elif prof == 0 and (ch in ";" or re.match(r"\b(?:limit|offset|union|window)\b", baixo[i:])):
                break
            if ch == "," and prof == 0:
                yield _limpar_termo(atual)
                atual = ""
            else:
                atual += ch
            i += 1
        yield _limpar_termo(atual)


def _limpar_termo(termo: str) -> str:
    return re.sub(r"\s+(?:asc|desc)?\s*(?:nulls\s+(?:first|last))?\s*$", "", termo.strip()).strip()


def violacoes_sql(sql: str) -> list[str]:
    """Usos crus (ORDER BY / MIN / MAX / comparação) das colunas texto num trecho SQL. Sensível ao alias."""
    baixo = sql.lower()
    tabelas = [t for t in COLUNAS_TEXTO if re.search(rf"\b{t}\b", baixo)]
    if not tabelas:
        return []
    alias = {}
    for m in re.finditer(r"\b(?:from|join)\s+([a-z_0-9]+)(?:\s+(?:as\s+)?([a-z_][a-z_0-9]*))?", baixo):
        alias[m.group(1)] = m.group(1)
        if m.group(2) and m.group(2) not in _PALAVRAS_SQL:
            alias[m.group(2)] = m.group(1)
    achados = []
    termos = list(_termos_order_by(baixo))
    for t in tabelas:
        ref = r"(?:\b([a-z_][a-z_0-9]*)\.)?\b(?:" + "|".join(COLUNAS_TEXTO[t]) + r")\b"
        for termo in termos:                       # termo do ORDER BY que É a coluna crua (não uma expressão)
            m = re.fullmatch(ref, termo)
            if m and (not m.group(1) or alias.get(m.group(1)) == t):
                achados.append(f"{t}: ORDER BY {termo!r}")
        padroes = (r"\b(?:min|max)\s*\(\s*" + ref + r"\s*\)",
                   ref + r"\s*(?:<=|>=|<|>|\bbetween\b)",
                   r"(?:<=|>=|<|>)\s*" + ref)
        for p in padroes:
            for m in re.finditer(p, baixo):
                q = m.group(1)
                if q and alias.get(q) != t:          # coluna de OUTRA tabela da mesma consulta (ex.: TFE, já Date)
                    continue
                achados.append(f"{t}: {m.group(0)[:80]!r}")
    return achados


def _varrer():
    alvos = [p for d in PASTAS for p in (RAIZ / d).rglob("*.py")] + [RAIZ / f for f in ARQUIVOS_SOLTOS]
    out = []
    for p in alvos:
        rel = p.relative_to(RAIZ).as_posix()
        if not p.exists() or any(rel.startswith(e) for e in EXCECOES):
            continue
        try:
            arvore = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for ln, s in _strings(arvore):
            out += [f"{rel}:{ln}: {v}" for v in violacoes_sql(s)]
    return out


# ── catraca ─────────────────────────────────────────────────────────────────────────────────────

def test_nenhum_order_by_min_max_ou_comparacao_sobre_data_texto_crua():
    achados = _varrer()
    assert not achados, ("data 'DD/MM/AAAA' ordenada/comparada crua — use `<col>_iso` (ob/ne/nl_siafe) ou "
                         "`datas_iso.expr_iso(col)`:\n" + "\n".join(achados))


@pytest.mark.parametrize("sql", [
    "SELECT MAX(data_emissao) FROM ob_orcamentaria_siafe",
    "SELECT processo, max(data_emissao) ultima FROM ob_orcamentaria_siafe GROUP BY processo",
    "SELECT * FROM ob_orcamentaria_siafe s WHERE credor=? ORDER BY s.data_emissao DESC LIMIT 1",
    "SELECT numero FROM nl_siafe WHERE data_emissao >= ?",
    "SELECT 1 FROM ne_siafe WHERE data_emissao BETWEEN ? AND ?",
    "SELECT nome FROM siga_sancoes WHERE doc=? ORDER BY status='Vigente' DESC, data_efetivacao DESC",
])
def test_controle_positivo_a_catraca_ve_o_uso_cru(sql):
    assert violacoes_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT MAX(data_emissao_iso) FROM ob_orcamentaria_siafe",
    "SELECT * FROM ob_orcamentaria_siafe s ORDER BY s.data_emissao_iso DESC",
    f"SELECT 1 FROM siga_sancoes ORDER BY {datas_iso.expr_iso('data_efetivacao')} DESC",
    # alias de OUTRA tabela (ordens_bancarias = TFE, já é Date no ORM)
    "SELECT s.valor, (SELECT t.ug_nome FROM ordens_bancarias t ORDER BY t.data_emissao DESC LIMIT 1) "
    "FROM ob_orcamentaria_siafe s WHERE s.credor=?",
    "SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE data_emissao=?",           # igualdade não ordena
    "SELECT MAX(data_emissao) FROM ordens_bancarias",                            # tabela fora da lista
])
def test_controle_negativo_a_catraca_nao_acusa_o_que_esta_certo(sql):
    assert violacoes_sql(sql) == []


# ── a expressão congelada da migração não diverge da viva ─────────────────────────────────────────

def _revisao():
    spec = importlib.util.spec_from_file_location("rev_0002", REVISAO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migracao_e_datas_iso_tem_a_mesma_expressao_e_as_mesmas_tabelas():
    rev = _revisao()
    assert rev.COLUNAS == datas_iso.COLUNAS_ISO
    for col in set(rev.COLUNAS.values()):
        assert rev._expr(col) == datas_iso.expr_iso(col)
    assert rev.down_revision == migrar.REVISAO_BASE and migrar.head() == rev.revision


def test_expressao_ordena_certo_e_texto_fora_do_formato_vira_null():
    con = sqlite3.connect(":memory:")
    e = datas_iso.expr_iso("d")
    vals = {d: con.execute(f"SELECT {e} FROM (SELECT ? AS d)", (d,)).fetchone()[0]
            for d in ("02/01/2026", "31/12/2025", "2025-12-31", "", "1/2/2026", "32/13/2025x")}
    assert vals["02/01/2026"] == "2026-01-02" and vals["31/12/2025"] == "2025-12-31"
    assert vals["02/01/2026"] > vals["31/12/2025"] and "02/01/2026" < "31/12/2025"   # o texto cru erra
    assert vals["2025-12-31"] is None and vals[""] is None and vals["1/2/2026"] is None
    assert vals["32/13/2025x"] is None


# ── ensaio em miniatura: upgrade / downgrade ─────────────────────────────────────────────────────

def _banco_antigo_com_siafe(db):
    models.Base.metadata.create_all(models.get_engine(db))
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE _alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
    con.executemany("INSERT INTO _alembic_version VALUES (?)", [(v,) for v in sorted(migrar.LEGADO_ESPERADO)])
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, "
                "valor REAL, exercicio INTEGER, PRIMARY KEY (numero_ob, ug_emitente, exercicio))")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?)",
                    [("2025OB1", "1", "31/12/2025", 10.0, 2025), ("2026OB1", "1", "02/01/2026", 20.0, 2026),
                     ("2026OB2", "1", "lixo", 30.0, 2026)])
    con.execute("CREATE TABLE ne_siafe (numero TEXT, data_emissao TEXT)")       # nl_siafe ausente: pulada
    con.commit()
    con.close()


def _xcols(con, t):
    return {r[1] for r in con.execute(f"PRAGMA table_xinfo({t})")}


def test_upgrade_cria_coluna_e_indice_e_downgrade_devolve_o_schema(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command

    db = tmp_path / "vivo.db"
    _banco_antigo_com_siafe(db)
    migrar.carimbar(db)
    assert migrar.atualizar(db)["ok"]
    con = sqlite3.connect(db)
    assert "data_emissao_iso" in _xcols(con, "ob_orcamentaria_siafe") and "data_emissao_iso" in _xcols(con, "ne_siafe")
    assert "data_emissao_iso" not in {r[1] for r in con.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}
    assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='nl_siafe'").fetchone()
    plano = " ".join(str(r) for r in con.execute(
        "EXPLAIN QUERY PLAN SELECT MAX(data_emissao_iso) FROM ob_orcamentaria_siafe"))
    assert "ix_ob_orcamentaria_siafe_data_emissao_iso" in plano
    assert con.execute("SELECT MAX(data_emissao_iso), MAX(data_emissao) FROM ob_orcamentaria_siafe").fetchone() \
        == ("2026-01-02", "lixo")
    assert con.execute("SELECT numero_ob FROM ob_orcamentaria_siafe WHERE data_emissao_iso IS NULL").fetchall() \
        == [("2026OB2",)]
    # INSERT sem lista de colunas segue valendo (a coluna gerada não entra na contagem)
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('2026OB3','1','15/03/2026',1.0,2026)")
    con.commit()
    con.close()

    with models.get_engine(db).begin() as c:
        command.downgrade(migrar._config(c), migrar.REVISAO_BASE)
    con = sqlite3.connect(db)
    assert "data_emissao_iso" not in _xcols(con, "ob_orcamentaria_siafe")
    assert not con.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'ix_%_data_emissao_iso'").fetchone()
    assert con.execute("SELECT COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe").fetchone() == (4, 61.0)
    con.close()
    assert migrar.atualizar(db)["ok"]                                    # e sobe de novo


def test_ddl_dos_coletores_ja_nasce_com_a_coluna_gerada():
    from compliance_agent import siafe_documento

    con = sqlite3.connect(":memory:")
    for tipo in ("NE", "NL"):
        con.execute(siafe_documento.TIPOS[tipo]["ddl"])
        assert "data_emissao_iso" in _xcols(con, siafe_documento.TIPOS[tipo]["tabela"])
    fonte = (RAIZ / "compliance_agent" / "siafe_ob_orcamentaria.py").read_text(encoding="utf-8")
    # as duas DDLs (criação e reconstrução da PK) levam a coluna — reconstruir sem ela apagaria a coluna
    assert fonte.count('coluna_gerada("data_emissao")') == 2


# ── paridade dos consumidores trocados ────────────────────────────────────────────────────────────

def test_acervo_ultima_ob_do_processo_e_a_mais_recente_de_verdade(tmp_path, monkeypatch):
    from compliance_agent import acervo

    db = tmp_path / "compliance.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob, ug_emitente, credor, nome_credor, data_emissao, "
                f"processo, valor, status, {datas_iso.coluna_gerada('data_emissao')})")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?)", [
        ("2025OB9", "080001", "10497795000149", "F", "31/12/2025", "SEI-080001/000633/2024", 1.0, "Contabilizado"),
        ("2026OB1", "080001", "10497795000149", "F", "02/01/2026", "SEI-080001/000633/2024", 2.0, "Contabilizado")])
    con.commit()
    con.close()
    monkeypatch.setattr(acervo, "DB_COMPLIANCE", db)
    for nome in ("DB_ACHADOS", "DB_PCRJ", "DB_LAI", "DB_SEI_RJ"):
        monkeypatch.setattr(acervo, nome, tmp_path / "nao_existe.db")
    hits = [h for h in acervo.buscar("10.497.795/0001-49")["hits"] if "siafe_ob" in (h.get("fonte") or "")]
    assert hits and hits[0]["data"] == "2026-01-02"                      # texto cru daria '31/12/2025'


def _siga_sancoes(con):
    con.execute("CREATE TABLE siga_sancoes (nome, enquadramento, data_efetivacao, orgao_apenador, status, doc)")
    con.executemany("INSERT INTO siga_sancoes VALUES (?,?,?,?,?,?)", [
        ("X", "ART. 87, INC. III", "31/12/2025", "SEEDUC", "Vigente", "10497795000149"),
        ("X", "ART. 87, INC. III", "02/01/2026", "SES", "Vigente", "10497795000149"),
        ("X", "advertência", "05/05/2026", "SEFAZ", "Encerrada", "10497795000149")])


def test_lex_sancoes_siga_vigente_mais_recente_primeiro(tmp_path, monkeypatch):
    from compliance_agent import lex_conflito

    db = tmp_path / "compliance.db"
    con = sqlite3.connect(db)
    _siga_sancoes(con)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (credor, valor, data_emissao, status)")
    con.commit()
    con.close()
    monkeypatch.setattr(lex_conflito, "_resolver_db", lambda *a, **k: db)
    datas = [s["desde"] for s in lex_conflito.sancoes_siga("10497795000149")]
    assert datas == ["02/01/2026", "31/12/2025", "05/05/2026"]           # vigentes primeiro, data real decrescente


def test_doerj_tac_sancao_siga_mais_recente_primeiro():
    import sys
    sys.path.insert(0, str(RAIZ / "tools"))
    import doerj_tac_favorecimento as dtf

    con = sqlite3.connect(":memory:")
    _siga_sancoes(con)
    con.execute("CREATE TABLE doerj_tac (fornecedor, objeto, valor, orgao)")
    sinal = next(s for s in dtf.sinais_de(con, "10497795000149", "EMPRESA X LTDA", 1, 1.0, {})
                 if s["sinal"] == "sancao_siga")
    assert [d for _, d, _ in sinal["evidencia"]["sancoes"]] == ["02/01/2026", "31/12/2025"]
