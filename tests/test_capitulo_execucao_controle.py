# -*- coding: utf-8 -*-
"""Capítulo do dossiê que LIGA os módulos novos ao produto (wiring, 2026-07-24).

Sem isto, `execucao_sinais`, `execucao_cerebro`, `nfe_verifica`, `parecer_cumprimento` e `foto_medicao`
ficam órfãos: passam nos testes e não chegam a lugar nenhum. O capítulo roda os cinco sobre os processos
SEI já capturados do fornecedor e devolve um bloco do dossiê no padrão da casa.
"""
from __future__ import annotations

import json

import pytest

from compliance_agent.reporting import capitulos_dossie as CD


def _processo(base, numero, docs):
    """Cria um processo no formato do arquivo SEI (manifest.json + texto/)."""
    pdir = base / CD._slug_processo(numero)
    (pdir / "texto").mkdir(parents=True)
    manifest = {"docs": []}
    for i, (titulo, tipo, conteudo) in enumerate(docs):
        rel = f"texto/{i:03d}.txt"
        (pdir / rel).write_text(conteudo, encoding="utf-8")
        manifest["docs"].append({"i": i, "titulo": titulo, "tipo": tipo, "fase": "", "texto": rel})
    (pdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return pdir


@pytest.fixture()
def arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(CD, "_ARQUIVO_SEI", tmp_path)
    return tmp_path


def test_sem_arquivo_capturado_devolve_none(arquivo):
    assert CD.secao_execucao_controle_previo(["SEI-999999/000001/2024"]) is None


def test_pagamento_sem_prova_de_entrega_aparece_no_capitulo(arquivo):
    _processo(arquivo, "SEI-120001/000001/2024", [
        ("Nota de Empenho", "empenho", "Nota de Empenho 2024NE000123."),
        ("Ordem Bancária", "ob", "Ordem Bancária 2024OB000456 paga ao fornecedor. "
                                 "Despacho de encaminhamento para pagamento."),
    ])
    s = CD.secao_execucao_controle_previo(["SEI-120001/000001/2024"])
    assert s and "html" in s
    h = s["html"].lower()
    assert "execução" in s["titulo"].lower()
    assert "medi" in h and ("nota fiscal" in h or "atesto" in h)     # diz o que falta
    assert "indício" in h or "fragilidade" in h                       # honesto


def test_condicionante_da_pge_nao_cumprida_aparece(arquivo):
    _processo(arquivo, "SEI-120001/000002/2024", [
        ("Parecer PGE 10/2024", "parecer",
         "PARECER Nº 10/2024 — PROCURADORIA GERAL DO ESTADO. Opino favoravelmente desde que: "
         "(i) seja juntada a pesquisa de preços com três cotações; "
         "(ii) conste a declaração de adequação orçamentária com a dotação."),
        ("Termo de Homologação", "homologacao", "Homologo o resultado do certame e adjudico o objeto."),
    ])
    s = CD.secao_execucao_controle_previo(["SEI-120001/000002/2024"])
    h = s["html"]
    assert "PGE" in h or "parecer" in h.lower()
    assert "condicionante" in h.lower()
    assert "53" in h                                   # cita o art. 53 da Lei 14.133


def test_nfe_em_contingencia_e_apontada(arquivo):
    from compliance_agent.nfe_verifica import digito_verificador
    base = "33" "2405" "05506560000136" "55" "001" "000123456" "4" "12345678"   # tpEmis 4 = EPEC
    chave = base + str(digito_verificador(base))
    _processo(arquivo, "SEI-120001/000003/2024", [
        ("Nota Fiscal", "nf", f"Ordem Bancária 2024OB000999. Nota fiscal eletrônica chave {chave}. "
                              "Boletim de medição. Atesto do fiscal. Relatório fotográfico."),
    ])
    h = CD.secao_execucao_controle_previo(["SEI-120001/000003/2024"])["html"]
    assert "conting" in h.lower()


def test_processo_regular_nao_inventa_achado(arquivo):
    _processo(arquivo, "SEI-120001/000004/2024", [
        ("Despacho", "despacho", "Encaminho o processo para instrução."),
    ])
    s = CD.secao_execucao_controle_previo(["SEI-120001/000004/2024"])
    h = (s or {}).get("html", "").lower()
    assert "vermelho" not in h or "não" in h            # sem pagamento não se acusa execução
