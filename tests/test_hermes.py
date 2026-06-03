import pytest

from mestre_yoda.hermes import HermesAgent
from mestre_yoda.memory import ConversationMemory, MemoryStore
from mestre_yoda.protocol import AgentRequest

from .fakes import (
    FakeAnthropic,
    FakeResponse,
    FakeServerToolUseBlock,
    FakeTextBlock,
    FakeThinkingBlock,
    FakeToolUseBlock,
)


class _Overloaded(Exception):
    status_code = 529


class _BadRequest(Exception):
    status_code = 400


@pytest.fixture
def memory(tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    yield ConversationMemory(store, max_history=10)
    store.close()


def _agent(client, memory, **kwargs):
    kwargs.setdefault("sleeper", _noop_sleep)
    return HermesAgent(
        client,
        memory,
        model="claude-opus-4-8",
        system_prompt="Yoda você é.",
        effort="high",
        **kwargs,
    )


async def _noop_sleep(_seconds: float) -> None:
    """Sleeper de teste — não dorme de verdade."""
    return None


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


async def test_web_search_no_conjunto_de_ferramentas(memory):
    client = FakeAnthropic([FakeResponse(content=[FakeTextBlock("ok")])])
    agent = _agent(client, memory, enable_web_search=True)
    await agent.respond(AgentRequest(chat_id=1, user_text="oi"))
    nomes = {t.get("name") for t in client.calls[0]["tools"]}
    assert "web_search" in nomes


async def test_web_search_desligada(memory):
    client = FakeAnthropic([FakeResponse(content=[FakeTextBlock("ok")])])
    agent = _agent(client, memory, enable_web_search=False)
    await agent.respond(AgentRequest(chat_id=1, user_text="oi"))
    nomes = {t.get("name") for t in client.calls[0]["tools"]}
    assert "web_search" not in nomes


async def test_pause_turn_retoma(memory):
    client = FakeAnthropic(
        [
            FakeResponse(
                content=[FakeServerToolUseBlock(name="web_search")],
                stop_reason="pause_turn",
            ),
            FakeResponse(content=[FakeTextBlock("Encontrei, eu.")]),
        ]
    )
    agent = _agent(client, memory, enable_web_search=True)
    resp = await agent.respond(AgentRequest(chat_id=1, user_text="notícias de hoje?"))
    assert "Encontrei" in resp.text
    assert "web_search" in resp.tools_used
    assert len(client.calls) == 2  # pausou e retomou


async def test_summarize(memory):
    client = FakeAnthropic([FakeResponse(content=[FakeTextBlock("Um resumo curto.")])])
    agent = _agent(client, memory)
    out = await agent.summarize("conversa longa aqui")
    assert out == "Um resumo curto."
    assert client.calls[0]["output_config"] == {"effort": "low"}


async def test_captura_thinking(memory):
    client = FakeAnthropic(
        [
            FakeResponse(
                content=[FakeThinkingBlock("ponderei a Força"), FakeTextBlock("resposta")]
            )
        ]
    )
    agent = _agent(client, memory)
    resp = await agent.respond(AgentRequest(chat_id=1, user_text="oi"))
    assert resp.thinking == "ponderei a Força"
    assert resp.text == "resposta"


async def test_retry_em_erro_transitorio(memory):
    chamadas = {"n": 0}
    esperas: list[float] = []

    async def flaky(**kwargs):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise _Overloaded("sobrecarga")
        return FakeResponse(content=[FakeTextBlock("Recuperei, eu.")])

    async def spy_sleep(s):
        esperas.append(s)

    client = FakeAnthropic()
    client.messages.create = flaky  # type: ignore[assignment]
    agent = _agent(client, memory, sleeper=spy_sleep)

    resp = await agent.respond(AgentRequest(chat_id=1, user_text="oi"))
    assert resp.ok is True
    assert "Recuperei" in resp.text
    assert chamadas["n"] == 2  # falhou e tentou de novo
    assert len(esperas) == 1  # esperou uma vez (backoff)


async def test_nao_retry_em_erro_definitivo(memory):
    chamadas = {"n": 0}

    async def fails(**kwargs):
        chamadas["n"] += 1
        raise _BadRequest("requisição inválida")

    client = FakeAnthropic()
    client.messages.create = fails  # type: ignore[assignment]
    agent = _agent(client, memory)

    resp = await agent.respond(AgentRequest(chat_id=1, user_text="oi"))
    assert resp.ok is False  # vira fallback amigável
    assert chamadas["n"] == 1  # 400 não é retentável


async def test_esgota_retries(memory):
    chamadas = {"n": 0}

    async def always(**kwargs):
        chamadas["n"] += 1
        raise _Overloaded("sempre sobrecarregado")

    client = FakeAnthropic()
    client.messages.create = always  # type: ignore[assignment]
    agent = _agent(client, memory, max_retries=2, sleeper=_noop_sleep)

    resp = await agent.respond(AgentRequest(chat_id=1, user_text="oi"))
    assert resp.ok is False
    assert chamadas["n"] == 3  # 1 tentativa + 2 retentativas


async def test_compose_retorna_response_com_uso(memory):
    client = FakeAnthropic([FakeResponse(content=[FakeTextBlock("Bom dia!")])])
    agent = _agent(client, memory)
    resp = await agent.compose("monte o briefing")
    assert resp.ok is True
    assert resp.text == "Bom dia!"
    assert resp.usage  # contadores de tokens presentes
