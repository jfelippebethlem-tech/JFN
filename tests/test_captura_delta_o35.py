# -*- coding: utf-8 -*-
"""O3.5 — captura por delta: cada CLASSE DE RISCO do replay dos manifestos históricos reproduzida contra o plano REAL
(`captura_delta.plano_de_captura`/`encaixe`) e a chave do E3 (`JFN_E3_DELTA`, desligada por padrão = sombra).
Classes: recaptura sem novidade (0 a baixar), documento novo, id_documento trocado sob o mesmo nº SEI (numeração
reaproveitada), título retificado, documento sem nº que muda de posição, restrito que aparece depois (guardado sem
texto), nº repetido (#k) com a ordem trocada, documento removido da árvore. Lacuna conhecida (xfail estrito): o E2
grava a identidade da árvore VIVA em `documentos` antes do E3, então o E3 não vê id_documento trocado."""
import json
import subprocess
from pathlib import Path

import pytest

from compliance_agent import captura_delta as D

URL = "https://sei.rj.gov.br/sei/controlador.php?acao=arvore_visualizar&id_documento={}"


def _no(titulo: str, idd: int) -> dict:
    return {"t": titulo, "u": URL.format(idd), "pai": ""}


def _guardados(nos: list[dict], chars: int = 100, sem_texto: tuple[int, ...] = ()) -> dict:
    man = {"docs": [{"i": i, "titulo": x["t"], "texto": "" if i in sem_texto else f"texto/{i:03d}.txt",
                     "chars": 0 if i in sem_texto else chars, "id_documento": D._id_documento(x)}
                    for i, x in enumerate(nos)]}
    return D.guardados(man)


K = [_no("Despacho (11111111)", 501), _no("Nota de Empenho (22222222)", 502), _no("Anexo sem número", 503)]


def _motivos(p) -> dict:
    return {b["doc_id"]: b["motivo"] for b in p["baixar"]}


def test_recaptura_sem_novidade_baixa_zero():
    p = D.plano_de_captura(K, _guardados(K))
    assert p["baixar"] == [] and len(p["manter"]) == 3 and p["arvore_igual"]


def test_documento_novo_e_baixado_so_ele():
    viva = K + [_no("Nota Fiscal (33333333)", 504)]
    p = D.plano_de_captura(viva, _guardados(K))
    assert _motivos(p) == {"sei:33333333": "novo"} and len(p["manter"]) == 3


def test_numeracao_reaproveitada_id_documento_trocado_rebaixa():
    viva = [K[0], _no("Nota de Empenho (22222222)", 999), K[2]]
    assert _motivos(D.plano_de_captura(viva, _guardados(K))) == {"sei:22222222": "retificado"}


def test_titulo_retificado_rebaixa_e_preserva_anterior():
    viva = [_no("Despacho RETIFICADO (11111111)", 501)] + K[1:]
    p = D.plano_de_captura(viva, _guardados(K))
    assert p["baixar"] == [{"i": 0, "doc_id": "sei:11111111", "motivo": "retificado", "preservar_anterior": True}]


def test_sem_numero_que_muda_de_posicao_rebaixa():
    viva = [K[2], K[0], K[1]]                       # o anexo sem nº foi para a posição 0
    m = _motivos(D.plano_de_captura(viva, _guardados(K)))
    assert m == {"pos:0": "novo"}                   # pos:0 não existia; pos:2 vira "removido" (nunca apagado)


def test_sem_numero_mesma_posicao_outro_documento_rebaixa():
    viva = [K[0], K[1], _no("Anexo sem número", 777)]
    assert _motivos(D.plano_de_captura(viva, _guardados(K))) == {"pos:2": "pos_sem_id"}


def test_restrito_que_aparece_depois_e_baixado():
    g = _guardados(K, sem_texto=(1,))              # na captura k o documento veio sem conteúdo (restrito)
    assert _motivos(D.plano_de_captura(K, g)) == {"sei:22222222": "sem_texto"}


def test_numero_repetido_com_ordem_trocada_rebaixa_pelo_id():
    rep = [_no("Anexo (55555555)", 601), _no("Anexo (55555555)", 602)]
    viva = [rep[1], rep[0]]
    m = _motivos(D.plano_de_captura(viva, _guardados(rep)))
    assert m == {"sei:55555555": "retificado", "sei:55555555#2": "retificado"}


def test_removido_da_arvore_nao_e_baixado_nem_apagado():
    g = _guardados(K)
    p = D.plano_de_captura(K[:2], g)
    assert p["baixar"] == [] and [r["doc_id"] for r in p["removidos"]] == ["pos:2"] and "pos:2" in g


# ── a chave do E3 ────────────────────────────────────────────────────────────────────────────────────────────
def test_chave_do_e3_desligada_por_padrao():
    assert D.modo_e3({}) == "sombra"
    assert D.modo_e3({"JFN_E3_DELTA": "0"}) == "sombra"
    assert D.modo_e3({"JFN_E3_DELTA": "1"}) == "1"
    assert D.modo(env={"JFN_CAPTURA_DELTA": D.modo_e3({})}) == "sombra"        # sombra: o encaixe não pula nada


def test_encaixe_com_a_chave_ligada_pula_o_guardado_e_desligada_nao(tmp_path):
    exp = tmp_path / "exp"
    exp.mkdir()
    g = {"docs": [[k, v["titulo"], v["chars"], v["id_documento"]] for k, v in _guardados(K).items()]}
    (exp / "TAG.json").write_text(json.dumps(g), encoding="utf-8")
    viva = K + [_no("Nota Fiscal (33333333)", 504)]
    onde = {"pasta_exportados": exp, "arquivo": tmp_path}
    pular, reg = D.encaixe("TAG", viva, env={"JFN_CAPTURA_DELTA": D.modo_e3({"JFN_E3_DELTA": "1"})}, **onde)
    assert pular == {0, 1, 2} and reg["baixados"] == 1
    pular, reg = D.encaixe("TAG", viva, env={"JFN_CAPTURA_DELTA": D.modo_e3({})}, **onde)
    assert pular == set() and reg["modo"] == "sombra" and reg["mantidos"] == 3


def test_navegador_real_passa_a_chave_ao_subprocesso(tmp_path, monkeypatch):
    from compliance_agent.aplicacao.estagios import arvore as A
    vistos = []

    def falso_run(cmd, **kw):
        vistos.append(kw["env"]["JFN_CAPTURA_DELTA"])
        (Path(kw["env"]["SEI_INTEGRA_RAIZ"]) / "integra_999003_000001_2026").mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", falso_run)
    monkeypatch.setattr(D, "GUARDADOS_DIR", tmp_path / "g")
    monkeypatch.delenv("JFN_E3_DELTA", raising=False)
    A.NavegadorSEI().capturar("999003/000001/2026", {"docs": []}, tmp_path)
    monkeypatch.setenv("JFN_E3_DELTA", "1")
    A.NavegadorSEI().capturar("999003/000001/2026", {"docs": []}, tmp_path)
    assert vistos == ["sombra", "1"]


# ── lacuna conhecida: identidade sobrescrita pelo E2 antes do E3 ──────────────────────────────────────────────
from tests.fluxo_pg import DSN, precisa_pg  # noqa: E402
from tests.test_estagio_arvore import PROC, pg  # noqa: E402,F401


def _e2(con, docs, ficha):
    from compliance_agent.aplicacao.estagios import Contexto
    from compliance_agent.aplicacao.estagios import arvore as A
    from tests.sei_falso import SEIFalso
    return A.registrar(con, PROC, A.ler_arvore(SEIFalso(docs), PROC),
                       Contexto("vm2", "arvore", f"arvore:{PROC}", ficha, 1), [])


def _k(idd: int, extra: bool = False) -> list[dict]:
    d = [{"t": "Despacho (11111111)", "u": URL.format(idd), "restrito": False}]
    return d + ([{"t": "Nota Fiscal (33333333)", "u": URL.format(504), "restrito": False}] if extra else [])


def _versao(con, doc_id):
    con.execute("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, vista_em, hash_de) VALUES "
                "(%s,%s,'s',0,'sei:e3','x','binario')", (PROC, doc_id))


LACUNA = ("O3.5 lacuna (0 casos em 422 recapturas do replay): o tree_hash é só dos doc_id, e o E2 sobrescreve "
          "título/id_documento de `documentos` quando a árvore muda — o id_documento CAPTURADO não fica guardado. "
          "Conserto: a versão grava o id_documento capturado e o E2 compara com ele.")


@precisa_pg
@pytest.mark.xfail(strict=True, reason=LACUNA)
def test_e2_ve_id_documento_trocado_sem_outra_mudanca(pg):  # noqa: F811
    con, _ = pg
    _e2(con, _k(501), 1)
    _versao(con, "sei:11111111")
    assert _e2(con, _k(999), 2)["estado"] == "documento_novo"        # hoje: sem_mudanca ⇒ o E3 nem é acionado


@precisa_pg
@pytest.mark.xfail(strict=True, reason=LACUNA)
def test_e3_ve_id_documento_trocado_quando_a_arvore_tambem_cresce(pg):  # noqa: F811
    from compliance_agent.aplicacao.estagios import capturar as C
    con, _ = pg
    _e2(con, _k(501), 1)
    _versao(con, "sei:11111111")
    assert _e2(con, _k(999, extra=True), 2)["estado"] == "documento_novo"   # a NF nova suja o processo
    plano = D.plano_de_captura(_k(999, extra=True), D.carregar_guardados(C.guardados_do_pg(con, PROC)))
    assert _motivos(plano) == {"sei:33333333": "novo", "sei:11111111": "retificado"}   # hoje: o Despacho é mantido
