# -*- coding: utf-8 -*-
"""Fundação da plataforma de evidências (docs/PLANO-PLATAFORMA-EVIDENCIAS.md, Fase 1): identidade estável do
documento, versão por conteúdo (a antiga nunca é sobrescrita), árvore canônica e fila com reserva + ficha de posse."""
import json

import pytest

from compliance_agent import evidencias as E


@pytest.fixture()
def con(tmp_path):
    c = E.conectar(tmp_path / "ev.db")
    yield c
    c.close()


def _pasta(raiz, tag, docs):
    """docs = [(titulo, texto), ...] no formato do data/sei_arquivo/<tag>."""
    p = raiz / tag
    (p / "texto").mkdir(parents=True)
    man = []
    for i, (titulo, texto) in enumerate(docs):
        rel = f"texto/{i:03d}_x.txt"
        (p / rel).write_text(texto, encoding="utf-8")
        man.append({"i": i, "titulo": titulo, "fase": "f", "tipo": "despacho", "texto": rel, "chars": len(texto)})
    (p / "manifest.json").write_text(json.dumps({"processo": tag.replace("_", "/"), "gerado_em": "2026-11-20",
                                                 "docs": man}), encoding="utf-8")
    return p


@pytest.mark.parametrize("titulo,esperado", [
    ("Despacho de Liquidação da Despesa (86490508)", "86490508"),
    ("Despacho de Encaminhamento de Processo 12345678", "12345678"),
    ("Nota Fiscal", None),
    ("comprovante 2025OB01234", None),          # número colado a letras não é id de documento
])
def test_id_sei_do_titulo(titulo, esperado):
    assert E.id_sei(titulo) == esperado


def test_arvore_canonica_nao_depende_da_ordem():
    assert E.hash_arvore(["3", "1", "2"]) == E.hash_arvore(["1", "2", "3"]) != E.hash_arvore(["1", "2"])


def test_importar_e_idempotente_e_versao_antiga_fica(con, tmp_path):
    p = _pasta(tmp_path, "100001_000001_2025", [("Contrato (11111111)", "cláusula primeira " * 5),
                                                 ("Nota Fiscal", "valor R$ 10,00 " * 5)])
    r1 = E.importar_pasta(con, p)
    assert r1 == {"processo": "100001/000001/2025", "documentos": 2, "versoes_novas": 2}
    assert E.importar_pasta(con, p)["versoes_novas"] == 0                      # de novo: nada muda
    assert con.execute("SELECT COUNT(*) FROM documentos").fetchone()[0] == 2
    ids = {r[0] for r in con.execute("SELECT doc_id FROM documentos")}
    assert ids == {"sei:11111111", "pos:1"}                                     # sem número → posição
    (p / "texto" / "000_x.txt").write_text("cláusula primeira RETIFICADA", encoding="utf-8")
    assert E.importar_pasta(con, p)["versoes_novas"] == 1
    assert con.execute("SELECT COUNT(*) FROM versoes WHERE doc_id='sei:11111111'").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM arvores").fetchone()[0] == 1          # árvore (ids) não mudou


def test_numero_repetido_no_processo_nao_some(con, tmp_path):
    p = _pasta(tmp_path, "100001_000002_2025", [("Despacho (22222222)", "a" * 50), ("Despacho (22222222)", "b" * 50)])
    E.importar_pasta(con, p)
    assert con.execute("SELECT COUNT(*) FROM documentos").fetchone()[0] == 2
    assert {r[0] for r in con.execute("SELECT doc_id FROM documentos")} == {"sei:22222222", "sei:22222222#2"}


def test_fila_reserva_com_prazo_e_ficha_de_posse(con):
    assert E.enfileirar(con, "ocr", "doc:1") is True
    assert E.enfileirar(con, "ocr", "doc:1") is False                          # idempotente
    j = E.reservar(con, "ocr", dono="itcampo", prazo_s=60, agora=1000)
    assert j["chave"] == "doc:1" and E.reservar(con, "ocr", dono="vm2", prazo_s=60, agora=1010) is None
    j2 = E.reservar(con, "ocr", dono="vm2", prazo_s=60, agora=1100)            # prazo venceu: outro assume
    assert j2["chave"] == "doc:1" and j2["ficha"] > j["ficha"]
    assert E.concluir(con, j["id"], j["ficha"]) is False                       # trabalhador antigo é recusado
    assert E.concluir(con, j2["id"], j2["ficha"]) is True
    assert E.reservar(con, "ocr", dono="x", prazo_s=60, agora=2000) is None    # concluído não volta


def test_job_envenenado_vai_para_quarentena_e_falha_devolve(con):
    """Revisão do plano (23/11): sem teto de tentativas, um job que sempre derruba o worker rodaria para sempre."""
    E.enfileirar(con, "ocr", "doc:9")
    t = 1000
    for _ in range(E.MAX_TENTATIVAS):
        j = E.reservar(con, "ocr", dono="w", prazo_s=10, agora=t)
        assert j is not None
        t += 20                                                               # worker morre; prazo vence
    assert E.reservar(con, "ocr", dono="w", prazo_s=10, agora=t) is None
    assert con.execute("SELECT estado FROM jobs WHERE chave='doc:9'").fetchone()[0] == "quarentena"
    E.enfileirar(con, "ocr", "doc:10")
    j = E.reservar(con, "ocr", dono="w", prazo_s=10, agora=t)
    assert E.falhar(con, j["id"], j["ficha"]) is True                         # devolve para a fila
    assert E.reservar(con, "ocr", dono="w2", prazo_s=10, agora=t)["chave"] == "doc:10"


def test_reserva_concorrente_nao_entrega_o_mesmo_job_duas_vezes(tmp_path):
    """Duas conexões disputando: cada job sai para UM só (a reserva é uma operação atômica)."""
    a, b = E.conectar(tmp_path / "c.db"), E.conectar(tmp_path / "c.db")
    for k in range(20):
        E.enfileirar(a, "x", f"k{k}")
    vistos = []
    for _ in range(10):
        vistos += [E.reservar(a, "x", dono="a", prazo_s=60)["chave"], E.reservar(b, "x", dono="b", prazo_s=60)["chave"]]
    assert len(vistos) == len(set(vistos)) == 20
