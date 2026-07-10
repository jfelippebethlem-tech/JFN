# Enxame de Avaliação + Direcionamento de Editais — Plano de Implementação (Spec 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detectar direcionamento em licitações municipais do Rio comparando editais de objeto semelhante cláusula-a-cláusula (a exigência de habilitação que só um edital do grupo impõe), com um enxame de agentes-lente julgando as candidatas.

**Architecture:** Funil determinístico (corpus → cláusulas → cluster semântico → peer-diff) reduz 14 mil editais a um punhado de cláusulas-anomalia por grupo; só essas sobem ao enxame de 6 agentes LLM free-tier (5 lentes + síntese adversarial). Tabelas aditivas no `compliance.db`; relatório PDF Kroll.

**Tech Stack:** Python 3.12, httpx, sqlite3 (raw, padrão `emendas/db.py`), Cohere embeddings (`tools/hermes_rag._embed`), LLM free-tier (`direcionamento_cerebro.gerar_sync`), reuso de `detectores/coletor_edital` + `e7_clausula_restritiva` + `knowledge.jurisprudencia`. Spec: `docs/superpowers/specs/2026-07-10-enxame-avaliacao-editais-design.md`.

## Global Constraints
- **Indício ≠ acusação**; **ausente ≠ 0** (campo não extraído → `nao_avaliavel`, nunca zero); presunção de legitimidade; proveniência por trecho em toda cláusula; CPF mascarado.
- **LLM só free-tier** via `direcionamento_cerebro.gerar_sync` (Gemini 2.5-flash→Groq→Cerebras). Nunca pago.
- **Funil determinístico ANTES do enxame** — nº de chamadas LLM ≈ nº de candidatas (dezenas), nunca 14 mil.
- **VM 2 vCPU**: 1 job pesado por vez; corpus/embeddings sob `coleta_lock`, fora de horário de sweep; escrita de estado atômica (tmp+os.replace).
- **CATMAT ~0% na PCRJ (verificado ao vivo)** → agrupamento SEMÂNTICO (embedding do objeto+itens), nunca por código de catálogo.
- Testes: `cd ~/JFN && .venv/bin/python -m pytest tests/<arquivo> -q`. Teste REAL (dado vivo) nos pontos marcados — meta do dono.

## File Structure
```
compliance_agent/editais/__init__.py        (novo)
compliance_agent/editais/db.py               (schema: edital_documento/clausula/cluster, clausula_veredito)
compliance_agent/editais/corpus.py           (baixa edital+itens → edital_documento)
compliance_agent/editais/clausulas.py        (extrai+rotula eixo → edital_clausula)
compliance_agent/editais/agrupar.py          (embeddings+cluster → edital_cluster)
compliance_agent/editais/peer_diff.py        (raridade×forçaE7 → candidatas)
compliance_agent/enxame/__init__.py          (novo)
compliance_agent/enxame/lentes.py            (5 agentes-lente + prompts)
compliance_agent/enxame/orquestrador.py      (dispara lentes, síntese adversarial → clausula_veredito)
tools/editais_corpus.py                      (runner de coleta do corpus)
tools/editais_direcionamento.py              (runner E2E: cluster→peer-diff→enxame→PDF)
tests/test_editais_db.py, test_editais_clausulas.py, test_editais_agrupar.py,
tests/test_editais_peer_diff.py, test_enxame_orquestrador.py, tests/test_editais_corpus.py
tests/fixtures/editais/*.txt  (3 editais reais do mesmo objeto + 1 distinto)
```

Interfaces existentes (usar, não recriar):
- `pncp.baixar_documentos(id_pncp, max_arquivos=5, max_chars=80000) -> [{titulo,tipo,url,n_chars,texto}]` (cache em data/pncp_cache/).
- `pncp.buscar_itens(id_pncp) -> [{numero,descricao,quantidade,unidade,valor_unitario,valor_total,ncm_catmat,situacao}]`. **Não traz materialOuServico** → o corpus busca o endpoint cru `/{cnpj}/compras/{ano}/{seq}/itens` p/ capturar `materialOuServico`.
- `tools/hermes_rag._embed(textos: list[str], input_type: str) -> list[list[float]]` (Cohere, lotes de 96, throttle 429). input_type: `"search_document"`.
- `direcionamento_cerebro.gerar_sync(prompt: str, sistema: str = "", timeout: float = 45.0) -> str`.
- `emendas.db.conectar()` — modelo do helper sqlite (WAL, row_factory).
- `reporting.render_html.gerar_pdf(ctx, nome_base)`; `reporting.pericia_fisc.ctx_de_achados`/`tabela_html`.
- `compliance_agent.coleta_lock.coleta_lock()`.

---

### Task 1: Schema — `editais/db.py`

**Files:** Create `compliance_agent/editais/__init__.py` (vazio), `compliance_agent/editais/db.py`; Test `tests/test_editais_db.py`

**Interfaces:**
- Produces: `conectar(db_path=None)` (reexporta `emendas.db.conectar`); `init_schema(con)` — CREATE IF NOT EXISTS das 4 tabelas.

- [ ] **Step 1: Teste falhando**
```python
# tests/test_editais_db.py
from compliance_agent.editais import db as ed
TABS = {"edital_documento", "edital_clausula", "edital_cluster", "clausula_veredito"}
def test_init_schema_idempotente(tmp_path):
    con = ed.conectar(tmp_path / "t.db")
    ed.init_schema(con); ed.init_schema(con)
    got = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert TABS <= got
```
- [ ] **Step 2: Rodar e ver falhar** — `pytest tests/test_editais_db.py -q` → ModuleNotFoundError.
- [ ] **Step 3: Implementar**
```python
# compliance_agent/editais/db.py
# -*- coding: utf-8 -*-
"""Schema do enxame de editais no compliance.db (aditivo)."""
from __future__ import annotations
import sqlite3
from compliance_agent.emendas.db import conectar  # reexport: mesmo helper WAL/row_factory

DDL = [
    """CREATE TABLE IF NOT EXISTS edital_documento (
        numero_controle_pncp TEXT PRIMARY KEY, ano INTEGER, orgao_cnpj TEXT,
        objeto TEXT, material_servico TEXT, valor_estimado REAL,
        texto TEXT, itens_json TEXT, documento_disponivel INTEGER DEFAULT 0,
        coletado_em TEXT DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS edital_clausula (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero_controle_pncp TEXT NOT NULL REFERENCES edital_documento(numero_controle_pncp),
        eixo TEXT, subtipo TEXT, texto TEXT, parametro_num REAL,
        assinatura TEXT, trecho_fonte TEXT)""",
    "CREATE INDEX IF NOT EXISTS ix_clau_ctrl ON edital_clausula(numero_controle_pncp)",
    "CREATE INDEX IF NOT EXISTS ix_clau_assin ON edital_clausula(assinatura)",
    """CREATE TABLE IF NOT EXISTS edital_cluster (
        id INTEGER PRIMARY KEY AUTOINCREMENT, assinatura_objeto TEXT,
        membros_json TEXT, tamanho INTEGER, avaliavel INTEGER DEFAULT 0,
        criado_em TEXT DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS clausula_veredito (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clausula_id INTEGER REFERENCES edital_clausula(id),
        cluster_id INTEGER REFERENCES edital_cluster(id),
        numero_controle_pncp TEXT, raridade REAL, forca_e7 TEXT, sumula TEXT,
        votos_json TEXT, score_final INTEGER, veredito TEXT,
        verificado_em TEXT DEFAULT (datetime('now')))""",
]

def init_schema(con: sqlite3.Connection) -> None:
    for ddl in DDL:
        con.execute(ddl)
    con.commit()
```
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git add compliance_agent/editais/ tests/test_editais_db.py && git commit -m "feat(editais): schema aditivo (documento/clausula/cluster/veredito)"`

---

### Task 2: Corpus — `editais/corpus.py` + runner

**Files:** Create `compliance_agent/editais/corpus.py`, `tools/editais_corpus.py`; Test `tests/test_editais_corpus.py`

**Interfaces:**
- Consumes: `pncp.baixar_documentos`, `db.conectar/init_schema`, `coleta_lock`.
- Produces: `async coletar_um(con, numero_controle_pncp) -> dict` ({"verificado","documento_disponivel","n_chars"}); `async coletar_corpus(con, limite=None, pausa=0.4) -> dict`; `_itens_crus(id_pncp) -> list[dict]` (endpoint cru, captura materialOuServico).

- [ ] **Step 1: Teste falhando** (parser dos itens crus, offline):
```python
# tests/test_editais_corpus.py
from compliance_agent.editais import corpus
def test_material_servico_predominante():
    itens = [{"materialOuServico": "M"}, {"materialOuServico": "M"}, {"materialOuServico": "S"}]
    assert corpus._material_predominante(itens) == "M"
    assert corpus._material_predominante([]) is None
```
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar**
```python
# compliance_agent/editais/corpus.py
# -*- coding: utf-8 -*-
"""Corpus de editais municipais: baixa texto do edital + itens → edital_documento.

POR QUE endpoint cru de itens: pncp.buscar_itens não traz materialOuServico (M/S),
que é o único classificador PREENCHIDO na PCRJ (CATMAT vem ~0%) e serve de
pré-partição barata no agrupamento. Degrada honesto: sem documento acessível →
documento_disponivel=0 (fica fora do peer-diff, não vira 'sem cláusula')."""
from __future__ import annotations
import json
from collections import Counter
import httpx
from compliance_agent.collectors import pncp
from compliance_agent.collectors.pncp import PNCP_BASE, _parse_id_pncp

def _material_predominante(itens: list[dict]) -> str | None:
    vals = [it.get("materialOuServico") for it in itens if it.get("materialOuServico")]
    return Counter(vals).most_common(1)[0][0] if vals else None

async def _itens_crus(id_pncp: str) -> list[dict]:
    pr = _parse_id_pncp(id_pncp)
    if not pr:
        return []
    cnpj, ano, seq = pr
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{PNCP_BASE}/orgaos/{cnpj}/compras/{ano}/{seq}/itens",
                            headers={"User-Agent": "JFN-Compliance/2.0"})
            return r.json() if r.status_code == 200 else []
    except Exception:
        return []

async def coletar_um(con, numero_controle_pncp: str, pausa: float = 0.4) -> dict:
    docs = await pncp.baixar_documentos(numero_controle_pncp)
    itens = await _itens_crus(numero_controle_pncp)
    texto = "\n".join(d.get("texto", "") for d in docs)
    disp = 1 if texto.strip() else 0
    lic = con.execute("select ano, orgao_cnpj, objeto, valor_estimado from pcrj_licitacoes "
                      "where numero_controle_pncp=?", (numero_controle_pncp,)).fetchone()
    con.execute(
        """INSERT INTO edital_documento (numero_controle_pncp, ano, orgao_cnpj, objeto,
              material_servico, valor_estimado, texto, itens_json, documento_disponivel)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(numero_controle_pncp) DO UPDATE SET texto=excluded.texto,
              itens_json=excluded.itens_json, documento_disponivel=excluded.documento_disponivel,
              material_servico=excluded.material_servico, coletado_em=datetime('now')""",
        (numero_controle_pncp, lic["ano"] if lic else None, lic["orgao_cnpj"] if lic else None,
         lic["objeto"] if lic else None, _material_predominante(itens),
         lic["valor_estimado"] if lic else None, texto[:400_000],
         json.dumps(itens, ensure_ascii=False)[:400_000], disp))
    con.commit()
    return {"verificado": True, "documento_disponivel": disp, "n_chars": len(texto)}

async def coletar_corpus(con, limite: int | None = None, pausa: float = 0.4) -> dict:
    import asyncio
    pend = [r[0] for r in con.execute(
        """select l.numero_controle_pncp from pcrj_licitacoes l
           left join edital_documento e on e.numero_controle_pncp = l.numero_controle_pncp
           where e.numero_controle_pncp is null and l.objeto is not null
           order by l.data_abertura desc""").fetchall()]
    if limite:
        pend = pend[:limite]
    com_doc = 0
    for nc in pend:
        r = await coletar_um(con, nc)
        com_doc += r["documento_disponivel"]
        await asyncio.sleep(pausa)
    return {"verificado": True, "processados": len(pend), "com_documento": com_doc}
```
```python
# tools/editais_corpus.py
#!/usr/bin/env python3
"""Runner: baixa o corpus de editais municipais. Uso: tools/editais_corpus.py [--limite N]"""
import argparse, asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compliance_agent.coleta_lock import coleta_lock
from compliance_agent.editais import corpus, db as ed

async def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limite", type=int, default=None)
    args = ap.parse_args()
    with coleta_lock():
        con = ed.conectar(); ed.init_schema(con)
        print(await corpus.coletar_corpus(con, limite=args.limite), flush=True)

if __name__ == "__main__":
    asyncio.run(main())
```
- [ ] **Step 4: Rodar unit e ver passar.**
- [ ] **Step 5: TESTE REAL (dado vivo):** `.venv/bin/python tools/editais_corpus.py --limite 40` → esperado `com_documento > 0`. Guardar como fixtures 3 editais do MESMO objeto (ex.: `select numero_controle_pncp, objeto from edital_documento where documento_disponivel=1 and objeto like '%medicament%' limit 3`) exportando `texto` para `tests/fixtures/editais/`.
- [ ] **Step 6: Commit** — `git commit -m "feat(editais): corpus (edital+itens via PNCP), material/serviço, degrada honesto"`

---

### Task 3: Cláusulas — `editais/clausulas.py`

**Files:** Create `compliance_agent/editais/clausulas.py`; Test `tests/test_editais_clausulas.py`

**Interfaces:**
- Consumes: `coletor_edital._linhas_com_contexto`/`_extrair_exigencias`/`_extrair_clausulas_restritivas` (já existem), `db`.
- Produces: `rotular_eixo(exig: dict) -> tuple[str,str]` (eixo, subtipo); `assinatura(clausula: dict) -> str`; `extrair_clausulas(texto: str, valor_estimado: float|None) -> list[dict]`; `gravar(con, numero_controle_pncp, clausulas) -> int`.

- [ ] **Step 1: Teste falhando** (rotulador + assinatura, offline):
```python
# tests/test_editais_clausulas.py
from compliance_agent.editais import clausulas
def test_rotular_eixo():
    assert clausulas.rotular_eixo({"tipo": "atestado"})[0] == "habilitacao_tecnica"
    assert clausulas.rotular_eixo({"tipo": "capital_social"})[0] == "habilitacao_econ_financeira"
def test_assinatura_agrupa_por_faixa():
    a = clausulas.assinatura({"tipo": "atestado", "quantitativo_exigido_pct": 60})
    b = clausulas.assinatura({"tipo": "atestado", "quantitativo_exigido_pct": 65})
    assert a == b   # mesma faixa (>50%)
```
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** — `_EIXO_POR_TIPO = {"atestado":("habilitacao_tecnica","atestado"), "capital_social":("habilitacao_econ_financeira","capital"), "patrimonio_liquido":("habilitacao_econ_financeira","patrimonio"), "visita":("habilitacao_tecnica","visita"), "marca":("condicao_participacao","marca"), "vinculo":("habilitacao_tecnica","vinculo"), "geografico":("condicao_participacao","geografico"), "indices":("habilitacao_econ_financeira","indices")}`; `rotular_eixo` retorna `_EIXO_POR_TIPO.get(exig["tipo"], ("condicao_participacao","outro"))`; `assinatura` = `f"{eixo}:{subtipo}:{faixa}"` onde faixa vem de bucketizar `quantitativo_exigido_pct`/`valor` (ex.: pct >50 → "alto", ≤50 → "baixo"; sem número → "n/a"); `extrair_clausulas` chama `_linhas_com_contexto` sobre o texto e roda `_extrair_exigencias`+`_extrair_clausulas_restritivas`, rotula cada uma; `gravar` insere em `edital_clausula` com `trecho_fonte = exig["prov"]`.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: TESTE REAL:** rodar `extrair_clausulas` sobre 1 fixture de edital real → conferir à mão que os eixos batem com o edital (critério de aceite nº 2). Anotar no commit.
- [ ] **Step 6: Commit** — `git commit -m "feat(editais): extração e rotulagem de cláusulas por eixo (Lei 14.133 62-70)"`

---

### Task 4: Agrupamento semântico — `editais/agrupar.py`

**Files:** Create `compliance_agent/editais/agrupar.py`; Test `tests/test_editais_agrupar.py`

**Interfaces:**
- Consumes: `tools/hermes_rag._embed`, `db`.
- Produces: `cosseno(a, b) -> float`; `agrupar(itens: list[dict], limiar=0.72) -> list[list[int]]` (itens = `[{"id","objeto","material_servico","valor_estimado","emb"?}]`, retorna listas de índices); `construir_clusters(con, limiar=0.72) -> dict` (embeda editais com documento, particiona por M/S e ordem de grandeza de valor, clusteriza, grava `edital_cluster`).

- [ ] **Step 1: Teste falhando** (clustering puro, embeddings sintéticos — sem rede):
```python
# tests/test_editais_agrupar.py
from compliance_agent.editais import agrupar
def test_agrupa_por_similaridade():
    itens = [
        {"id": 1, "material_servico": "M", "valor_estimado": 1000, "emb": [1.0, 0.0]},
        {"id": 2, "material_servico": "M", "valor_estimado": 1200, "emb": [0.99, 0.01]},
        {"id": 3, "material_servico": "M", "valor_estimado": 900,  "emb": [0.0, 1.0]},
    ]
    grupos = agrupar.agrupar(itens, limiar=0.9)
    ids = sorted(sorted(itens[i]["id"] for i in g) for g in grupos)
    assert [1, 2] in ids and [3] in ids
def test_particao_por_material():
    itens = [{"id":1,"material_servico":"M","valor_estimado":1,"emb":[1.0,0.0]},
             {"id":2,"material_servico":"S","valor_estimado":1,"emb":[1.0,0.0]}]
    grupos = agrupar.agrupar(itens, limiar=0.5)
    assert all(len(g) == 1 for g in grupos)   # M e S nunca no mesmo grupo
```
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** — `cosseno` numpy; `agrupar`: agrupamento aglomerativo simples (para cada item, junta ao 1º grupo cujo representante tenha cosseno ≥ limiar E mesma partição `(material_servico, floor(log10(valor+1)))`, senão novo grupo); `construir_clusters`: lê `edital_documento` com `documento_disponivel=1`, monta o texto `objeto + descrições de itens`, chama `_embed(textos, "search_document")`, roda `agrupar`, grava cada grupo em `edital_cluster` (`avaliavel = tamanho >= 3`).
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: TESTE REAL:** rodar `construir_clusters` sobre o corpus baixado; verificar que os 3 editais-fixture do mesmo objeto caíram no mesmo cluster e 1 distinto não (critério nº 3).
- [ ] **Step 6: Commit** — `git commit -m "feat(editais): agrupamento semântico (Cohere) com partição M/S+valor"`

---

### Task 5: Peer-diff — `editais/peer_diff.py`

**Files:** Create `compliance_agent/editais/peer_diff.py`; Test `tests/test_editais_peer_diff.py`

**Interfaces:**
- Consumes: `db`, `detectores.e7_clausula_restritiva.E7ClausulaRestritiva`.
- Produces: `raridade(assinatura, clausulas_do_cluster) -> float`; `forca_e7(clausula, valor_estimado) -> tuple[str,str]` (nivel, sumula); `candidatas(con, cluster_id, limiar_raridade=0.7) -> list[dict]`.

- [ ] **Step 1: Teste falhando** (raridade pura):
```python
# tests/test_editais_peer_diff.py
from compliance_agent.editais import peer_diff
def test_raridade():
    # 'X' aparece em 1 de 4 editais → raridade 0.75
    clau = [("e1","X"),("e2","Y"),("e3","Y"),("e4","Y")]
    assert peer_diff.raridade("X", clau) == 0.75
    assert peer_diff.raridade("Y", clau) == 0.25
```
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** — `raridade(assin, pares)` = `1 - (nº editais distintos com a assinatura / nº editais distintos no cluster)`; `forca_e7`: monta ctx `{clausulas_edital:[clausula], valor_estimado}`, chama `E7ClausulaRestritiva().avaliar(ctx)`, lê nível (forte/medio/fraco) e súmula do resultado; `candidatas`: para o cluster, lista cláusulas dos membros, calcula raridade por assinatura, filtra `raridade >= limiar`, anexa `forca_e7`, score = `raridade * {forte:1.0,medio:0.6,fraco:0.3}[nivel]`, retorna ordenado por score desc.
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: TESTE REAL:** rodar `candidatas` num cluster real; conferir à mão que a cláusula marcada rara de fato só aparece na minoria (critério nº 4).
- [ ] **Step 6: Commit** — `git commit -m "feat(editais): peer-diff (raridade no grupo × força E7 por súmula)"`

---

### Task 6: Enxame — `enxame/lentes.py` + `enxame/orquestrador.py`

**Files:** Create `compliance_agent/enxame/__init__.py`, `enxame/lentes.py`, `enxame/orquestrador.py`; Test `tests/test_enxame_orquestrador.py`

**Interfaces:**
- Consumes: `direcionamento_cerebro.gerar_sync`, `emendas.pericia`/`pcrj.pericia_gastos` (lente beneficiário), `knowledge.jurisprudencia`.
- Produces: `LENTES` (lista de `(nome, fn)` onde fn = `(dossie: dict) -> dict {"voto":0-10,"justificativa","citacao"}`); `avaliar(dossie: dict, gerar=None) -> dict {"score_final","veredito","votos"}`. `dossie` = `{clausula, objeto, sumula, raridade, irmaos_sem_clausula:[trechos], vencedor_doc, sinais_beneficiario}`.

- [ ] **Step 1: Teste falhando** (síntese determinística com lentes injetadas):
```python
# tests/test_enxame_orquestrador.py
from compliance_agent.enxame import orquestrador as orq
def _lente(voto):
    return lambda dossie, gerar=None: {"voto": voto, "justificativa": "x", "citacao": "y"}
def test_sintese_mediana(monkeypatch):
    monkeypatch.setattr(orq, "LENTES", [("a",_lente(8)),("b",_lente(9)),("c",_lente(7)),
                                        ("refutador",_lente(6)),("e",_lente(8))])
    r = orq.avaliar({"clausula": {}, "objeto": "x"})
    assert r["score_final"] == 8 and r["veredito"] == "direcionamento"
def test_empate_pende_pro_refutador(monkeypatch):
    monkeypatch.setattr(orq, "LENTES", [("a",_lente(5)),("refutador",_lente(2))])
    r = orq.avaliar({"clausula": {}, "objeto": "x"})
    assert r["score_final"] <= 4   # desempate cético
```
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** — `lentes.py`: 5 funções (`lente_proporcionalidade`, `lente_jurisprudencia`, `lente_competicao`, `lente_refutador`, `lente_beneficiario`), cada uma monta prompt específico do `dossie`, chama `gerar_sync`, faz parse do JSON `{voto,justificativa,citacao}` (com fallback honesto: parse falho → voto None, não conta). Prompt do refutador é explicitamente adversarial ("tente DERRUBAR a hipótese; só vote alto se não achar justificativa técnica legítima"). `orquestrador.py`: `LENTES` referencia as 5; `avaliar` roda todas (votos válidos só), `score_final = round(mediana)`; se mediana entre 4 e 6 (limítrofe), puxa para o voto do refutador; `veredito` = "direcionamento" se score ≥ 7, "indício fraco" 4–6, "normal" <4. Grava nada aqui (o runner grava).
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `git commit -m "feat(enxame): 5 lentes free-tier + síntese adversarial (desempate pró-refutador)"`

---

### Task 7: Runner E2E — `tools/editais_direcionamento.py`

**Files:** Create `tools/editais_direcionamento.py`; Test: reuso E2E (sem unit novo — é orquestração).

**Interfaces:**
- Consumes: tudo acima + `reporting.pericia_fisc.ctx_de_achados`, `render_html.gerar_pdf`, `pcrj.pericia_gastos`/`emendas.pericia` p/ sinais do vencedor.
- Produces: `reports/editais_direcionamento_<data>.pdf` + XLSX + alertas (`edital_direcionamento`) + casos vault (veredito ≥ 8).

- [ ] **Step 1:** montar o dossiê por candidata (buscar no cluster os trechos dos irmãos que NÃO têm a cláusula; buscar o vencedor da licitação — se disponível no PNCP, senão marca `vencedor=n/d`; rodar sinais de beneficiário sobre o vencedor).
- [ ] **Step 2:** para cada candidata (cap configurável, default 200 — logar se truncar), chamar `orquestrador.avaliar`, gravar `clausula_veredito` + `alertas`.
- [ ] **Step 3:** montar `ctx` Kroll agrupado por cluster (objeto, cláusula rara, quem impôs × quem não, súmula, veredito, vencedor+sinais) e gerar PDF via `gerar_pdf`.
- [ ] **Step 4: TESTE REAL E2E:** rodar sobre ≥1 cluster real → PDF com ≥1 veredito ranqueado e súmula citada; **revisar 3 achados à mão** (anti-falso-positivo) antes de declarar pronto (critério nº 6). Veredito ≥ 8 → nota em `~/vault/casos/`.
- [ ] **Step 5: Commit** — `git commit -m "feat(editais): runner E2E direcionamento → PDF Kroll + casos vault"`

---

### Task 8: Registro e encerramento

- [ ] **Step 1:** registrar `editais_corpus` e `editais_direcionamento` em `capabilities.yaml` (padrão `tipo: cli`).
- [ ] **Step 2:** nota `~/vault/aprendizados/enxame-editais.md` (CATMAT ~0% → semântico; funil determinístico antes do enxame; desempate pró-refutador) + link no MOC.
- [ ] **Step 3:** suíte `pytest tests/ -k "editais or enxame" -q` → tudo PASS.
- [ ] **Step 4:** commit final + push.

---

## Cobertura do spec (self-review)
| Requisito spec | Task |
|---|---|
| A. Corpus (texto+itens, degrada honesto) | 2 |
| B. Extração+rotulagem de cláusulas por eixo | 3 |
| C. Agrupamento semântico (CATMAT~0%→embedding) | 4 |
| D. Peer-diff (raridade×E7) | 5 |
| E. Enxame (5 lentes + síntese adversarial) | 6 |
| F. Cruzamento beneficiário | 7 (dossiê+lente) |
| G. Saída PDF Kroll + vault | 7 |
| Schema 4 tabelas | 1 |
| Testes reais (aceite 1–6) | 2,3,4,5,7 |
| capabilities+vault | 8 |
