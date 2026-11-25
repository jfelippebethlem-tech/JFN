# -*- coding: utf-8 -*-
"""E15 `materializar` (O7.1): visão = corpo exato da rota legada em arquivo, rota só lê, frescor por visão.

Paridade por rota migrada: a resposta da rota SEM visão (cálculo legado = "antes") é byte a byte a resposta COM a visão
materializada ("depois"), para cada uma das 10 visões; e, com base real de fixture, os números de /api/certames/lista.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timezone

import pytest
from fastapi.responses import JSONResponse

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, estagio_de
from compliance_agent.aplicacao.estagios import materializar as M
from compliance_agent.fluxo.fila import Resultado


@pytest.fixture()
def caches_isolados(monkeypatch):
    """O materializador zera os caches em memória e desvia o cache de disco — no teste, cópias descartáveis."""
    from rotas import acervo as A
    from rotas import investigacao as inv
    from rotas import sistema as S
    monkeypatch.setattr(inv, "_cache", {})
    monkeypatch.setattr(inv, "_CACHE_DIR", inv._CACHE_DIR)
    monkeypatch.setattr(S, "_stats_cache", {})
    monkeypatch.setattr(A, "_EST", {})


def _ctx(nome: str) -> Contexto:
    return Contexto(no="vm1", tipo=f"materializar:{nome}", chave=f"materializar:{nome}", ficha=1, tentativa=1)


# ── armazenamento ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_gravar_ler_e_conferir_ida_e_volta():
    v = M.VISOES["siafe_stats"]
    corpo = json.dumps({"ok": True, "total": 3, "pago": {"valor": 1.5}}).encode()
    meta = M.gravar(v, corpo, json.loads(corpo), 1.234)
    lido = M.ler("siafe_stats")
    assert lido is not None and lido[0] == corpo and lido[1]["sha256"] == M.sha256(corpo)
    assert meta["universo"] == 3 and meta["slo_s"] == v.slo_s and meta["fonte"] == v.dados
    assert M.conferir("siafe_stats", {"sha256": meta["sha256"], "gerado_em": meta["gerado_em"]})["ok"]


def test_corpo_adulterado_nao_e_servido_e_falha_a_conferencia():
    v = M.VISOES["siafe_stats"]
    corpo = b'{"ok": true, "total": 3}'
    meta = M.gravar(v, corpo, json.loads(corpo), 0.1)
    (M.diretorio() / "siafe_stats.json").write_bytes(b'{"ok": true, "total": 4}')
    assert M.ler("siafe_stats") is None and M.resposta("siafe_stats") is None     # rota cai no legado
    c = M.conferir("siafe_stats", {"sha256": meta["sha256"], "gerado_em": meta["gerado_em"]})
    assert not c["ok"] and any("sha256" in m for m in c["motivos"])


@pytest.mark.parametrize("corpo", [b'{"erro": "fonte fora", "total": 3}', b'{"error": "boom", "total": 3}'])
def test_corpo_que_declara_erro_falha_a_conferencia(corpo):
    """Revisão de falhas caladas 1.14: "erro" e "error" no corpo, nos dois lugares (cálculo e conferência)."""
    meta = M.gravar(M.VISOES["siafe_stats"], corpo, json.loads(corpo), 0.1)
    c = M.conferir("siafe_stats", {"sha256": meta["sha256"], "gerado_em": meta["gerado_em"]})
    assert not c["ok"] and "corpo declara erro" in c["motivos"]


def test_universo_ausente_e_indisponivel_nunca_zero():
    assert M._campo({"n": 0}, "n") == 0
    assert M._campo({"x": 1}, "n") is None and M._campo({"rede": [1, 2]}, "len:rede") == 2
    assert M._campo({"n": True}, "n") is None                                     # bool não é contagem
    meta = M.gravar(M.VISOES["siafe_stats"], b'{"ok": true}', {"ok": True}, 0.1)
    assert meta["universo"] is None and meta["universo_estado"] == "INDISPONIVEL"


# ── cálculo e estágio ───────────────────────────────────────────────────────────────────────────────────────────────
def _falsa(monkeypatch, nome: str, resp_ou_fn):
    v = M.VISOES[nome]
    mod, fn = v.legado.split(":")
    import importlib
    alvo = importlib.import_module(mod)
    original = getattr(alvo, fn)
    from starlette.responses import Response
    impl = (lambda *a, **k: resp_ou_fn) if isinstance(resp_ou_fn, Response) else resp_ou_fn
    if asyncio.iscoroutinefunction(original):
        async def fake(*a, **k):
            return impl(*a, **k)
        monkeypatch.setattr(alvo, fn, fake)
    else:
        monkeypatch.setattr(alvo, fn, impl)


@pytest.mark.parametrize("resp", [JSONResponse({"ok": False, "erro": "x"}, status_code=500),
                                  JSONResponse({"ok": False, "erro": "fonte fora"}),
                                  JSONResponse({"error": "boom"}),
                                  JSONResponse({"erro": "rota legada com 200"})])   # 1.14: "erro" sem ok:False
def test_erro_da_rota_nao_vira_visao_e_a_anterior_fica(monkeypatch, caches_isolados, resp):
    boa = M.gravar(M.VISOES["siafe_stats"], b'{"ok": true, "total": 9}', {"ok": True, "total": 9}, 0.1)
    _falsa(monkeypatch, "siafe_stats", resp)
    with pytest.raises(RuntimeError):
        M._handler({"visao": "siafe_stats"}, _ctx("siafe_stats"))
    assert M.ler_meta("siafe_stats")["sha256"] == boa["sha256"]


def test_handler_e_efeito_pelo_registro(monkeypatch, caches_isolados):
    _falsa(monkeypatch, "conflito", JSONResponse({"ok": True, "rede": [{"v": 1.25}, {"v": 2}]}))
    est = estagio_de("materializar:conflito")
    assert est is M.ESTAGIO and est.recursos == ["materializar"]
    r = est.handler({}, _ctx("conflito"))
    assert r.efeito["universo"] == 2 and r.eventos[0]["chave"] == "conflito"
    assert est.efeito({}, _ctx("conflito"), r)
    # handler que declara o que o disco não tem: efeito recusa
    falso = Resultado(efeito={**r.efeito, "sha256": "0" * 64})
    assert not est.efeito({}, _ctx("conflito"), falso)


def test_visao_invalida_e_erro_permanente():
    with pytest.raises(ErroPermanente):
        M._handler({"visao": "nao_existe"}, _ctx("nao_existe"))


def test_cli_rodar_imprime_linha_de_prova(monkeypatch, caches_isolados, capsys):
    _falsa(monkeypatch, "siafe_stats", JSONResponse({"ok": True, "total": 5}))
    assert M.main(["rodar", "--visao", "siafe_stats"]) == 0
    import re
    assert re.search(r"materializar: [a-z_]+ sha256 [0-9a-f]{16} conferido", capsys.readouterr().out)


# ── frescor (sensor E18) ────────────────────────────────────────────────────────────────────────────────────────────
def test_frescor_fresca_atrasada_e_ausente():
    v = M.VISOES["siafe_stats"]
    M.gravar(v, b'{"ok": true, "total": 1}', {"ok": True, "total": 1}, 0.1)
    M.gravar(M.VISOES["conflito"], b'{"ok": true, "rede": []}', {"ok": True, "rede": []}, 0.1)
    agora = time.time() + M.VISOES["conflito"].slo_s - 10          # conflito (SLO 6 h) fresca, siafe (1 h) atrasada
    f = M.frescor(agora=agora)
    assert f["total"] == len(M.VISOES) and f["frescas"] == 1
    assert f["atrasadas"] == ["siafe_stats"] and "conflito" not in f["ausentes"]
    assert len(f["ausentes"]) == len(M.VISOES) - 2


def test_sensor_g_visoes_conta_atrasada_e_ausente_e_grava_detalhe():
    from compliance_agent.fluxo import sensores as S
    M.gravar(M.VISOES["siafe_stats"], b'{"ok": true, "total": 1}', {"ok": True, "total": 1}, 0.1)
    ctx = S.Ctx(no="vm1", con=None, agora=datetime.now(timezone.utc))
    ls = M.g_visoes(ctx)
    agg = ls[0]
    assert agg.nome == "visoes.atrasadas" and agg.valor == float(len(M.VISOES) - 1)
    assert agg.rotulos["frescas"] == 1 and agg.rotulos["total"] == len(M.VISOES)
    det = {x.rotulos["visao"]: x for x in ls[1:]}
    assert det["siafe_stats"].valor is not None and det["siafe_stats"].rotulos["sensor"] == "FRESCA"
    assert det["conflito"].valor is None                                         # ausente = não mediu, nunca 0
    slos = S.carregar_slos()
    assert S.avaliar(slos.slos["visoes_frescor"], agg.valor)[0] == "ATRASADO"
    assert "frescor_visoes" in S.GRUPOS and "visoes.atrasadas" in slos.por_sensor()


# ── paridade por rota migrada: antes (legado) = depois (visão), byte a byte ─────────────────────────────────────────
def _rotas():
    from rotas import acervo as A
    from rotas import investigacao as inv
    from rotas import sistema as S
    return {
        "conflito": lambda: inv.api_conflito(),
        "compliance_painel": lambda: inv.api_painel(),
        "compliance_graph": lambda: asyncio.run(inv.api_compliance_graph()),
        "certames_prefeitura": lambda: inv.api_certames_lista(esfera="prefeitura", limite=600, q=""),
        "certames_estado": lambda: inv.api_certames_lista(esfera="estado", limite=600, q=""),
        "fontes_frescor": lambda: inv.api_fontes_frescor(),
        "coendereco_clusters": lambda: inv.api_coendereco_clusters(),
        "siafe_stats": lambda: S.api_siafe_stats(),
        "pncp_conluio_estado": lambda: inv.api_pncp_conluio(esfera="estado"),
        "acervo_estatisticas": lambda: asyncio.run(A.api_acervo_estatisticas()),
    }


_VISOES_DE_ROTA = sorted(n for n in M.VISOES if not n.startswith("lente_"))   # lente_*: tests/test_lentes_completas.py


def test_toda_visao_tem_rota_de_paridade():
    assert set(_rotas()) == set(_VISOES_DE_ROTA)


@pytest.mark.parametrize("nome", _VISOES_DE_ROTA)
def test_paridade_rota_antes_igual_depois(monkeypatch, caches_isolados, nome):
    corpo = {"ok": True, "n": 7, "n_orgaos": 3, "total": 1234567.89, "rede": [{"valor": 10.5}], "nodes": [1, 2],
             "fontes": [{"fonte": "x"}], "resumo": {"total": 2, "analisados": 1}, "dados": {"n_clusters": 4},
             "obs": {"total": 11, "valor_total": 99.99}, "texto": "ação — São João"}
    _falsa(monkeypatch, nome, lambda *a, **k: JSONResponse(corpo))
    chamar = _rotas()[nome]
    antes = chamar()
    assert antes.status_code == 200 and antes.headers["X-JFN-Visao"] == f"ausente:{nome}"
    assert M.main(["rodar", "--visao", nome]) == 0
    depois = chamar()
    assert depois.headers["X-JFN-Visao"] == nome and depois.headers["X-JFN-Visao-Gerado-Em"]
    assert bytes(depois.body) == bytes(antes.body)
    assert json.loads(depois.body) == corpo


def test_parametro_fora_do_padrao_nao_le_a_visao(monkeypatch, caches_isolados):
    from rotas import investigacao as inv
    M.gravar(M.VISOES["conflito"], b'{"ok": true, "rede": ["VISAO"]}', {"ok": True, "rede": ["VISAO"]}, 0.1)
    monkeypatch.setattr(inv, "_api_conflito_legado", lambda *a, **k: JSONResponse({"ok": True, "rede": ["LEGADO"]}))
    assert json.loads(inv.api_conflito(cnpj="123").body)["rede"] == ["LEGADO"]
    assert json.loads(inv.api_conflito().body)["rede"] == ["VISAO"]


@pytest.fixture()
def base_certames(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    con = sqlite3.connect(tmp_path / "data" / "compliance.db")
    con.executescript("""
    CREATE TABLE edital_documento (numero_controle_pncp TEXT, orgao_cnpj TEXT, ano INT, objeto TEXT, valor_estimado REAL);
    CREATE TABLE certame_indice (certame TEXT, score REAL, faixa TEXT, confianca REAL, prioridade REAL, familias_json TEXT);
    CREATE TABLE orgao_esfera (cnpj TEXT, nome TEXT, esfera TEXT);
    """)
    for i, cnpj in enumerate(("42498600000171", "30449862000167", "42498733000148", "00394452000103")):
        nc = f"{cnpj}-1-00000{i}/2025"
        con.execute("INSERT INTO edital_documento VALUES (?,?,2025,'obra de reforma',?)", (nc, cnpj, 1000.0 * (i + 1)))
        con.execute("INSERT INTO certame_indice VALUES (?,?,?,?,?,?)",
                    (nc, 61.5 + i, "alta", 0.8, 10 - i, json.dumps({"preco": {"apuravel": True, "valor": 12.345}})))
    con.executemany("INSERT INTO orgao_esfera VALUES (?,?,?)", [("30449862000167", "ALERJ", "estadual-rj")])
    con.commit()
    con.close()
    from rotas import investigacao as R
    monkeypatch.setattr(R, "RAIZ", tmp_path)


@pytest.mark.parametrize("esfera", ["estado", "prefeitura"])
def test_paridade_certames_com_base_real(base_certames, caches_isolados, esfera):
    from rotas import investigacao as R
    antes = R.api_certames_lista(esfera=esfera, limite=600, q="")
    assert antes.headers["X-JFN-Visao"] == f"ausente:certames_{esfera}"
    assert M.main(["rodar", "--visao", f"certames_{esfera}"]) == 0
    depois = R.api_certames_lista(esfera=esfera, limite=600, q="")
    assert depois.headers["X-JFN-Visao"] == f"certames_{esfera}" and bytes(depois.body) == bytes(antes.body)
    d = json.loads(depois.body)
    assert d["resumo"]["total"] == (2 if esfera == "estado" else 1)
    assert M.ler_meta(f"certames_{esfera}")["universo"] == d["resumo"]["total"]


# ── configuração ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_rotina_religada_na_o90_cobre_toda_visao_e_fontes_existem():
    from compliance_agent.fluxo import grafo
    g = grafo.carregar()
    r = g.rotinas["materializar_painel"]
    assert r.estagio == "E15" and r.ativa is True and "Religada na O9.0" in r.nota      # O9.0 (25/11/2026)
    assert {p[p.index("--visao") + 1] for p in r.argvs()} == set(M.VISOES)
    for v in M.VISOES.values():
        assert set(v.fontes) <= set(g.fontes), (v.nome, set(v.fontes) - set(g.fontes))
    assert set(r.evento.depende) == {f for v in M.VISOES.values() for f in v.fontes}


def test_prewarm_nao_aquece_mais_visao_materializada():
    sh = (M.RAIZ / "tools" / "prewarm_painel.sh").read_text(encoding="utf-8")
    import re
    aquecidas = set(re.findall(r'^\s*"([^"]+)"', sh, re.M))
    assert not aquecidas & {v.rota.removeprefix("/api/") for v in M.VISOES.values()}
