import pytest

from mestre_yoda.hermes import HermesAgent
from mestre_yoda.memory import ConversationMemory, MemoryStore
from mestre_yoda.protocol import AgentRequest

from .fakes import (
    FakeAnthropic,
    FakeResponse,
    FakeTextBlock,
    FakeToolUseBlock,
)


@pytest.fixture
def memory(tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    yield ConversationMemory(store, max_history=10)
    store.close()


def _agent(client, memory):
    return HermesAgent(
        client,
        memory,
        model="claude-opus-4-8",
        system_prompt="Yoda você é.",
        effort="high",
    )


async def test_resposta_simples(memory):
    client = FakeAnthropic([FakeResponse(content=[FakeTextBlock("Olá, padawan.")])])
    agent = _agent(client, memory)

    resp = await agent.respond(AgentRequest(chat_id=1, user_text="oi"))

    assert resp.ok is True
    assert "padawan" in resp.text
    # Mensagem do usuário e do assistente foram persistidas.
    ctx = memory.build_context(1)
    assert [m.role for m in ctx.messages] == ["user", "assistant"]


async def test_loop_de_ferramenta(memory):
    client = FakeAnthropic(
        [
            FakeResponse(
                content=[FakeToolUseBlock(name="remember_fact",
                                          input={"key": "nome", "value": "Luke"})],
                stop_reason="tool_use",
            ),
            FakeResponse(content=[FakeTextBlock("Lembrarei, eu.")]),
        ]
    )
    agent = _agent(client, memory)

    resp = await agent.respond(AgentRequest(chat_id=1, user_text="meu nome é Luke"))

    assert resp.tools_used == ("remember_fact",)
    assert "Lembrarei" in resp.text
    assert memory.facts(1) == {"nome": "Luke"}
    # Duas chamadas ao Claude: a do tool_use e a final.
    assert len(client.calls) == 2


async def test_usa_adaptive_thinking_e_effort(memory):
    client = FakeAnthropic([FakeResponse(content=[FakeTextBlock("ok")])])
    agent = _agent(client, memory)
    await agent.respond(AgentRequest(chat_id=1, user_text="oi"))
    chamada = client.calls[0]
    assert chamada["thinking"] == {"type": "adaptive"}
    assert chamada["output_config"] == {"effort": "high"}
    # System é lista com o prompt congelado e cache_control no primeiro bloco.
    assert chamada["system"][0]["cache_control"] == {"type": "ephemeral"}


async def test_contexto_injeta_resumo_e_fatos(memory):
    memory._store.set_summary(1, "Conversaram sobre a Força.")
    memory.remember_fact(1, "nome", "Rey")
    client = FakeAnthropic([FakeResponse(content=[FakeTextBlock("ok")])])
    agent = _agent(client, memory)

    await agent.respond(AgentRequest(chat_id=1, user_text="oi"))

    system_blocks = client.calls[0]["system"]
    assert len(system_blocks) == 2  # congelado + memória dinâmica
    dinamico = system_blocks[1]["text"]
    assert "Força" in dinamico
    assert "Rey" in dinamico


async def test_falha_vira_resposta_amigavel(memory):
    client = FakeAnthropic()

    async def boom(**kwargs):
        raise RuntimeError("API caiu")

    client.messages.create = boom  # type: ignore[assignment]
    agent = _agent(client, memory)

    resp = await agent.respond(AgentRequest(chat_id=1, user_text="oi"))
    assert resp.ok is False
    assert "Força" in resp.text  # mensagem de fallback do Yoda


async def test_summarize(memory):
    client = FakeAnthropic([FakeResponse(content=[FakeTextBlock("Um resumo curto.")])])
    agent = _agent(client, memory)
    out = await agent.summarize("conversa longa aqui")
    assert out == "Um resumo curto."
    assert client.calls[0]["output_config"] == {"effort": "low"}
