# -*- coding: utf-8 -*-
"""Compressão do cache SEI: nada se perde, o estado VIVO não é tocado, e falha PRESERVA o original.

CONTEXTO. `data/sei_cache/` chegou a **25,2 GB**, dos quais **23,1 GB em 5.965 blobs `cdp_*.json`**
(91,6%) contra 180 MB do texto já extraído — razão de 128×. A política de poda existia
(`sei/indice.podar_cache`) e **nunca teve um caller**; o docstring dela prometia podar `json` que o
código não tocava. A ordem do dono é: nada é apagado, tudo em arquivos menores.

O DEFEITO QUE ESTES TESTES TRAVAM. `comprimir_caches` validava o comprimido por `tamanho > 0` e
removia o original. Um `.gz`/`.zst` truncado tem tamanho > 0 — a validação passava e o original ia
embora. Agora a prova é o sha256 do conteúdo DESCOMPRIMIDO, e qualquer falha preserva o original.

E o diretório NÃO é só cache: ali moram `siafe_state.json` (evita MFA por ~30 dias), o lock de
coleta, os checkpoints de OB, o `.mfa_code` e o progresso do sweep. Um `find -name '*.json' -delete`
mataria dias de captura.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

import pytest

from compliance_agent.sei import cache_arquivo as CA


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    """`data/` de mentira com um blob antigo, estado vivo e um blob recente."""
    import compliance_agent.manutencao as M

    (tmp_path / "sei_cache").mkdir()
    monkeypatch.setattr(M, "_DATA", tmp_path)
    c = tmp_path / "sei_cache"
    antigo = time.time() - 72 * 3600

    (c / "cdp_SEI_260007_004415_2025.json").write_text(
        json.dumps({"texto": "AB" * 5000, "documentos": [1, 2, 3]}), encoding="utf-8")
    (c / "siafe_state.json").write_text('{"cookies": "nao-me-toque"}', encoding="utf-8")
    (c / "sei_sweep_progress.json").write_text('{"feitos": {"x": 1}}', encoding="utf-8")
    (c / "cdp_SEI_999_recente.json").write_text('{"a": 1}' * 2000, encoding="utf-8")

    for nome in ("cdp_SEI_260007_004415_2025.json", "siafe_state.json", "sei_sweep_progress.json"):
        os.utime(c / nome, (antigo, antigo))
    return c


def test_estado_vivo_do_siafe_e_do_sweep_nunca_e_comprimido(cache):
    """Se `siafe_state.json` for tocado, a próxima coleta pede MFA — e o sweep perde o progresso."""
    import compliance_agent.manutencao as M

    res = M.comprimir_cache_sei(idade_horas=48.0)
    assert (cache / "siafe_state.json").read_text(encoding="utf-8") == '{"cookies": "nao-me-toque"}'
    assert (cache / "sei_sweep_progress.json").exists()
    assert not (cache / "siafe_state.json.zst").exists()
    assert res["pulados"]["estado_vivo"] == 2


def test_blob_dentro_do_ttl_de_leitura_fica_intacto(cache):
    """`collectors/sei_cdp.py` reusa cache com menos de 24 h — comprimir dentro da janela é desperdício."""
    import compliance_agent.manutencao as M

    res = M.comprimir_cache_sei(idade_horas=48.0)
    assert (cache / "cdp_SEI_999_recente.json").exists()
    assert res["pulados"]["recente"] == 1


def test_compressao_preserva_o_conteudo_byte_a_byte(cache):
    """A prova é o sha256 do descomprimido — não o tamanho do arquivo."""
    import compliance_agent.manutencao as M

    alvo = cache / "cdp_SEI_260007_004415_2025.json"
    sha_antes = hashlib.sha256(alvo.read_bytes()).hexdigest()

    M.comprimir_cache_sei(idade_horas=48.0)

    assert not alvo.exists(), "o original deveria ter saído depois da prova"
    assert (cache / "cdp_SEI_260007_004415_2025.json.zst").exists()
    assert hashlib.sha256(CA.ler_bytes(alvo)).hexdigest() == sha_antes


def test_leitura_e_transparente_para_quem_consome(cache):
    """`relacionados.py` lê blob de QUALQUER idade — é ele que a compressão cegaria."""
    import compliance_agent.manutencao as M

    alvo = cache / "cdp_SEI_260007_004415_2025.json"
    M.comprimir_cache_sei(idade_horas=48.0)

    assert CA.localizar(alvo) is not None
    assert CA.ler_json(alvo)["documentos"] == [1, 2, 3]
    nomes = {CA.nome_logico(p) for p in CA.glob_cache(cache, "cdp_SEI_*.json")}
    assert "cdp_SEI_260007_004415_2025.json" in nomes


def test_verificacao_que_falha_PRESERVA_o_original(cache, monkeypatch):
    """O defeito original: `tamanho > 0` aceitava comprimido truncado e apagava o dado.

    Aqui a verificação é sabotada de propósito. O contrato é: original PRESERVADO, comprimido
    removido, contador de abortos em 1 — e **nenhum byte perdido**.
    """
    import compliance_agent.manutencao as M

    alvo = cache / "cdp_SEI_260007_004415_2025.json"
    conteudo = alvo.read_bytes()
    monkeypatch.setattr(M, "_sha256_descomprimido", lambda *a, **k: "sha-que-nao-bate")

    res = M.comprimir_cache_sei(idade_horas=48.0)

    assert alvo.exists(), "verificação falhou e o original FOI APAGADO — é exatamente o bug antigo"
    assert alvo.read_bytes() == conteudo
    assert not (cache / "cdp_SEI_260007_004415_2025.json.zst").exists()
    assert res["pulados"]["abortado"] == 1
    assert res["arquivos"] == []


def test_a_whitelist_cobre_os_prefixos_que_os_callers_realmente_usam():
    """Guarda contra alguém renomear um prefixo de estado e a compressão passar a comer captura.

    Os nomes vêm dos callers: siafe_session/siafe_coord/siafe_ob_orcamentaria/siafe_runner,
    mfa_telegram, rotas/sistema.py e server.py.
    """
    for nome in ("siafe_state.json", "siafe_lock.json", "siafe_coord.json", "siafe_mfa.json",
                 "sei_sweep_progress.json", "sei_sweep_loop.out", ".mfa_code",
                 "ob_orcamentaria_checkpoint.json", "uggrande_133100_2025.json",
                 "mgsclean_obs_2025.json", "manifest.json"):
        assert CA.eh_estado_vivo(nome), f"{nome} saiu da whitelist — captura viva em risco"
    assert not CA.eh_estado_vivo("cdp_SEI_260007_004415_2025.json")


def test_json_invalido_devolve_None_e_nao_dicionario_vazio(tmp_path):
    """`{}` diria "processo sem relacionados"; `None` diz "não consegui ler". Vazio ≠ ausente."""
    ruim = tmp_path / "cdp_SEI_x.json"
    ruim.write_text("{isto nao e json", encoding="utf-8")
    assert CA.ler_json(ruim) is None
    assert CA.ler_json(tmp_path / "nao_existe.json") is None
