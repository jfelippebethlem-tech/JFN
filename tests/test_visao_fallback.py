"""Fallback de visão: ordem, teto, kill-switch e o motivo dizível. Tudo offline."""
import pytest

from compliance_agent.llm import visao

IMG = b"\xff\xd8\xff\xe0fake-jpeg"


@pytest.fixture(autouse=True)
def _zera(monkeypatch):
    """Cada teste começa com o contador limpo e as chaves controladas."""
    visao._gastas = 0
    for k in ("JFN_VISAO_OFF", "JFN_VISAO_TETO", "JFN_VISAO_PROVEDORES"):
        monkeypatch.delenv(k, raising=False)
    for k in ("OPENROUTER_API_KEY", "NVIDIA_API_KEY", "GEMINI_API_KEY", "GEMINI_API_KEYS",
              "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
        monkeypatch.setenv(k, "chave-de-teste")


def _falha_todos(monkeypatch):
    monkeypatch.setattr(visao, "_via_openai_compat", lambda *a, **k: (None, None))
    monkeypatch.setattr(visao, "_via_gemini", lambda *a, **k: (None, None))


def test_kill_switch_desliga_sem_gastar(monkeypatch):
    monkeypatch.setenv("JFN_VISAO_OFF", "1")
    r = visao.descrever(IMG, "oi")
    assert not r["ok"] and "desligado" in r["motivo"]
    assert visao.requisicoes_gastas() == 0


def test_teto_para_antes_de_chamar(monkeypatch):
    monkeypatch.setenv("JFN_VISAO_TETO", "2")
    _falha_todos(monkeypatch)
    for _ in range(3):
        visao.descrever(IMG, "oi")
    r = visao.descrever(IMG, "oi")
    assert not r["ok"] and "teto" in r["motivo"]


def test_primeiro_provedor_que_responde_encerra(monkeypatch):
    chamados = []

    def _oc(base, chave, modelos, img, prompt, mt):
        chamados.append(base)
        return "descrição", modelos[0]

    monkeypatch.setattr(visao, "_via_openai_compat", _oc)
    r = visao.descrever(IMG, "oi")
    assert r["ok"] and r["provedor"] == "openrouter"
    assert len(chamados) == 1, "não pode seguir consultando depois de obter resposta"


def test_cai_para_o_proximo_provedor(monkeypatch):
    """OpenRouter falha, NVIDIA responde — é o fallback fazendo o trabalho."""
    def _oc(base, chave, modelos, img, prompt, mt):
        return (None, None) if "openrouter" in base else ("veio da nvidia", modelos[0])

    monkeypatch.setattr(visao, "_via_openai_compat", _oc)
    r = visao.descrever(IMG, "oi")
    assert r["ok"] and r["provedor"] == "nvidia"
    assert visao.requisicoes_gastas() == 2


def test_restringir_provedores_respeita_a_lista(monkeypatch):
    """`JFN_VISAO_PROVEDORES=openrouter` é como ficar só no $0 estrutural."""
    monkeypatch.setenv("JFN_VISAO_PROVEDORES", "openrouter")
    _falha_todos(monkeypatch)
    visao.descrever(IMG, "oi")
    assert visao.requisicoes_gastas() == 1, "consultou provedor fora da lista pedida"


def test_sem_chave_nenhuma_diz_sem_provedor(monkeypatch):
    for k in ("OPENROUTER_API_KEY", "NVIDIA_API_KEY", "GEMINI_API_KEY", "GEMINI_API_KEYS",
              "CLOUDFLARE_API_TOKEN"):
        monkeypatch.setenv(k, "")
    r = visao.descrever(IMG, "oi")
    assert not r["ok"] and r["motivo"] == "sem provedor com chave"


def test_falha_de_todos_nao_se_confunde_com_ausencia(monkeypatch):
    """INDISPONÍVEL ≠ 0: 'todos falharam' e 'sem provedor' são estados diferentes."""
    _falha_todos(monkeypatch)
    r = visao.descrever(IMG, "oi")
    assert not r["ok"] and r["motivo"] == "todos os provedores falharam"


def test_nunca_levanta_excecao(monkeypatch):
    """Visão é enriquecimento — não pode derrubar a análise que a chamou."""
    def _explode(*a, **k):
        raise RuntimeError("provedor caiu")

    monkeypatch.setattr(visao, "_via_openai_compat", _explode)
    monkeypatch.setattr(visao, "_via_gemini", _explode)
    with pytest.raises(RuntimeError):
        visao._via_openai_compat()          # confirma que o dublê realmente levanta
    r = visao.descrever(IMG, "oi")
    assert r["ok"] is False


def test_modelos_openrouter_sao_todos_free():
    """Regra absoluta: no OpenRouter, SEMPRE `:free`."""
    assert all(m.endswith(":free") for m in visao.OPENROUTER_VISAO)
