# -*- coding: utf-8 -*-
"""O8.5 — leitura única nos pontos reais (achado do ensaio, 25/11/2026).

1. `preparar` do E8 e do E11 lia o texto de CADA documento DUAS vezes no mesmo job: `LI._docs(pasta)` para os
   originais e de novo dentro de `LI.fatiar` (que chamava `_docs` por conta própria). Medido pelo registro de leituras
   (`fluxo/leituras`): todo documento com `n = 2` no modo `rodar`. Correção na origem: `fatiar(..., docs=)` recebe a
   lista já lida; sem `docs`, o comportamento de antes (os outros chamadores não mudam).
2. O registro de leituras: agrega por (tipo, sha, versão) dentro do job; `repetida_pct` conta a mesma chave em MAIS
   DE UM job; a conferência de efeito fica fora do SLO; chamada de LLM recusada não é leitura.
3. `estagio_de("calibrar:…")` devolve o E13 (o motor não alcançava o estágio — FALTA anotada na O5.4).
"""
import json
from pathlib import Path

import pytest

from compliance_agent import evidencias as EV
from compliance_agent import leitura_integral as LI
from compliance_agent.fluxo import leituras as L
from compliance_agent.sei import acervo_texto

PROC = "999001/000001/2026"


def _acervo(tmp_path: Path, monkeypatch, n: int = 3) -> Path:
    monkeypatch.setattr(EV, "ARQUIVO", tmp_path)
    monkeypatch.setattr(LI, "_CONF", set())
    pasta = tmp_path / PROC.replace("/", "_")
    (pasta / "texto").mkdir(parents=True)
    man = {"captura_completa": True, "docs_faltantes": [], "docs": []}
    for i in range(n):
        rel = f"texto/{i:03d}.txt"
        (pasta / rel).write_text(f"Despacho {i}: autorizo o pagamento de R$ {i + 1}.000,00 à ACME LTDA. " * 5,
                                 encoding="utf-8")
        man["docs"].append({"i": i, "titulo": f"Despacho ({1000 + i})", "texto": rel, "ocr": False})
    (pasta / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return pasta


def _contar_leituras(monkeypatch) -> dict:
    vistos: dict = {}
    original = acervo_texto.ler

    def ler(pasta, doc, *a, **kw):
        vistos[doc["texto"]] = vistos.get(doc["texto"], 0) + 1
        return original(pasta, doc, *a, **kw)
    monkeypatch.setattr(acervo_texto, "ler", ler)
    return vistos


def test_e8_preparar_le_cada_documento_uma_vez(tmp_path, monkeypatch):
    from compliance_agent.aplicacao.estagios import fatos as F
    _acervo(tmp_path, monkeypatch)
    vistos = _contar_leituras(monkeypatch)
    p = F.preparar(PROC, set(), set())
    assert p.fatias and len(vistos) == 3
    assert set(vistos.values()) == {1}, f"documento relido no mesmo job: {vistos}"


def test_e11_preparar_le_cada_documento_uma_vez(tmp_path, monkeypatch):
    from compliance_agent.aplicacao.estagios import periciar as P
    _acervo(tmp_path, monkeypatch)
    vistos = _contar_leituras(monkeypatch)
    p = P.preparar(PROC, [])
    assert p.fatias and len(vistos) == 3
    assert set(vistos.values()) == {1}, f"documento relido no mesmo job: {vistos}"


def test_fatiar_com_docs_e_identico_ao_sem_docs(tmp_path, monkeypatch):
    pasta = _acervo(tmp_path, monkeypatch, n=5)
    a = LI.fatiar(pasta, alvo=400)
    b = LI.fatiar(pasta, alvo=400, docs=LI._docs(pasta))
    assert a == b


# ── registro de leituras (puro) ───────────────────────────────────────────────────────────────────────────────
def _linha(estagio, sha, job, modo="rodar", n=1, tipo="pdf", versao="v1"):
    return {"estagio": estagio, "tipo": tipo, "sha": sha, "versao": versao, "modo": modo, "n": n, "job_chave": job}


def test_resumo_conta_repeticao_entre_jobs_e_separa_conferencia_e_releitura_no_job():
    linhas = [_linha("texto", "a", "j1", n=2), _linha("texto", "b", "j1"), _linha("texto", "a", "j2"),
              _linha("texto", "a", "j1", modo="conferir"), _linha("ocr", "a", "j3"),
              _linha("fatos", "a", "j4", versao="li-2", tipo="texto"), _linha("fatos", "a", "j5", versao="li-3",
                                                                               tipo="texto")]
    r = L.resumir(linhas)
    assert r["leituras"] == 6 and r["distintas"] == 5 and r["repetidas"] == 1
    assert r["repetida_pct"] == pytest.approx(16.67)
    assert r["releituras_no_job"] == 1 and r["conferencia"] == 1
    assert r["repetidas_lista"][0]["estagio"] == "texto" and r["repetidas_lista"][0]["jobs"] == ["j1", "j2"]


def test_sem_leitura_e_indisponivel_nunca_zero():
    assert L.repetida_pct(0, 0) is None
    assert L.resumir([])["repetida_pct"] is None


def test_registro_agrega_no_job_e_ignora_tipo_desconhecido():
    r = L.Registro(estagio="texto", versao="e4-1", modo="rodar", job_chave="texto:x", ficha=7)
    r.anotar("pdf", "s1")
    r.anotar("pdf", "s1")
    r.anotar("pdf", "s2", versao="outra")
    r.anotar("inventado", "s3")
    r.anotar("pdf", "")
    linhas = r.linhas()
    assert [(x[2], x[3], x[4], x[8]) for x in linhas] == [("pdf", "s1", "e4-1", 2), ("pdf", "s2", "outra", 1)]


def test_ganchos_anotam_pdf_texto_e_llm_concluida_mas_nao_a_recusada(tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz")
    from compliance_agent.adaptadores.llm import gateway as G
    pdf = tmp_path / "a.pdf"
    d = fitz.open()
    d.new_page().insert_text((72, 72), "texto nativo da pagina")
    d.save(pdf)
    d.close()
    chamadas = {"n": 0}

    class R:
        modelo = "m"

    def falso(tarefa, mensagens, **kw):
        chamadas["n"] += 1
        if kw.get("prompt_version") == "recusa":
            raise G.SemProvedor("sem provedor", [])
        return R()
    monkeypatch.setattr(G, "chamar", falso)
    reg = L.instrumentar(L.Registro(estagio="texto", versao="e4-1", modo="rodar"))
    try:
        fitz.open(pdf).close()
        fitz.open(pdf).close()
        (tmp_path / "t.txt").write_text("um texto", encoding="utf-8")
        acervo_texto.ler(tmp_path, {"texto": "t.txt"})
        G.chamar("x", [{"role": "user", "content": "oi"}], prompt_version="p1")
        with pytest.raises(G.SemProvedor):
            G.chamar("x", [{"role": "user", "content": "oi"}], prompt_version="recusa")
    finally:
        L.desinstrumentar()
    tipos = {(x[2], x[4]): x[8] for x in reg.linhas()}
    assert tipos[("pdf", "e4-1")] == 2                  # o mesmo PDF aberto 2× no job = 1 linha, n = 2
    assert tipos[("texto", "e4-1")] == 1
    assert tipos[("llm", "p1")] == 1 and ("llm", "recusa") not in tipos
    assert chamadas["n"] == 2 and G.chamar is falso     # desinstrumentar devolve o original


def test_estagio_de_alcanca_o_e13_calibrar():
    from compliance_agent.aplicacao.estagios import calibrar, estagio_de
    assert estagio_de("calibrar") is calibrar.ESTAGIO
    assert estagio_de("calibrar:e10.ob_antes_da_liquidacao") is calibrar.ESTAGIO


# ── E4: o mesmo PDF (mesmo sha256) anexado em dois documentos é extraído UMA vez ─────────────────────────────────
@pytest.fixture()
def pg_texto():
    import uuid

    import psycopg

    from compliance_agent.aplicacao.estagios import texto as T
    from tests.fluxo_pg import DSN
    nome = f"tmp_o85e4_{uuid.uuid4().hex[:10]}"
    T.aplicar_schema(DSN, nome)
    try:
        yield nome
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')


def _precisa_pg():
    from tests.fluxo_pg import precisa_pg
    return precisa_pg


@_precisa_pg()
def test_e4_mesmo_binario_em_dois_documentos_e_lido_uma_vez(pg_texto, tmp_path):
    from compliance_agent.aplicacao.estagios import texto as T
    from tests.fluxo_pg import DSN
    from tests.test_estagio_texto import PROC, ctx, pdf_de
    a = pdf_de(tmp_path / "a.pdf", ["nativa", "escaneada"])
    b = tmp_path / "b.pdf"
    b.write_bytes(a.read_bytes())                                   # o MESMO anexo em outro documento
    sha = T.sha256_arquivo(a)
    regs, efs = [], []
    for k, (doc, pdf) in enumerate((("sei:1", a), ("sei:2", b)), 1):
        c = ctx("texto", doc, sha, ficha=k)
        pl = {"processo": PROC, "doc_id": doc, "sha256": sha, "arquivo": str(pdf), "dsn": DSN, "esquema": pg_texto,
              "raiz_texto": str(tmp_path / "texto")}
        reg = L.instrumentar(L.Registro(estagio="texto", versao=T.VERSAO, modo="rodar", job_chave=c.chave))
        try:
            r = T._handler(pl, c)
        finally:
            L.desinstrumentar()
        regs.append(reg)
        efs.append((r, T._efeito(pl, c, r)))
    assert [len([x for x in r.linhas() if x[2] == "pdf"]) for r in regs] == [1, 0]   # o 2º job não abre o PDF
    (r1, ok1), (r2, ok2) = efs
    assert ok1 and ok2                                                 # efeito conferido nos dois (relê na conferência)
    assert r1.efeito["texto_sha"] == r2.efeito["texto_sha"] and r2.efeito["escaneadas"] == [2]
    assert {e["tipo"] for e in r2.eventos} == {"texto_novo", "pagina_escaneada"}
    assert L.resumir([{"estagio": "texto", "tipo": x[2], "sha": x[3], "versao": x[4], "modo": "rodar", "n": x[8],
                       "job_chave": x[6]} for r in regs for x in r.linhas()])["repetidas"] == 0
