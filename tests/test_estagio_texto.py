# -*- coding: utf-8 -*-
"""E4 `texto` (O3.4): perfil por página (nativa/escaneada/branca) e do documento (mista/invalida), transformacao +
versão de texto + lateral no PG (esquema temporário), efeito que relê o PDF e pega o lateral adulterado,
idempotência pela entrada e o binário achado pela aquisição do E3 (sha256 conferido). PDFs gerados aqui (PyMuPDF)."""
import json
import uuid

import pytest
import yaml

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, estagio_de
from compliance_agent.aplicacao.estagios import texto as T
from tests.fluxo_pg import DSN, precisa_pg

PROC = "270006/000236/2026"
NATIVO = "Nota de liquidação 2026NL000123 — valor R$ 1.234,56 — credor 11.222.333/0001-81 conferido. "


def pdf_de(caminho, paginas):
    """`paginas`: lista de 'nativa' | 'escaneada' | 'branca' | ('escaneada', 'carimbo')."""
    import fitz
    doc = fitz.open()
    for k, p in enumerate(paginas):
        tipo, carimbo = (p, "") if isinstance(p, str) else p
        pg = doc.new_page()
        if tipo == "nativa":
            pg.insert_text((72, 72), NATIVO, fontsize=9)
        elif tipo == "escaneada":
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 80), 0)
            pix.set_rect(pix.irect, (200, 200, 200 - k))       # uma imagem por página (dedup por hash é O3.6)
            pg.insert_image(fitz.Rect(20, 20, 580, 800), pixmap=pix)
            if carimbo:
                pg.insert_text((30, 30), carimbo, fontsize=6)
    doc.save(caminho)
    doc.close()
    return caminho


def ctx(tipo: str, doc_id: str, sha: str, ficha: int = 1) -> Contexto:
    return Contexto(no="vm2", tipo=tipo, chave=T.chave_job(tipo, PROC, doc_id, sha), ficha=ficha, tentativa=1)


@pytest.fixture()
def pg():
    import psycopg
    nome = f"tmp_textoocr_{uuid.uuid4().hex[:10]}"
    T.aplicar_schema(DSN, nome)
    T.aplicar_schema(DSN, nome)                                       # idempotente
    con = T.conectar(DSN, nome)
    try:
        yield con, nome
    finally:
        con.close()
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')


def rodar_e4(nome, tmp_path, pdf, doc_id="sei:111", ficha=1):
    sha = T.sha256_arquivo(pdf)
    c = ctx("texto", doc_id, sha, ficha)
    pl = {"processo": PROC, "doc_id": doc_id, "sha256": sha, "arquivo": str(pdf), "dsn": DSN, "esquema": nome,
          "raiz_texto": str(tmp_path / "texto")}
    r = T._handler(pl, c)
    return r, T._efeito(pl, c, r), pl, c


# ── puro ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_perfil_por_pagina_e_documento(tmp_path):
    ex = T.extrair(pdf_de(tmp_path / "a.pdf", ["nativa", "escaneada", "branca", ("escaneada", "Pag 4")]))
    assert [p["perfil"] for p in ex["paginas"]] == ["nativa", "escaneada", "branca", "escaneada"]
    assert ex["perfil"] == T.MISTA and ex["escaneadas"] == [2, 4]
    assert ex["paginas"][3]["texto"].strip() == "Pag 4"                 # o carimbo nativo é guardado
    assert T.extrair(pdf_de(tmp_path / "b.pdf", ["nativa", "nativa"]))["perfil"] == T.NATIVA
    assert T.extrair(pdf_de(tmp_path / "c.pdf", ["branca"]))["perfil"] == T.BRANCA
    assert T.texto_composto(ex).count(T.QUEBRA) == 3                    # \f separa as páginas (o E8 conta assim)


def test_texto_de_waf_ou_menu_do_sei_e_invalido(tmp_path):
    import fitz
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Web Page Blocked - Attack ID: 2026 - the url you requested has been blocked")
    doc.save(tmp_path / "waf.pdf")
    ex = T.extrair(tmp_path / "waf.pdf")
    assert ex["perfil"] == T.INVALIDA and "WAF" in ex["invalido"]


def test_pdf_que_nao_abre_e_permanente(tmp_path):
    (tmp_path / "x.pdf").write_bytes(b"isto nao e pdf")
    with pytest.raises(ErroPermanente):
        T.extrair(tmp_path / "x.pdf")


def test_registro_e_rotina_inativa():
    assert estagio_de("texto:x") is T.ESTAGIO
    rot = yaml.safe_load(open(T.A.RAIZ / "config" / "fluxo.yaml", encoding="utf-8"))["rotinas"]["texto_e4"]
    assert rot["estagio"] == "E4" and rot["ativa"] is False and "parada de obras" in rot["bloqueio"]


# ── PostgreSQL ───────────────────────────────────────────────────────────────────────────────────────────────
@precisa_pg
def test_e4_grava_transformacao_versao_e_lateral_e_e_idempotente(pg, tmp_path):
    con, nome = pg
    pdf = pdf_de(tmp_path / "001.pdf", ["nativa", "escaneada"])
    r, ok, _, _ = rodar_e4(nome, tmp_path, pdf)
    assert ok, r.efeito["conferencia"]
    assert r.efeito["escaneadas"] == [2] and r.efeito["perfil"] == T.MISTA
    tipos = [e["tipo"] for e in r.eventos]
    assert tipos == ["texto_novo", "pagina_escaneada"]                   # E8 e E5; não vai ao E7 antes do OCR
    r2, ok2, _, _ = rodar_e4(nome, tmp_path, pdf, ficha=2)
    assert ok2
    assert con.execute("SELECT count(*) FROM transformacao WHERE tipo = 'texto_nativo'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM versoes WHERE hash_de = 'texto' AND origem = 'sei:e4'").fetchone()[0] == 1


@precisa_pg
def test_so_nativo_vai_direto_ao_e7(pg, tmp_path):
    _, nome = pg
    r, ok, _, _ = rodar_e4(nome, tmp_path, pdf_de(tmp_path / "002.pdf", ["nativa"]))
    assert ok and [e["tipo"] for e in r.eventos] == ["texto_novo", "sem_ocr"]


@precisa_pg
def test_so_escaneado_nao_grava_versao_de_texto_vazia(pg, tmp_path):
    con, nome = pg
    r, ok, _, _ = rodar_e4(nome, tmp_path, pdf_de(tmp_path / "003.pdf", ["escaneada"]))
    assert ok and not r.efeito["versao_texto"] and [e["tipo"] for e in r.eventos] == ["pagina_escaneada"]
    assert con.execute("SELECT count(*) FROM versoes").fetchone()[0] == 0


@precisa_pg
def test_efeito_pega_lateral_adulterado(pg, tmp_path):
    _, nome = pg
    r, ok, pl, c = rodar_e4(nome, tmp_path, pdf_de(tmp_path / "004.pdf", ["nativa"]))
    lat = tmp_path / "texto" / "270006_000236_2026"
    arq = next(lat.glob("*.e4.json"))
    d = json.loads(arq.read_text(encoding="utf-8"))
    d["paginas"][0]["texto"] = "outro texto"
    arq.write_text(json.dumps(d), encoding="utf-8")
    assert ok and not T._efeito(pl, c, r)


@precisa_pg
def test_binario_achado_pela_aquisicao_do_e3_e_sha_conferido(pg, tmp_path):
    con, nome = pg
    out = tmp_path / "integra_x"
    out.mkdir()
    pdf = pdf_de(out / "000.pdf", ["nativa"])
    (out / "manifest.json").write_text(json.dumps({"docs": [{"i": 0, "arquivo": "000.pdf",
                                                             "titulo": "Despacho 90000000"}]}))
    sha = T.sha256_arquivo(pdf)
    con.execute("INSERT INTO aquisicao(id, fonte, detalhe) VALUES ('e3:t', 'sei:e3', %s)",
                (json.dumps({"outdir": str(out)}),))
    con.execute("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, vista_em, hash_de, aquisicao_id) VALUES "
                "(%s, 'sei:90000000', %s, 0, 'sei:e3', 'x', 'binario', 'e3:t')", (PROC, sha))
    assert T.localizar_binario(con, PROC, "sei:90000000", sha) == pdf
    jobs = T.jobs_da_aquisicao(con, "e3:t")
    assert [j["chave"] for j in jobs] == [T.chave_job("texto", PROC, "sei:90000000", sha)]
    pdf.write_bytes(pdf.read_bytes() + b"%lixo")                        # outro arquivo no lugar
    with pytest.raises(ErroPermanente, match="não é a versão"):
        T.localizar_binario(con, PROC, "sei:90000000", sha)


def test_captura_ausente_no_no_e_trazida_da_vm2(tmp_path, monkeypatch):
    """26/11/2026: o E4 tem a VM-1 de volta e o E5 prefere o it-campo, mas a captura canônica mora na VM-2; fora dela a
    pasta faltava («manifest.json ausente»). Pasta ausente no nó ⇒ traz da VM-2 (rsync --checksum) e segue; o sha256
    da versão continua conferido depois."""
    from compliance_agent.aplicacao.estagios import texto as T
    out = tmp_path / "data" / "sei_cache" / "integra_9_9_2026"
    chamados = []

    def rodar(argv, **k):
        chamados.append(argv)
        out.mkdir(parents=True, exist_ok=True)
        (out / "manifest.json").write_text('{"docs": []}')
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    monkeypatch.setattr(T.subprocess, "run", rodar)
    monkeypatch.setenv("JFN_E3_ESPELHO", "vm2-ts:JFN-worker/data/sei_cache")
    assert T.trazer_captura(out) is True
    assert chamados[0][0] == "rsync" and chamados[0][-2] == "vm2-ts:JFN-worker/data/sei_cache/integra_9_9_2026/"
    monkeypatch.delenv("JFN_E3_ESPELHO")
    assert T.trazer_captura(tmp_path / "outra") is False               # sem destino canônico: não tenta
