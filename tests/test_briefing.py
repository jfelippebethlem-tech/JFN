import pytest

from mestre_yoda.briefing import BRIEFING_INSTRUCTIONS, compose_briefing
from mestre_yoda.hermes import _BRIEFING_FALLBACK, HermesAgent
from mestre_yoda.memory import ConversationMemory, MemoryStore

from .fakes import FakeAnthropic, FakeResponse, FakeTextBlock


@pytest.fixture
def memory(tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    yield ConversationMemory(store, max_history=10)
    store.close()


def _agent(client, memory, **kwargs):
    return HermesAgent(
        client,
        memory,
        model="claude-opus-4-8",
        system_prompt="Yoda você é.",
        **kwargs,
    )


async def test_compose_briefing_devolve_texto(memory):
    client = FakeAnthropic(
        [FakeResponse(content=[FakeTextBlock("Bom dia, Mestre Jorge! 🌅")])]
    )
    agent = _agent(client, memory)

    texto = await compose_briefing(agent)

    assert "Mestre Jorge" in texto
    # O roteiro do briefing foi enviado como mensagem do usuário.
    assert client.calls[0]["messages"][0]["content"] == BRIEFING_INSTRUCTIONS


async def test_compose_oferece_mercado_e_web(memory):
    client = FakeAnthropic([FakeResponse(content=[FakeTextBlock("ok")])])
    agent = _agent(client, memory, enable_web_search=True)

    await compose_briefing(agent)

    nomes = {t.get("name") for t in client.calls[0]["tools"]}
    assert "get_market_data" in nomes
    assert "web_search" in nomes


async def test_compose_nao_persiste_na_memoria(memory):
    client = FakeAnthropic([FakeResponse(content=[FakeTextBlock("ok")])])
    agent = _agent(client, memory)

    await compose_briefing(agent)

    # Briefing é one-shot: nada vai para o histórico de nenhum chat.
    assert memory.build_context(0).messages == []


async def test_compose_falha_vira_fallback(memory):
    client = FakeAnthropic()

    async def boom(**kwargs):
        raise RuntimeError("API caiu")

    client.messages.create = boom  # type: ignore[assignment]
    agent = _agent(client, memory)

    texto = await compose_briefing(agent)
    assert texto == _BRIEFING_FALLBACK


async def test_compose_texto_vazio_vira_fallback(memory):
    client = FakeAnthropic([FakeResponse(content=[FakeTextBlock("")])])
    agent = _agent(client, memory)

    texto = await compose_briefing(agent)
    assert texto == _BRIEFING_FALLBACK
