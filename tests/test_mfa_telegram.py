# -*- coding: utf-8 -*-
"""Testes do fluxo MFA-via-Telegram (envio + captura passiva), sem rede e sem dormir de verdade."""
import compliance_agent.mfa_telegram as mfa


class _Clock:
    """Relógio falso: avança quando o código 'dorme'. Faz o loop terminar sem time.sleep real."""
    def __init__(self, t0=1000.0):
        self.t = t0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


# ───────────────────────── extrair_codigo ─────────────────────────

def test_extrair_codigo_puro():
    assert mfa.extrair_codigo("123456") == "123456"


def test_extrair_codigo_em_frase():
    assert mfa.extrair_codigo("o codigo e 8421 ok") == "8421"


def test_extrair_codigo_remove_quote():
    # _texto_resposta tira o quote do Telegram antes de extrair
    assert mfa.extrair_codigo('[Replying to: "🔐 SIAFE codigo"] 778899') == "778899"


def test_extrair_codigo_ignora_texto_sem_numero():
    assert mfa.extrair_codigo("liberei o siafe") is None


def test_extrair_codigo_ignora_numero_grande():
    # CNPJ de 14 dígitos não é código MFA (\b…\b de 4-8 não casa o bloco de 14)
    assert mfa.extrair_codigo("28470707000180") is None


# ───────────────────────── pedir_codigo_mfa ─────────────────────────

def test_pedir_captura_do_telegram(monkeypatch, tmp_path):
    enviados = []
    monkeypatch.setattr(mfa, "notificar", lambda txt: enviados.append(txt) or True)
    monkeypatch.setattr(mfa, "CODE_FILE", tmp_path / ".mfa_code")
    monkeypatch.setattr(mfa, "DATA", tmp_path)
    # o dono responde "654321" no Telegram (1 mensagem nova)
    monkeypatch.setattr(mfa, "mensagens_novas_telegram", lambda desde, state_db=None: [(desde + 1, "654321")])
    clk = _Clock()
    cod = mfa.pedir_codigo_mfa("SIAFE", timeout_s=300, poll_s=5, _agora=clk.now, _sleep=clk.sleep)
    assert cod == "654321"
    assert any("MFA" in t for t in enviados)          # pediu
    assert (tmp_path / ".mfa_code").read_text().strip() == "654321"   # gravou p/ auditoria


def test_pedir_fallback_arquivo(monkeypatch, tmp_path):
    monkeypatch.setattr(mfa, "notificar", lambda txt: True)
    cf = tmp_path / ".mfa_code"
    monkeypatch.setattr(mfa, "CODE_FILE", cf)
    monkeypatch.setattr(mfa, "DATA", tmp_path)
    monkeypatch.setattr(mfa, "mensagens_novas_telegram", lambda desde, state_db=None: [])
    # código posto manualmente (SSH) DEPOIS do unlink inicial: simula escrevendo no 1º sleep
    clk = _Clock()
    orig_sleep = clk.sleep

    def sleep_e_escreve(s):
        cf.write_text("4815")
        clk.sleep = orig_sleep        # só escreve uma vez
        orig_sleep(s)
    clk.sleep = sleep_e_escreve
    cod = mfa.pedir_codigo_mfa("SEI", timeout_s=300, poll_s=5, _agora=clk.now, _sleep=clk.sleep)
    assert cod == "4815"


def test_pedir_timeout_retorna_none(monkeypatch, tmp_path):
    avisos = []
    monkeypatch.setattr(mfa, "notificar", lambda txt: avisos.append(txt) or True)
    monkeypatch.setattr(mfa, "CODE_FILE", tmp_path / ".mfa_code")
    monkeypatch.setattr(mfa, "DATA", tmp_path)
    monkeypatch.setattr(mfa, "mensagens_novas_telegram", lambda desde, state_db=None: [])
    clk = _Clock()
    cod = mfa.pedir_codigo_mfa("SIAFE", timeout_s=30, poll_s=5, _agora=clk.now, _sleep=clk.sleep)
    assert cod is None
    assert any("não recebi" in t.lower() for t in avisos)
