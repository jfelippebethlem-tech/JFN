import pytest

from mestre_yoda import tools
from mestre_yoda.market import MarketDataUnavailable, Quote
from mestre_yoda.memory import ConversationMemory, MemoryStore
from mestre_yoda.tools import build_registry, market_tool


@pytest.fixture
def memory(tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    yield ConversationMemory(store, max_history=10)
    store.close()


def test_remember_e_recall(memory):
    reg = build_registry(memory, chat_id=1)
    out = reg.execute("remember_fact", {"key": "nome", "value": "Luke"})
    assert "Luke" in out
    assert memory.facts(1) == {"nome": "Luke"}
    assert "nome: Luke" in reg.execute("recall_facts", {})


def test_remember_falta_argumento(memory):
    reg = build_registry(memory, chat_id=1)
    out = reg.execute("remember_fact", {"key": "nome"})
    assert "obrigatórios" in out


def test_ferramenta_desconhecida(memory):
    reg = build_registry(memory, chat_id=1)
    assert "desconhecida" in reg.execute("voar", {})


def test_get_current_time(memory):
    reg = build_registry(memory, chat_id=1)
    out = reg.execute("get_current_time", {})
    assert out  # alguma string de data/hora
    assert any(c.isdigit() for c in out)


def test_schemas_tem_nomes(memory):
    reg = build_registry(memory, chat_id=1)
    nomes = {s["name"] for s in reg.schemas()}
    assert {"get_current_time", "remember_fact", "recall_facts"} <= nomes


def test_market_tool_no_registro(memory):
    reg = build_registry(memory, chat_id=1)
    nomes = {s["name"] for s in reg.schemas()}
    assert "get_market_data" in nomes


def test_market_tool_formata_cotacoes(monkeypatch):
    def fake_fetch(*args, **kwargs):
        return [Quote("Dólar", "USDBRL=X", 5.10, 0.4)]

    monkeypatch.setattr(tools, "fetch_quotes", fake_fetch)
    out = market_tool().handler({})
    assert "Dólar" in out
    assert "+0.40%" in out


def test_market_tool_degrada_sem_inventar(monkeypatch):
    def boom(*args, **kwargs):
        raise MarketDataUnavailable("fonte fora do ar")

    monkeypatch.setattr(tools, "fetch_quotes", boom)
    out = market_tool().handler({})
    # Em vez de números falsos, orienta a buscar na web.
    assert "invente" in out.lower()
    assert "web" in out.lower()
