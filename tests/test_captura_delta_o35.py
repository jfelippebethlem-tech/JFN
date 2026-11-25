# -*- coding: utf-8 -*-
"""O3.5 — captura por delta: cada CLASSE DE RISCO do replay dos manifestos históricos reproduzida contra o plano REAL
(`captura_delta.plano_de_captura`/`encaixe`) e a chave do E3 (`JFN_E3_DELTA`, desligada por padrão = sombra).
Classes: recaptura sem novidade (0 a baixar), documento novo, id_documento trocado sob o mesmo nº SEI (numeração
reaproveitada), título retificado, documento sem nº que muda de posição, restrito que aparece depois (guardado sem
texto), nº repetido (#k) com a ordem trocada, documento removido da árvore. E as 2 lacunas de identidade fechadas:
o tree_hash inclui o id_documento e a versão grava a identidade CAPTURADA (captura_002), então id_documento trocado
ou título retificado voltam a faltar no E2 e o E3 os rebaixa, mesmo quando a árvore também cresce."""
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


def _versao(con, doc_id, idd="501", titulo="Despacho (11111111)"):
    """Versão como o E3 grava (captura_002): com o id_documento e o título CAPTURADOS."""
    con.execute("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, vista_em, hash_de, id_documento, titulo) "
                "VALUES (%s,%s,'s',0,'sei:e3','x','binario',%s,%s)", (PROC, doc_id, idd, titulo))




@precisa_pg
def test_legado_sem_identidade_capturada_nao_vira_retificado(pg):  # noqa: F811
    con, _ = pg
    _e2(con, _k(501), 1)
    con.execute("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, vista_em, hash_de) VALUES "
                "(%s,'sei:11111111','t',100,'sei_arquivo','x','texto')", (PROC,))   # O3.1: sem id_documento
    assert _e2(con, _k(999), 2)["faltantes"] == 0                      # nada a comparar: segue como antes


@precisa_pg
@pytest.mark.parametrize("mesmos_bytes", [False, True])
def test_troca_de_id_ponta_a_ponta_rebaixa_so_ele_e_converge(pg, monkeypatch, tmp_path, mesmos_bytes):  # noqa: F811
    """E2→E3 reais: id_documento trocado sob o mesmo nº ⇒ E2 documento_novo ⇒ E3 rebaixa SÓ ele ⇒ E2 sem mudança.
    Com os MESMOS bytes (o PDF não mudou), a versão atualiza a identidade — senão o E2 pediria para sempre."""
    from compliance_agent.aplicacao.estagios import Contexto
    from compliance_agent.aplicacao.estagios import arvore as A
    from compliance_agent.aplicacao.estagios import capturar as C
    from tests.sei_falso import SEIFalso, arvore_falsa
    con, nome = pg
    monkeypatch.setenv("JFN_E3_DELTA", "1")
    docs = arvore_falsa(5)
    nav = SEIFalso(docs)
    if mesmos_bytes:
        orig = SEIFalso.capturar

        def capturar(self, processo, guardados, raiz):
            out = orig(self, processo, guardados, raiz)
            for f in Path(out).glob("*.pdf"):
                f.write_bytes(b"%PDF mesmo conteudo " + f.name.encode())
            return out
        monkeypatch.setattr(SEIFalso, "capturar", capturar)
    monkeypatch.setattr(A, "obter_navegador", lambda: nav)

    def e2(f):
        ctx = Contexto("vm2", "arvore", f"arvore:{PROC}", f, 1)
        r = A._handler({"processo": PROC, "esquema": nome}, ctx)
        assert A._efeito({"esquema": nome}, ctx, r)
        return r.efeito

    def e3(f):
        ctx = Contexto("vm2", "capturar", f"capturar:{PROC}", f, 1)
        r = C._handler({"processo": PROC, "esquema": nome, "raiz": str(tmp_path)}, ctx)
        return C._efeito({"esquema": nome}, ctx, r)

    assert e2(1)["estado"] == A.DOC_NOVO and e3(1) and nav.baixados[-1] == [0, 1, 2, 3, 4]
    assert e2(2)["estado"] == A.SEM_MUDANCA
    docs[2] = dict(docs[2], u=docs[2]["u"].replace("500002", "777777"))   # numeração reaproveitada
    ef = e2(3)
    assert ef["estado"] == A.DOC_NOVO and ef["faltantes"] == 1
    assert e3(3) and nav.baixados[-1] == [2]
    assert e2(4)["estado"] == A.SEM_MUDANCA                                # convergiu (não pede de novo)
    # título retificado no MESMO segundo da captura anterior (vista_em empata): ainda dispara e converge
    docs[2] = dict(docs[2], t="Despacho RETIFICADO 2 (90000002)")
    ef5 = e2(5)
    assert ef5["estado"] == A.DOC_NOVO and ef5["faltantes"] == 1
    # o arquivo do MESMO id_documento já está na pasta (retomada pelo id, como o sei_integra_completa): a versão
    # passa a carregar a identidade nova sem novo download, e o E2 converge
    assert e3(5) and nav.baixados[-1] == []
    assert e2(6)["estado"] == A.SEM_MUDANCA
