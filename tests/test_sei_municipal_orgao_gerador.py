"""O SEI municipal exige Órgão Gerador marcado — sem ele, nenhum POST sai.

O handler de submit do `prefeitura.sei.rio` faz `alert('Nenhum Órgão Gerador selecionado.')`
e retorna. O Playwright descarta alerts em silêncio, então a falha se apresentava como
"a página não mudou" — sintoma que convida a culpar bloqueio quando é requisito de formulário.
"""
import asyncio

import pytest

from compliance_agent.collectors.sei_cdp import _JS_MARCA_ORGAO, submit_sei_search

HTML_MUNICIPAL = """
<html><body>
<input type="checkbox" data-name="selectItemselOrgaoPesquisa[]" value="0" id="a">
<input type="checkbox" data-name="selectItemselOrgaoPesquisa[]" value="35" id="b">
<input type="checkbox" data-name="selectItemselOrgaoPesquisa[]" value="62" id="c">
</body></html>"""
HTML_ESTADUAL = "<html><body><input id='txtProtocoloPesquisa'></body></html>"


def _rodar(cenario):
    try:
        from playwright.async_api import async_playwright
    except ImportError:                                        # pragma: no cover
        pytest.skip("playwright não instalado")

    async def _main():
        async with async_playwright() as p:
            b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                return await cenario(await b.new_page())
            finally:
                await b.close()
    try:
        return asyncio.run(_main())
    except Exception as e:                                     # pragma: no cover
        if "executable doesn't exist" in str(e).lower() or "browsertype.launch" in str(e).lower():
            pytest.skip(f"chromium indisponível nesta máquina: {e}")
        raise


def test_marca_apenas_o_orgao_pedido():
    async def c(pg):
        await pg.set_content(HTML_MUNICIPAL)
        r = await pg.evaluate(_JS_MARCA_ORGAO, "35")
        return r, await pg.eval_on_selector("#b", "e=>e.checked"), \
            await pg.eval_on_selector("#a", "e=>e.checked")
    r, pedido, alheio = _rodar(c)
    assert r["ok"] and r["marcados"] == 1 and r["total"] == 3
    assert pedido is True
    assert alheio is False, "marcar órgão que não foi pedido mudaria o universo da busca em silêncio"


def test_orgao_inexistente_nao_inventa_marcacao():
    async def c(pg):
        await pg.set_content(HTML_MUNICIPAL)
        return await pg.evaluate(_JS_MARCA_ORGAO, "999")
    r = _rodar(c)
    assert r["ok"] is False and r["marcados"] == 0


def test_none_marca_todos_para_busca_ampla():
    async def c(pg):
        await pg.set_content(HTML_MUNICIPAL)
        return await pg.evaluate(_JS_MARCA_ORGAO, None)
    r = _rodar(c)
    assert r["ok"] and r["marcados"] == 3


def test_sem_widget_declara_motivo_e_nao_explode():
    """O SEI estadual não tem esse widget: a função precisa dizer isso, não quebrar."""
    async def c(pg):
        await pg.set_content(HTML_ESTADUAL)
        return await pg.evaluate(_JS_MARCA_ORGAO, "35")
    r = _rodar(c)
    assert r["ok"] is False and "não está no DOM" in r["motivo"]


def test_parametro_e_opcional_e_nao_muda_o_sei_estadual():
    import inspect
    par = inspect.signature(submit_sei_search).parameters["orgao_gerador"]
    assert par.default is None, "default diferente de None mudaria o comportamento do estadual"


def test_alertas_do_formulario_sao_devolvidos():
    """Alerta é diagnóstico: separa 'requisito não atendido' de 'captcha errado'."""
    import inspect
    src = inspect.getsource(submit_sei_search)
    assert 'page.on("dialog"' in src
    assert '"alertas": alertas' in src
