# Enxame de Contratos "Tribunal de Contas" — Plano de Implementação (Spec 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emitir parecer técnico estilo Tribunal de Contas por contrato da PCRJ, compondo detectores X + Lex + preços de mercado + sinais cruzados num dossiê compartilhado, deliberado por um enxame com memória e auto-melhoria.

**Architecture:** Dossiê compartilhado (barramento anti-monólito) que cada "pensamento" lê/escreve; funil determinístico (t_aditivo/prorrogação/execução/sobrepreço/Lex/sinais) → câmara LLM free-tier só nos candidatos (com RAG+memória) → parecer TC (relatório/fundamentação/conclusão/voto) → feedback em memoria_aprendizado. Reusa o enxame-núcleo do Spec 1.

**Tech Stack:** Python 3.12, httpx, sqlite3 (padrão `editais/db.py`), PNCP termos (api/pncp/v1), Painel de Preços (dadosabertos.compras.gov.br), reuso de `lex_indicadores_fraude`, `hermes_rag`, `enxame/*`, `emendas.pericia`/`pcrj.pericia_gastos`. Spec: `docs/superpowers/specs/2026-07-11-enxame-contratos-tribunal-design.md`.

## Global Constraints
- **Indício ≠ acusação**; **presunção de legitimidade**; **ausente ≠ 0**; **empenho ≠ liquidação ≠ pago**; proveniência por número; CPF mascarado.
- **LLM só free-tier** (`direcionamento_cerebro.gerar_sync`); funil determinístico ANTES da câmara.
- **VM 2 vCPU**: 1 job pesado por vez; `coleta_lock` na coleta de termos; cache de preço 30d; escrita atômica.
- **Painel best-effort**: item sem CATMAT confiável → sobrepreço só no peer, declarado (nunca inventa referência).
- **Aditivo art. 125**: >25% de acréscimo de VALOR (50% só reforma — ver `objetoTermoContrato`); aditivo só de prazo ≠ acréscimo de valor.
- Testes: `cd ~/JFN && .venv/bin/python -m pytest tests/<arquivo> -q`. Teste REAL nos pontos marcados.

## File Structure
```
compliance_agent/contratos/__init__.py         (novo)
compliance_agent/contratos/db.py                (schema: contrato_aditivo, contrato_dossie, contrato_parecer, preco_referencia_cache)
compliance_agent/contratos/dossie.py            (montar_dossie — o barramento)
compliance_agent/contratos/thoughts.py          (t_aditivo/t_prorrogacao/t_execucao_financeira/t_sobrepreco/t_lex/t_sinais_cruzados)
compliance_agent/contratos/parecer.py           (deliberar + render_parecer_ctx + gravar_e_aprender)
compliance_agent/collectors/precos.py           (Painel de Preços: catmat_por_descricao + preco_referencia + cache)
compliance_agent/collectors/pncp.py             (MOD: termos_contrato)
compliance_agent/enxame/memoria.py              (contexto_memoria + registrar_veredito — reusável)
compliance_agent/enxame/lentes.py               (MOD: lentes recebem rag_ctx/memoria_ctx)
tools/contratos_parecer.py                      (runner E2E)
tests/test_contratos_db.py, test_precos.py, test_pncp_termos.py, test_contratos_dossie.py,
tests/test_contratos_thoughts.py, test_enxame_memoria.py, test_contratos_parecer.py
tests/fixtures/contratos/pncp_termos.json, painel_preco.json  (já capturados ao vivo)
```
Interfaces existentes (usar, não recriar):
- `pncp._parse_id_pncp(id)`, `pncp.PNCP_BASE` (=api/pncp/v1), `pncp.buscar_itens`.
- `lex_indicadores_fraude.triagem(sinais: dict) -> {n_indicadores,score_risco,faixa,indicadores,tipologias}`; `sinais_do_contexto(ctx) -> dict` (chaves: concentracao_alta, contratacao_direta, edital_restritivo, fracionamento, coincidencia_participantes, desconto_atipico…).
- `hermes_rag.consultar(pergunta, k=6) -> list[dict]`.
- `enxame.orquestrador.avaliar(dossie, gerar=None) -> {score_final, veredito, votos}`; `enxame.lentes.LENTES`.
- `editais.db.conectar` (reexport de emendas.db); `reporting.render_html.render_html/gerar_pdf`.
- `emendas.pericia`/`pcrj.pericia_gastos` p/ sinais do fornecedor.

---

### Task 1: Schema — `contratos/db.py`
**Files:** Create `compliance_agent/contratos/__init__.py` (vazio), `compliance_agent/contratos/db.py`; Test `tests/test_contratos_db.py`
**Interfaces:** Produces `conectar` (reexport emendas.db), `init_schema(con)`.

- [ ] **Step 1: Teste falhando**
```python
# tests/test_contratos_db.py
from compliance_agent.contratos import db as cd
TABS = {"contrato_aditivo", "contrato_dossie", "contrato_parecer", "preco_referencia_cache"}
def test_init_schema_idempotente(tmp_path):
    con = cd.conectar(tmp_path / "t.db"); cd.init_schema(con); cd.init_schema(con)
    got = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert TABS <= got
```
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar**
```python
# compliance_agent/contratos/db.py
# -*- coding: utf-8 -*-
"""Schema do enxame de contratos no compliance.db (aditivo)."""
from __future__ import annotations
import sqlite3
from compliance_agent.emendas.db import conectar
__all__ = ["conectar", "init_schema", "DDL"]
DDL = [
    """CREATE TABLE IF NOT EXISTS contrato_aditivo (
        id INTEGER PRIMARY KEY AUTOINCREMENT, numero_controle_pncp TEXT NOT NULL,
        sequencial_termo INTEGER, numero_termo TEXT, objeto TEXT,
        valor_acrescido REAL, valor_global REAL, prazo_aditado_dias INTEGER,
        vigencia_fim TEXT, qualif_acrescimo TEXT, qualif_vigencia TEXT, qualif_reajuste TEXT,
        fundamento_legal TEXT, coletado_em TEXT DEFAULT (datetime('now')),
        UNIQUE(numero_controle_pncp, sequencial_termo))""",
    "CREATE INDEX IF NOT EXISTS ix_adit_ctrl ON contrato_aditivo(numero_controle_pncp)",
    """CREATE TABLE IF NOT EXISTS contrato_dossie (
        numero_controle_pncp TEXT PRIMARY KEY, dossie_json TEXT,
        montado_em TEXT DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS contrato_parecer (
        id INTEGER PRIMARY KEY AUTOINCREMENT, numero_controle_pncp TEXT,
        conclusao TEXT, score INTEGER, dimensoes_json TEXT, parecer_json TEXT,
        emitido_em TEXT DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS preco_referencia_cache (
        catmat TEXT PRIMARY KEY, mediana REAL, n INTEGER, minimo REAL, maximo REAL,
        atualizado_em TEXT DEFAULT (datetime('now')))""",
]
def init_schema(con: sqlite3.Connection) -> None:
    for ddl in DDL:
        con.execute(ddl)
    con.commit()
```
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git add compliance_agent/contratos/ tests/test_contratos_db.py && git commit -m "feat(contratos): schema (aditivo/dossie/parecer/preco_cache)"`

---

### Task 2: PNCP termos aditivos — MOD `collectors/pncp.py`
**Files:** Modify `compliance_agent/collectors/pncp.py`; Test `tests/test_pncp_termos.py` (fixture `pncp_termos.json` já capturado)
**Interfaces:** Produces `_parse_termo(t: dict) -> dict`; `async termos_contrato(cnpj, ano, seq) -> list[dict]` (204→[]); `async coletar_aditivos(con, numero_controle_pncp) -> int`.

- [ ] **Step 1: Teste falhando**
```python
# tests/test_pncp_termos.py
import json; from pathlib import Path
from compliance_agent.collectors import pncp
FIX = json.loads((Path(__file__).parent/"fixtures"/"contratos"/"pncp_termos.json").read_text())
def test_parse_termo():
    row = pncp._parse_termo(FIX[0])
    assert row["valor_acrescido"] == 37313280.0
    assert "prorroga" in (row["objeto"] or "").lower()
    assert row["vigencia_fim"] == "2028-03-31"
```
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** (adicionar ao fim de pncp.py):
```python
def _parse_termo(t: dict) -> dict:
    return {
        "sequencial_termo": t.get("sequencialTermoContrato"),
        "numero_termo": t.get("numeroTermoContrato"),
        "objeto": t.get("objetoTermoContrato"),
        "valor_acrescido": t.get("valorAcrescido"),
        "valor_global": t.get("valorGlobal"),
        "prazo_aditado_dias": t.get("prazoAditadoDias"),
        "vigencia_fim": t.get("dataVigenciaFim"),
        "qualif_acrescimo": t.get("qualificacaoAcrescimoSupressao"),
        "qualif_vigencia": t.get("qualificacaoVigencia"),
        "qualif_reajuste": t.get("qualificacaoReajuste"),
        "fundamento_legal": t.get("fundamentoLegal"),
    }

async def termos_contrato(cnpj: str, ano: int, seq: int) -> list[dict]:
    """Termos aditivos de um contrato (api/pncp/v1; 200=lista, 204=sem termos)."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{PNCP_BASE}/orgaos/{cnpj}/contratos/{ano}/{seq}/termos",
                            headers={"User-Agent": "JFN-Compliance/2.0"})
            if r.status_code == 204:
                return []
            if r.status_code != 200:
                return []
            return [_parse_termo(t) for t in (r.json() or [])]
    except Exception:
        return []

async def coletar_aditivos(con, numero_controle_pncp: str) -> int:
    """numero_controle_pncp = 'CNPJ-2-SEQ/ANO'. Grava em contrato_aditivo. Idempotente."""
    pr = _parse_id_pncp(numero_controle_pncp)
    if not pr:
        return 0
    cnpj, ano, seq = pr
    termos = await termos_contrato(cnpj, ano, seq)
    for row in termos:
        con.execute(
            """INSERT OR IGNORE INTO contrato_aditivo (numero_controle_pncp, sequencial_termo,
                 numero_termo, objeto, valor_acrescido, valor_global, prazo_aditado_dias,
                 vigencia_fim, qualif_acrescimo, qualif_vigencia, qualif_reajuste, fundamento_legal)
               VALUES (:ncp,:sequencial_termo,:numero_termo,:objeto,:valor_acrescido,:valor_global,
                 :prazo_aditado_dias,:vigencia_fim,:qualif_acrescimo,:qualif_vigencia,:qualif_reajuste,:fundamento_legal)""",
            {**row, "ncp": numero_controle_pncp})
    con.commit()
    return len(termos)
```
Nota: `_parse_id_pncp` devolve `(cnpj, ano, seq)` onde seq é o sequencial do controle — **conferir na impl.** que casa com o `sequencialContrato` do termos (o teste vivo do Step 4 valida; se divergir, resolver o seq via `buscar_contratos_pcrj` que traz `sequencialContrato`).
- [ ] **Step 4: Testes passam; TESTE REAL:** `python -c "import asyncio; from compliance_agent.contratos import db as cd; from compliance_agent.collectors import pncp; con=cd.conectar(); cd.init_schema(con); print(asyncio.run(pncp.coletar_aditivos(con,'42498733000148-2-000004/2024')))"` → ≥1 aditivo; valorAcrescido confere com o PNCP (critério nº 1).
- [ ] **Step 5: Commit** — `git commit -m "feat(pncp): termos aditivos (api/pncp/v1) → contrato_aditivo"`

---

### Task 3: Painel de Preços — `collectors/precos.py`
**Files:** Create `compliance_agent/collectors/precos.py`; Test `tests/test_precos.py` (fixture `painel_preco.json`)
**Interfaces:** Produces `_norm(s)->str`; `catmat_por_descricao(desc: str, limite=5) -> list[dict]` ({codigo,nome,score}); `async preco_referencia(catmat: str, con=None) -> dict` ({disponivel,mediana,n,minimo,maximo}, cache 30d); `_mediana_precos(payload: dict) -> dict`.

- [ ] **Step 1: Teste falhando** (parser do preço, offline):
```python
# tests/test_precos.py
import json; from pathlib import Path
from compliance_agent.collectors import precos
FIX = json.loads((Path(__file__).parent/"fixtures"/"contratos"/"painel_preco.json").read_text())
def test_mediana_precos():
    r = precos._mediana_precos(FIX)
    assert r["disponivel"] is True and r["n"] >= 1 and r["mediana"] > 0
```
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar**
```python
# compliance_agent/collectors/precos.py
# -*- coding: utf-8 -*-
"""Âncora de mercado — Painel de Preços via API pública de dados abertos.

O front paineldeprecos.planejamento.gov.br dá 403 (WAF); o acesso público é
dadosabertos.compras.gov.br. Cadeia: descrição → PDM (nomePdm) → classe →
item (CATMAT) → preço unitário. Cache 30d por CATMAT (preco_referencia_cache).
Degrada honesto: sem CATMAT confiável → {disponivel: False} (nunca inventa preço).
"""
from __future__ import annotations
import statistics, unicodedata
import httpx

BASE = "https://dadosabertos.compras.gov.br"
_UA = {"User-Agent": "JFN-Compliance/2.0"}
_TIMEOUT = 30

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())

def _get(path: str, params: dict) -> dict | None:
    try:
        r = httpx.get(f"{BASE}{path}", params=params, headers=_UA, timeout=_TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None

def catmat_por_descricao(desc: str, limite: int = 5) -> list[dict]:
    """PDM por palavra-chave → classe → itens (CATMAT). Ranqueia por overlap de tokens."""
    kw = _norm(desc).split()
    if not kw:
        return []
    pdm = _get("/modulo-material/3_consultarPdmMaterial",
               {"pagina": 1, "tamanhoPagina": 10, "nomePdm": kw[0]})
    classes = {p.get("codigoClasse") for p in (pdm or {}).get("resultado", []) if p.get("codigoClasse")}
    itens = []
    for cl in list(classes)[:2]:
        it = _get("/modulo-material/4_consultarItemMaterial",
                  {"pagina": 1, "tamanhoPagina": 50, "codigoClasse": cl})
        for x in (it or {}).get("resultado", []):
            d = _norm(x.get("descricaoItem") or "")
            score = sum(1 for t in kw if t in d)
            if score:
                itens.append({"codigo": str(x.get("codigoItem")), "nome": x.get("descricaoItem"), "score": score})
    itens.sort(key=lambda i: -i["score"])
    return itens[:limite]

def _mediana_precos(payload: dict) -> dict:
    precos = [x.get("precoUnitario") for x in (payload or {}).get("resultado", []) if x.get("precoUnitario")]
    if not precos:
        return {"disponivel": False, "n": 0}
    return {"disponivel": True, "n": len(precos), "mediana": statistics.median(precos),
            "minimo": min(precos), "maximo": max(precos)}

async def preco_referencia(catmat: str, con=None) -> dict:
    if con is not None:
        row = con.execute("select mediana,n,minimo,maximo, julianday('now')-julianday(atualizado_em) "
                          "from preco_referencia_cache where catmat=?", (catmat,)).fetchone()
        if row and row[4] is not None and row[4] < 30:
            return {"disponivel": True, "mediana": row[0], "n": row[1], "minimo": row[2], "maximo": row[3]}
    payload = _get("/modulo-pesquisa-preco/1_consultarMaterial",
                   {"pagina": 1, "tamanhoPagina": 50, "codigoItemCatalogo": catmat})
    r = _mediana_precos(payload or {})
    if con is not None and r.get("disponivel"):
        con.execute("""INSERT INTO preco_referencia_cache (catmat, mediana, n, minimo, maximo, atualizado_em)
                       VALUES (?,?,?,?,?, datetime('now'))
                       ON CONFLICT(catmat) DO UPDATE SET mediana=excluded.mediana, n=excluded.n,
                         minimo=excluded.minimo, maximo=excluded.maximo, atualizado_em=datetime('now')""",
                    (catmat, r["mediana"], r["n"], r["minimo"], r["maximo"]))
        con.commit()
    return r
```
- [ ] **Step 4: Testes passam; TESTE REAL:** `python -c "import asyncio; from compliance_agent.collectors import precos; print(precos.catmat_por_descricao('parafuso encadernacao latao')); print(asyncio.run(precos.preco_referencia('200333')))"` → CATMAT resolvido + preço (critério nº 3).
- [ ] **Step 5: Commit** — `git commit -m "feat(precos): âncora Painel de Preços (compras.gov.br) descrição→CATMAT→preço, cache 30d"`

---

### Task 4: Dossiê compartilhado — `contratos/dossie.py`
**Files:** Create `compliance_agent/contratos/dossie.py`; Test `tests/test_contratos_dossie.py`
**Interfaces:** Consumes `contrato_aditivo`, `pcrj_contratos`, `pcrj_despesa`, `pncp.buscar_itens`, sinais. Produces `montar_dossie(con, numero_controle_pncp, com_rede=True) -> dict` com chaves: `contrato, aditivos, pagamentos, itens, sinais_fornecedor, proveniencia`.

- [ ] **Step 1: Teste falhando** (montagem a partir do DB semeado, sem rede — itens injetáveis):
```python
# tests/test_contratos_dossie.py
from compliance_agent.contratos import db as cd, dossie
def _seed(con):
    cd.init_schema(con)
    con.execute("""create table if not exists pcrj_contratos (numero_controle_pncp text primary key,
        ano int, orgao_cnpj text, orgao_nome text, fornecedor_documento text, fornecedor_nome text,
        tipo text, objeto text, valor_inicial real, valor_global real, data_assinatura text,
        vigencia_ini text, vigencia_fim text, num_aditivos int, fonte text, numero_compra text)""")
    con.execute("""create table if not exists pcrj_despesa (id integer primary key, exercicio int,
        orgao text, credor_documento text, credor_nome text, natureza text, fonte_recurso text,
        empenhado real, liquidado real, pago real, arquivo_origem text)""")
    con.execute("insert into pcrj_contratos (numero_controle_pncp, fornecedor_documento, objeto, valor_inicial, valor_global) values ('C1','11222333000181','obra X',100000,100000)")
    con.execute("insert into contrato_aditivo (numero_controle_pncp, sequencial_termo, valor_acrescido) values ('C1',1,40000)")
    con.commit()
def test_montar_dossie(tmp_path):
    con = cd.conectar(tmp_path/"t.db"); _seed(con)
    d = dossie.montar_dossie(con, "C1", com_rede=False, itens_fn=lambda nc: [])
    assert d["contrato"]["valor_inicial"] == 100000
    assert d["aditivos"][0]["valor_acrescido"] == 40000
    assert "proveniencia" in d
```
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** — `montar_dossie` lê `pcrj_contratos` (contrato), `contrato_aditivo` (aditivos), `pcrj_despesa` por `credor_documento=fornecedor_documento` (pagamentos: soma empenhado/liquidado/pago), `itens_fn(nc)` (default `lambda nc: asyncio.run(pncp.buscar_itens(nc))`), e sinais do fornecedor (reuso: consultas diretas a `sancoes_federais`/`emenda_favorecidos`/`rede_socios_fornecedores` como em `editais_direcionamento._sinais_vencedor`, guardadas por _tem_tabela). `proveniencia` = dict `{campo: fonte}`. Retorna o dict.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git commit -m "feat(contratos): dossiê compartilhado (contrato+aditivos+pagamentos+itens+sinais)"`

---

### Task 5: Pensamentos determinísticos — `contratos/thoughts.py`
**Files:** Create `compliance_agent/contratos/thoughts.py`; Test `tests/test_contratos_thoughts.py`
**Interfaces:** Produces `t_aditivo(d)->list`, `t_prorrogacao(d)->list`, `t_execucao_financeira(d)->list`, `t_sobrepreco(d, ref_fn=None)->list`, `t_lex(d)->list`, `t_sinais_cruzados(d)->list`, `rodar_thoughts(d, ref_fn=None)->list`. Achado: `{dimensao, risco, texto, norma, proveniencia}`.

- [ ] **Step 1: Testes falhando** (um por thought):
```python
# tests/test_contratos_thoughts.py
from compliance_agent.contratos import thoughts as T
def test_t_aditivo_valor_dispara():
    d = {"contrato": {"valor_inicial": 100000, "objeto": "serviço de limpeza"},
         "aditivos": [{"valor_acrescido": 40000, "objeto": "acréscimo de 40%", "qualif_vigencia": None}]}
    a = T.t_aditivo(d)
    assert a and a[0]["risco"] >= 6 and "125" in a[0]["norma"]
def test_t_aditivo_so_prazo_nao_dispara():
    d = {"contrato": {"valor_inicial": 100000, "objeto": "x"},
         "aditivos": [{"valor_acrescido": 0, "objeto": "prorrogação de prazo", "qualif_vigencia": "Sim"}]}
    assert T.t_aditivo(d) == []
def test_t_execucao_pago_acima():
    d = {"contrato": {"valor_global": 100000}, "pagamentos": {"pago": 150000, "empenhado": 150000, "liquidado": 150000}}
    a = T.t_execucao_financeira(d)
    assert a and a[0]["risco"] >= 6
def test_t_sobrepreco_peer(monkeypatch):
    d = {"itens": [{"descricao": "caneta azul", "unidade": "un", "valor_unitario": 30.0}],
         "contrato": {}}
    a = T.t_sobrepreco(d, ref_fn=lambda desc: {"disponivel": True, "mediana": 10.0, "n": 5})
    assert a and a[0]["risco"] >= 6 and "3" in str(a[0]["proveniencia"].get("ratio", ""))[:1] or a[0]["risco"] >= 6
```
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** — limiares nomeados no topo: `ADITIVO_LIMITE=0.25`, `ADITIVO_REFORMA=0.50`, `SOBREPRECO_RATIO=1.3`, `PRORROGACAO_MIN_EXERC=3`.
  - `t_aditivo`: soma `valor_acrescido` dos aditivos; ratio = soma/valor_inicial; se ratio > 0.25 (ou 0.50 quando `objeto`/reforma) → achado risco `min(9, 5+int(ratio*4))`, norma "Lei 14.133/2021 art. 125". Aditivo com `valor_acrescido` 0 e `qualif_vigencia` = só prazo → ignora.
  - `t_prorrogacao`: usa `d["contrato"]` + eventual `d.get("historico_exercicios")`; se ≥ PRORROGACAO_MIN_EXERC → achado (art. 106/107). (No dossiê simples, marca `nao_avaliavel` se sem histórico.)
  - `t_execucao_financeira`: `pago > valor_global` → achado risco 7 (texto com empenhado/liquidado/pago separados, art. 63); pago==0 com contrato vigente → informativo.
  - `t_sobrepreco`: para cada item, `ref = ref_fn(descricao)` (default liga peer+Painel na impl.); se `valor_unitario > ratio*ref["mediana"]` → achado risco `min(9,5+int(valor_unitario/ref["mediana"]))`, proveniencia inclui `ratio`. Sem ref disponível → não marca (ausente ≠ 0).
  - `t_lex`: `triagem(sinais_do_contexto(_ctx_lex(d)))`; se faixa ≠ 🟢 → achado risco por score, dimensão "lex". (`_ctx_lex` mapeia o dossiê p/ o ctx que `sinais_do_contexto` espera.)
  - `t_sinais_cruzados`: lê `d["sinais_fornecedor"]`; cada sinal presente → achado dimensão "beneficiario" risco 6-8.
  - `rodar_thoughts`: concatena todos, ordena por risco.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git commit -m "feat(contratos): 6 pensamentos determinísticos (aditivo/prorrogação/execução/sobrepreço/Lex/sinais)"`

---

### Task 6: Memória — `enxame/memoria.py`
**Files:** Create `compliance_agent/enxame/memoria.py`; Test `tests/test_enxame_memoria.py`
**Interfaces:** Produces `registrar_veredito(con, categoria, chave, veredito, score)`; `contexto_memoria(con, categoria, chave) -> str`.

- [ ] **Step 1: Teste falhando**
```python
# tests/test_enxame_memoria.py
from compliance_agent.editais import db as ed
from compliance_agent.enxame import memoria
def _seed(con):
    con.execute("""create table if not exists memoria_aprendizado (id integer primary key,
        categoria text, chave text, valor text, confianca real, n_observacoes int,
        fonte text, primeira_vez text, ultima_vez text)""")
    con.commit()
def test_registrar_e_recuperar(tmp_path):
    con = ed.conectar(tmp_path/"t.db"); _seed(con)
    memoria.registrar_veredito(con, "contrato_aditivo", "11222333000181", "refutado: dentro do limite", 3)
    memoria.registrar_veredito(con, "contrato_aditivo", "11222333000181", "refutado: idem", 3)
    row = con.execute("select n_observacoes from memoria_aprendizado where categoria='contrato_aditivo' and chave='11222333000181'").fetchone()
    assert row[0] == 2
    ctx = memoria.contexto_memoria(con, "contrato_aditivo", "11222333000181")
    assert "refutado" in ctx.lower()
```
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** — `registrar_veredito`: UPSERT em `memoria_aprendizado` por (categoria, chave), incrementando `n_observacoes`, guardando o último `valor`, `ultima_vez=now`. `contexto_memoria`: SELECT o `valor`+`n_observacoes` da (categoria, chave); retorna string "MEMÓRIA: este fornecedor/dimensão já teve veredito '<valor>' em N análises anteriores — considere antes de re-acusar." ou "" se nada.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git commit -m "feat(enxame): memória de veredito (não re-acusar refutado) reusável"`

---

### Task 7: Câmara + parecer — MOD `enxame/lentes.py`, `contratos/parecer.py`
**Files:** Modify `compliance_agent/enxame/lentes.py` (dossiê aceita `rag_ctx`/`memoria_ctx`); Create `compliance_agent/contratos/parecer.py`; Test `tests/test_contratos_parecer.py`
**Interfaces:** Produces `deliberar(con, dossie, achados, gerar=None) -> dict` ({conclusao, score, dimensoes, voto, relatorio}); `render_parecer_ctx(parecer) -> dict`; `gravar_e_aprender(con, parecer)`.

- [ ] **Step 1:** em `lentes.py`, no `_dossie_txt`, acrescentar (quando presentes) `dossie.get("rag_ctx")` e `dossie.get("memoria_ctx")` ao texto — pequena extensão, não reescrita. Teste: `test_dossie_txt_inclui_memoria` (monta dossiê com memoria_ctx, checa que aparece no prompt).
- [ ] **Step 2: Teste falhando do parecer** (enxame mockado):
```python
# tests/test_contratos_parecer.py
from compliance_agent.contratos import parecer
def test_deliberar_monta_4_secoes(monkeypatch, tmp_path):
    from compliance_agent.editais import db as ed
    con = ed.conectar(tmp_path/"t.db")
    con.execute("create table if not exists memoria_aprendizado (id integer primary key, categoria text, chave text, valor text, confianca real, n_observacoes int, fonte text, primeira_vez text, ultima_vez text)")
    con.commit()
    dossie = {"contrato": {"numero_controle_pncp":"C1","fornecedor_documento":"11222333000181","fornecedor_nome":"ACME","objeto":"obra","valor_inicial":100000,"valor_global":140000},
              "aditivos": [], "pagamentos": {}, "sinais_fornecedor": []}
    achados = [{"dimensao":"aditivo","risco":8,"texto":"acréscimo 40%","norma":"art. 125","proveniencia":{}}]
    monkeypatch.setattr(parecer, "_deliberar_achado", lambda con,d,a,gerar=None: {"score_final":8,"veredito":"indício de irregularidade","votos":{}})
    p = parecer.deliberar(con, dossie, achados)
    assert p["conclusao"] in ("regular","diligência","indício de irregularidade")
    assert set(["relatorio","fundamentacao","conclusao","voto"]) <= set(p)
```
- [ ] **Step 3: Implementar** — `_deliberar_achado(con, dossie, achado, gerar)`: injeta `rag_ctx = hermes_rag.consultar(f"{achado['dimensao']} {achado['norma']}")` e `memoria_ctx = memoria.contexto_memoria(con, f"contrato_{achado['dimensao']}", dossie['contrato']['fornecedor_documento'])` no dossiê, chama `enxame.orquestrador.avaliar`. `deliberar`: roda `_deliberar_achado` em cada achado risco≥5, `score = max` dos vereditos; `conclusao` = "indício de irregularidade" (≥7) / "diligência" (4-6) / "regular" (<4); monta `relatorio` (fatos+valores), `fundamentacao` (por dimensão: fatos+norma+jurisprudência RAG+voto), `voto` (recomendação por conclusão). `gravar_e_aprender`: grava `contrato_parecer` + `memoria.registrar_veredito` por dimensão.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git commit -m "feat(contratos): câmara delibera parecer TC (relatório/fundamentação/conclusão/voto) com RAG+memória"`

---

### Task 8: Runner E2E — `tools/contratos_parecer.py`
**Files:** Create `tools/contratos_parecer.py`
**Interfaces:** Consumes tudo acima + `render_html.gerar_pdf`, `pericia_fisc.ctx_de_achados`.
- [ ] **Step 1:** selecionar contratos com aditivo (`num_aditivos>0` ou tipo Contrato) → `coletar_aditivos` (sob `coleta_lock`) → `montar_dossie` → `rodar_thoughts` (com `ref_fn` = peer+Painel) → `deliberar` p/ os que têm achado → `gravar_e_aprender`.
- [ ] **Step 2:** por parecer, `render_parecer_ctx` → `gerar_pdf` (`reports/contrato_parecer_<controle>_<data>.pdf`); índice consolidado XLSX; `--telegram` envia; conclusão "irregularidade" → caso vault.
- [ ] **Step 3: TESTE REAL E2E:** rodar sobre ≥1 contrato PCRJ real com aditivo → parecer PDF com as 4 seções, norma e jurisprudência citadas; **revisar 3 à mão** (anti-falso-positivo) antes de pronto (critérios 6-7).
- [ ] **Step 4: Commit** — `git commit -m "feat(contratos): runner E2E parecer TC → PDF + índice + casos vault"`

---

### Task 9: Registro e encerramento
- [ ] **Step 1:** registrar `contratos_parecer` em `capabilities.yaml` (tipo: cli).
- [ ] **Step 2:** nota `~/vault/aprendizados/enxame-contratos.md` (PNCP termos api/pncp/v1; Painel via compras.gov.br PDM→CATMAT→preço; dossiê compartilhado; memória anti-re-acusação) + link no MOC.
- [ ] **Step 3:** suíte `pytest tests/ -k "contratos or precos or pncp_termos or enxame_memoria" -q` → PASS.
- [ ] **Step 4:** commit final + push.

---

## Cobertura do spec (self-review)
| Requisito spec | Task |
|---|---|
| Schema (aditivo/dossie/parecer/preco_cache) | 1 |
| PNCP termos aditivos (RESOLVIDO) | 2 |
| Painel de Preços (RESOLVIDO, PDM→CATMAT→preço) | 3 |
| Dossiê compartilhado (barramento) | 4 |
| Thoughts: aditivo/prorrogação/execução/sobrepreço/Lex/sinais | 5 |
| Memória + inteligência progressiva | 6 (+auto_melhorar já existente) |
| Câmara + parecer TC (4 seções) + RAG | 7 |
| Saída PDF + casos + Telegram | 8 |
| Testes reais (aceite 1-7) | 2,3,4,5,8 |
| capabilities + vault | 9 |
