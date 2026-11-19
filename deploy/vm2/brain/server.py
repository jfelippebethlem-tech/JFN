"""Second Brain JFN — API REST + MCP (streamable HTTP) + painel web. Só na Tailnet."""
from __future__ import annotations

import contextlib
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

import brain_core as B

# ---------------------------------------------------------------- MCP
mcp = FastMCP(
    "jfn-brain",
    instructions=(
        "Segundo cérebro compartilhado do Jorge (vault Obsidian do JFN, shared-brain das VMs, "
        "relatório do graphify e memórias versionadas). Antes de responder sobre projetos, decisões "
        "ou contexto do Jorge, use brain_search/brain_recall. Grave fatos duráveis com brain_remember "
        "(nunca segredos/credenciais). Para corrigir um fato, use supersedes com o id antigo."),
    stateless_http=True, json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["jfn-agent-2.tailbbe6c9.ts.net:8443", "jfn-agent-2.tailbbe6c9.ts.net:10000", "jfn-agent-2.tailbbe6c9.ts.net",
                       "127.0.0.1:8788", "localhost:8788", "100.74.228.51:8788"],
        allowed_origins=["https://jfn-agent-2.tailbbe6c9.ts.net:8443", "https://claude.ai", "https://jfn-agent-2.tailbbe6c9.ts.net:10000"]),
)
mcp.settings.streamable_http_path = "/"


@mcp.tool()
def brain_search(query: str, k: int = 8, source: str | None = None) -> list[dict]:
    """Busca nas notas — uma linha por NOTA (palavra por nota inteira, com peso no título; identificador citado
    na pergunta vem na frente; o vetor completa). source opcional: vault | shared | graphify."""
    return B.search(query, k=min(k, 25), source=source)


@mcp.tool()
def brain_note(ref: str) -> dict | None:
    """Lê uma nota inteira por caminho, nome ([[link]]) ou título aproximado."""
    return B.get_note(ref)


@mcp.tool()
def brain_neighbors(ref: str, depth: int = 1) -> dict:
    """Grafo: notas/tags/memórias ligadas a uma nota ou entidade (depth 1-3)."""
    return B.neighbors(ref, depth=depth)


@mcp.tool()
def brain_recall(query: str, k: int = 8, kind: str | None = None, em: str | None = None) -> list[dict]:
    """Recupera memórias ativas. kind: episodica|semantica|procedural|decisoria|experiencial|identidade.
    em (data ISO, opcional): o que o cérebro SABIA naquela data."""
    return B.recall(query, k=min(k, 25), kind=kind, em=em)


@mcp.tool()
def brain_entity(ref: str, com: str | None = None) -> dict:
    """Cruzamento por entidade, sem modelo: tudo o que cita um CNPJ, nº de processo SEI, UG ("UG 133100") ou nº de OB —
    notas (casos primeiro), memórias e as outras entidades que aparecem junto. `com`: segunda entidade; devolve só o
    que cita AS DUAS (ex.: ref="UG 296100", com="12.345.678/0001-90"). Menção ≠ pagamento: valor pago é no SIAFE."""
    return B.entity(ref, com=com)


@mcp.tool()
def brain_history(ref: str) -> list[dict]:
    """Versões de um fato (chave ou id): o que foi dito, quando foi registrado e quando deixou de valer."""
    return B.historico(ref)


@mcp.tool()
def brain_remember(content: str, kind: str = "semantica", subject: str | None = None,
                   source: str = "agente", confidence: float = 0.8,
                   supersedes: int | None = None, tags: list[str] | None = None,
                   chave: str | None = None, valeu_de: str | None = None, valeu_ate: str | None = None,
                   prova_doc: str | None = None, prova_trecho: str | None = None) -> dict:
    """Grava uma memória durável (um fato por chamada). Informe source (ex.: claude-vm1, hermes).
    Para atualizar um fato existente, passe supersedes=<id antigo> ou a mesma `chave`: o antigo vira 'substituida'.
    Opcionais: valeu_de/valeu_ate (quando o fato valeu, ISO) e prova_doc/prova_trecho (documento primário e trecho literal)."""
    return B.remember(content, kind, subject, source, confidence, supersedes, tags, chave=chave, valeu_de=valeu_de,
                      valeu_ate=valeu_ate, prova_doc=prova_doc, prova_trecho=prova_trecho)


@mcp.tool()
def brain_forget(memory_id: int, source: str = "agente") -> dict:
    """Revoga uma memória (fica no histórico, sai das buscas)."""
    return B.forget(memory_id, source)


@mcp.tool()
def brain_stats() -> dict:
    """Tamanho e frescor do cérebro."""
    return B.stats()


# ---------------------------------------------------------------- HTTP
@contextlib.asynccontextmanager
async def lifespan(_):
    B.embed_one("aquecimento")
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="JFN Brain", lifespan=lifespan, docs_url="/api/docs")
app.mount("/mcp", mcp.streamable_http_app())
UI = Path(__file__).with_name("ui.html")


class MemIn(BaseModel):
    content: str = Field(min_length=3)
    kind: str = "semantica"
    subject: str | None = None
    source: str = "painel"
    confidence: float = 0.8
    supersedes: int | None = None
    tags: list[str] | None = None
    chave: str | None = None
    valeu_de: str | None = None
    valeu_ate: str | None = None
    prova_doc: str | None = None
    prova_trecho: str | None = None
    proposta: bool = False


@app.get("/", response_class=HTMLResponse)
def home():
    return UI.read_text(encoding="utf-8")


@app.get("/api/search")
def api_search(q: str = Query(min_length=2), k: int = 10, source: str | None = None):
    return B.search(q, k=min(k, 25), source=source)


@app.get("/api/recall")
def api_recall(q: str = Query(min_length=2), k: int = 8, kind: str | None = None, em: str | None = None):
    return B.recall(q, k=min(k, 25), kind=kind, em=em)


@app.get("/api/entity")
def api_entity(ref: str, com: str | None = None):
    return B.entity(ref, com=com)


@app.get("/api/history")
def api_history(ref: str):
    return B.historico(ref)


@app.get("/api/proposals")
def api_proposals(limit: int = 50):
    return B.proposals(limit)


@app.get("/api/note")
def api_note(ref: str):
    n = B.get_note(ref)
    if not n:
        raise HTTPException(404, "nota não encontrada")
    return n


@app.get("/api/neighbors")
def api_neighbors(ref: str, depth: int = 1):
    return B.neighbors(ref, depth)


@app.post("/api/memories")
def api_remember(m: MemIn):
    try:
        return B.remember(**m.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/stats")
def api_stats():
    return B.stats()


@app.get("/healthz")
def health():
    return {"ok": True}
