# -*- coding: utf-8 -*-
"""O8.4 — os avisos calados pelo silêncio de 17/11 (data/telegram_silenciado.jsonl) fechados na ORIGEM.

Catraca: classe `fechado` em config/avisos_calados.yaml tem PROVA no produtor (o envio não está mais lá, ou o
conserto está); `registrado` tem ação humana. O sensor da automelhoria mede o EFEITO: aviso fechado que volta a ser
calado reabre o item; aviso sem classe não some."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from tools import automelhoria_geral as A  # noqa: E402

CLASSES = yaml.safe_load((RAIZ / "config" / "avisos_calados.yaml").read_text(encoding="utf-8"))["classes"]
AGORA = datetime(2026, 11, 26, 12, 0).timestamp()


def test_registro_bem_formado_e_contagem_do_plano():
    for cid, c in CLASSES.items():
        assert {"origem", "padrao", "n_ate_20261124", "causa", "destino", "estado"} <= set(c), cid
        assert c["estado"] in ("fechado", "registrado"), cid
        if c["estado"] == "fechado":
            assert c.get("produtor") and c.get("fechado_em") and (c.get("marcador") or c.get("marcador_presente")), cid
        else:
            assert c.get("acao_humana"), cid
    assert sum(c["n_ate_20261124"] for c in CLASSES.values()) == 107          # 101 do plano + 6 até 24/11 12h29


@pytest.mark.parametrize("cid", sorted(k for k, c in CLASSES.items() if c["estado"] == "fechado"))
def test_fechado_na_origem_tem_prova_no_produtor(cid):
    c = CLASSES[cid]
    texto = (RAIZ / c["produtor"]).read_text(encoding="utf-8")
    if c.get("marcador"):
        assert c["marcador"] not in texto, f"{c['produtor']} voltou a montar o aviso '{cid}'"
    if c.get("marcador_presente"):
        assert c["marcador_presente"] in texto, f"{c['produtor']} perdeu o conserto de '{cid}'"


@pytest.mark.parametrize("origem,inicio,esperado", [
    ("automelhoria", "🔁 Automelhoria: 1 problema(s) novo(s)", "automelhoria-novidades"),
    ("ronda", "🔴 <b>systemd</b>: <b>jfn-ronda.service</b> FALHOU", "systemd-onfailure"),
    ("ronda", "🛡️ <b>JFN — ronda</b>\n🚨 <b>7 novo(s)", "ronda-eventos"),
    ("ronda", "🩺 <b>SLO de pipelines</b>\n🔴", "slo-pipelines"),
    ("?", "🔴 Pipelines PCRJ com falha (3):", "pcrj-saude"),
    ("digest_diario", "🛡️ *Digest de fiscalização — 17/11/2026*", "digest-diario"),
    ("__main__", "16. FULANO DE TAL [***.000.000-**] — EMPRESA X", "socios-cpf-captcha"),
    ("nova_origem", "qualquer coisa", None),
])
def test_classificacao(origem, inicio, esperado):
    assert A.classe_do_aviso({"origem": origem, "inicio": inicio}, CLASSES) == esperado


def test_fechado_que_volta_reabre_e_antigo_nao():
    antigo = {"t": "2026-11-20 10:00:00", "origem": "automelhoria", "inicio": "🔁 Automelhoria: x"}
    assert A.avaliar_avisos([antigo], CLASSES, AGORA) == []
    volta = {**antigo, "t": "2026-11-25 10:00:00"}
    ps = A.avaliar_avisos([antigo, volta], CLASSES, AGORA)
    assert [p["assinatura"] for p in ps] == ["aviso:automelhoria-novidades"] and "VOLTOU" in ps[0]["titulo"]


def test_registrado_recente_vira_item_e_velho_nao():
    ln = {"t": "2026-11-25 07:00:00", "origem": "digest_diario", "inicio": "🛡️ *Digest de fiscalização"}
    ps = A.avaliar_avisos([ln], CLASSES, AGORA)
    assert ps[0]["assinatura"] == "aviso:digest-diario" and ps[0]["acao_humana"].startswith("dono decide")
    assert A.avaliar_avisos([{**ln, "t": "2026-11-01 07:00:00"}], CLASSES, AGORA) == []


def test_sem_classe_nao_some():
    ps = A.avaliar_avisos([{"t": "2026-11-25 07:00:00", "origem": "x", "inicio": "?"}], CLASSES, AGORA)
    assert [p["assinatura"] for p in ps] == ["aviso:sem-classe"] and "x" in ps[0]["detalhe"]


def test_quedas_systemd_inclusive_a_que_ja_voltou():
    q = lambda t, u="jfn.service", e="active": {"t": t, "unidade": u, "estado": e, "nrestarts": "3"}  # noqa: E731
    ps = A.avaliar_quedas_systemd([q("2026-11-25 01:00:00"), q("2026-11-25 05:00:00"), q("2026-11-25 06:00:00", "k")],
                                  AGORA)
    assert [p["assinatura"] for p in ps] == ["systemd-queda:jfn.service"] and "2×" in ps[0]["titulo"]
    assert A.avaliar_quedas_systemd([q("2026-11-01 01:00:00"), q("2026-11-02 01:00:00")], AGORA) == []


def test_notificar_falha_grava_registro_sem_telegram():
    sh = (RAIZ / "tools" / "notificar_falha.sh").read_text(encoding="utf-8")
    assert "data/falhas_systemd.jsonl" in sh and "notificar(" not in sh
