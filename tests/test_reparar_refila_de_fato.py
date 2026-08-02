# -*- coding: utf-8 -*-
"""Reparar não é mover cache: é fazer o processo VOLTAR À FILA.

Bug real (2026-08-02, meu): o requeue afastava o cache para a quarentena mas só zerava o
progress `if numero in feitos`. O `_pular` do `sei_sweep` decide por `n_docs > 0` no progress —
então 54 processos ficaram no pior estado possível: **sem cache E marcados como lidos**, ou
seja, nunca mais seriam capturados nem teriam o texto antigo. Construir, testar o dry-run e não
verificar o EFEITO é a família [[construido-testado-nunca-rodado]].

O contrato que estes testes travam: depois de reparar, o processo tem `n_docs == 0` no
progress — existisse ou não a chave antes.
"""
import json
from datetime import datetime

import pytest

from tools import sei_reparar_truncados as R


@pytest.fixture()
def ambiente(tmp_path, monkeypatch):
    cache = tmp_path / "sei_cache"
    cache.mkdir()
    prog = cache / "sei_sweep_progress.json"
    monkeypatch.setattr(R, "RAIZ", tmp_path)
    monkeypatch.setattr(R, "CACHE", cache)
    monkeypatch.setattr(R, "PROGRESS", prog)
    monkeypatch.setattr(R, "QUARENTENA", cache / "_truncados")
    return cache, prog


def _cache_truncado(cache, tag="270131_000140_2023"):
    p = cache / f"cdp_SEI_{tag}.json"
    p.write_text(json.dumps({"numero": f"SEI-{tag.replace('_', '/')}",
                             "documentos": [{"i": 0}], "conteudo_documentos": []}), encoding="utf-8")
    return p


def test_processo_ja_no_progress_volta_com_n_docs_zero(ambiente):
    cache, prog = ambiente
    _cache_truncado(cache)
    prog.write_text(json.dumps({"feitos": {"SEI-270131/000140/2023": {"n_docs": 55, "tentativas": 1}}}))
    R.reparar(aplicar=True)
    feitos = json.loads(prog.read_text())["feitos"]
    assert feitos["SEI-270131/000140/2023"]["n_docs"] == 0, "continuaria sendo pulado pelo sweep"


def test_processo_AUSENTE_do_progress_tambem_e_marcado(ambiente):
    """Era a brecha: sem a chave, o antigo `if numero in feitos` não escrevia nada — e o cache
    já tinha ido para a quarentena. Marcar é barato e torna o estado explícito."""
    cache, prog = ambiente
    _cache_truncado(cache)
    prog.write_text(json.dumps({"feitos": {}}))
    R.reparar(aplicar=True)
    feitos = json.loads(prog.read_text())["feitos"]
    assert feitos.get("SEI-270131/000140/2023", {}).get("n_docs") == 0


def test_cap_refila_mesmo_sem_chave_previa(ambiente):
    cache, prog = ambiente
    tag = "080002_012345_2024"
    (cache / f"cdp_SEI_{tag}.json").write_text("{}", encoding="utf-8")
    (tmp := R.RAIZ / "data").mkdir(parents=True, exist_ok=True)
    (tmp / "recaptura_cap21k.json").write_text(json.dumps({"processos": [tag], "prioridade": []}))
    prog.write_text(json.dumps({"feitos": {}}))
    r = R.reparar_cap(aplicar=True, max_n=5)
    assert r["encontrados"] == 1
    feitos = json.loads(prog.read_text())["feitos"]
    assert feitos["SEI-080002/012345/2024"]["n_docs"] == 0
    assert "reparado_cap21k_em" in feitos["SEI-080002/012345/2024"]


def test_o_cache_vai_para_quarentena_e_nao_some(ambiente):
    """Nada se apaga: o cache tem de estar auditável na quarentena."""
    cache, prog = ambiente
    p = _cache_truncado(cache)
    prog.write_text(json.dumps({"feitos": {}}))
    R.reparar(aplicar=True)
    assert not p.exists()
    assert (cache / "_truncados" / p.name).exists()


def test_dry_run_nao_toca_em_nada(ambiente):
    cache, prog = ambiente
    p = _cache_truncado(cache)
    prog.write_text(json.dumps({"feitos": {"SEI-270131/000140/2023": {"n_docs": 55}}}))
    antes = prog.read_text()
    R.reparar(aplicar=False)
    assert p.exists() and prog.read_text() == antes


def test_marca_de_reparo_registra_quando(ambiente):
    cache, prog = ambiente
    _cache_truncado(cache)
    prog.write_text(json.dumps({"feitos": {}}))
    R.reparar(aplicar=True)
    ent = json.loads(prog.read_text())["feitos"]["SEI-270131/000140/2023"]
    datetime.fromisoformat(ent["reparado_truncado_em"])       # tem de ser ISO parseável
