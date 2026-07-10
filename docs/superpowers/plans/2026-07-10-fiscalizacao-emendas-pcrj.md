# Fiscalização Emendas Federais RJ + Gastos/Licitações PCRJ — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coletar emendas parlamentares federais (dois recortes RJ) e despesa/contratos/licitações da Prefeitura do Rio, cruzar favorecidos e seus sócios com doações eleitorais/sanções/folhas, e emitir perícia em PDF padrão Kroll.

**Architecture:** Coletores `httpx` puros (sem browser) gravando tabelas aditivas no `data/compliance.db`; detectores determinísticos em SQL+Python; runners CLI em `tools/`; relatório via `reporting.render_html`. Spec: `docs/superpowers/specs/2026-07-10-fiscalizacao-emendas-pcrj-design.md`.

**Tech Stack:** Python 3.11, httpx, sqlite3 (raw, padrão `pcrj/db.py`), pytest, API Portal da Transparência (chave `PORTAL_TRANSPARENCIA_KEY` já no `.env`), API Câmara, API Transferegov (PostgREST), PNCP consulta v1.

## Global Constraints

- **Empenho ≠ Liquidação ≠ Pago** — nunca somar nem apresentar empenhado como pago; colunas sempre separadas.
- **INDISPONÍVEL ≠ 0** — falha de fonte retorna `{"verificado": False, "motivo": ...}` (padrão `collectors/ceis.py`), nunca "limpo"/zero silencioso.
- **Indício ≠ acusação** — todo texto de alerta usa "indício de", cita fonte e escala de risco 0–10 explícita.
- **CPF sempre mascarado** na saída (`***123456**` estilo Portal); CNPJ pode ser pleno.
- **VM 2 vCPU** — nada de browser; rate ≤ 60 req/min no Portal da Transparência (limite 90); 1 job pesado por vez; escrita de estado atômica (`tmp` + `os.replace`).
- **Sem billing** — BigQuery `datario` NÃO entra sem aprovação explícita do dono; só fontes HTTP gratuitas.
- Código novo casa com o estilo existente (docstrings PT-BR com "POR QUE", honestidade no retorno, `httpx`).
- Testes: `cd ~/JFN && python -m pytest tests/<arquivo> -v` (pytest já configurado no pyproject).

## File Structure

```
compliance_agent/emendas/__init__.py      (novo, vazio)
compliance_agent/emendas/db.py            (novo — DDL emendas/roster/PIX + conectar())
compliance_agent/emendas/camara.py        (novo — roster 46+ deputados RJ, legislaturas 56/57)
compliance_agent/emendas/coletor.py       (novo — paginação /emendas, filtro 2 recortes, checkpoint)
compliance_agent/emendas/favorecidos.py   (novo — /emendas/documentos/{codigo} → CNPJs)
compliance_agent/emendas/transferegov.py  (novo — planos de ação das emendas PIX, UF=RJ)
compliance_agent/emendas/pericia.py       (novo — detectores 1–6)
compliance_agent/pcrj/gastos_db.py        (novo — DDL pcrj_despesa/pcrj_contratos/pcrj_licitacoes)
compliance_agent/pcrj/contasrio.py        (novo — inventário+download+parse CSVs ContasRio)
compliance_agent/pcrj/pericia_gastos.py   (novo — detectores 7–10)
compliance_agent/collectors/pncp.py       (modificar — coleta municipal Rio via codigoMunicipioIbge)
tools/emendas_coletar.py                  (novo — runner CLI de coleta)
tools/emendas_pericia.py                  (novo — runner perícia+PDF emendas)
tools/pcrj_gastos_coletar.py              (novo — runner ContasRio+PNCP municipal)
tools/pcrj_pericia_gastos.py              (novo — runner perícia+PDF PCRJ)
tests/test_emendas_db.py, tests/test_emendas_coletor.py, tests/test_emendas_favorecidos.py,
tests/test_emendas_transferegov.py, tests/test_pericia_emendas.py,
tests/test_pncp_pcrj.py, tests/test_contasrio.py, tests/test_pericia_gastos.py
```

Interfaces externas já existentes (usar, não recriar):
- `compliance_agent/pcrj/db.py::conectar()` — modelo do helper sqlite (WAL, timeout 30).
- `compliance_agent/reporting/render_html.py::render_html(ctx: dict) -> str` e `async html_to_pdf(html: str, destino: str) -> str`.
- `compliance_agent/notifications/telegram.py::enviar_mensagem`, `enviar_arquivo` (async).
- Tabelas locais: `sancoes_federais(cadastro, cpf_cnpj, nome, categoria, data_inicio, data_fim, orgao, uf, processo, fundamentacao)`; `doacoes_eleitorais(cpf_cnpj_doador, nome_doador, nome_candidato, cargo_candidato, partido, uf, valor, data_doacao, ano_eleicao)`; `socios_receita(cnpj_basico, ident, nome_socio, nome_norm, doc_socio, qualificacao_cod, qualificacao_txt, data_entrada, faixa_etaria, fonte_mes)`; `empresas_min(cnpj_basico, razao_social, natureza_cod, fonte_mes)`.
- `tools/baixar_receita_dump.sh` + `tools/socios_dump_sweep.py` — dump/carga QSA da Receita.
- `compliance_agent/pcrj/resolvedor_municipio.py` — nome→código IBGE.

---

### Task 1: Schema — `emendas/db.py` e `pcrj/gastos_db.py`

**Files:**
- Create: `compliance_agent/emendas/__init__.py` (vazio), `compliance_agent/emendas/db.py`, `compliance_agent/pcrj/gastos_db.py`
- Test: `tests/test_emendas_db.py`

**Interfaces:**
- Produces: `emendas.db.conectar(db_path=None) -> sqlite3.Connection` (default `data/compliance.db`, WAL, `row_factory=sqlite3.Row`); `emendas.db.init_schema(con) -> None`; `pcrj.gastos_db.init_schema(con) -> None`. Todas as DDL `CREATE TABLE IF NOT EXISTS` — aditivo, roda N vezes sem erro.

- [ ] **Step 1: Teste falhando**

```python
# tests/test_emendas_db.py
import sqlite3
from compliance_agent.emendas import db as edb
from compliance_agent.pcrj import gastos_db

TABELAS_EMENDAS = {"emendas", "emenda_favorecidos", "emendas_pix_planos", "deputados_federais_rj"}
TABELAS_PCRJ = {"pcrj_despesa", "pcrj_contratos", "pcrj_licitacoes"}

def _tabelas(con):
    return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}

def test_init_schema_cria_tabelas_e_e_idempotente(tmp_path):
    con = edb.conectar(tmp_path / "t.db")
    edb.init_schema(con); edb.init_schema(con)          # idempotente
    gastos_db.init_schema(con); gastos_db.init_schema(con)
    t = _tabelas(con)
    assert TABELAS_EMENDAS <= t and TABELAS_PCRJ <= t

def test_emendas_upsert_por_codigo(tmp_path):
    con = edb.conectar(tmp_path / "t.db"); edb.init_schema(con)
    row = dict(codigo="202544110010", ano=2025, autor_raw="LUCIANO VIEIRA",
               autor_norm="LUCIANO VIEIRA", tipo="Emenda Individual - Transferências com Finalidade Definida",
               e_pix=0, funcao="Saúde", subfuncao="Assistência hospitalar e ambulatorial",
               localidade_gasto="DUAS BARRAS - RJ", uf_destino="RJ", municipio_destino_ibge="3301603",
               empenhado=41161.0, liquidado=41161.0, pago=41161.0,
               resto_inscrito=0.0, resto_cancelado=0.0, resto_pago=0.0,
               recorte="DESTINO_RJ", fonte="portal_transparencia")
    edb.upsert_emenda(con, row); row["pago"] = 0.0; edb.upsert_emenda(con, row)
    got = con.execute("select count(*), max(pago) from emendas").fetchone()
    assert got[0] == 1 and got[1] == 0.0
```

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_emendas_db.py -v` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar**

```python
# compliance_agent/emendas/db.py
# -*- coding: utf-8 -*-
"""Schema das emendas federais no compliance.db (aditivo, espelha pcrj/db.py).

POR QUE tabelas próprias: emenda tem chave natural (codigoEmenda) e valores nas
3 fases (empenhado/liquidado/pago) que NUNCA se somam — regra-mãe do projeto.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
_DB_PADRAO = _REPO / "data" / "compliance.db"

DDL = [
    """CREATE TABLE IF NOT EXISTS deputados_federais_rj (
        id_camara INTEGER PRIMARY KEY, nome TEXT NOT NULL, nome_norm TEXT NOT NULL,
        nome_civil TEXT, partido TEXT, uf TEXT DEFAULT 'RJ',
        legislaturas TEXT, situacao TEXT, coletado_em TEXT DEFAULT (datetime('now')))""",
    "CREATE INDEX IF NOT EXISTS ix_depfed_nome_norm ON deputados_federais_rj(nome_norm)",
    """CREATE TABLE IF NOT EXISTS emendas (
        codigo TEXT PRIMARY KEY, ano INTEGER NOT NULL,
        autor_raw TEXT, autor_norm TEXT, autor_id_camara INTEGER,
        tipo TEXT, e_pix INTEGER DEFAULT 0, funcao TEXT, subfuncao TEXT,
        localidade_gasto TEXT, uf_destino TEXT, municipio_destino_ibge TEXT,
        empenhado REAL, liquidado REAL, pago REAL,
        resto_inscrito REAL, resto_cancelado REAL, resto_pago REAL,
        recorte TEXT, fonte TEXT, coletado_em TEXT DEFAULT (datetime('now')))""",
    "CREATE INDEX IF NOT EXISTS ix_emendas_autor ON emendas(autor_norm)",
    "CREATE INDEX IF NOT EXISTS ix_emendas_uf ON emendas(uf_destino, ano)",
    """CREATE TABLE IF NOT EXISTS emenda_favorecidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo_emenda TEXT NOT NULL REFERENCES emendas(codigo),
        documento_favorecido TEXT, nome_favorecido TEXT,
        fase TEXT, documento_ref TEXT, valor REAL,
        coletado_em TEXT DEFAULT (datetime('now')),
        UNIQUE(codigo_emenda, documento_favorecido, fase, documento_ref))""",
    "CREATE INDEX IF NOT EXISTS ix_emfav_doc ON emenda_favorecidos(documento_favorecido)",
    """CREATE TABLE IF NOT EXISTS emendas_pix_planos (
        id_plano INTEGER PRIMARY KEY, codigo_plano TEXT, ano INTEGER,
        cnpj_beneficiario TEXT, nome_beneficiario TEXT, uf TEXT, municipio TEXT,
        situacao TEXT, valor_custeio REAL, valor_investimento REAL,
        payload_json TEXT, coletado_em TEXT DEFAULT (datetime('now')))""",
]

def conectar(db_path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(db_path) if db_path else _DB_PADRAO
    con = sqlite3.connect(str(p), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con

def init_schema(con: sqlite3.Connection) -> None:
    for ddl in DDL:
        con.execute(ddl)
    con.commit()

_COLS_EMENDA = ("codigo","ano","autor_raw","autor_norm","autor_id_camara","tipo","e_pix",
    "funcao","subfuncao","localidade_gasto","uf_destino","municipio_destino_ibge",
    "empenhado","liquidado","pago","resto_inscrito","resto_cancelado","resto_pago",
    "recorte","fonte")

def upsert_emenda(con: sqlite3.Connection, row: dict) -> None:
    vals = [row.get(c) for c in _COLS_EMENDA]
    sets = ",".join(f"{c}=excluded.{c}" for c in _COLS_EMENDA if c != "codigo")
    con.execute(
        f"INSERT INTO emendas ({','.join(_COLS_EMENDA)}) VALUES ({','.join('?'*len(_COLS_EMENDA))}) "
        f"ON CONFLICT(codigo) DO UPDATE SET {sets}", vals)
```

```python
# compliance_agent/pcrj/gastos_db.py
# -*- coding: utf-8 -*-
"""Schema de gastos/contratos/licitações da PCRJ no compliance.db (aditivo)."""
from __future__ import annotations
import sqlite3

DDL = [
    """CREATE TABLE IF NOT EXISTS pcrj_despesa (
        id INTEGER PRIMARY KEY AUTOINCREMENT, exercicio INTEGER NOT NULL,
        orgao TEXT, unidade TEXT, credor_documento TEXT, credor_nome TEXT,
        natureza TEXT, fonte_recurso TEXT,
        empenhado REAL, liquidado REAL, pago REAL,
        arquivo_origem TEXT, coletado_em TEXT DEFAULT (datetime('now')),
        UNIQUE(exercicio, orgao, credor_documento, natureza, fonte_recurso, arquivo_origem))""",
    "CREATE INDEX IF NOT EXISTS ix_pcrjdesp_credor ON pcrj_despesa(credor_documento)",
    """CREATE TABLE IF NOT EXISTS pcrj_contratos (
        numero_controle_pncp TEXT PRIMARY KEY, ano INTEGER,
        orgao_cnpj TEXT, orgao_nome TEXT, unidade TEXT,
        fornecedor_documento TEXT, fornecedor_nome TEXT, tipo TEXT, objeto TEXT,
        valor_inicial REAL, valor_global REAL, data_assinatura TEXT,
        vigencia_ini TEXT, vigencia_fim TEXT, num_aditivos INTEGER DEFAULT 0,
        fonte TEXT DEFAULT 'pncp', coletado_em TEXT DEFAULT (datetime('now')))""",
    "CREATE INDEX IF NOT EXISTS ix_pcrjcontr_forn ON pcrj_contratos(fornecedor_documento)",
    """CREATE TABLE IF NOT EXISTS pcrj_licitacoes (
        numero_controle_pncp TEXT PRIMARY KEY, ano INTEGER, modalidade TEXT,
        objeto TEXT, valor_estimado REAL, situacao TEXT, data_abertura TEXT,
        orgao_cnpj TEXT, orgao_nome TEXT, amparo TEXT,
        fonte TEXT DEFAULT 'pncp', coletado_em TEXT DEFAULT (datetime('now')))""",
]

def init_schema(con: sqlite3.Connection) -> None:
    for ddl in DDL:
        con.execute(ddl)
    con.commit()
```

- [ ] **Step 4: Rodar e ver passar** — `python -m pytest tests/test_emendas_db.py -v` → 2 PASS.
- [ ] **Step 5: Commit** — `git add compliance_agent/emendas/ compliance_agent/pcrj/gastos_db.py tests/test_emendas_db.py && git commit -m "feat(emendas): schema aditivo emendas/PIX/roster + gastos PCRJ"`

---

### Task 2: Roster — `emendas/camara.py`

**Files:**
- Create: `compliance_agent/emendas/camara.py`
- Test: `tests/test_emendas_camara.py`

**Interfaces:**
- Consumes: `emendas.db.conectar/init_schema`.
- Produces: `listar_deputados_rj(legislaturas=(56, 57)) -> dict` com `{"verificado": bool, "deputados": list[dict], "motivo": str|None}`; `gravar_roster(con, deputados) -> int`; `norm_nome(s) -> str` (maiúsculas, sem acento, espaços únicos — **usada também pelo coletor e perícia**).

- [ ] **Step 1: Teste falhando**

```python
# tests/test_emendas_camara.py
from compliance_agent.emendas import camara
from compliance_agent.emendas import db as edb

def test_norm_nome():
    assert camara.norm_nome("Altineu Côrtes ") == "ALTINEU CORTES"
    assert camara.norm_nome("Chris  Tonietto") == "CHRIS TONIETTO"

def test_gravar_roster_dedup_por_id(tmp_path):
    con = edb.conectar(tmp_path / "t.db"); edb.init_schema(con)
    deps = [{"id": 1, "nome": "Fulano", "siglaPartido": "XX", "idLegislatura": 56},
            {"id": 1, "nome": "Fulano", "siglaPartido": "XX", "idLegislatura": 57}]
    n = camara.gravar_roster(con, deps)
    assert n == 1
    row = con.execute("select legislaturas from deputados_federais_rj where id_camara=1").fetchone()
    assert row[0] == "56,57"
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar**

```python
# compliance_agent/emendas/camara.py
# -*- coding: utf-8 -*-
"""Roster de deputados federais do RJ (API Dados Abertos da Câmara, sem chave).

POR QUE 2 legislaturas: emendas 2019–2026 = legislaturas 56 e 57; ex-deputados
autores de emendas antigas precisam constar para o recorte AUTOR_RJ funcionar.
"""
from __future__ import annotations
import unicodedata
import httpx

API = "https://dadosabertos.camara.leg.br/api/v2"
_TIMEOUT = 30

def norm_nome(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())

def listar_deputados_rj(legislaturas: tuple[int, ...] = (56, 57)) -> dict:
    deputados: dict[int, dict] = {}
    try:
        with httpx.Client(timeout=_TIMEOUT, headers={"accept": "application/json"}) as cli:
            for leg in legislaturas:
                url = f"{API}/deputados?siglaUf=RJ&idLegislatura={leg}&itens=100&ordem=ASC&ordenarPor=nome"
                while url:
                    r = cli.get(url); r.raise_for_status()
                    j = r.json()
                    for d in j["dados"]:
                        d["idLegislatura"] = leg
                        prev = deputados.get(d["id"])
                        if prev:
                            prev["_legs"].add(leg)
                        else:
                            d["_legs"] = {leg}; deputados[d["id"]] = d
                    url = next((l["href"] for l in j.get("links", []) if l["rel"] == "next"), None)
    except Exception as e:  # INDISPONÍVEL ≠ 0
        return {"verificado": False, "deputados": [], "motivo": f"API Câmara: {e}"}
    return {"verificado": True, "deputados": list(deputados.values()), "motivo": None}

def gravar_roster(con, deputados: list[dict]) -> int:
    vistos: dict[int, dict] = {}
    for d in deputados:
        legs = sorted(d.get("_legs") or {d.get("idLegislatura")})
        if d["id"] in vistos:
            legs = sorted(set(vistos[d["id"]]["legs"]) | set(legs))
        vistos[d["id"]] = {"d": d, "legs": legs}
    for v in vistos.values():
        d = v["d"]
        con.execute(
            """INSERT INTO deputados_federais_rj (id_camara, nome, nome_norm, partido, legislaturas)
               VALUES (?,?,?,?,?)
               ON CONFLICT(id_camara) DO UPDATE SET nome=excluded.nome, nome_norm=excluded.nome_norm,
                 partido=excluded.partido, legislaturas=excluded.legislaturas""",
            (d["id"], d["nome"], norm_nome(d["nome"]), d.get("siglaPartido"),
             ",".join(map(str, v["legs"]))))
    con.commit()
    return len(vistos)
```

- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Smoke vivo (1 chamada):** `python -c "from compliance_agent.emendas.camara import listar_deputados_rj; r=listar_deputados_rj(); print(r['verificado'], len(r['deputados']))"` → esperado `True` e **≥ 46** (leg. 56+57 somam mais que os 46 atuais).
- [ ] **Step 6: Commit** — `git commit -m "feat(emendas): roster deputados federais RJ (legislaturas 56/57)"`

---

### Task 3: Coletor de emendas — `emendas/coletor.py` + runner

**Files:**
- Create: `compliance_agent/emendas/coletor.py`, `tools/emendas_coletar.py`
- Test: `tests/test_emendas_coletor.py`

**Interfaces:**
- Consumes: `camara.norm_nome`, `db.upsert_emenda`, `db.conectar/init_schema`.
- Produces: `parse_brl(s) -> float`; `classificar_recorte(emenda: dict, roster_norm: set[str]) -> str|None` (retorna `"AUTOR_RJ"`, `"DESTINO_RJ"`, `"AMBOS"` ou `None`); `coletar_ano(con, ano, chave, pausa=1.0) -> dict` com checkpoint atômico em `data/emendas_checkpoint.json`.

- [ ] **Step 1: Testes falhando**

```python
# tests/test_emendas_coletor.py
from compliance_agent.emendas import coletor

def test_parse_brl():
    assert coletor.parse_brl("41.161,00") == 41161.0
    assert coletor.parse_brl("") == 0.0
    assert coletor.parse_brl(None) == 0.0

ROSTER = {"LUCIANO VIEIRA"}

def _em(autor="X", loc="CUIABÁ - MT"):
    return {"nomeAutor": autor, "localidadeDoGasto": loc}

def test_classificar_recorte():
    assert coletor.classificar_recorte(_em("LUCIANO VIEIRA", "DUAS BARRAS - RJ"), ROSTER) == "AMBOS"
    assert coletor.classificar_recorte(_em("LUCIANO VIEIRA", "CUIABÁ - MT"), ROSTER) == "AUTOR_RJ"
    assert coletor.classificar_recorte(_em("GENERAL GIRAO", "RIO DE JANEIRO (UF)"), ROSTER) == "DESTINO_RJ"
    assert coletor.classificar_recorte(_em("GENERAL GIRAO", "RIO GRANDE DO NORTE (UF)"), ROSTER) is None

def test_e_pix():
    assert coletor.e_pix("Emenda Individual - Transferências Especiais") == 1
    assert coletor.e_pix("Emenda Individual - Transferências com Finalidade Definida") == 0
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar**

```python
# compliance_agent/emendas/coletor.py
# -*- coding: utf-8 -*-
"""Coleta paginada de /api-de-dados/emendas (Portal da Transparência).

POR QUE baixar o ano INTEIRO e filtrar client-side: a API não filtra por UF de
autor nem de destino; o volume (~10k emendas/ano, ~15/página) cabe em ~10 min
a 60 req/min. Checkpoint por (ano, página) permite retomar sem repetir.
"""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path

import httpx

from .camara import norm_nome
from . import db as edb

_BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
_REPO = Path(__file__).resolve().parent.parent.parent
_CKPT = _REPO / "data" / "emendas_checkpoint.json"
_TIMEOUT = 30

def parse_brl(v) -> float:
    if not v:
        return 0.0
    s = re.sub(r"[R$\s]", "", str(v))
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0

def e_pix(tipo: str) -> int:
    return 1 if "especia" in (tipo or "").lower() else 0

def _uf_destino(localidade: str) -> str | None:
    loc = (localidade or "").strip().upper()
    m = re.search(r"-\s*([A-Z]{2})$", loc)           # "DUAS BARRAS - RJ"
    if m:
        return m.group(1)
    if loc.endswith("(UF)"):                          # "RIO DE JANEIRO (UF)"
        return {"RIO DE JANEIRO": "RJ"}.get(loc[:-4].strip(), loc[:-4].strip()[:2])
    return None

def classificar_recorte(emenda: dict, roster_norm: set[str]) -> str | None:
    autor = norm_nome(emenda.get("nomeAutor") or "")
    # autor pode vir com sufixo "(EX-PARLAMENTAR ...)" — compara o prefixo antes do parêntese
    autor_base = autor.split("(")[0].strip()
    autor_rj = autor_base in roster_norm
    destino_rj = _uf_destino(emenda.get("localidadeDoGasto") or "") == "RJ"
    if autor_rj and destino_rj:
        return "AMBOS"
    if autor_rj:
        return "AUTOR_RJ"
    if destino_rj:
        return "DESTINO_RJ"
    return None

def _chave() -> str:
    return (os.environ.get("PORTAL_TRANSPARENCIA_KEY", "")
            or os.environ.get("TRANSPARENCIA_API_KEY", "")).strip()

def _ckpt_load() -> dict:
    try:
        return json.loads(_CKPT.read_text("utf-8"))
    except Exception:
        return {}

def _ckpt_save(d: dict) -> None:
    tmp = _CKPT.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), "utf-8")
    os.replace(tmp, _CKPT)          # escrita atômica — lição rotas-split

def _row_de_api(e: dict, recorte: str) -> dict:
    loc = e.get("localidadeDoGasto") or ""
    return dict(
        codigo=e["codigoEmenda"], ano=int(e["ano"]),
        autor_raw=e.get("nomeAutor"), autor_norm=norm_nome((e.get("nomeAutor") or "").split("(")[0]),
        autor_id_camara=None, tipo=e.get("tipoEmenda"), e_pix=e_pix(e.get("tipoEmenda") or ""),
        funcao=e.get("funcao"), subfuncao=e.get("subfuncao"),
        localidade_gasto=loc, uf_destino=_uf_destino(loc), municipio_destino_ibge=None,
        empenhado=parse_brl(e.get("valorEmpenhado")), liquidado=parse_brl(e.get("valorLiquidado")),
        pago=parse_brl(e.get("valorPago")), resto_inscrito=parse_brl(e.get("valorRestoInscrito")),
        resto_cancelado=parse_brl(e.get("valorRestoCancelado")), resto_pago=parse_brl(e.get("valorRestoPago")),
        recorte=recorte, fonte="portal_transparencia")

def coletar_ano(con, ano: int, chave: str | None = None, pausa: float = 1.0) -> dict:
    """Retorna {"verificado", "paginas", "retidas", "motivo"}. Retoma do checkpoint."""
    chave = chave or _chave()
    if not chave:
        return {"verificado": False, "paginas": 0, "retidas": 0, "motivo": "sem PORTAL_TRANSPARENCIA_KEY"}
    roster = {r[0] for r in con.execute("select nome_norm from deputados_federais_rj")}
    if not roster:
        return {"verificado": False, "paginas": 0, "retidas": 0, "motivo": "roster vazio — rode camara primeiro"}
    ck = _ckpt_load()
    pagina = int(ck.get(str(ano), 0)) + 1
    retidas = 0
    with httpx.Client(timeout=_TIMEOUT, headers={"chave-api-dados": chave}) as cli:
        while True:
            r = cli.get(f"{_BASE}/emendas", params={"ano": ano, "pagina": pagina})
            if r.status_code == 429:                 # rate limit: espera e repete a página
                time.sleep(30); continue
            if r.status_code != 200:
                return {"verificado": False, "paginas": pagina - 1, "retidas": retidas,
                        "motivo": f"HTTP {r.status_code} na página {pagina}"}
            lote = r.json()
            if not lote:
                break
            for e in lote:
                rec = classificar_recorte(e, roster)
                if rec:
                    edb.upsert_emenda(con, _row_de_api(e, rec)); retidas += 1
            con.commit()
            ck[str(ano)] = pagina; _ckpt_save(ck)
            pagina += 1
            time.sleep(pausa)                        # ≤60 req/min
    return {"verificado": True, "paginas": pagina - 1, "retidas": retidas, "motivo": None}
```

```python
# tools/emendas_coletar.py
#!/usr/bin/env python3
"""Runner: roster Câmara + emendas 2019–2026 (retomável).
Uso: python tools/emendas_coletar.py [--anos 2019 2020 ...] [--pausa 1.0]"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from compliance_agent.emendas import db as edb, camara, coletor

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anos", nargs="*", type=int, default=list(range(2019, 2027)))
    ap.add_argument("--pausa", type=float, default=1.0)
    args = ap.parse_args()
    con = edb.conectar(); edb.init_schema(con)
    r = camara.listar_deputados_rj()
    if not r["verificado"]:
        print(f"INDISPONÍVEL: {r['motivo']}"); sys.exit(2)
    print(f"roster: {camara.gravar_roster(con, r['deputados'])} deputados")
    for ano in args.anos:
        res = coletor.coletar_ano(con, ano, pausa=args.pausa)
        print(f"{ano}: {res}")
        if not res["verificado"]:
            sys.exit(2)     # supervisor/cron pode reexecutar — checkpoint retoma

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar testes e ver passar.**
- [ ] **Step 5: Validação viva mínima (1 ano):** `python tools/emendas_coletar.py --anos 2025` → esperado `verificado True`, `retidas > 0`. Conferir 1 deputado contra a consulta pública: `select autor_raw, sum(empenhado), sum(pago) from emendas where ano=2025 and autor_norm='<DEPUTADO>' ` vs. https://portaldatransparencia.gov.br/emendas/consulta — mesmos valores (critério de aceite nº 2).
- [ ] **Step 6: Commit** — `git commit -m "feat(emendas): coletor paginado com 2 recortes RJ e checkpoint atômico"`

---

### Task 4: Favorecidos — `emendas/favorecidos.py`

**Files:**
- Create: `compliance_agent/emendas/favorecidos.py`
- Test: `tests/test_emendas_favorecidos.py` + fixture `tests/fixtures/emenda_documentos.json`

**Interfaces:**
- Consumes: `db.conectar`, tabela `emendas`.
- Produces: `coletar_favorecidos(con, chave=None, pausa=1.0, max_emendas=None) -> dict` — para cada emenda sem favorecidos coletados, GET `/emendas/documentos/{codigo}` paginado e insere em `emenda_favorecidos`.

- [ ] **Step 1: Capturar fixture real** (campo exatos do payload variam da doc — capturar antes de codar o parser):

```bash
KEY=$(grep '^PORTAL_TRANSPARENCIA_KEY=' ~/JFN/.env | cut -d= -f2)
COD=$(sqlite3 ~/JFN/data/compliance.db "select codigo from emendas where pago>0 limit 1")
curl -sS -H "chave-api-dados: $KEY" \
  "https://api.portaldatransparencia.gov.br/api-de-dados/emendas/documentos/$COD?pagina=1" \
  | python3 -m json.tool | tee tests/fixtures/emenda_documentos.json | head -40
```

Anotar no fixture os nomes reais dos campos de favorecido (esperados: `favorecido`/`codigoFavorecido` ou `nomeFavorecido`/`cnpjCpfFavorecido`, `fase`, `documento`, `valor`). **Se o endpoint retornar 404/vazio para todas**, registrar INDISPONÍVEL e usar fallback: endpoint `/despesas/documentos-relacionados` por código de empenho — decisão documentada no commit.

- [ ] **Step 2: Teste falhando** (parser sobre a fixture):

```python
# tests/test_emendas_favorecidos.py
import json
from pathlib import Path
from compliance_agent.emendas import favorecidos

FIX = json.loads((Path(__file__).parent / "fixtures" / "emenda_documentos.json").read_text())

def test_parse_documentos_extrai_favorecido():
    rows = favorecidos.parse_documentos("202544110010", FIX)
    assert rows and rows[0]["codigo_emenda"] == "202544110010"
    assert rows[0]["documento_favorecido"] and rows[0]["nome_favorecido"]
```

- [ ] **Step 3: Implementar** — `parse_documentos(codigo, payload) -> list[dict]` mapeando os campos reais da fixture (ajustar nomes conforme capturado; CPF de pessoa física → mascarar com `re.sub(r"^\d{3}", "***", doc)` quando len==11) e:

```python
# topo do módulo: reusa infra do coletor — não duplicar
import time
import httpx
from .coletor import _BASE, _chave, parse_brl

def coletar_favorecidos(con, chave=None, pausa=1.0, max_emendas=None) -> dict:
    chave = chave or _chave()
    if not chave:
        return {"verificado": False, "motivo": "sem chave", "emendas": 0, "favorecidos": 0}
    pend = [r[0] for r in con.execute(
        """select e.codigo from emendas e
           left join emenda_favorecidos f on f.codigo_emenda = e.codigo
           where f.id is null and (e.pago > 0 or e.empenhado > 0)
           order by e.pago desc""").fetchall()]
    if max_emendas:
        pend = pend[:max_emendas]
    tot = 0
    with httpx.Client(timeout=30, headers={"chave-api-dados": chave}) as cli:
        for cod in pend:
            pagina = 1
            while True:
                r = cli.get(f"{_BASE}/emendas/documentos/{cod}", params={"pagina": pagina})
                if r.status_code == 429:
                    time.sleep(30); continue
                if r.status_code != 200 or not r.json():
                    break
                for row in parse_documentos(cod, r.json()):
                    con.execute("""INSERT OR IGNORE INTO emenda_favorecidos
                        (codigo_emenda, documento_favorecido, nome_favorecido, fase, documento_ref, valor)
                        VALUES (:codigo_emenda,:documento_favorecido,:nome_favorecido,:fase,:documento_ref,:valor)""", row)
                    tot += 1
                con.commit(); pagina += 1; time.sleep(pausa)
    return {"verificado": True, "emendas": len(pend), "favorecidos": tot, "motivo": None}
```

- [ ] **Step 4: Testes passam; validação viva com `max_emendas=5`** → critério de aceite nº 4 (≥80% com CNPJ válido de 14 dígitos).
- [ ] **Step 5: Commit** — `git commit -m "feat(emendas): favorecidos por documento de empenho (CNPJ final)"`

---

### Task 5: Emendas PIX — `emendas/transferegov.py`

**Files:**
- Create: `compliance_agent/emendas/transferegov.py`
- Test: `tests/test_emendas_transferegov.py`

**Interfaces:**
- Produces: `coletar_planos_rj(con, pausa=0.5) -> dict` — pagina PostgREST `https://api.transferegov.gestao.gov.br/transferenciasespeciais/plano_acao_especial?uf_beneficiario_plano_acao=eq.RJ&limit=500&offset=N` até vazio; upsert em `emendas_pix_planos` (id_plano = `id_plano_acao`; payload integral em `payload_json` para não perder campos).

- [ ] **Step 1: Teste falhando** — `parse_plano(item) -> dict` com o item real já capturado na sondagem (id_plano_acao=22296, MUNICIPIO DE RIO BONITO, situação IMPEDIDO — colar como fixture inline no teste):

```python
def test_parse_plano():
    item = {"id_plano_acao": 22296, "codigo_plano_acao": "09032022-3-022296",
            "ano_plano_acao": 2022, "situacao_plano_acao": "IMPEDIDO",
            "cnpj_beneficiario_plano_acao": "28741072000109",
            "nome_beneficiario_plano_acao": "MUNICIPIO DE RIO BONITO",
            "uf_beneficiario_plano_acao": "RJ"}
    row = transferegov.parse_plano(item)
    assert row["id_plano"] == 22296 and row["situacao"] == "IMPEDIDO" and row["uf"] == "RJ"
```

- [ ] **Step 2–4: Implementar (httpx, sem chave, retorno honesto), testes passam, validação viva** — `select situacao, count(*) from emendas_pix_planos group by 1` deve mostrar distribuição plausível e ≥1 linha (critério de aceite nº 3).
- [ ] **Step 5: Commit** — `git commit -m "feat(emendas): planos de ação das emendas PIX (Transferegov) UF=RJ"`

---

### Task 6: PNCP municipal — modificar `collectors/pncp.py` + runner PCRJ

**Files:**
- Modify: `compliance_agent/collectors/pncp.py` (após `ORGAOS_RJ`, ~linha 50)
- Create: `tools/pcrj_gastos_coletar.py` (parte PNCP; ContasRio entra na Task 7)
- Test: `tests/test_pncp_pcrj.py`

**Interfaces:**
- Consumes: `_get_consulta(endpoint, params)` existente; `pcrj.gastos_db.init_schema`.
- Produces: em `pncp.py`: `MUNICIPIO_RIO_IBGE = "3304557"`, `CNPJ_PCRJ = "42498733000148"`, `async coletar_contratos_pcrj(data_ini: str, data_fim: str) -> dict` (datas `AAAAMMDD`; pagina `/contratos?cnpjOrgao=...`), `async coletar_contratacoes_municipio_rio(data_ini, data_fim, modalidades=MODALIDADES_PADRAO) -> dict` (usa `/contratacoes/publicacao` com `uf=RJ&codigoMunicipioIbge=3304557` — descobre TODOS os órgãos municipais, inclusive empresas públicas, sem lista manual de CNPJs). Ambos retornam `{"verificado", "itens", "motivo"}`.
- Gravação: função `gravar_contratos(con, itens)` / `gravar_licitacoes(con, itens)` no runner mapeando para `pcrj_contratos`/`pcrj_licitacoes` (campos vistos no payload real: `numeroControlePncpCompra`→PK, `niFornecedor`, `orgaoEntidade.cnpj/razaoSocial`, `tipoContrato.nome`, `dataAssinatura`, `dataVigenciaInicio/Fim`).

- [ ] **Step 1: Teste falhando** — `_simplificar_contrato_pcrj(payload_real) -> dict` com o contrato real capturado na sondagem (2024NE000921, fornecedor 18809570000354) como fixture inline.
- [ ] **Step 2: Implementar; atenção `tamanhoPagina` mínimo = 10** (400 abaixo disso — verificado ao vivo).
- [ ] **Step 3: Validação viva:** coletar 2025-S1 → `select count(*) from pcrj_contratos` > 0 e `select distinct orgao_cnpj from pcrj_contratos` ⊇ {42498733000148} (critério de aceite nº 6).
- [ ] **Step 4: Commit** — `git commit -m "feat(pncp): coleta municipal Rio (contratos + contratações por código IBGE)"`

---

### Task 7: ContasRio — inventário + parser de despesa por credor

**Files:**
- Create: `compliance_agent/pcrj/contasrio.py`, `tools/contasrio_descobrir.py`
- Test: `tests/test_contasrio.py`

**Interfaces:**
- Produces: `descobrir_arquivos() -> dict` (`{"verificado", "arquivos": [{tema, url, rotulo}], "motivo"}`); `carregar_csv(con, caminho, exercicio, tema) -> int`; `parse_valor_ptbr(s) -> float` (reusa `coletor.parse_brl` — importar, não duplicar).

**Contexto para quem implementa (descoberto na pesquisa de 2026-07-10):** as páginas-tema (`/web/contasrio/liquidacao-orcamentario`, `/despesa-por-orgao`, `/contratos-por-favorecido`, etc.) são Liferay; os arquivos ficam na document library (`/web/arquivogeral`). O HTML estático das páginas NÃO expõe os links diretos — eles vêm de portlet. Estratégia em ordem: (1) requisitar a página-tema e seguir o link `arquivogeral` da mesma sessão (cookie `JSESSIONID`), parseando a listagem de pastas/arquivos; (2) se a listagem exigir JS, tentar a API de document library do Liferay (`/api/jsonws/dlapp/get-file-entries` costuma estar aberta em portais Liferay 6/7); (3) esgotadas 1–2, registrar INDISPONÍVEL, abrir chamado LAI/e-SIC e propor ao dono o fallback BigQuery `datario` (precisa aprovação — billing). **Vaadin do app FINCON está fora de cogitação.**

- [ ] **Step 1: Escrever `tools/contasrio_descobrir.py`** — script exploratório que executa as estratégias 1–2 e grava inventário em `data/contasrio_inventario.json` (escrita atômica). Critério verificável: inventário com ≥1 arquivo de "liquidação orçamentária" e ≥1 de "contratos por favorecido" para exercício ≥2024. Saída no terminal: tabela tema × nº de arquivos.
- [ ] **Step 2: Baixar 1 arquivo de liquidação e commitar amostra de 50 linhas** em `tests/fixtures/contasrio_liquidacao_amostra.csv` (dado público; amostra pequena para não inchar o repo).
- [ ] **Step 3: Teste falhando** — `carregar_csv` sobre a fixture: nº de linhas inseridas == linhas do CSV − cabeçalho; soma de `liquidado` > 0; encoding correto (arquivos da CGM costumam ser `latin-1`; detectar com fallback `utf-8-sig` → `latin-1`).
- [ ] **Step 4: Implementar parser** — mapear colunas do CSV real para `pcrj_despesa` (órgão, credor CNPJ/CPF-mascarado, natureza, valores por fase). Sanity por agregado: `sum(empenhado) >= sum(liquidado) >= sum(pago)` no exercício — se violar, logar e NÃO abortar (restos a pagar de exercícios anteriores quebram a desigualdade legitimamente; anotar no docstring).
- [ ] **Step 5: Testes passam; carga viva do exercício 2025** → critério de aceite nº 5.
- [ ] **Step 6: Commit** — `git commit -m "feat(pcrj): despesa por credor via dados abertos ContasRio (inventário + carga)"`

---

### Task 8: Ampliar QSA local (operacional — pré-requisito do cruzamento)

**Files:** nenhum código novo — usar `tools/baixar_receita_dump.sh socios` + `tools/socios_dump_sweep.py` existentes.

- [ ] **Step 1:** conferir espaço (`df -h /` — dump Socios ≈ 4–5 GB zipado) e load antes de iniciar; rodar `bash tools/baixar_receita_dump.sh socios` em background fora de horário de sweep (o script já tem guarda de load/RAM).
- [ ] **Step 2:** carregar com `python tools/socios_dump_sweep.py` (ler `--help` antes; é o loader que populou os 27k atuais).
- [ ] **Step 3: Verificação:** `select count(*) from socios_receita` deve saltar de ~27k para ordem de 10⁷ (dump nacional completo) — OU, se o dono preferir não gastar disco, carga PARCIAL é aceitável com esta regra: todo favorecido/credor novo dispara consulta on-demand ao `minhareceita.org` (grátis) e gravação em `socios_receita` com `fonte_mes='minhareceita'`. Decisão registrada no commit/vault.
- [ ] **Step 4:** anotar contagem final no vault (`aprendizados/` — cobertura QSA).

---

### Task 9: Perícia de emendas — `emendas/pericia.py` (detectores 1–6)

**Files:**
- Create: `compliance_agent/emendas/pericia.py`
- Test: `tests/test_pericia_emendas.py`

**Interfaces:**
- Consumes: tabelas `emendas`, `emenda_favorecidos`, `emendas_pix_planos`, `sancoes_federais(cpf_cnpj, cadastro, categoria, orgao)`, `socios_receita(cnpj_basico, nome_norm, doc_socio)`, `doacoes_eleitorais(cpf_cnpj_doador, nome_doador, nome_candidato, valor, ano_eleicao)`, `camara.norm_nome`.
- Produces: `rodar_todas(con) -> list[dict]` — cada achado: `{"detector": str, "risco": int(0-10), "titulo": str, "descricao": str, "evidencias": dict, "codigo_emenda": str|None}`. Funções individuais: `d1_pix_impedida`, `d2_concentracao_autor`, `d3_favorecido_sancionado`, `d4_favorecido_fantasma`, `d5_retroalimentacao_eleitoral`, `d6_empenho_sem_pagamento`.

- [ ] **Step 1: Testes falhando** — DB temporário semeado; um teste por detector. Exemplos dos três centrais:

```python
# tests/test_pericia_emendas.py (trecho — semear com edb.init_schema + inserts diretos)
def test_d3_favorecido_sancionado(con_semeado):
    con = con_semeado
    con.execute("insert into emenda_favorecidos (codigo_emenda, documento_favorecido, nome_favorecido, fase, valor) values ('E1','11222333000181','ACME LTDA','pagamento',100000)")
    con.execute("insert into sancoes_federais (cadastro, cpf_cnpj, nome, categoria, orgao) values ('CEIS','11222333000181','ACME LTDA','Inidoneidade','CGU')")
    achados = pericia.d3_favorecido_sancionado(con)
    assert len(achados) == 1 and achados[0]["risco"] >= 8

def test_d5_retroalimentacao_eleitoral(con_semeado):
    con = con_semeado
    # autor da emenda recebeu doação de sócio (match por CPF = forte)
    con.execute("insert into emendas (codigo, ano, autor_raw, autor_norm, recorte) values ('E2',2024,'Dep Fulano','DEP FULANO','AUTOR_RJ')")
    con.execute("insert into emenda_favorecidos (codigo_emenda, documento_favorecido, nome_favorecido) values ('E2','11222333000181','ACME LTDA')")
    con.execute("insert into socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio) values ('11222333','JOAO DA SILVA','JOAO DA SILVA','***456789**')")
    con.execute("insert into doacoes_eleitorais (cpf_cnpj_doador, nome_doador, nome_candidato, valor, ano_eleicao) values ('***456789**','JOAO DA SILVA','DEP FULANO',50000,2022)")
    achados = pericia.d5_retroalimentacao_eleitoral(con)
    assert len(achados) == 1
    assert "indício" in achados[0]["descricao"].lower()

def test_d6_empenho_sem_pagamento(con_semeado):
    con = con_semeado
    con.execute("""insert into emendas (codigo, ano, autor_norm, empenhado, pago, resto_cancelado, recorte)
                   values ('E3',2023,'DEP X',1000000,0,900000,'DESTINO_RJ')""")
    achados = pericia.d6_empenho_sem_pagamento(con)
    assert achados and "empenhado" in achados[0]["descricao"] and "pago" in achados[0]["descricao"]
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.** Consultas de referência (ajustar limiares no topo do módulo, com comentário do porquê):

```python
# D3 — join direto por documento (14 dígitos) e por cnpj_basico (8) p/ filiais:
SQL_D3 = """
select f.codigo_emenda, f.documento_favorecido, f.nome_favorecido, f.valor,
       s.cadastro, s.categoria, s.orgao
from emenda_favorecidos f
join sancoes_federais s
  on s.cpf_cnpj = f.documento_favorecido
  or (length(f.documento_favorecido) = 14 and substr(s.cpf_cnpj,1,8) = substr(f.documento_favorecido,1,8))
"""
# D5 — sócio do favorecido doou para o autor. Match A (CPF-mascarado igual) risco 8;
#      match B (só nome_norm) risco 4 com aviso de homônimo (regra de honestidade).
SQL_D5 = """
select e.codigo, e.autor_norm, f.documento_favorecido, f.nome_favorecido,
       s.nome_norm as socio, d.valor as doacao, d.ano_eleicao,
       case when d.cpf_cnpj_doador = s.doc_socio and s.doc_socio != '' then 'CPF' else 'NOME' end as match_tipo
from emendas e
join emenda_favorecidos f on f.codigo_emenda = e.codigo
join socios_receita s on s.cnpj_basico = substr(f.documento_favorecido,1,8)
join doacoes_eleitorais d
  on d.nome_candidato = e.autor_norm
 and (d.cpf_cnpj_doador = s.doc_socio or upper(d.nome_doador) = s.nome_norm)
"""
# D2 — concentração: % da carteira do autor num único município (janela = carteira toda)
SQL_D2 = """
select autor_norm, localidade_gasto, sum(empenhado) as v,
       sum(sum(empenhado)) over (partition by autor_norm) as total
from emendas where autor_norm != '' group by 1, 2
"""
# D1: emendas_pix_planos.situacao in ('IMPEDIDO', ...) ou e_pix=1 sem plano correspondente (join por cnpj+ano).
# D4: reusar os 8 sinais — import do módulo /fantasma existente sobre empresas_min/minhareceita.
# D6: empenhado > 0 and pago = 0 and (resto_cancelado / empenhado) > 0.5 → risco proporcional.
```

Texto de todo achado: `"Indício de <X>: … (fonte: <API/tabela>, coletado em <data>). Empenhado R$ A; liquidado R$ B; pago R$ C."` — valores com separador de milhar e 2 casas (`f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")`).

- [ ] **Step 4: Testes passam.** `rodar_todas` também insere em `alertas` (tipo=`emendas_<detector>`, severidade=risco, evidencias=JSON).
- [ ] **Step 5: Commit** — `git commit -m "feat(emendas): perícia determinística — 6 detectores com escala de risco"`

---

### Task 10: Perícia PCRJ — `pcrj/pericia_gastos.py` (detectores 7–10)

**Files:**
- Create: `compliance_agent/pcrj/pericia_gastos.py`
- Test: `tests/test_pericia_gastos.py`

**Interfaces:**
- Consumes: `pcrj_despesa`, `pcrj_contratos`, `pcrj_licitacoes`, `socios_receita`, `empresas_min`, folha PCRJ (`pcrj/db.py`), `minhareceita` on-demand.
- Produces: `rodar_todas(con) -> list[dict]` (mesmo formato da Task 9): `d7_fracionamento` (≥3 dispensas/empenhos < teto Lei 14.133 art. 75 — R$ 62.725,68 compras 2026, constante nomeada no topo — mesmo credor+órgão em 90 dias), `d8_credor_recem_aberto` (data_entrada do CNPJ < 180 dias antes do 1º contrato — via minhareceita `data_inicio_atividade`), `d9_socio_na_folha` (QSA × folha PCRJ por nome_norm = indício, nunca afirmação — homônimo), `d10_rede_concorrentes` (mesmo `cnpj_basico`-sócio em ≥2 fornecedores contratados pelo mesmo órgão no ano; + aditivos: `num_aditivos` com valor_global > 1.25 × valor_inicial).

- [ ] **Step 1: Testes falhando** — semear temp DB, um teste por detector, asserts sobre risco e texto honesto. Exemplo do d7 (os demais seguem a mesma forma, cada um semeando seu cenário mínimo):

```python
# tests/test_pericia_gastos.py (trecho)
def test_d7_fracionamento(con_semeado):
    con = con_semeado
    for i in range(3):   # 3 empenhos abaixo do teto p/ mesmo credor+órgão em 90 dias
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       fornecedor_documento, fornecedor_nome, tipo, valor_global, data_assinatura)
                       values (?,2025,'42498733000148','11222333000181','ACME','Empenho',50000,?)""",
                    (f"C{i}", f"2025-03-{10+i:02d}"))
    achados = pericia_gastos.d7_fracionamento(con)
    assert len(achados) == 1 and achados[0]["risco"] >= 6
    assert "indício" in achados[0]["descricao"].lower()
```
- [ ] **Step 2: Implementar; Step 3: testes passam; Step 4: rodar sobre dados vivos e revisar 5 achados manualmente (anti-falso-positivo antes do relatório).**
- [ ] **Step 5: Commit** — `git commit -m "feat(pcrj): perícia de gastos — fracionamento, credor novo, sócio na folha, rede"`

---

### Task 11: Relatórios PDF + runners de perícia

**Files:**
- Create: `tools/emendas_pericia.py`, `tools/pcrj_pericia_gastos.py`

**Interfaces:**
- Consumes: `emendas.pericia.rodar_todas`, `pcrj.pericia_gastos.rodar_todas`, `reporting.render_html.render_html(ctx) -> str`, `async html_to_pdf(html, destino)`, `notifications.telegram.enviar_arquivo`.
- Produces: `reports/emendas_rj_<data>.pdf` e `reports/pcrj_gastos_<data>.pdf` + XLSX de apoio.

- [ ] **Step 1:** ler `reporting/render_html.py:80` para o formato exato do `ctx` (seções/tabelas) e 1 relatório recente (`reports/pericia_camara_2026-07-06.html`) como gabarito visual.
- [ ] **Step 2:** montar `ctx`: capa (título, data, escopo, fontes com data de coleta), sumário executivo (nº de achados por risco), 1 seção por detector com tabela (valores milhar+2 casas, CPFs mascarados), seção de metodologia (recortes, INDISPONÍVEL≠0, indício≠acusação, escala 0–10), rodapé com referências normativas (art. 166/166-A CF, Lei 14.133 arts. 75/94/125, LC 131/2009).
- [ ] **Step 3:** gerar PDF vivo; abrir e revisar esteticamente (padrão Kroll — regra absoluta nº 1 do CLAUDE.md).
- [ ] **Step 4:** flag `--telegram` envia via `enviar_arquivo`; achado risco ≥ 8 vira nota `~/vault/casos/<slug>.md` (formato dos casos existentes: frontmatter status/risco + evidências + próximos passos).
- [ ] **Step 5: Commit** — `git commit -m "feat(fiscalizacao): relatórios PDF Kroll emendas RJ + gastos PCRJ"`

---

### Task 12: Registro e encerramento

- [ ] **Step 1:** registrar os 4 runners novos em `capabilities.yaml` (padrão das entradas existentes) para o Hermes/telegram enxergar.
- [ ] **Step 2:** atualizar `~/vault` — nota nova `aprendizados/fontes-emendas-pcrj.md` (fontes, limites de rate, decisões: Vaadin descartado, BigQuery pendente de aprovação, AGPL do br-acc → reimplementar) + link no MOC de Pesquisa; caso aberto se a perícia viva gerar risco ≥ 8.
- [ ] **Step 3:** rodar suíte inteira `python -m pytest tests/ -k "emendas or contasrio or pncp_pcrj or pericia" -v` → tudo PASS.
- [ ] **Step 4:** commit final + push (`git push`) — trabalho relevante sempre commitado antes de encerrar (regra §5).

---

## Cobertura do spec (self-review)

| Requisito do spec | Task |
|---|---|
| Roster 46 deputados (aceite 1) | 2 |
| Emendas 2019–2026, 2 recortes, conferência com Portal (aceite 2) | 3 |
| PIX × Transferegov (aceite 3) | 5 |
| Favorecidos CNPJ ≥80% + sanções (aceite 4) | 4, 9 |
| `pcrj_despesa` 2025 + sanity (aceite 5) | 7 |
| PNCP municipal (aceite 6) | 6 |
| Detectores 1–10 + PDF (aceite 7) | 9, 10, 11 |
| Cruzamento sócios (br-acc) | 8, 9 (D5), 10 (D9/D10) |
| Camada 2 (doweb, TCM, CEAP, painel, PGFN/CEPIM/CEAF, BigQuery) | fora deste plano — anotada na Task 12 |
