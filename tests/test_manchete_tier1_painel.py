# -*- coding: utf-8 -*-
"""O7.3 na TELA (Playwright/Chromium headless — roda na VM-2 ou no it-campo, `tools/testar_na_vm2.sh`): com 0
detectores Tier 1, nenhum número de detector é renderizado como manchete no Início/cockpit, nos Sinais críticos nem na
aba Alertas; o painel diz "nenhuma manchete calibrada" com o porquê; sem o estado de calibração, falha FECHADA; o
"34/13" não aparece; e o seletor global de lente (O7.2) recorta as consultas e diz quais ficaram no universo inteiro.
Nenhum `pageerror`.

Sem servidor: a página, o bundle e o CSS vêm do disco (os arquivos versionados), e cada `/api/*` é respondido por
fixture — o estado de calibração é o REAL (`manchete_painel.estado()`, registro e inventário do repositório).
Os números das fixtures são escolhidos para serem achados no texto se vazarem (7.058 alertas, R$ 123.456,78 …).
"""
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pytest

pw = pytest.importorskip("playwright.sync_api")

RAIZ = Path(__file__).resolve().parents[1]
BASE = "http://painel.teste"
ALERTAS, ECON, FENIX = 7058, 123456.78, 9876543.21


def _estado_real() -> dict:
    from compliance_agent.qualidade import manchete_painel
    return manchete_painel.estado()


def _fixtures() -> dict:
    return {
        "/api/compliance/painel": {"ok": True, "alertas": {"total": ALERTAS, "alta": 1234, "media": 5000, "baixa": 824},
                                   "lista_alertas": [{"tipo": "fracionamento", "titulo": "Possível fracionamento — X",
                                                      "severidade": "alta", "descricao": "d"}],
                                   "obs": {"ultimo_dia": "2026-11-23", "n_ultimo_dia": 12, "valor_ultimo_dia": 4321.0,
                                           "total": 99, "valor_total": 1000.0}},
        "/api/comparador/economia": {"ok": True, "economia_total": ECON, "n_compras_acima_mediana": 42,
                                     "por_esfera": {"estado": {"n": 1, "economia": 1.0}}},
        "/api/intel/fenix": {"ok": True, "total_apos_baixa": FENIX, "n_defunta_confirmada": 54},
        "/api/intel/comunidades": {"ok": True, "n": 4376, "n_por_rating": {"🔴": 77, "🟡": 88}},
        "/api/intel/lift": {"ok": True, "detectores": [{"detector": "x", "lift": 3.3, "n": 500, "sancionados": 9}],
                            "taxa_base": 0.01},
        "/api/governo_couto": {"ok": True, "pontos_atencao": {"itens": [
            {"grau": "🔴", "verificacao": "VERIFICADO", "regra_ou_hipotese": "D05 · PONTO-SECRETO-COUTO",
             "valor_ob": 555.0, "explicacao_inocente": "x"}]}},
        "/api/pericia_contabil": {"ok": True, "esferas": {"Estado do RJ": {
            "placar": {"A_MAIOR": 31}, "excesso_a_maior": 8888888.88, "deficit_encerrado": 1.0, "a_maior": [],
            "verificacao": {"placar": "VERIFICADO na fonte"}}}},
        "/api/esteira/lentes": {"ok": True, "lentes": [
            {"lente": "bombeiros", "descricao": "CBMERJ e FUNESBOM", "esfera": "estado", "prioridade": 0.2,
             "eixos_extra": [], "paridade": "p", "visao": {"estado": "FRESCA"}}]},
        "/api/esteira/lente": {"ok": True, "lente": "bombeiros", "esfera": "estado", "descricao": "CBMERJ",
                               "filtro": ["UG 166100"], "fonte": "SIAFE", "estado": "VERIFICADO",
                               "universo": {"n": 3, "obs": 3, "obs_pagas": 2, "valor_pago": 3141.59,
                                            "fora_da_soma": {"obs": 1, "valor": 1.0}, "credores": 1,
                                            "processos_legiveis": 1, "ultima_ob_paga": "2026-11-20"},
                               "determinavel": {"obs": 1, "valor": 3000.0},
                               "indeterminado": {"sem_processo": {"obs": 1, "valor": 141.59},
                                                 "processo_nao_sei": {"obs": 0, "valor": 0.0}},
                               "cobertura": {"fracao_do_pago_ligavel_ao_sei": 0.955}, "ugs": [], "credores_topo": [],
                               "achados": {"estado": "VERIFICADO", "totais": {"confirmado": 1, "descartado": 2,
                                                                               "nao_avaliavel": 3},
                                           "detectores": [], "fonte": "achados.db", "leitura": "l"},
                               "fila": {"rotulo": "ordem de exame — NÃO é probabilidade", "itens": [
                                   {"processo": "270006/000001/2026", "ob_paga": 3000.0, "componentes": {
                                       "escalar_valor": 0.49, "bonus_lente": 0.2, "couto": True},
                                    "lente_motivo": "ug:166100"}]}},
    }


def _servidor(estado, pedidos):
    fx = _fixtures()

    def tratar(route):
        u = urlparse(route.request.url)
        pedidos.append(route.request.url)
        if u.path in ("/", "/painel"):
            return route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                 body=(RAIZ / "static/jfn-painel.html").read_text(encoding="utf-8"))
        if u.path.startswith("/static/"):
            arq = RAIZ / u.path.lstrip("/")
            if not arq.is_file():
                return route.fulfill(status=404, body="")
            tipo = mimetypes.guess_type(arq.name)[0] or "application/octet-stream"
            return route.fulfill(status=200, content_type=tipo, body=arq.read_bytes())
        if u.path == "/api/eventos/stream":
            return route.fulfill(status=200, content_type="text/event-stream", body="")
        if u.path == "/api/manchetes/estado":
            if estado is None:
                return route.fulfill(status=500, content_type="application/json",
                                     body=json.dumps({"ok": False, "erro": "fixture: estado fora do ar"}))
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(estado))
        if u.path in fx:
            lente = (parse_qs(u.query).get("lente") or [None])[0]
            hdr = {"X-JFN-Lente": lente} if u.path == "/api/esteira/lente" and lente else {}
            return route.fulfill(status=200, content_type="application/json", headers=hdr,
                                 body=json.dumps(fx[u.path], ensure_ascii=False))
        if u.path.startswith("/api/") or u.path == "/status":
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"ok": False, "erro": "fixture: rota sem dado no teste"}))
        return route.fulfill(status=404, body="")
    return tratar


@pytest.fixture(scope="module")
def navegador():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True, args=["--no-sandbox"])
        except pw.Error as e:          # navegador do Playwright não instalado nesta máquina
            pytest.skip(f"chromium do Playwright indisponível: {e}")
        yield b
        b.close()


def _abrir(navegador, estado, hash_=""):
    ctx = navegador.new_context(viewport={"width": 1400, "height": 1000}, reduced_motion="reduce")
    pagina = ctx.new_page()
    erros, pedidos = [], []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.route("**/*", _servidor(estado, pedidos))
    pagina.goto(BASE + "/painel" + hash_, wait_until="domcontentloaded")
    return ctx, pagina, erros, pedidos


def _texto(pagina) -> str:
    return pagina.evaluate("document.body.innerText")


def _vazou(txt: str) -> list[str]:
    alvos = ["7.058", "123.456,78", "9.876.543,21", "8.888.888,88", "PONTO-SECRETO-COUTO", "3,30×"]
    return [a for a in alvos if a in txt]


def test_inicio_sem_tier1_nao_renderiza_manchete_de_detector(navegador):
    estado = _estado_real()
    assert estado["por_tier"]["1"] == 0, "o teste supõe o estado de hoje (0 Tier 1)"
    ctx, pagina, erros, _ = _abrir(navegador, estado)
    try:
        pagina.wait_for_function("document.querySelector('#mch-aviso') && /Nenhuma manchete calibrada/"
                                 ".test(document.querySelector('#mch-aviso').innerText)", timeout=60000)
        pagina.wait_for_function("document.querySelector('#cki-alertas .meta') && /não é manchete/"
                                 ".test(document.querySelector('#cki-alertas .meta').innerText)", timeout=60000)
        pagina.wait_for_function("/não é manchete/.test((document.querySelector('#c61-preoc')||{}).innerText||'')",
                                 timeout=60000)
        pagina.wait_for_function("/não é manchete/.test((document.querySelector('#v63-n-econ')||{}).innerText||'')",
                                 timeout=60000)
        pagina.wait_for_timeout(1500)
        txt = _texto(pagina)
        assert not _vazou(txt), _vazou(txt)
        for i in ("alertas", "fenix", "compras", "com", "lift"):
            assert pagina.inner_text(f"#cki-{i} .val").strip() == "—", i
        assert pagina.inner_text("#ck-econ").strip() == "—"
        assert pagina.inner_text("#v63-n-alertas .v63-num-v").strip() == "—"
        assert not re.search(r"34 (alertas )?conferidos|13 não se sustentaram|conferidos 34", txt)
        assert "Tier 2:" in pagina.inner_text("#mch-aviso")
        assert not erros, erros
    finally:
        ctx.close()


def test_sem_estado_de_calibracao_falha_fechada(navegador):
    ctx, pagina, erros, _ = _abrir(navegador, None)
    try:
        pagina.wait_for_function("/INDISPONÍVEL/.test((document.querySelector('#mch-aviso')||{}).innerText||'')",
                                 timeout=60000)
        pagina.wait_for_function("document.querySelector('#cki-alertas .meta') && /não é manchete/"
                                 ".test(document.querySelector('#cki-alertas .meta').innerText)", timeout=60000)
        pagina.wait_for_timeout(1500)
        assert not _vazou(_texto(pagina)), _vazou(_texto(pagina))
        assert not erros, erros
    finally:
        ctx.close()


def test_aba_alertas_diz_fila_de_triagem(navegador):
    ctx, pagina, erros, _ = _abrir(navegador, _estado_real(), "#e_alertas")
    try:
        pagina.wait_for_function("/Fila de triagem — não é manchete/.test(document.querySelector('#view').innerText)",
                                 timeout=60000)
        assert "Tier" in pagina.inner_text("#view")
        assert not erros, erros
    finally:
        ctx.close()


def test_lente_global_recorta_e_diz_o_que_ficou_no_universo_inteiro(navegador):
    ctx, pagina, erros, pedidos = _abrir(navegador, _estado_real())
    try:
        pagina.wait_for_selector("#lente-sel", timeout=60000)
        pagina.select_option("#lente-sel", "bombeiros")
        pagina.wait_for_function("!document.querySelector('#lente-faixa').hidden && "
                                 "/UNIVERSO INTEIRO/.test(document.querySelector('#lente-faixa').innerText)", timeout=60000)
        pagina.click("#lente-rec summary")
        pagina.wait_for_function("/3\\.141,59/.test(document.querySelector('#lente-corpo').innerText)", timeout=30000)
        corpo = pagina.inner_text("#lente-corpo")
        assert "INDETERMINADO" in corpo and "141,59" in corpo and "NÃO é probabilidade" in corpo
        assert "não avaliáveis" in corpo
        com = [p for p in pedidos if "lente=bombeiros" in p]
        assert any("/api/compliance/painel" in p for p in com)
        assert not any(re.search(r"/api/(ao-vivo|manchetes|esteira/lentes|lentes)\b[^?]*\?[^#]*lente=bombeiros", p)
                       for p in pedidos)
        assert not _vazou(_texto(pagina)), _vazou(_texto(pagina))
        pagina.click("#lente-tirar")
        pagina.wait_for_function("document.querySelector('#lente-faixa').hidden", timeout=30000)
        assert not erros, erros
    finally:
        ctx.close()
