"""Senha do SIAFE recusada não é tentada de novo enquanto o .env não mudar (18/11/2026: o diário tentou a mesma
senha recusada em 16, 17 e 18/11 — três logins errados seguidos aproximam o bloqueio do usuário do dono)."""
from compliance_agent import siafe_ob_orcamentaria as M


def test_trava_por_impressao_da_senha(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "_TRAVA_SENHA", tmp_path / "siafe_senha_recusada.json")
    assert M._senha_bloqueada("usuario", "senhaA") is False
    M._registrar_recusa("usuario", "senhaA")
    txt = (tmp_path / "siafe_senha_recusada.json").read_text()
    assert "senhaA" not in txt                              # nunca a senha em disco
    assert M._senha_bloqueada("usuario", "senhaA") is True  # mesma senha: não tenta
    assert M._senha_bloqueada("usuario", "senhaB") is False  # dono trocou no .env: tenta
    M._liberar_senha()
    assert M._senha_bloqueada("usuario", "senhaA") is False
