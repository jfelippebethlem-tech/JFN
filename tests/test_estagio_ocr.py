# -*- coding: utf-8 -*-
"""E5 `ocr` (O3.4): OCR SÓ onde está vazio (página nativa nunca é lida; o carimbo nativo da página escaneada fica,
inteiro e primeiro), VAZIO NÃO É FEITO (sem 2º motor: nada no PG e efeito falha; com 2º motor de outra família:
`vazia_conferida`), erro de inferência é erro, bbox e motor@versão no lateral, idempotência no PG, escolha do
executor (GPU só no it-campo; volta CPU) e a migração das filas legadas (plano puro + replay num esquema temporário
do fluxo, idempotente, 0 perda). Executores FALSOS: nenhum OCR de verdade roda aqui."""
import pytest

from compliance_agent.aplicacao.estagios import ErroPermanente, estagio_de
from compliance_agent.aplicacao.estagios import ocr as O
from compliance_agent.aplicacao.estagios import texto as T
from compliance_agent.aplicacao.estagios import texto_ocr_legado as L
from tests.fluxo_pg import DSN, con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures do fluxo temporário
from tests.test_estagio_texto import PROC, ctx, pdf_de, pg, rodar_e4  # noqa: F401 — fixture do esquema temporário


class Falso:
    def __init__(self, familia, textos=None, erro=False):
        self.familia, self.textos, self.erro, self.pedidas = familia, textos or {}, erro, []

    def motor(self):
        return f"{self.familia}@teste"

    def ler(self, pdf, paginas):
        self.pedidas.append(list(paginas))
        if self.erro:
            raise O.ErroInferencia("bloco com erro de inferência")
        return {n: O.Leitura(self.textos.get(n, ""), [{"texto": "x", "bbox": [1, 2, 3, 4], "conf": 0.9}]
                             if self.textos.get(n) else [], 100, 200) for n in paginas}


def _e4(tmp_path, paginas):
    pdf = pdf_de(tmp_path / "001.pdf", paginas)
    return pdf, T.extrair(pdf)


# ── puro ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_ocr_nao_substitui_texto_existente(tmp_path):
    pdf, e4 = _e4(tmp_path, ["nativa", ("escaneada", "Pag 2"), "branca"])
    g = Falso("gpu", {1: "LIXO QUE NÃO PODE ENTRAR", 2: "Valor total R$ 9.999,00"})
    r = O.ocr_documento(pdf, e4, g, None)
    assert g.pedidas == [[2]]                                          # só a escaneada; nativa e branca nunca
    pags = r["texto_composto"].split(T.QUEBRA)
    assert pags[0] == e4["paginas"][0]["texto"]                         # nativa intacta
    assert pags[1].startswith("Pag 2") and pags[1].endswith("R$ 9.999,00")   # carimbo nativo primeiro, OCR depois
    assert "LIXO" not in r["texto_composto"] and r["paginas"]["2"]["linhas"][0]["bbox"] == [1, 2, 3, 4]
    assert r["paginas"]["2"]["motor"] == "gpu@teste"


def test_vazio_nao_e_feito_sem_segundo_motor(tmp_path):
    pdf, e4 = _e4(tmp_path, ["escaneada"])
    r = O.ocr_documento(pdf, e4, Falso("rapidocr"), None)
    assert r["pendentes"] == [1] and r["paginas"]["1"]["estado"] == O.VAZIA_PENDENTE


def test_vazio_conferido_por_outra_familia_e_resgate_do_segundo(tmp_path):
    pdf, e4 = _e4(tmp_path, ["escaneada", "escaneada"])
    segundo = Falso("tesseract", {2: "NOTA FISCAL 123"})
    r = O.ocr_documento(pdf, e4, Falso("rapidocr"), segundo)
    assert segundo.pedidas == [[1, 2]] and r["pendentes"] == []
    p1 = dict(r["paginas"]["1"])
    assert len(p1.pop("img_sha")) == 64 and p1.pop("perfil") == T.ESCANEADA           # O3.6: hash + perfil por página
    assert p1 == {"estado": O.VAZIA_CONFERIDA, "motor": "rapidocr@teste", "conferido_por": "tesseract@teste",
                  "texto": "", "linhas": []}
    assert r["paginas"]["2"]["motor"] == "tesseract@teste" and r["paginas"]["2"]["primeiro_vazio"] == "rapidocr@teste"
    # mesma família não confere a si mesma
    assert O.ocr_documento(pdf, e4, Falso("rapidocr"), Falso("rapidocr"))["pendentes"] == [1, 2]


def test_erro_de_inferencia_e_erro_nao_vazio(tmp_path):
    pdf, e4 = _e4(tmp_path, ["escaneada"])
    with pytest.raises(O.ErroInferencia):
        O.ocr_documento(pdf, e4, Falso("gpu", erro=True), Falso("rapidocr"))
    with pytest.raises(ErroPermanente):                                 # sem página escaneada: nada a fazer
        O.ocr_documento(pdf, T.extrair(pdf_de(tmp_path / "n.pdf", ["nativa"])), Falso("gpu"), None)


def test_escolha_do_executor_e_volta_cpu(monkeypatch):
    monkeypatch.delenv(O.ENV_EXECUTOR, raising=False)
    monkeypatch.setattr(O, "_gpu_disponivel", lambda: True)
    p, s = O.escolher("itcampo")
    assert isinstance(p, O.ExecutorGPU) and isinstance(s, O.ExecutorCPU)
    p, s = O.escolher("vm2")
    assert isinstance(p, O.ExecutorCPU) and isinstance(s, O.ExecutorTesseract)
    monkeypatch.setenv(O.ENV_EXECUTOR, "cpu")                          # it-campo forçado à CPU (ensaio)
    assert isinstance(O.escolher("itcampo")[0], O.ExecutorCPU)
    assert estagio_de("ocr:x") is O.ESTAGIO and O.ESTAGIO.recursos == ["cpu_pesado"]
    assert O.ESTAGIO.volta["nos"] == ["vm2"] and O.NOS == ["itcampo"]


def test_plano_da_migracao_legada():
    f = {"fila_gpu": ["integra_270006_000236_2026/001.pdf", "integra_270006_000236_2026/002.pdf"],
         "reserva": {"integra_270006_000236_2026/003.pdf": {"estado": "reservado", "em": "2026-11-20 10:00:00"},
                     "integra_270006_000236_2026/004.pdf": {"estado": "entregue", "em": "2026-11-20 10:00:00"}},
         "aplicado": [{"tag": "270006_000236_2026", "i": 2, "acao": "preenchido", "em": "2026-11-20 11:00:00"},
                      {"tag": "270006_000236_2026", "i": 5, "acao": "descartado_sem_texto", "em": "2026-11-20"}],
         "conferir": [], "ia_conferencia": [
             {"tag": "270006_000236_2026", "i": 2, "tipo": "valor", "norma": "1.00", "estado": "a_conferir",
              "em": "2026-11-21"}], "confirmacao": [], "frio": [], "hd": {}, "listagem": {}}
    proc = {"270006_000236_2026": PROC}
    docs = {(PROC, 1): "sei:1", (PROC, 2): "sei:2"}
    pl = L.planejar(f, proc, docs, "2026-10-25")
    assert sorted(pl["jobs"]) == sorted([
        f"ocr:{PROC}|sei:1|legado", f"ocr:{PROC}|pos:3|legado", f"ocr:{PROC}|pos:4|legado",   # entregue sem aplicar
        f"ocr:{PROC}|pos:5|legado",                                     # descartado vazio volta ao E5
        f"confirmar_ocr:{PROC}|sei:2|legado"])
    assert "legado/fila_gpu_ja_aplicado|integra_270006_000236_2026/002.pdf" in pl["feitos"]
    assert pl["jobs"][f"ocr:{PROC}|pos:3|legado"]["payload"]["sem_identidade"] is True
    assert pl["jobs"][f"ocr:{PROC}|sei:1|legado"]["payload"]["estagio"] == "E5"


@precisa_pg
def test_migracao_aplicada_e_idempotente_e_sem_perda(con):  # noqa: F811
    f = {"fila_gpu": ["integra_270006_000236_2026/001.pdf"], "reserva": {}, "aplicado": [
        {"tag": "270006_000236_2026", "i": 2, "acao": "substituido", "em": "2026-11-20"}], "conferir": [],
         "ia_conferencia": [], "confirmacao": [], "frio": [], "hd": {}, "listagem": {}}
    pl = L.planejar(f, {}, {}, "2026-10-25")
    assert L.aplicar(con, pl) == {"jobs_novos": 1, "eventos_novos": 1}
    assert L.aplicar(con, pl) == {"jobs_novos": 0, "eventos_novos": 0}
    rec = L.reconferir(con, pl)
    assert rec["perdidos"] == 0 and rec["jobs_por_tipo"] == {"ocr": 1}


# ── PostgreSQL ───────────────────────────────────────────────────────────────────────────────────────────────
def _e5(nome, tmp_path, pdf, sha, executores, monkeypatch, ficha=1):
    monkeypatch.setattr(O, "obter_executores", lambda no: executores)
    c = ctx("ocr", "sei:111", sha, ficha)
    pl = {"processo": PROC, "doc_id": "sei:111", "sha256": sha, "arquivo": str(pdf), "dsn": DSN, "esquema": nome,
          "raiz_texto": str(tmp_path / "texto")}
    r = O._handler(pl, c)
    return r, O._efeito(pl, c, r)


@precisa_pg
def test_e5_grava_so_com_todas_resolvidas_e_vazio_nao_vira_feito(pg, tmp_path, monkeypatch):  # noqa: F811
    con, nome = pg
    pdf = pdf_de(tmp_path / "001.pdf", ["nativa", "escaneada"])
    rodar_e4(nome, tmp_path, pdf)
    sha = T.sha256_arquivo(pdf)
    r, ok = _e5(nome, tmp_path, pdf, sha, (Falso("rapidocr"), None), monkeypatch)
    assert not ok and not r.efeito["gravado"] and r.eventos == []
    assert con.execute("SELECT count(*) FROM transformacao WHERE tipo = 'ocr'").fetchone()[0] == 0
    texto = {2: "CNPJ 11.222.333/0001-81 valor R$ 1.234,56"}
    r, ok = _e5(nome, tmp_path, pdf, sha, (Falso("rapidocr", texto), None), monkeypatch, ficha=2)
    assert ok, r.efeito["conferencia"]
    assert [e["tipo"] for e in r.eventos] == ["texto_novo", "numero_ia"]
    r, ok = _e5(nome, tmp_path, pdf, sha, (Falso("rapidocr", texto), None), monkeypatch, ficha=3)
    assert ok, r.efeito.get("conferencia")
    assert con.execute("SELECT count(*) FROM transformacao WHERE tipo = 'ocr'").fetchone()[0] == 1
    assert con.execute("SELECT ocr FROM versoes WHERE origem = 'sei:e5'").fetchall() == [("rapidocr@teste",)]


@precisa_pg
def test_e5_efeito_pega_nativo_trocado_no_lateral(pg, tmp_path, monkeypatch):  # noqa: F811
    import json
    _, nome = pg
    pdf = pdf_de(tmp_path / "001.pdf", [("escaneada", "Pag 1")])
    rodar_e4(nome, tmp_path, pdf)
    sha = T.sha256_arquivo(pdf)
    r, ok = _e5(nome, tmp_path, pdf, sha, (Falso("gpu", {1: "texto lido"}), None), monkeypatch)
    assert ok
    arq = T.caminho_lateral(PROC, "sei:111", sha, "e5", tmp_path / "texto")
    d = json.loads(arq.read_text(encoding="utf-8"))
    d["texto_composto"] = "texto lido"                                  # OCR por cima do carimbo nativo
    arq.write_text(json.dumps(d), encoding="utf-8")
    c = ctx("ocr", "sei:111", sha)
    assert not O._efeito({"dsn": DSN, "esquema": nome}, c, r)


# ── O3.6: img_sha por página e dedup por hash de imagem ─────────────────────────────────────────────────────────
def _pdf_repetido(caminho, cores):
    """Páginas escaneadas com a imagem de cada cor: cores iguais ⇒ pixels idênticos (página repetida)."""
    import fitz
    doc = fitz.open()
    for cor in cores:
        pg = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 80), 0)
        pix.set_rect(pix.irect, (cor, cor, cor))
        pg.insert_image(fitz.Rect(20, 20, 580, 800), pixmap=pix)
    doc.save(caminho)
    doc.close()
    return caminho


def test_pagina_repetida_le_uma_vez_e_cache_por_motor(tmp_path):
    pdf = _pdf_repetido(tmp_path / "r.pdf", [200, 150, 200])
    e4 = T.extrair(pdf)
    g = Falso("gpu", {1: "NF 1 total R$ 10,00", 2: "outra página", 3: "NÃO PODE SER LIDA"})
    cache = O.CacheImagem(tmp_path / "dedup")
    r = O.ocr_documento(pdf, e4, g, None, cache)
    assert g.pedidas == [[1, 2]]                                         # a 3 é a mesma imagem da 1
    p = r["paginas"]
    assert p["3"]["texto"] == p["1"]["texto"] and p["3"]["dedup_de"] == {"pagina": 1}
    assert p["1"]["img_sha"] == p["3"]["img_sha"] != p["2"]["img_sha"] and len(p["1"]["img_sha"]) == 64
    assert r["dedup"] == {"paginas": 3, "imagens_distintas": 2, "reusadas": [3]} and r["cache_reusadas"] == []
    # outro documento com a mesma imagem: o MESMO motor não relê; outro motor (ou outra versão) relê
    pdf2 = _pdf_repetido(tmp_path / "s.pdf", [150])
    g2 = Falso("gpu", {1: "não pode ser lida de novo"})
    r2 = O.ocr_documento(pdf2, T.extrair(pdf2), g2, None, cache)
    assert g2.pedidas == [] and r2["paginas"]["1"]["texto"] == "outra página"
    assert r2["cache_reusadas"] == [1] and "dedup_de" not in r2["paginas"]["1"]      # lateral igual com e sem cache
    g3 = Falso("rapidocr", {1: "lida pelo outro motor"})
    assert O.ocr_documento(pdf2, T.extrair(pdf2), g3, None, cache)["paginas"]["1"]["texto"] == "lida pelo outro motor"


def test_vazio_nao_entra_no_cache_e_registro_de_outra_imagem_nao_vale(tmp_path):
    pdf = _pdf_repetido(tmp_path / "v.pdf", [90])
    e4 = T.extrair(pdf)
    cache = O.CacheImagem(tmp_path / "dedup")
    assert O.ocr_documento(pdf, e4, Falso("gpu"), None, cache)["pendentes"] == [1]
    assert not list((tmp_path / "dedup").rglob("*.json"))                # vazio nunca é cacheado
    r = O.ocr_documento(pdf, e4, Falso("gpu", {1: "lido"}), None, cache)
    sha = r["paginas"]["1"]["img_sha"]
    arq = cache._arq(sha, "gpu@teste")
    d = T.ler_lateral(arq)[0]
    T.gravar_lateral(arq, d | {"img_sha": "0" * 64})                    # registro de outra imagem no lugar
    g = Falso("gpu", {1: "relido"})
    assert O.ocr_documento(pdf, e4, g, None, cache)["paginas"]["1"]["texto"] == "relido" and g.pedidas == [[1]]


@precisa_pg
def test_e5_efeito_confere_img_sha_e_dedup(pg, tmp_path, monkeypatch):  # noqa: F811
    import json
    _, nome = pg
    pdf = _pdf_repetido(tmp_path / "001.pdf", [120, 120])
    rodar_e4(nome, tmp_path, pdf)
    sha = T.sha256_arquivo(pdf)
    r, ok = _e5(nome, tmp_path, pdf, sha, (Falso("gpu", {1: "lido 1", 2: "lido 2"}), None), monkeypatch)
    assert ok, r.efeito["conferencia"]
    assert r.efeito["conferencia"]["dedup_coerente"] and r.efeito["conferencia"]["img_sha_por_pagina"]
    arq = T.caminho_lateral(PROC, "sei:111", sha, "e5", tmp_path / "texto")
    d = json.loads(arq.read_text(encoding="utf-8"))
    assert d["paginas"]["2"]["dedup_de"] == {"pagina": 1} and d["paginas"]["2"]["texto"] == "lido 1"
    d["paginas"]["2"]["img_sha"] = "f" * 64                              # reuso de página que NÃO é a mesma imagem
    arq.write_text(json.dumps(d), encoding="utf-8")
    c = O.conferir(T.conectar(DSN, nome), r.efeito)
    assert not c["ok"] and not c["dedup_coerente"]


class FalsoIncompleto(Falso):
    """Motor que devolve texto MAS com bloco de texto vazio (o modo de falha do Surya medido na O3.6)."""

    def ler(self, pdf, paginas):
        out = super().ler(pdf, paginas)
        return {n: O.Leitura(le.texto, le.linhas, le.largura, le.altura, blocos_vazios=2) for n, le in out.items()}


def test_incompleta_nao_vira_texto_vai_ao_segundo_e_nao_entra_no_cache(tmp_path):
    pdf = _pdf_repetido(tmp_path / "i.pdf", [77])
    e4 = T.extrair(pdf)
    cache = O.CacheImagem(tmp_path / "dedup")
    g = FalsoIncompleto("gpu", {1: "cabeçalho lido, tabela de valores perdida"})
    r = O.ocr_documento(pdf, e4, g, Falso("rapidocr", {1: "cabeçalho e tabela R$ 1.234,56"}), cache)
    p = r["paginas"]["1"]
    assert p["motor"] == "rapidocr@teste" and p["primeiro_incompleto"] == "gpu@teste" and p["estado"] == O.TEXTO
    assert p["blocos_vazios_do_primeiro"] == 2 and "R$ 1.234,56" in r["texto_composto"]
    assert cache.obter(p["img_sha"], "gpu@teste") is None                # a incompleta nunca é reusada
    # sem 2º motor: pendente (nada vira feito com pedaço faltando)
    r = O.ocr_documento(pdf, e4, FalsoIncompleto("gpu", {1: "parcial"}), None)
    assert r["pendentes"] == [1] and "incompleta" in r["paginas"]["1"]["motivo"]
    # 2º motor sem texto: também pendente, o parcial do 1º não entra
    r = O.ocr_documento(pdf, e4, FalsoIncompleto("gpu", {1: "parcial"}), Falso("rapidocr"))
    assert r["pendentes"] == [1] and r["texto_composto"] == ""


def test_documento_acima_do_teto_e_lido_inteiro_em_lotes(tmp_path, monkeypatch):
    """Achado 1.10: a página acima do teto ficava `vazia_pendente` ⇒ nada no PG, `falhou_efeito` terminal sem evento
    e o E7 preso em `ocr_pendente` para sempre. Agora o teto é o tamanho do LOTE: o documento é lido inteiro, um lote
    por vez (memória limitada), e cada página continua lida uma vez."""
    monkeypatch.setattr(O, "MAX_PAGINAS", 2)
    pdf = _pdf_repetido(tmp_path / "longo.pdf", [10, 20, 30])
    g = Falso("gpu", {1: "um", 2: "dois", 3: "tres"})
    r = O.ocr_documento(pdf, T.extrair(pdf), g, Falso("rapidocr"))
    assert g.pedidas == [[1, 2], [3]] and r["pendentes"] == [] and r["alvo"] == [1, 2, 3]
    assert [r["paginas"][k]["texto"] for k in ("1", "2", "3")] == ["um", "dois", "tres"]
    assert all(len(v["img_sha"]) == 64 for v in r["paginas"].values())


def test_segundo_motor_que_nao_devolve_a_pagina_e_erro_nao_vazia_conferida(tmp_path):
    """Achado 1.9: o 2º motor que omitia a página fazia dela `vazia_conferida` "por dois motores" — o 2º nunca a leu.
    Omissão é erro de inferência (o job tenta de novo), como já era no 1º motor."""
    class Omite(Falso):
        def ler(self, pdf, paginas):
            out = super().ler(pdf, paginas)
            out.pop(2, None)
            return out
    pdf, e4 = _e4(tmp_path, ["escaneada", "escaneada"])
    with pytest.raises(O.ErroInferencia, match="2º motor"):
        O.ocr_documento(pdf, e4, Falso("rapidocr"), Omite("tesseract"))


def test_nativo_com_form_feed_nao_desalinha_as_paginas(tmp_path):
    """O3.6: o texto nativo pode trazer `\\f` (o separador de páginas do composto). O efeito conferia o nativo partindo
    o composto pelo separador e reprovava 5,5% dos mistos reais; agora usa as páginas compostas guardadas."""
    pdf, e4 = _e4(tmp_path, ["nativa", "escaneada"])
    e4["paginas"][0]["texto"] = "cabeçalho\fcorpo nativo"
    r = O.ocr_documento(pdf, e4, Falso("gpu", {2: "lido"}), None)
    assert len(r["compostas"]) == 2 and r["compostas"][0] == "cabeçalho\fcorpo nativo"
    assert T.QUEBRA.join(r["compostas"]) == r["texto_composto"] and len(r["texto_composto"].split(T.QUEBRA)) == 3


@precisa_pg
def test_e5_documento_acima_do_teto_grava_e_emite_os_eventos(pg, tmp_path, monkeypatch):  # noqa: F811
    """Achado 1.10 ponta a ponta: antes, `gravado: False`, efeito reprovado e NENHUM evento (o E7 nunca soltava o
    original e o E8 nunca via o texto). Lido em lotes, grava a transformação e emite os três eventos."""
    con, nome = pg
    monkeypatch.setattr(O, "MAX_PAGINAS", 1)
    pdf = pdf_de(tmp_path / "001.pdf", ["nativa", "escaneada", "escaneada"])
    rodar_e4(nome, tmp_path, pdf)
    sha = T.sha256_arquivo(pdf)
    g = Falso("rapidocr", {2: "NOTA 1", 3: "NOTA 2"})
    r, ok = _e5(nome, tmp_path, pdf, sha, (g, None), monkeypatch)
    assert ok, r.efeito.get("conferencia")
    assert g.pedidas == [[2], [3]] and r.efeito["paginas"] == {O.TEXTO: [2, 3]}
    assert [e["tipo"] for e in r.eventos] == ["texto_novo", "numero_ia"]
