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
    assert r["paginas"]["1"] == {"estado": O.VAZIA_CONFERIDA, "motor": "rapidocr@teste",
                                 "conferido_por": "tesseract@teste", "texto": "", "linhas": []}
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
    assert [e["tipo"] for e in r.eventos] == ["texto_novo", "numero_ia", "terminado"]
    r, ok = _e5(nome, tmp_path, pdf, sha, (Falso("rapidocr", texto), None), monkeypatch, ficha=3)
    assert ok
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
