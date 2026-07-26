# -*- coding: utf-8 -*-
"""Leitor do SEI da Prefeitura do Rio (prefeitura.sei.rio) — helpers puros.

O SEI municipal é independente do SEI-RJ estadual (itkava) e do SIGA (acesso.processo.rio,
que tem reCAPTCHA vetado). A pesquisa pública saiu do 404 e responde em
prefeitura.sei.rio, atrás de defesa anti-bot F5 (exige browser real) + captcha de imagem
(resolvido por OCR, reusando compliance_agent.captcha_solver via sei_cdp).

Estes testes travam a parte PURA (formato de nº de processo SEI.RIO e montagem da URL);
a leitura ao vivo é browser-dependente e validada em execução supervisionada.
"""
import pytest

from compliance_agent.pcrj.sei_prefeitura import (
    normalizar_processo,
    processo_valido,
    url_pesquisa_publica,
)


@pytest.mark.parametrize("bruto,limpo", [
    ("000900.048716/2026-91", "000900.048716/2026-91"),
    ("  000900.048716 / 2026-91 ", "000900.048716/2026-91"),
    ("Processo nº.: 000900.048716/2026-91", "000900.048716/2026-91"),
    ("01300.002091/2026-43", "01300.002091/2026-43"),
])
def test_normaliza_processo_seirio(bruto, limpo):
    assert normalizar_processo(bruto) == limpo


def test_processo_invalido_retorna_none():
    assert normalizar_processo("sem numero aqui") is None
    assert normalizar_processo("") is None


def test_processo_valido():
    assert processo_valido("000900.048716/2026-91") is True
    assert processo_valido("09/002.991/2022") is False   # formato SIGA, não SEI.RIO
    assert processo_valido("lixo") is False


def test_url_pesquisa_aponta_para_prefeitura_sei_rio():
    u = url_pesquisa_publica()
    assert u.startswith("https://prefeitura.sei.rio/")
    assert "md_pesq_processo_pesquisar.php" in u
    assert "protocolo_pesquisar" in u
