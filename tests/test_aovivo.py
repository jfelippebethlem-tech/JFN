# -*- coding: utf-8 -*-
"""AO VIVO: saneamento obrigatório, estado dos motores, lista branca de log e o contrato da API."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from compliance_agent.aovivo import api, coleta
from compliance_agent.aovivo.saneamento import TETO, sanear


@pytest.mark.parametrize("sujo, proibido", [
    ("baixando https://exemplo.gov.br/doc?token=abc123&x=1 agora", "token=abc123"),
    ("contato fulano.silva@exemplo.gov.br respondeu", "fulano.silva@exemplo.gov.br"),
    ("servidor 123.456.789-09 localizado", "123.456.789-09"),
    ("cpf 12345678909 na folha", "12345678909"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF123456789", "eyJhbGciOiJIUzI1NiJ9"),
    ("usando chave sk-ant-REDACTED", "sk-ant-REDACTED"),
    ("senha=SuperSecreta123 no log", "SuperSecreta123"),
    ("hash 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08 ok", "9f86d081884c7d65"),
])
def test_saneamento_remove_segredo_email_cpf_e_url_com_query(sujo, proibido):
    assert proibido not in sanear(sujo)


def test_saneamento_corta_em_140_e_preserva_o_que_e_inocente():
    assert len(sanear("x" * 500)) <= TETO and len(sanear("palavra " * 80)) <= TETO
    assert sanear("recaptura 3/5: processo com 16 documentos lidos") == "recaptura 3/5: processo com 16 documentos lidos"
    assert sanear("CNPJ 42498600000171 e processo SEI-260006/023315/2024") == "CNPJ 42498600000171 e processo SEI-260006/023315/2024"


AGORA = 1_800_000_000.0


def test_estado_do_motor():
    e = coleta.estado_do_motor
    falhou = {"LoadState": "loaded", "ActiveState": "failed", "ExecMainStatus": "1", "InactiveEnterTimestamp": "@1799990000"}
    assert e(falhou, None, None, AGORA) == {"estado": "falhou", "desde": 1799990000.0, "proxima": None, "saida": 1}
    rodando = {"LoadState": "loaded", "ActiveState": "activating", "ExecMainStatus": "0", "ExecMainStartTimestamp": "@1799999000"}
    assert e(rodando, None, None, AGORA)["estado"] == "rodando" and e(rodando, None, None, AGORA)["desde"] == 1799999000.0
    parado = {"LoadState": "loaded", "ActiveState": "inactive", "ExecMainStatus": "0"}
    assert e(parado, None, None, AGORA)["estado"] == "ocioso"
    timer = {"LoadState": "loaded", "ActiveState": "active", "NextElapseUSecRealtime": "Sat 2027-01-16 06:00:00 -03"}
    r = e(parado, timer, None, AGORA)
    assert r["estado"] == "agendado" and r["proxima"] > AGORA
    # falha NÃO vira "agendado" só porque há timer: continua falhou, com a próxima tentativa informada
    assert e(falhou, timer, None, AGORA)["estado"] == "falhou" and e(falhou, timer, None, AGORA)["proxima"] > AGORA
    # timer monotônico (sem hora de parede): agendado, e a hora NÃO é inventada
    mono = {"LoadState": "loaded", "ActiveState": "active", "NextElapseUSecRealtime": ""}
    assert e(parado, mono, None, AGORA) == {"estado": "agendado", "desde": None, "proxima": None, "saida": 0}
    # trava presa = rodando agora, mesmo sem unit; unit inexistente = ocioso (não "falhou")
    assert e(None, None, True, AGORA)["estado"] == "rodando" and e(None, None, False, AGORA)["estado"] == "ocioso"
    assert e({"LoadState": "not-found"}, None, None, AGORA)["estado"] == "ocioso"


def test_timestamps_do_systemd():
    assert coleta._unix("@1794214860") == 1794214860.0 and coleta._unix("") is None and coleta._unix("@0") is None
    assert coleta._ts_timer("Mon 2026-11-16 06:00:00 -03") == coleta._ts_timer("Mon 2026-11-16 09:00:00 +00")
    assert coleta._ts_timer("n/a") is None


def test_catalogo_integro():
    cat = coleta.catalogo()
    ids = [m["id"] for m in cat]
    assert len(ids) == len(set(ids)) and {"sei-noturno", "siafe-ob", "dados-abertos-rj", "intel-cache", "territorio", "massare"} <= set(ids) \
        and not {"tfe", "tfe-ob", "warp"} & set(ids)  # TFE desligado pelo dono em 13/11/2026
    for m in cat:
        assert m["nome"] and m.get("classe") in ("motor", "infra")
        assert m.get("unidade") or m.get("trava") or m.get("contador") or m.get("sonda_env"), m["id"]
        for ev in m.get("eventos", []):
            __import__("re").compile(ev["regex"])
            assert "{" not in ev["texto"].replace("{1}", "").replace("{2}", "").replace("{3}", "").replace("{4}", "")


def _coletor_falso(tmp_path, monkeypatch, linhas):
    log = tmp_path / "sei.log"
    log.write_text("")
    monkeypatch.setattr(coleta, "catalogo", lambda: [
        {"id": "sei", "nome": "SEI noturno", "classe": "motor", "unidade": "jfn-sei-noturno", "log": str(log), "eventos": [
            {"regex": r"\[recap (\d+)/(\d+)\] SEI-[\d/]+: (\d+) → (\d+) docs com texto", "texto": "recaptura {1}/{2}: processo com {4} documentos lidos",
             "progresso": [1, 2]}]},
        {"id": "tfe-ob", "nome": "TFE · OBs", "classe": "motor", "unidade": "jfn-tfe-ob"}])
    estado = {"sei": "activating", "tfe": "failed"}
    monkeypatch.setattr(coleta, "ler_systemd", lambda units: {
        "jfn-sei-noturno.service": {"Id": "jfn-sei-noturno.service", "LoadState": "loaded", "ActiveState": estado["sei"], "ExecMainStatus": "0",
                                    "ExecMainStartTimestamp": "@%d" % (time.time() - 60)},
        "jfn-tfe-ob.service": {"Id": "jfn-tfe-ob.service", "LoadState": "loaded", "ActiveState": estado["tfe"], "ExecMainStatus": "1",
                               "InactiveEnterTimestamp": "@%d" % (time.time() - 7200)}})
    monkeypatch.setattr(coleta, "travas_presas", lambda: set())
    c = coleta.Coletor()
    return c, log, estado


def test_log_so_vira_evento_pela_lista_branca(tmp_path, monkeypatch):
    c, log, estado = _coletor_falso(tmp_path, monkeypatch, [])
    c.tick(forcar=True)
    assert [m["estado"] for m in c.motores] == ["rodando", "falhou"]            # o que falhou aparece como falhou
    assert c.eventos_publicos() == []                                           # falha de 2 h atrás: fora da janela de 1 h
    agora = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(log, "a") as f:
        f.write(f"[{agora}]   [recap 3/5] SEI-260006/023315/2024: 16 → 16 docs com texto\n")
        f.write(f"[{agora}] senha=abc123 token=XYZ linha que NÃO está na lista branca\n")
        f.write("Traceback (most recent call last): fulano@exemplo.com\n")
    c.tick(forcar=True)
    evs = c.eventos_publicos()
    assert [e["texto"] for e in evs] == ["recaptura 3/5: processo com 16 documentos lidos"]     # linha bruta nunca sai
    assert evs[0]["motor"] == "sei" and evs[0]["tipo"] == "progresso" and "_ts" not in evs[0]
    sei = next(m for m in c.motores if m["id"] == "sei")
    assert sei["progresso"] == pytest.approx(0.6) and sei["ultimo_evento"]["texto"].startswith("recaptura 3/5")
    assert sum(sei["atividade"]) == 1 and len(sei["atividade"]) == 60
    estado["sei"] = "inactive"                                                  # transição real → evento "terminou"
    c.tick(forcar=True)
    assert c.eventos_publicos()[-1]["texto"] == "SEI noturno: terminou"
    assert next(m for m in c.motores if m["id"] == "sei")["progresso"] is None
    assert c.eventos_publicos(depois_de=evs[0]["id"])[0]["texto"] == "SEI noturno: terminou"    # replay por Last-Event-ID


def test_systemd_mudo_e_indisponivel_nao_ocioso(tmp_path, monkeypatch):
    c, _log, _e = _coletor_falso(tmp_path, monkeypatch, [])
    monkeypatch.setattr(coleta, "ler_systemd", lambda units: None)
    c.tick(forcar=True)
    assert {m["estado"] for m in c.motores} == {"indisponivel"} and c.fontes["systemd"] is False


def test_api_estado_e_stream(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    c, log, _estado = _coletor_falso(tmp_path, monkeypatch, [])
    monkeypatch.setattr(api, "coletor", lambda: c)
    monkeypatch.setattr(coleta, "INTERVALO", 0.0)
    app = FastAPI()
    app.include_router(api.router)
    j = TestClient(app).get("/api/ao-vivo/estado").json()
    assert {m["id"]: m["estado"] for m in j["motores"]} == {"sei": "rodando", "tfe-ob": "falhou"}
    assert j["resumo"]["falhou"] == 1 and j["fontes"] == {"systemd": True, "travas": True} and "eventos_min" in j
    for m in j["motores"]:
        assert set(m) >= {"id", "nome", "classe", "estado", "desde", "proxima", "progresso", "ultimo_evento", "atividade"}
    rotas = {r.path: r.methods for r in api.router.routes}
    assert rotas == {"/api/ao-vivo/estado": {"GET"}, "/api/ao-vivo/stream": {"GET"}}        # só leitura: nenhuma rota de escrita

    class Req:
        async def is_disconnected(self):
            return False

    async def colher():
        partes = []
        ger = api.gerar(Req(), max_ciclos=2)
        partes.append(await ger.__anext__())
        partes.append(await ger.__anext__())
        with open(log, "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]   [recap 1/5] SEI-1/2/2024: 0 → 4 docs com texto\n")
        async for p in ger:
            partes.append(p)
        return partes

    partes = asyncio.run(colher())
    assert partes[0].startswith("retry:") and partes[1].startswith("event: estado\n")
    ev = [p for p in partes if "event: evento" in p]
    assert len(ev) == 1 and ev[0].startswith("id: ") and json.loads(ev[0].split("data: ", 1)[1])["texto"].startswith("recaptura 1/5")
