# -*- coding: utf-8 -*-
"""Critério POSITIVO da pesquisa pública do SEI municipal (deploy/vm2/sei_pcrj_criterio.py).

Defeito medido ao vivo em 24/11/2026 (~/vault/refatoracao/sei-pcrj-captcha-falso-privado.md): captcha
ERRADO devolve página idêntica à de "aceito e sem resultado". Ler a ausência da frase de erro como
"aceito" gravou 962 processos como privados (disponivel=0) sem prova. O que se trava aqui:

- página com linha de resultado = PÚBLICO;
- página sem linha e sem frase = INDETERMINADO (nunca "privado");
- página com a frase = CAPTCHA_ERRADO (retentar);
- os coletores irmãos (busca, enum, conferir) não dão por FEITO o que não tem prova.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
import sys
import types
from pathlib import Path

import pytest

VM2 = Path(__file__).resolve().parent.parent / "deploy" / "vm2"
FIX = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(VM2))

import sei_pcrj_criterio as C  # noqa: E402


def _fix(nome: str) -> str:
    return (FIX / nome).read_text(encoding="utf-8")


def _texto(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


# ── 1. o critério sobre HTML ───────────────────────────────────────────────────────────────────────

def test_pagina_com_linha_de_resultado_e_publico():
    html = _fix("sei_pcrj_pesquisa_publico.html")
    n_linhas, n_links = C.contar_resultado(html)
    assert n_linhas > 0 and n_links > 0
    assert C.classificar_html(html, _texto(html)) == C.PUBLICO


def test_linha_sem_link_ainda_prova_a_pesquisa_aceita():
    html = re.sub(r'href="[^"]*"', 'href="#"', _fix("sei_pcrj_pesquisa_publico.html"))
    assert C.contar_resultado(html) == (2, 0)
    assert C.classificar_html(html, _texto(html)) == C.PUBLICO


def test_pagina_sem_linha_e_sem_frase_e_indeterminado_nunca_privado():
    html = _fix("sei_pcrj_pesquisa_sem_prova.html")
    assert C.contar_resultado(html) == (0, 0)
    assert C.classificar_html(html, _texto(html)) == C.INDETERMINADO


def test_so_cabecalho_tambem_e_indeterminado():
    html = _fix("sei_pcrj_pesquisa_sem_prova.html").replace(
        '<table id="pesquisaResultado" class="pesquisaResultado" width="99%"></table>',
        '<table id="pesquisaResultado"><tr><th>Resultado da pesquisa</th></tr></table>')
    assert C.contar_resultado(html) == (0, 0)
    assert C.classificar_html(html, _texto(html)) == C.INDETERMINADO


def test_frase_de_erro_e_captcha_errado_retentar():
    html = _fix("sei_pcrj_pesquisa_captcha_errado.html")
    assert C.classificar_html(html, _texto(html)) == C.CAPTCHA_ERRADO
    # com acento ou sem, maiúscula ou não
    assert C.classificar(0, 0, "CÓDIGO DE CONFIRMAÇÃO INVÁLIDO") == C.CAPTCHA_ERRADO


def test_prova_positiva_vence_a_frase():
    assert C.classificar(1, 0, "código de confirmação inválido") == C.PUBLICO


def test_tabela_aninhada_nao_conta_como_linha():
    html = ('<table id="pesquisaResultado"><tr><th>cab</th></tr>'
            '<tr><td><table><tr><td>a</td></tr><tr><td>b</td></tr></table></td></tr></table>'
            '<table><tr><td>fora</td></tr></table>')
    assert C.contar_resultado(html) == (1, 0)


def test_nenhum_valor_de_leitura_e_privado():
    """A classe PRIVADO não existe nesta fonte: a página não deixa observá-la."""
    assert {C.PUBLICO, C.CAPTCHA_ERRADO, C.INDETERMINADO} == {"publico", "captcha_errado", "indeterminado"}


# ── 2. os coletores irmãos: página falsa, sweep substituído por um stub ─────────────────────────────

class _Elem:
    async def screenshot(self):
        return b"png"

    async def fill(self, _v):
        return None


class _PaginaFalsa:
    """Devolve, a cada submissão, o próximo (texto, linhas) do roteiro."""

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.submissoes = 0
        self._atual = ("", [])
        self.url = "https://prefeitura.sei.rio/sei/x"

    async def query_selector(self, _sel):
        return _Elem()

    async def wait_for_load_state(self, *_a, **_k):
        return None

    async def goto(self, *_a, **_k):
        return None

    async def fill(self, *_a, **_k):
        return None

    async def click(self, *_a, **_k):
        self._submeter()

    def _submeter(self):
        self._atual = self.roteiro.pop(0) if self.roteiro else ("", [])
        self.submissoes += 1

    async def inner_text(self, _sel):
        return self._atual[0]

    async def evaluate(self, js, *args):
        if "fetch(" in js:                      # paginação AJAX: nada além da 1ª página
            return {"status": 200, "itens": len(self._atual[1]), "linhas": []}
        if "hash_download" in js:
            return []
        if "pesquisaTituloRegistro" in js:
            return list(self._atual[1])
        return None


@pytest.fixture
def irmaos(monkeypatch, tmp_path):
    stub = types.ModuleType("sei_pcrj_sweep")
    stub.RAIZ = tmp_path
    stub.DB = tmp_path / "sei_pcrj.db"
    stub.BASE = "https://prefeitura.sei.rio"
    stub._SEL_CAP_IMG = "#imgCaptcha"
    stub._SEL_CAP_FLD = "#txtInfraCaptcha"
    stub._ERRO_CAPTCHA = C.ERRO_CAPTCHA
    stub._norm_txt = C.norm_txt
    stub._now = lambda: "2026-11-24 00:00:00"
    stub.ocr_captcha = lambda _png: "abc12"

    async def _abrir_form(_page, _numero, *, espera=5):
        return True

    async def _submeter(page):
        page._submeter()

    stub._abrir_form = _abrir_form
    stub._submeter = _submeter
    monkeypatch.setitem(sys.modules, "sei_pcrj_sweep", stub)
    for m in ("sei_pcrj_busca", "sei_pcrj_enum", "sei_pcrj_conferir"):
        monkeypatch.delitem(sys.modules, m, raising=False)
    import sei_pcrj_busca as B
    import sei_pcrj_conferir as F
    import sei_pcrj_enum as E

    async def _sem_espera(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", _sem_espera)
    return B, E, F


_LINHA = {"prot": "000100.000244/2026-10", "titulo": "X nº000100.000244/2026-10", "href": "h",
          "meta": "Unidade: CR-SEI.RIO Data: 12/01/2026", "snip": ""}


def test_busca_sem_prova_vira_erro_indeterminado_e_o_termo_nao_fica_feito(irmaos):
    B, _, _ = irmaos
    pg = _PaginaFalsa([("", [])] * 10)
    r = asyncio.run(B.buscar_termo(pg, "TUISE"))
    assert r["erro"].startswith("indeterminado")
    assert pg.submissoes == C.MAX_SEM_PROVA


def test_busca_frase_retenta_e_linha_prova(irmaos):
    B, _, _ = irmaos
    pg = _PaginaFalsa([("Código de confirmação inválido", []), ("", [_LINHA])])
    r = asyncio.run(B.buscar_termo(pg, "TUISE"))
    assert "erro" not in r and len(r["linhas"]) == 1 and r["captchas"] == 2


def test_busca_termo_feito_so_com_linhas(irmaos, tmp_path, monkeypatch):
    B, _, _ = irmaos
    con = sqlite3.connect(":memory:")
    con.executescript(B.DDL)
    con.executemany("INSERT INTO sei_pcrj_busca_termo VALUES (?,?,?,?,?)", [
        ("COM_PROVA", 3, 3, None, "t"), ("ZERO_ANTIGO", 0, 0, None, "t"),
        ("INDET", None, 0, "indeterminado: 3", "t")])
    arq = tmp_path / "termos.txt"
    arq.write_text("INDET\nZERO_ANTIGO\nCOM_PROVA\nNOVO\n", encoding="utf-8")
    monkeypatch.setattr(B, "TERMOS", arq)
    assert B._termos_pendentes(con) == ["NOVO", "INDET", "ZERO_ANTIGO"]


def test_enum_sem_prova_vira_erro_e_dia_zero_nao_conta_como_feito(irmaos):
    _, E, _ = irmaos
    pg = _PaginaFalsa([("", [])] * 10)
    r = asyncio.run(E.enumerar_dia(pg, "01/09/2026"))
    assert r["erro"].startswith("indeterminado")
    con = sqlite3.connect(":memory:")
    con.executescript(E.DDL)
    ontem = E.date.today() - E.timedelta(days=1)
    anteontem = ontem - E.timedelta(days=1)
    con.executemany("INSERT INTO sei_pcrj_enum_dia VALUES (?,?,?,?,?,?)", [
        (ontem.strftime("%d/%m/%Y"), 0, 0, 1, None, "t"),          # 0 do critério antigo: volta
        (anteontem.strftime("%d/%m/%Y"), 100, 90, 1, None, "t")])  # com prova: feito
    pend = E._dias_pendentes(con)
    assert ontem.strftime("%d/%m/%Y") in pend
    assert anteontem.strftime("%d/%m/%Y") not in pend


def test_conferir_sem_documento_nem_recusa_e_indeterminado(irmaos):
    _, _, F = irmaos
    pg = _PaginaFalsa([("Conferência de Autenticidade", [])] * 10)
    r = asyncio.run(F.conferir(pg, "5950912", "B3825257"))
    assert r["erro"].startswith("indeterminado") and pg.submissoes == C.MAX_SEM_PROVA


def test_conferir_recusa_do_par_e_prova_negativa(irmaos):
    _, _, F = irmaos
    pg = _PaginaFalsa([("Documento não encontrado", [])])
    assert asyncio.run(F.conferir(pg, "1", "X"))["erro"] == "par não confere"


def test_conferir_pendentes_so_pula_o_que_tem_prova(irmaos, tmp_path):
    _, _, F = irmaos
    con = sqlite3.connect(":memory:")
    con.execute(F.DDL)
    for v, erro in (("1", None), ("2", "par não confere"), ("3", "sem link de download"),
                    ("4", "indeterminado: 3")):
        con.execute("INSERT INTO sei_pcrj_documento (verificador, crc, erro) VALUES (?,?,?)", (v, "C", erro))
    arq = tmp_path / "pares.txt"
    arq.write_text("".join(f"{v}\tC\n" for v in ("3", "1", "4", "2", "5")), encoding="utf-8")
    assert [p[0] for p in F._pares_pendentes(con, arq)] == ["5", "3", "4"]


# ── 3. leitores da VM-1: NULL é INDETERMINADO — nem 0, nem público, e não apaga prova ──────────────

def test_ingest_null_nao_vira_zero_nem_apaga_prova(tmp_path):
    from tools.pcrj_sei_ingest import ingerir

    origem = tmp_path / "sei_pcrj.db"
    o = sqlite3.connect(origem)
    o.execute("CREATE TABLE sei_pcrj_processo (numero TEXT PRIMARY KEY, disponivel INTEGER, "
              "captcha_tentativas INTEGER, texto TEXT, url TEXT, capturado_em TEXT)")
    linhas = [("P1", 1, 1, "nºP1 Unidade: X Data: 01/01/2026", "u", "t"),   # prova
              ("P2", None, 3, "", "u", "t"),                                  # indeterminado
              ("P3", None, 3, "", "u", "t")]                                  # indeterminado com prova antiga
    o.executemany("INSERT INTO sei_pcrj_processo VALUES (?,?,?,?,?,?)", linhas)
    o.commit()
    o.close()
    db = tmp_path / "pcrj.db"
    ingerir(origem, db_path=db)
    c = sqlite3.connect(db)
    c.execute("UPDATE pcrj_processo SET disponivel=1 WHERE numero_processo='P3'")   # prova anterior na VM-1
    c.execute("INSERT INTO pcrj_processo (numero_processo, sistema, disponivel) VALUES ('P4','SEI.RIO',0)")
    c.commit()
    c.close()
    o = sqlite3.connect(origem)
    o.execute("INSERT INTO sei_pcrj_processo VALUES ('P4',NULL,3,'','u','t')")  # 0 legado -> NULL
    o.commit()
    o.close()
    r = ingerir(origem, db_path=db)
    got = dict(sqlite3.connect(db).execute("SELECT numero_processo, disponivel FROM pcrj_processo"))
    assert got == {"P1": 1, "P2": None, "P3": 1, "P4": None}
    assert r["publicos"] == 1                     # NULL não conta como público


def test_painel_so_rotula_zero_explicito_e_nao_trata_null_como_nao_encontrado():
    js = (Path(__file__).resolve().parent.parent / "static" / "js" / "src" / "abas" / "acervo.js").read_text(encoding="utf-8")
    # o rótulo "indisponível" e o "não encontrado" exigem o valor EXPLÍCITO (=== 0 / === false): NULL não dispara
    assert "disponivel_na_pesquisa_publica === 0" in js
    assert "cv.encontrado === false" in js
    assert not re.search(r"!\s*id\.disponivel_na_pesquisa_publica|disponivel_na_pesquisa_publica\s*==\s*(0|null)\b", js)
