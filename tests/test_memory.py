import pytest

from mestre_yoda.memory import ConversationMemory, MemoryStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(str(tmp_path / "mem.db"))
    yield s
    s.close()


def test_mensagens_em_ordem(store):
    store.add_message(1, "user", "oi")
    store.add_message(1, "assistant", "olá")
    msgs = store.recent_messages(1, 10)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[0].content == "oi"


def test_role_invalido(store):
    with pytest.raises(ValueError):
        store.add_message(1, "system", "x")


def test_fatos_upsert(store):
    store.upsert_fact(1, "nome", "Luke")
    store.upsert_fact(1, "nome", "Anakin")
    assert store.get_facts(1) == {"nome": "Anakin"}


def test_clear_chat_preserva_fatos(store):
    store.add_message(1, "user", "oi")
    store.set_summary(1, "resumo")
    store.upsert_fact(1, "nome", "Yoda")
    store.clear_chat(1)
    assert store.recent_messages(1, 10) == []
    assert store.get_summary(1) is None
    assert store.get_facts(1) == {"nome": "Yoda"}  # fatos sobrevivem


def test_excluding_recent(store):
    for i in range(5):
        store.add_message(1, "user", f"m{i}")
    antigas = store.messages_excluding_recent(1, keep_recent=2)
    assert [m.content for m in antigas] == ["m0", "m1", "m2"]


def test_recent_limita_por_chat(store):
    store.add_message(1, "user", "a")
    store.add_message(2, "user", "b")
    assert len(store.recent_messages(1, 10)) == 1


async def test_maybe_summarize_dispara(store):
    chamadas = []

    async def fake_summarizer(text: str) -> str:
        chamadas.append(text)
        return "RESUMO"

    mem = ConversationMemory(store, max_history=4, summarizer=fake_summarizer)
    for i in range(6):
        mem.record_user(1, f"msg{i}")

    resumiu = await mem.maybe_summarize(1)
    assert resumiu is True
    assert len(chamadas) == 1
    # As 4 mais recentes permanecem; o resumo foi gravado.
    ctx = mem.build_context(1)
    assert ctx.summary == "RESUMO"
    assert len(ctx.messages) == 4


async def test_maybe_summarize_nao_dispara_abaixo_do_limite(store):
    async def fake_summarizer(text: str) -> str:  # pragma: no cover
        raise AssertionError("não deveria ser chamado")

    mem = ConversationMemory(store, max_history=10, summarizer=fake_summarizer)
    mem.record_user(1, "oi")
    assert await mem.maybe_summarize(1) is False


async def test_summary_buffer_adia_resumo(store):
    chamadas = []

    async def fake_summarizer(text: str) -> str:
        chamadas.append(text)
        return "RESUMO"

    # max_history=4, buffer=4 → só resume acima de 8 mensagens.
    mem = ConversationMemory(
        store, max_history=4, summarizer=fake_summarizer, summary_buffer=4
    )
    for i in range(8):
        mem.record_user(1, f"msg{i}")
    # 8 == limiar; ainda não resume.
    assert await mem.maybe_summarize(1) is False
    assert chamadas == []

    mem.record_user(1, "estourou")  # agora são 9, acima do limiar
    assert await mem.maybe_summarize(1) is True
    assert len(chamadas) == 1
    # Mantém as 4 mais recentes intactas.
    assert len(mem.build_context(1).messages) == 4


async def test_maybe_summarize_resiliente_a_erro(store):
    async def boom(text: str) -> str:
        raise RuntimeError("falha de rede")

    mem = ConversationMemory(store, max_history=2, summarizer=boom)
    for i in range(5):
        mem.record_user(1, f"m{i}")
    # Erro no resumidor não deve propagar nem perder mensagens.
    assert await mem.maybe_summarize(1) is False
    assert store.message_count(1) == 5
