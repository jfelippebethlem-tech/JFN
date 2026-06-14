# -*- coding: utf-8 -*-
"""Teste OFFLINE do detector de PROCESSOS-PAI de contratação (``tools/sei_pais.py``).

Sem browser, sem rede, sem prod DB: monta um cache temporário de cdp_*.json e verifica:
1. Pai citado no CONTEÚDO de um doc perto de palavra-chave ("processo de contratação em andamento
   de nº SEI-...") é detectado com confiança ALTA (o caso IDESI 010538 → 000821).
2. Refs do MENU lateral (boilerplate, repetidas em N páginas) são DESCARTADAS (denylist).
3. Um pai que JÁ está no cache NÃO é re-enfileirado (anti-duplicata).
4. O próprio número do docket nunca vira "pai".
"""
import json

import pytest

from tools import sei_pais


@pytest.fixture
def cache_tmp(tmp_path, monkeypatch):
    """Aponta o CACHE do módulo p/ um diretório temporário e devolve um writer de cdp_*.json."""
    cdir = tmp_path / "sei_cache"
    cdir.mkdir()
    monkeypatch.setattr(sei_pais, "CACHE", cdir)

    def escrever(numero: str, d: dict):
        d.setdefault("numero", numero)
        nome = "cdp_" + numero.replace("/", "_").replace("-", "_") + ".json"
        (cdir / nome).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    return escrever


# o MENU lateral do SEI (boilerplate) que aparece em TODA página — refs aqui são ruído
_MENU = " ".join(f"SEI-330005/{i:06d}/2026" for i in range(1, 6)) * 1


def test_detecta_pai_de_conteudo_com_keyword(cache_tmp):
    # docket de pagamento (IDESI-like) cujo despacho aponta o processo de contratação
    cache_tmp("SEI-080002/010538/2024", {
        "documentos": [{"url": "x"}],
        "texto": "MENU LATERAL " + _MENU,
        "conteudo_documentos": [{"conteudo":
            "Despacho. Importante mencionar que existe processo de contratação em andamento de "
            "nº SEI-080002/000821/2024 que virá a suprir a demanda ora em tela."}],
    })
    pais = sei_pais.detectar_pais()
    refs = {p["pai"]: p for p in pais}
    assert "SEI-080002/000821/2024" in refs
    assert refs["SEI-080002/000821/2024"]["confianca"] == "alta"
    assert refs["SEI-080002/000821/2024"]["fonte"] == "conteudo"


def test_boilerplate_do_menu_eh_descartado(cache_tmp):
    # 50 dockets cujo `texto` repete o MESMO conjunto de refs (menu) → denylist as exclui
    for k in range(50):
        cache_tmp(f"SEI-080002/{k:06d}/2024", {
            "documentos": [], "conteudo_documentos": [],
            "texto": "qualquer SEI-330005/000024/2026 SEI-330005/000005/2026 menu",
        })
    pais = sei_pais.detectar_pais()
    detectados = {p["pai"] for p in pais}
    assert "SEI-330005/000024/2026" not in detectados
    assert "SEI-330005/000005/2026" not in detectados


def test_pai_ja_em_cache_nao_reenfileira(cache_tmp):
    # docket cita 000821 no conteúdo, MAS 000821 já está no cache → não deve reaparecer na fila
    cache_tmp("SEI-080002/010538/2024", {
        "documentos": [{"url": "x"}], "texto": _MENU,
        "conteudo_documentos": [{"conteudo":
            "processo de contratação SEI-080002/000821/2024 referente ao contrato."}],
    })
    cache_tmp("SEI-080002/000821/2024", {"documentos": [{"url": "y"}], "texto": "ja lido"})
    pais = sei_pais.detectar_pais()
    assert "SEI-080002/000821/2024" not in {p["pai"] for p in pais}


def test_proprio_numero_nao_vira_pai(cache_tmp):
    cache_tmp("SEI-080002/010538/2024", {
        "documentos": [{"url": "x"}], "texto": _MENU,
        "conteudo_documentos": [{"conteudo":
            "processo de contratação SEI-080002/010538/2024 (este mesmo)."}],
    })
    pais = sei_pais.detectar_pais()
    assert "SEI-080002/010538/2024" not in {p["pai"] for p in pais}


def test_ref_sem_keyword_no_conteudo_nao_eh_alta(cache_tmp):
    # ref isolada no conteúdo SEM nenhuma palavra-chave de contratação por perto → não vira pai 'alta'
    cache_tmp("SEI-080002/010538/2024", {
        "documentos": [{"url": "x"}], "texto": _MENU,
        "conteudo_documentos": [{"conteudo":
            "Nota fiscal anexada. Ver também SEI-080002/000999/2024 para histórico de pagamento."}],
    })
    pais = sei_pais.detectar_pais()
    altos = {p["pai"] for p in pais if p["confianca"] == "alta"}
    assert "SEI-080002/000999/2024" not in altos


def test_formatos_reais_do_cache(cache_tmp):
    # regressão: grafias REAIS vistas no cache ao vivo — 'nºSEI-' sem espaço + NBSP (caso IDESI), e o
    # padrão '·Processo Principal nº SEI-...'. Ambas têm de virar pai ALTA (regex + janela de keyword).
    cache_tmp("SEI-330002/049435/2025", {
        "documentos": [{"url": "x"}], "texto": _MENU,
        "conteudo_documentos": [{"conteudo":
            "análise, a saber: ·Processo nº SEI-330002/049435/2025 "
            "·Processo Principal nº SEI-330002/003168/2024 ·Órgão: DER."}],
    })
    cache_tmp("SEI-080002/099999/2024", {
        "documentos": [{"url": "x"}], "texto": _MENU,
        "conteudo_documentos": [{"conteudo":
            "existe processo de contratação em andamento de nºSEI-080002/000821/2024 "
            "que virá a suprir a demanda."}],
    })
    altos = {p["pai"] for p in sei_pais.detectar_pais() if p["confianca"] == "alta"}
    assert "SEI-330002/003168/2024" in altos
    assert "SEI-080002/000821/2024" in altos
