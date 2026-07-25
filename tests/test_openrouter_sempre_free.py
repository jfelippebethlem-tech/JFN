"""Regra ABSOLUTA do dono: no OpenRouter, SEMPRE `:free`. Sem exceção.

O guard vivia só nos wrappers (`openrouter_chat` etc.). Quem chamasse `_openai_compat_chat_sync`
direto passava por fora — e era o caso de `verificacao_endereco._vlm_classificar`, que mandava
toda análise de fachada para `google/gemini-2.5-flash-lite`, modelo PAGO (não tem variante
`:free`). A conta é `is_free_tier: False`, então cobrança ia direto.
"""
import httpx
import pytest

from compliance_agent.llm import free_llm


def _captura_modelo(monkeypatch) -> dict:
    """Intercepta o POST e devolve o que FOI ENVIADO — sem tocar a rede."""
    enviado: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            enviado.update(json or {})
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    return enviado


@pytest.mark.parametrize("pedido", [
    "google/gemini-2.5-flash-lite",          # o default que estava em produção
    "anthropic/claude-opus-4",
    "openai/gpt-4o",
])
def test_openrouter_forca_free_mesmo_chamando_a_funcao_baixa(monkeypatch, pedido):
    enviado = _captura_modelo(monkeypatch)
    free_llm._openai_compat_chat_sync(free_llm.OPENROUTER_BASE, "k", pedido, [{"role": "user", "content": "oi"}])
    assert enviado["model"].endswith(":free"), f"modelo PAGO escapou: {enviado['model']}"


def test_free_ja_pedido_nao_e_alterado(monkeypatch):
    enviado = _captura_modelo(monkeypatch)
    free_llm._openai_compat_chat_sync(free_llm.OPENROUTER_BASE, "k", "google/gemma-4-31b-it:free",
                                      [{"role": "user", "content": "oi"}])
    assert enviado["model"] == "google/gemma-4-31b-it:free"


def test_outros_provedores_nao_ganham_sufixo(monkeypatch):
    """`:free` é sufixo do OpenRouter — pôr em Groq/Cerebras quebraria o modelo."""
    enviado = _captura_modelo(monkeypatch)
    free_llm._openai_compat_chat_sync(free_llm.GROQ_BASE, "k", "llama-3.3-70b-versatile",
                                      [{"role": "user", "content": "oi"}])
    assert enviado["model"] == "llama-3.3-70b-versatile"


def test_default_de_visao_da_fachada_e_free():
    """O default do código é o que roda: o `.env` não define `OPENROUTER_VISION_MODEL`."""
    import inspect

    from compliance_agent import verificacao_endereco
    src = inspect.getsource(verificacao_endereco._vlm_classificar)
    assert 'OPENROUTER_VISION_MODEL", "' in src
    default = src.split('OPENROUTER_VISION_MODEL", "')[1].split('"')[0]
    assert default.endswith(":free"), f"default de visão é PAGO: {default}"
