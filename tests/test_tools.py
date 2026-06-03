import pytest

from mestre_yoda.memory import ConversationMemory, MemoryStore
from mestre_yoda.tools import build_registry


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
