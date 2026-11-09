"""Nemotron 3.x é modelo de RACIOCÍNIO: com teto de 300 tokens devolvia content VAZIO (finish 'length') e a
visão inteira do OpenRouter falhava (medido 09/11/2026). Cada provedor desliga o raciocínio por uma chave."""
from compliance_agent.llm.free_llm import _sem_raciocinio


def test_openrouter_nemotron_desliga_raciocinio():
    p = {"model": "nvidia/nemotron-3.5-super-vl:free"}
    _sem_raciocinio("https://openrouter.ai/api/v1", p)
    assert p["reasoning"] == {"enabled": False}


def test_nvidia_nemotron_desliga_pelo_template():
    p = {"model": "nvidia/nemotron-3.5-super-vl-120b-a12b"}
    _sem_raciocinio("https://integrate.api.nvidia.com/v1", p)
    assert p["chat_template_kwargs"] == {"enable_thinking": False}


def test_outros_modelos_intactos():
    p = {"model": "qwen/qwen3.8-27b"}
    _sem_raciocinio("https://openrouter.ai/api/v1", p)
    assert p == {"model": "qwen/qwen3.8-27b"}
