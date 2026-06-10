import pytest

from mestre_yoda.protocol import BRIEFING, CHAT, AgentRequest, AgentResponse


def test_request_valido():
    req = AgentRequest(chat_id=1, user_text="olá", user_name="Luke")
    assert req.chat_id == 1
    assert req.metadata == {}
    assert req.kind == CHAT


def test_request_kind_briefing():
    req = AgentRequest(chat_id=1, user_text="briefing", kind=BRIEFING)
    assert req.kind == BRIEFING


def test_request_kind_invalido():
    with pytest.raises(ValueError):
        AgentRequest(chat_id=1, user_text="olá", kind="telepatia")


def test_request_texto_vazio():
    with pytest.raises(ValueError):
        AgentRequest(chat_id=1, user_text="   ")


def test_request_chat_id_tipo():
    with pytest.raises(TypeError):
        AgentRequest(chat_id="x", user_text="olá")  # type: ignore[arg-type]


def test_response_failure():
    resp = AgentResponse.failure("deu ruim")
    assert resp.ok is False
    assert resp.text == "deu ruim"


def test_response_ok_padrao():
    resp = AgentResponse(text="oi")
    assert resp.ok is True
    assert resp.tools_used == ()
