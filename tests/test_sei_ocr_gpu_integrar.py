"""Integrador do OCR por IA (GPU do it-campo) no arquivo canônico do SEI — 18/11/2026."""
from __future__ import annotations

import json

import tools.sei_ocr_gpu_integrar as G


def _monta(tmp_path, docs: list[dict], textos: dict[str, str], gpu: dict[int, str]):
    arq, cache = tmp_path / "sei_arquivo" / "111_222_2024", tmp_path / "sei_cache" / "integra_111_222_2024"
    (arq / "texto").mkdir(parents=True)
    cache.mkdir(parents=True)
    for nome, t in textos.items():
        (arq / "texto" / nome).write_text(t, encoding="utf-8")
    (arq / "manifest.json").write_text(json.dumps({"processo": "111/222/2024", "docs": docs}), encoding="utf-8")
    for i, t in gpu.items():
        (cache / f"{i:03d}.ocr_gpu.txt").write_text(t, encoding="utf-8")
        (cache / f"{i:03d}.ocr_gpu.json").write_text(json.dumps({"motor": "surya-ocr-2.5", "paginas": 1}))
    return arq, cache


def test_preenche_sem_texto_nunca_substitui_texto_existente_e_nunca_toca_nativo(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(G, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(G, "LEDGER", tmp_path / "ledger.jsonl")
    docs = [
        {"i": 0, "titulo": "Nota Fiscal 53", "fase": "despesa", "tipo": "nota_fiscal", "texto": "", "chars": 0,
         "ocr": False, "nao_capturado": True},
        {"i": 1, "titulo": "Publicação DO", "fase": "indefinida", "tipo": "outro", "texto": "texto/001_pub.txt",
         "chars": 60, "ocr": True},
        {"i": 2, "titulo": "Despacho", "fase": "tramitacao", "tipo": "despacho", "texto": "texto/002_desp.txt",
         "chars": 70, "ocr": False},
    ]
    textos = {"001_pub.txt": "[Publicação DO] (fase: indefinida · tipo: outro)\n\nDIÁRIO E) OFICIAL DO RFO DE JANEIRO",
              "002_desp.txt": "[Despacho] (fase: tramitacao · tipo: despacho)\n\nEncaminho o processo à DIRAF."}
    gpu = {0: "NOTA FISCAL DE SERVIÇO Nº 53 Valor R$ 94.999,98", 1: "DIÁRIO OFICIAL DO ESTADO DO RIO DE JANEIRO",
           2: "lixo que não pode substituir o nativo"}
    arq, _ = _monta(tmp_path, docs, textos, gpu)
    res = G.integrar()
    man = json.loads((arq / "manifest.json").read_text())
    d0, d1, d2 = man["docs"]
    assert d0["texto"] and d0["ocr"] is True and d0["ocr_motor"].startswith("surya") and d0["chars"] > 40
    assert "94.999,98" in (arq / d0["texto"]).read_text()
    assert (arq / d0["texto"]).read_text().startswith("[Nota Fiscal 53] (fase: despesa · tipo: nota_fiscal)")
    # 20/11/2026 (dono: 100% acurado): texto existente NUNCA é substituído; o da GPU fica ao lado
    assert "RFO" in (arq / d1["texto"]).read_text() and d1.get("ocr_motor") is None
    assert "RIO DE JANEIRO" in (arq / d1["ocr_gpu_ao_lado"]).read_text()
    assert d2 == docs[2]                                              # nativo intocado
    assert "lixo" not in (arq / "texto" / "002_desp.txt").read_text()
    assert (res["preenchidos"], res["substituidos"], res["nativos_mantidos"]) == (1, 0, 1)
    # idempotente: segunda rodada não refaz
    assert G.integrar()["preenchidos"] == 0 and G.integrar()["substituidos"] == 0


def test_texto_gpu_vazio_nao_substitui(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(G, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(G, "LEDGER", tmp_path / "ledger.jsonl")
    docs = [{"i": 1, "titulo": "Pub", "fase": "x", "tipo": "outro", "texto": "texto/001_pub.txt", "chars": 60, "ocr": True}]
    arq, _ = _monta(tmp_path, docs, {"001_pub.txt": "[Pub] (fase: x · tipo: outro)\n\ntexto do tesseract razoável"},
                    {1: "  \n[página 1]\n  "})
    G.integrar()
    assert "tesseract" in (arq / "texto" / "001_pub.txt").read_text()


def test_fila_prioriza_nota_fiscal_sem_texto_e_pula_nativo_e_aplicado(tmp_path, monkeypatch):
    import tools.sei_ocr_gpu_fila as F
    arq = tmp_path / "sei_arquivo" / "111_222_2024"
    arq.mkdir(parents=True)
    docs = [{"i": 0, "tipo": "despacho", "chars": 500, "ocr": True},          # tesseract, prioridade baixa
            {"i": 1, "tipo": "nota_fiscal", "chars": 0},                      # sem texto, NF → primeiro
            {"i": 2, "tipo": "nota_fiscal", "chars": 900, "ocr": False},       # nativo → nunca
            {"i": 3, "tipo": "ordem_bancaria", "chars": 300, "ocr": True},     # tesseract OB
            {"i": 4, "tipo": "nota_fiscal", "chars": 0},                       # já aplicado → fora
            {"i": 5, "tipo": "nota_fiscal", "chars": 0}]                       # sem PDF no frio → fora
    (arq / "manifest.json").write_text(json.dumps({"docs": docs}))
    monkeypatch.setattr(F, "ARQUIVO", tmp_path / "sei_arquivo")
    frio = {f"integra_111_222_2024/{i:03d}.pdf" for i in range(5)}
    fila = F.montar(frio, {("111_222_2024", 4)})
    assert fila == ["integra_111_222_2024/001.pdf", "integra_111_222_2024/003.pdf", "integra_111_222_2024/000.pdf"]


def test_texto_com_acento_quebrado_nao_entra(tmp_path, monkeypatch):
    """18/11/2026: o vLLM 0.34 devolvia 'Liquida��o' (byte do ç/ã cortado). Texto com U+FFFD não entra no arquivo."""
    monkeypatch.setattr(G, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(G, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(G, "LEDGER", tmp_path / "ledger.jsonl")
    docs = [{"i": 0, "titulo": "NL", "fase": "despesa", "tipo": "nota_liquidacao", "texto": "", "chars": 0}]
    arq, _ = _monta(tmp_path, docs, {}, {0: "Nota de Liquida��o encerrado até Mar�o valor 1.234,56 " * 3})
    res = G.integrar()
    assert res["preenchidos"] == 0 and res.get("texto_corrompido") == 1
    assert json.loads((arq / "manifest.json").read_text())["docs"][0]["chars"] == 0


def test_entrega_vazia_nao_fica_registrada_e_pode_voltar(tmp_path, monkeypatch):
    """18/11/2026: 36 entregas vazias (vLLM fora do ar) ficaram no registro como 'gpu_vazio' e nunca voltariam."""
    monkeypatch.setattr(G, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(G, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(G, "LEDGER", tmp_path / "ledger.jsonl")
    docs = [{"i": 0, "titulo": "NF", "fase": "despesa", "tipo": "nota_fiscal", "texto": "", "chars": 0}]
    arq, cache = _monta(tmp_path, docs, {}, {0: "[página 1]\n"})
    G.integrar()
    assert not (cache / "000.ocr_gpu.txt").exists()                          # apagada para a releitura chegar
    (cache / "000.ocr_gpu.txt").write_text("NOTA FISCAL Nº 53 valor R$ 94.999,98 serviço prestado em março", encoding="utf-8")
    assert G.integrar()["preenchidos"] == 1


def test_um_unico_caractere_quebrado_ja_barra(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(G, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(G, "LEDGER", tmp_path / "ledger.jsonl")
    docs = [{"i": 0, "titulo": "NL", "fase": "despesa", "tipo": "nota_liquidacao", "texto": "", "chars": 0}]
    _monta(tmp_path, docs, {}, {0: "Nota de Liquida�ão valor 1.234,56 referente ao contrato 12/2024 " * 2})
    assert G.integrar()["preenchidos"] == 0


def test_texto_existente_nunca_e_substituido_mesmo_com_cnpj_mantido(tmp_path, monkeypatch):
    """20/11/2026 (lote real do frio, conferido à mão): o Surya devolveu blocos vazios (razão social, CNPJ do
    prestador, discriminação) onde o Tesseract tinha texto. Perda de bloco não se mede só por CNPJ: o texto atual fica
    SEMPRE, inclusive quando o novo mantém todos os CNPJ; o da GPU vai ao lado (`.gpu.txt`)."""
    monkeypatch.setattr(G, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(G, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(G, "LEDGER", tmp_path / "ledger.jsonl")
    docs = [{"i": 0, "titulo": "NF", "fase": "despesa", "tipo": "nota_fiscal", "texto": "texto/000_nf.txt", "chars": 90,
             "ocr": True},
            {"i": 1, "titulo": "NF", "fase": "despesa", "tipo": "nota_fiscal", "texto": "texto/001_nf.txt", "chars": 90,
             "ocr": True}]
    tess = "[NF] (fase: despesa · tipo: nota_fiscal)\n\nPrestador ARIES CNPJ 06.049,955/0001.10 valor 100.033,95 " \
           "tomador 42.498.642/0001-02"
    textos = {"000_nf.txt": tess, "001_nf.txt": tess}
    gpu = {0: "Tomador CNPJ 42.498.642/0001-02 VALOR TOTAL R$ 100.033,95 (bloco do prestador veio vazio) <|30|>",
           1: "Prestador CNPJ 06.049.955/0001-10 tomador 42.498.642/0001-02 VALOR TOTAL R$ 100.033,95"}
    arq, _ = _monta(tmp_path, docs, textos, gpu)
    res = G.integrar()
    assert res["substituidos"] == 0
    d0, d1 = json.loads((arq / "manifest.json").read_text())["docs"]
    for d, nome in ((d0, "000_nf.txt"), (d1, "001_nf.txt")):
        assert (arq / "texto" / nome).read_text() == tess
        assert d["texto"] == f"texto/{nome}" and d.get("ocr_motor") is None
    assert "<|30|>" not in (arq / d0["ocr_gpu_ao_lado"]).read_text()          # token do modelo não vaza
    acoes = [json.loads(ln)["acao"] for ln in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert acoes == ["mantido_existente_gpu_ao_lado"] * 2


def test_manifesto_gravado_sob_a_trava_e_ocupado_volta_depois(tmp_path, monkeypatch):
    """20/11/2026: o integrador regravava o manifesto inteiro sem trava (o que a captura gravasse no meio sumia).
    Agora é reler-mesclar-gravar sob `manifest.json.lock`; trava ocupada → nada gravado nem registrado, volta depois."""
    import functools

    from compliance_agent.llm.arquivo_estado import trava
    from compliance_agent.sei import acervo_texto
    monkeypatch.setattr(G, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(G, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(G, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(G, "mutar_manifesto", functools.partial(acervo_texto.mutar_manifesto, espera=0.2))
    docs = [{"i": 0, "titulo": "NF", "fase": "despesa", "tipo": "nota_fiscal", "texto": "", "chars": 0}]
    arq, _ = _monta(tmp_path, docs, {}, {0: "NOTA FISCAL Nº 53 valor R$ 94.999,98 serviço prestado em março"})
    with trava(arq / "manifest.json.lock", 1) as pegou:
        assert pegou
        res = G.integrar()
    assert res["preenchidos"] == 0 and res["manifesto_ocupado"] == 1
    assert not (tmp_path / "ledger.jsonl").exists()
    # outro escritor muda o manifesto no meio: o integrador relê e preserva o campo novo
    man = json.loads((arq / "manifest.json").read_text())
    man["capturado_em"] = "2026-11-20 19:00"
    (arq / "manifest.json").write_text(json.dumps(man))
    assert G.integrar()["preenchidos"] == 1
    man = json.loads((arq / "manifest.json").read_text())
    assert man["capturado_em"] == "2026-11-20 19:00" and man["docs"][0]["ocr_motor"].startswith("surya")
