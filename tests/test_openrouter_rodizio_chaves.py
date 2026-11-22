"""Dono 22/11/2026: cada e-mail do OpenRouter tem uma chave com cota grátis SEPARADA — usar todas, em rodízio.
A chave que estourar o limite DIÁRIO dos :free (429 'free-models-per-day') sai até a virada UTC e a próxima assume."""
import httpx

from compliance_agent.llm import free_llm as F

A, B, C = "sk-or-v1-" + "a" * 64, "sk-or-v1-" + "b" * 64, "sk-or-v1-" + "c" * 64
CORPO_DIARIO = '{"error":{"message":"Rate limit exceeded: free-models-per-day. Add 10 credits","code":429}}'


def _amb(monkeypatch, tmp_path):
    monkeypatch.setattr(F, "_OR_ESGOTADAS", tmp_path / "or_esgotadas.json")
    monkeypatch.setenv("OPENROUTER_API_KEY", A)
    monkeypatch.setenv("OPENROUTER_API_KEY_RESERVA", B)
    monkeypatch.setenv("OPENROUTER_API_KEY_2", C)
    monkeypatch.setenv("OPENROUTER_API_KEY_3", A)          # repetida não conta duas vezes


def test_pool_ordem_sem_repeticao(monkeypatch, tmp_path):
    _amb(monkeypatch, tmp_path)
    assert F._openrouter_chaves() == [A, B, C]
    assert F._openrouter_key() == A


def test_429_diario_esgota_a_chave_e_a_proxima_assume(monkeypatch, tmp_path):
    _amb(monkeypatch, tmp_path)
    assert F.notar_openrouter(A, 429, CORPO_DIARIO) is True
    assert F._openrouter_key() == B
    assert F.notar_openrouter(B, 429, "upstream temporarily rate-limited") is False   # 429 passageiro não esgota
    assert F._openrouter_key() == B
    F.notar_openrouter(B, 429, CORPO_DIARIO)
    F.notar_openrouter(C, 429, CORPO_DIARIO)
    assert F._openrouter_key() == A                        # todas esgotadas: devolve a 1ª (o 429 segue honesto)


def test_esgotada_volta_na_virada_utc(monkeypatch, tmp_path):
    _amb(monkeypatch, tmp_path)
    F.notar_openrouter(A, 429, CORPO_DIARIO)
    monkeypatch.setattr(F, "_dia_utc", lambda: "2099-01-01")
    assert F._openrouter_key() == A


def test_chamada_troca_de_chave_no_429_diario_sem_esperar(monkeypatch, tmp_path):
    _amb(monkeypatch, tmp_path)
    usadas = []

    class Cli:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json, headers):
            k = headers["Authorization"].split()[-1]
            usadas.append(k)
            req = httpx.Request("POST", url)
            if k == A:
                return httpx.Response(429, text=CORPO_DIARIO, request=req)
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}, request=req)

    monkeypatch.setattr(F.httpx, "Client", Cli)
    monkeypatch.setattr(F, "_sleep_backoff", lambda *a, **k: (_ for _ in ()).throw(AssertionError("esperou")))
    r = F._openai_compat_chat_sync_retry(F.OPENROUTER_BASE, A, "x/y:free", [{"role": "user", "content": "oi"}])
    assert r == "ok" and usadas == [A, B]


def test_chave_nunca_vai_ao_arquivo_de_estado(monkeypatch, tmp_path):
    _amb(monkeypatch, tmp_path)
    F.notar_openrouter(A, 429, CORPO_DIARIO)
    assert A not in (tmp_path / "or_esgotadas.json").read_text()
