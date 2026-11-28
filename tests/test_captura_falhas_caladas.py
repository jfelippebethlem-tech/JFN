# -*- coding: utf-8 -*-
"""Revisão de falhas caladas no E2/E3/delta (itens 1.7, 1.8, S2 e S6), cada uma reproduzida antes do conserto:
1.7 "Nenhum resultado" do cracked impedia o abrir_processo e virava ErroPermanente sem controle positivo;
1.8 binário que o E4 declarou INVALIDA (página de WAF/menu) contava como capturado e a retomada pelo id o reusava;
S2  a recontagem de faltas do E3 cobria só o manifesto (um manifesto parcial escondia o que nunca veio);
S6  exportado de guardados corrompido caía calado no manifesto do arquivo; guardado sem id_documento mantido sem
    registro. Navegador sempre FALSO; PG só em esquema temporário."""
import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

from compliance_agent import captura_delta as D
from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente
from compliance_agent.aplicacao.estagios import arvore as A
from compliance_agent.aplicacao.estagios import capturar as C
from tests.fluxo_pg import DSN, precisa_pg
from tests.sei_falso import SEIFalso, arvore_falsa
from tests.test_estagio_arvore import PROC, pg  # noqa: F401 — fixture do esquema temporário


# ── 1.7 ─────────────────────────────────────────────────────────────────────────────────────────────────────
class _NavVazio:
    def __init__(self, **kw):
        self.kw = kw

    def arvore(self, processo, pagina):
        return A.PaginaArvore(docs=[], via="teste", **self.kw)


def _e2_vazio(monkeypatch, **kw):
    monkeypatch.setattr(A, "obter_navegador", lambda: _NavVazio(**kw))
    return A._handler({"processo": PROC}, Contexto("vm2", "arvore", f"arvore:{PROC}", 1, 1))


def test_nenhum_resultado_sem_controle_positivo_e_transitorio(monkeypatch):
    for controle in (None, False):
        with pytest.raises(RuntimeError, match="INDISPONIVEL"):
            _e2_vazio(monkeypatch, sem_resultado=True, controle_positivo=controle)


def test_nenhum_resultado_com_controle_positivo_e_permanente(monkeypatch):
    with pytest.raises(ErroPermanente, match="controle positivo"):
        _e2_vazio(monkeypatch, sem_resultado=True, controle_positivo=True)
    from compliance_agent.sei import pesquisa_publica as PP
    monkeypatch.setattr(A, "obter_navegador_publico", lambda: PP.NavegadorPublico(
        sessao=object(), consultar_fn=lambda s, p: (PP.NAO_ACHADO, None)))       # O3.8: nem a pesquisa pública o acha
    with pytest.raises(ErroPermanente, match="RESTRITO.*não o encontra"):
        _e2_vazio(monkeypatch, restrito="Unidade atual não possui acesso")


def _sr_falso(monkeypatch, cracked: dict, abre: bool, controle_docs: list):
    """tools.sei_reader e o Playwright falsos para o `NavegadorSEI._arvore` (sem navegador)."""
    chamadas = {"abrir": 0, "controle": []}
    sr = types.SimpleNamespace()

    async def navegador_sei(pw, args=None):
        return None, types.SimpleNamespace(new_page=_nova), False

    class _Pg:
        async def add_init_script(self, *_a):
            return None

        async def evaluate(self, *_a):
            return "Nenhum resultado encontrado."

    async def _nova():
        return _Pg()

    async def entrar(pg, **_k):
        return True

    async def ler_cracked(pg, proc):
        if proc == A.PI.chave_processo(A.CONTROLE_POSITIVO):
            chamadas["controle"].append(proc)
            return {"documentos": controle_docs}
        return dict(cracked)

    async def abrir_processo(pg, proc):
        chamadas["abrir"] += 1
        return abre

    async def arvore_do_fonte(pg):
        return [{"titulo": "Despacho (12345678)", "url": "x?id_documento=1"}]

    async def fechar_sei(*_a, **_k):
        return None

    sr.navegador_sei, sr.entrar, sr._ler_cracked, sr.abrir_processo = navegador_sei, entrar, ler_cracked, abrir_processo
    sr.arvore_do_fonte, sr.fechar_sei, sr.ULTIMA_FALHA_LOGIN = arvore_do_fonte, fechar_sei, ""
    sr.aviso_restrito = lambda txt: None
    monkeypatch.setitem(sys.modules, "tools.sei_reader", sr)
    import tools
    monkeypatch.setattr(tools, "sei_reader", sr, raising=False)
    import compliance_agent.recursos as R
    import playwright.async_api as PW

    class _Ctx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(PW, "async_playwright", lambda: _Ctx())
    monkeypatch.setattr(R, "browser_lock_async", lambda **_k: _Ctx())
    return chamadas


def test_navegador_tenta_abrir_mesmo_com_nenhum_resultado(monkeypatch):
    ch = _sr_falso(monkeypatch, {"documentos": [], "sem_resultado": True}, abre=True, controle_docs=[])
    pa = asyncio.run(A.NavegadorSEI()._arvore(PROC))
    assert ch["abrir"] == 1 and pa.docs and pa.via == "fallback/arvore_do_fonte"   # antes: nem tentava
    assert ch["controle"] == []                                                     # achou: controle não roda


def test_navegador_roda_controle_positivo_quando_nada_abre(monkeypatch):
    ch = _sr_falso(monkeypatch, {"documentos": [], "sem_resultado": True}, abre=False, controle_docs=[{"url": "u"}])
    pa = asyncio.run(A.NavegadorSEI()._arvore(PROC))
    assert ch["abrir"] == 1 and pa.docs == [] and pa.sem_resultado and pa.controle_positivo is True
    ch = _sr_falso(monkeypatch, {"documentos": [], "sem_resultado": True}, abre=False, controle_docs=[])
    assert asyncio.run(A.NavegadorSEI()._arvore(PROC)).controle_positivo is False


# ── S6 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_exportado_corrompido_e_erro_e_nao_cai_no_manifesto(tmp_path):
    exp, arq = tmp_path / "exp", tmp_path / "arq"
    (arq / "TAG").mkdir(parents=True)
    (arq / "TAG" / "manifest.json").write_text(json.dumps({"docs": [{"i": 0, "titulo": "A (11111111)",
                                                                     "texto": "t.txt", "chars": 9}]}))
    exp.mkdir()
    (exp / "TAG.json").write_text("{corrompido")
    with pytest.raises(ValueError, match="ilegíveis"):
        D.guardados_do_processo("TAG", pasta_exportados=exp, arquivo=arq)
    (exp / "TAG.json").unlink()                                        # sem exportado: o manifesto vale (como antes)
    assert list(D.guardados_do_processo("TAG", pasta_exportados=exp, arquivo=arq)) == ["sei:11111111"]


def test_mantido_sem_id_documento_fica_registrado():
    viva = [{"t": "A (11111111)", "u": "x?id_documento=5"}]
    p = D.plano_de_captura(viva, {"sei:11111111": {"titulo": "A (11111111)", "chars": 9, "id_documento": ""}})
    assert p["manter"] and p["mantidos_sem_id_documento"] == 1
    p = D.plano_de_captura(viva, {"sei:11111111": {"titulo": "A (11111111)", "chars": 9, "id_documento": "5"}})
    assert p["mantidos_sem_id_documento"] == 0


# ── 1.8 e S2 (PostgreSQL) ───────────────────────────────────────────────────────────────────────────────────
def _e2(nome, f):
    ctx = Contexto("vm2", "arvore", f"arvore:{PROC}", f, 1)
    r = A._handler({"processo": PROC, "dsn": DSN, "esquema": nome}, ctx)
    assert A._efeito({"dsn": DSN, "esquema": nome}, ctx, r)
    return r.efeito


def _e3(nome, f, raiz):
    ctx = Contexto("vm2", "capturar", f"capturar:{PROC}", f, 1)
    r = C._handler({"processo": PROC, "dsn": DSN, "esquema": nome, "raiz": str(raiz)}, ctx)
    return r, C._efeito({"dsn": DSN, "esquema": nome}, ctx, r)


@precisa_pg
def test_binario_invalido_volta_a_faltar_e_e_rebaixado(pg, monkeypatch, tmp_path):  # noqa: F811
    con, nome = pg
    monkeypatch.setenv("JFN_E3_DELTA", "1")
    nav = SEIFalso(arvore_falsa(4))
    monkeypatch.setattr(A, "obter_navegador", lambda: nav)
    assert _e2(nome, 1)["estado"] == A.DOC_NOVO and _e3(nome, 1, tmp_path)[1]
    sha1 = con.execute("SELECT sha256 FROM versoes WHERE processo = %s AND doc_id = 'sei:90000001'",
                       (PROC,)).fetchone()[0]
    con.execute("INSERT INTO transformacao(processo, doc_id, tipo, entrada_sha, saida_sha, motor, parametros) "
                "VALUES (%s,'sei:90000001','texto_nativo',%s,'x','pymupdf','{\"perfil\": \"invalida\"}')",
                (PROC, sha1))                                          # o E4 viu página de WAF no lugar do documento
    ef = _e2(nome, 2)
    assert ef["estado"] == A.DOC_NOVO and ef["faltantes"] == 1          # antes: sem_mudanca (contava como capturado)
    orig = SEIFalso.capturar

    def capturar_bom(self, processo, guardados, raiz):
        out = orig(self, processo, guardados, raiz)
        if (out / "001.pdf").exists():
            (out / "001.pdf").write_bytes(b"%PDF documento de verdade")
        return out
    monkeypatch.setattr(SEIFalso, "capturar", capturar_bom)
    r, ok = _e3(nome, 2, tmp_path)
    out = tmp_path / f"integra_{PROC.replace('/', '_')}"
    assert ok and nav.baixados[-1] == [1]                              # só ele, de novo (não "retomado" pelo id)
    assert [p.name for p in (out / "_invalidos").iterdir()] == [f"001.{sha1[:12]}.pdf"]   # preservado, não apagado
    assert _e2(nome, 3)["estado"] == A.SEM_MUDANCA


@precisa_pg
def test_manifesto_parcial_nao_esconde_falta(pg, monkeypatch, tmp_path):  # noqa: F811
    con, nome = pg
    nav = SEIFalso(arvore_falsa(5))
    monkeypatch.setattr(A, "obter_navegador", lambda: nav)
    assert _e2(nome, 1)["faltantes"] == 5
    orig = SEIFalso.capturar

    def so_o_baixado(self, processo, guardados, raiz):
        out = orig(self, processo, guardados, raiz)
        man = json.loads((out / "manifest.json").read_text())
        man["docs"] = man["docs"][:3]                                   # o manifesto lista só 3 dos 5
        for f in ("003.pdf", "004.pdf"):
            (out / f).unlink()
        (out / "manifest.json").write_text(json.dumps(man))
        return out
    monkeypatch.setattr(SEIFalso, "capturar", so_o_baixado)
    r, ok = _e3(nome, 1, tmp_path)
    assert not ok and r.efeito["conferencia"]["faltas_recontadas"] == 2  # antes: 0 ⇒ efeito "ok"


@precisa_pg
def test_invalido_sob_identidade_nova_com_versao_antiga_valida_ainda_falta(pg, monkeypatch, tmp_path):  # noqa: F811
    """A versão antiga (válida) é de OUTRA identidade; a da identidade viva é inválida ⇒ falta (achado no replay rd2:
    a identidade da versão inválida 'casava' e o E2 dizia sem_mudanca)."""
    con, nome = pg
    monkeypatch.setenv("JFN_E3_DELTA", "1")
    docs = arvore_falsa(2)
    nav = SEIFalso(docs)
    monkeypatch.setattr(A, "obter_navegador", lambda: nav)
    assert _e2(nome, 1)["estado"] == A.DOC_NOVO and _e3(nome, 1, tmp_path)[1]
    docs[1] = dict(docs[1], u=docs[1]["u"].replace("500001", "700001"))             # id trocado ⇒ versão nova
    assert _e2(nome, 2)["estado"] == A.DOC_NOVO and _e3(nome, 2, tmp_path)[1]
    sha = con.execute("SELECT sha256 FROM versoes WHERE processo = %s AND doc_id = 'sei:90000001' AND "
                      "id_documento = '700001'", (PROC,)).fetchone()[0]
    con.execute("INSERT INTO transformacao(processo, doc_id, tipo, entrada_sha, saida_sha, motor, parametros) "
                "VALUES (%s,'sei:90000001','texto_nativo',%s,'x','pymupdf','{\"perfil\": \"invalida\"}')", (PROC, sha))
    ef = _e2(nome, 3)
    assert ef["estado"] == A.DOC_NOVO and ef["faltantes"] == 1


@precisa_pg
def test_relatorio_fotografico_so_com_texto_do_cache_volta_a_faltar(pg, monkeypatch):  # noqa: F811
    """27/11/2026 — regra única #58 (ex-`sei_integra_fila`): o caminho antigo do CACHE trazia só o texto; relatório
    fotográfico chegava sem foto e o processo «tinha texto», então a íntegra nunca era pedida (175 processos / 252
    relatórios medidos). A versão LEGADA de documento com recaptura pedida não conta como captura."""
    con, nome = pg
    nav = SEIFalso(arvore_falsa(4))
    monkeypatch.setattr(A, "obter_navegador", lambda: nav)
    assert _e2(nome, 1)["estado"] == A.DOC_NOVO
    for (k,) in con.execute("SELECT doc_id FROM documentos WHERE processo = %s", (PROC,)).fetchall():
        con.execute("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, ocr, vista_em, hash_de) "
                    "VALUES (%s, %s, %s, 100, 'sei_arquivo', NULL, '2026-09-24', 'texto')", (PROC, k, "t" + k))
    assert _e2(nome, 2)["faltantes"] == 0                                # o legado conta como captura…
    con.execute("INSERT INTO recaptura_pedida(processo, doc_id, motivo) VALUES (%s, 'sei:90000001', "
                "'relatório fotográfico só com o texto do cache')", (PROC,))
    ef = _e2(nome, 3)
    assert ef["estado"] == A.DOC_NOVO and ef["faltantes"] == 1          # …menos o que pediu recaptura
    con.execute("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, ocr, vista_em, hash_de) "
                "VALUES (%s, 'sei:90000001', 'binario-novo', 100, 'sei:e3', NULL, '2026-11-27', 'binario')", (PROC,))
    assert _e2(nome, 4)["faltantes"] == 0                                # a versão nova do E3 vale: auto-limitante


class _NavRestrito:
    """A unidade logada vê o processo como RESTRITO (sem documento)."""
    def arvore(self, processo, pagina):
        return A.PaginaArvore(docs=[], restrito="Unidade atual não possui acesso ao processo restrito", via="teste")


def _publico(baixados):
    from compliance_agent.sei import pesquisa_publica as PP
    arv = PP.Arvore([PP.Documento("90000001", "Despacho", "01/02/2025", "01/02/2025", "U", PP.BASE + "d1"),
                     PP.Documento("90000002", "Nota fiscal", "01/02/2025", "01/02/2025", "U", PP.BASE + "d2"),
                     PP.Documento("90000003", "Parecer", "01/02/2025", "01/02/2025", "U", None)])   # sem link

    def baixar(u):
        baixados.append(u)
        return b"%PDF documento publico " + u.encode()
    return PP.NavegadorPublico(sessao=object(), baixar=baixar, consultar_fn=lambda s, p: (PP.classificar(arv), arv))


@precisa_pg
def test_restrito_da_unidade_le_e_captura_pela_pesquisa_publica(pg, monkeypatch, tmp_path):  # noqa: F811
    """O3.8 (27/11/2026): RESTRITO é da unidade logada, não do público. O E2 lê a árvore pública (o sem-link fica
    restrito, declarado) e o E3 baixa por HTTP só os com link, no MESMO contrato (versão, sha256, faltas = 0)."""
    con, nome = pg
    baixados = []
    pub = _publico(baixados)
    monkeypatch.setattr(A, "obter_navegador", lambda: _NavRestrito())
    monkeypatch.setattr(A, "obter_navegador_publico", lambda: pub)
    ef = _e2(nome, 1)
    assert ef["estado"] == A.DOC_NOVO and ef["via"] == "pesquisa_publica" and ef["faltantes"] == 2 and ef["restritos"] == 1
    r, ok = _e3(nome, 1, tmp_path)
    assert ok and sorted(baixados) == [pub._docs[PROC][0]["u"], pub._docs[PROC][1]["u"]]
    assert con.execute("SELECT count(*) FROM versoes WHERE processo = %s AND origem LIKE 'sei:e3%%'",
                       (PROC,)).fetchone()[0] == 2
    assert _e2(nome, 2)["faltantes"] == 0                                # convergiu: nada falta, o restrito não é falta


@precisa_pg
def test_restrito_sem_link_publico_continua_fora_de_alcance(pg, monkeypatch):  # noqa: F811
    from compliance_agent.sei import pesquisa_publica as PP
    so = PP.Arvore([PP.Documento("90000003", "Parecer", "01/02/2025", "01/02/2025", "U", None)])
    monkeypatch.setattr(A, "obter_navegador", lambda: _NavRestrito())
    monkeypatch.setattr(A, "obter_navegador_publico", lambda: PP.NavegadorPublico(
        sessao=object(), consultar_fn=lambda s, p: (PP.classificar(so), so)))
    con, nome = pg
    with pytest.raises(A.ForaDeAlcance, match="só mostra a árvore"):
        A._handler({"processo": PROC, "dsn": DSN, "esquema": nome}, Contexto("vm2", "arvore", f"arvore:{PROC}", 1, 1))
