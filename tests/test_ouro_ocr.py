# -*- coding: utf-8 -*-
"""Ouro congelado do OCR (O3.6): rótulo só com 2 FAMÍLIAS concordando + recorte (RapidOCR e PP-OCRv6 são a mesma
família Paddle); o resto vai à revisão, com o porquê; separação da calibração por bloco (só processo reservado, nunca
processo das bancadas que escolheram motor); congelado com sha256 e data, sem regravar; `humano=False` declarado."""
import json

import pytest

from compliance_agent.qualidade import ouro as OU
from compliance_agent.qualidade import ouro_ocr as OO

CNPJ = "11.222.333/0001-81"


def _proc_reservado(reservado=True):
    for k in range(1, 5000):
        p = f"SEI-270006/{k:06d}/2025"
        if OO.reservado(p) is reservado:
            return p
    raise AssertionError("sem processo")


def test_familias_paddle_conta_uma_so():
    assert OO.familia("rapidocr@3.10 PP-OCRv5") == OO.familia("ppocrv6@paddleocr3.7 medium") == "paddle"
    assert OO.familia("surya@0.24 (vLLM)") == "surya" and OO.familia("tesseract@5.3") == "tesseract"
    rot, rev = OO.rotular_pagina({"rapidocr@x": f"CNPJ {CNPJ}", "ppocrv6@y": f"CNPJ {CNPJ}"},
                                 {("cnpj", "11222333000181")})
    assert rot == [] and rev[0]["motivo"] == "uma_familia"               # duas leituras Paddle não são consenso


def test_rotulo_exige_duas_familias_e_recorte():
    lt = {"surya@a": f"CNPJ {CNPJ} total R$ 1.234,56", "tesseract@b": f"CNPJ {CNPJ} total R$ 1.234,58",
          "rapidocr@c": "total R$ 1.234,56"}
    rot, rev = OO.rotular_pagina(lt, {("cnpj", "11222333000181")})
    assert rot == ["cnpj:11222333000181"]
    motivos = {r["numero"]: r["motivo"] for r in rev}
    assert motivos == {"valor:1234.56": "recorte_nao_conferiu", "valor:1234.58": "uma_familia"}
    with pytest.raises(OO.ErroOuroOCR):
        OO.rotular_pagina({"motor-desconhecido": "x"}, set())
    # NF não tem recorte: só com as três famílias
    nf = {"surya@a": "Nota Fiscal nº 123", "tesseract@b": "Nota Fiscal nº 123", "rapidocr@c": "Nota Fiscal nº 128"}
    rot, rev = OO.rotular_pagina(nf, set(), {"valor", "cnpj", "data", "processo"})
    assert rot == [] and rev[0]["motivo"] == "tipo_sem_recorte_e_sem_as_3_familias"
    nf["rapidocr@c"] = "Nota Fiscal nº 123"
    assert OO.rotular_pagina(nf, set(), {"valor", "cnpj", "data", "processo"})[0] == ["nf:123"]


def test_separacao_da_calibracao():
    assert OO.vazamentos([_proc_reservado()], []) == []
    assert OO.vazamentos([_proc_reservado(False)], [])[0].startswith("nao_reservado:")
    p = _proc_reservado()
    assert any(v.startswith("processo:") for v in OO.vazamentos([p], [p]))
    # o processo da bancada de 23/11 (calibração dos motores) nunca entra, nem se o sorteio o reservasse
    assert any(v.startswith("processo:") for v in OO.vazamentos(["SEI-030001/087722/2024"], []))
    assert OO.reservado(p) == OU.reservado_ouro(OU.bloco({"processo": OO.chave_processo(p)}))


def _pag(sha="a" * 64, processo=None, rotulado_em="2026-11-25", **kw):
    return OO.PaginaOuro(item="x/001.pdf#1", processo=processo or _proc_reservado(), grupo="nota_fiscal",
                         tipo_doc="nota_fiscal", img_sha=sha, rotulos=("cnpj:11222333000181",),
                         revisar=({"numero": "valor:1.00", "motivo": "uma_familia"},), motores=("surya@a",),
                         rotulado_em=rotulado_em, **kw)


def test_congela_le_e_recusa_adulteracao_regravacao_e_repeticao(tmp_path):
    arq = OO.congelar([_pag(), _pag("b" * 64)], tmp_path, "2026-11-25")
    pags = OO.ler_congelado(arq)
    assert len(pags) == 2 and all(not p.humano and p.metodo == OO.METODO for p in pags)
    man = json.loads(arq.with_name(arq.name.replace(".jsonl", ".manifesto.json")).read_text())
    assert man["por_grupo"] == {"nota_fiscal": 2} and man["humano"] is False and man["revisar"] == 2
    with pytest.raises(OO.ErroOuroOCR):
        OO.congelar([_pag()], tmp_path, "2026-11-25")                   # nunca regravar
    with pytest.raises(OO.ErroOuroOCR):
        OO.congelar([_pag(), _pag()], tmp_path / "r", "2026-11-25")     # mesma imagem duas vezes
    with pytest.raises(OO.ErroOuroOCR):
        OO.congelar([_pag(rotulado_em="2026-11-26")], tmp_path / "t", "2026-11-25")
    with pytest.raises(OO.ErroOuroOCR):
        OO.congelar([_pag(processo=_proc_reservado(False))], tmp_path / "v", "2026-11-25")
    arq.write_text(arq.read_text().replace("11222333000181", "11222333000182"))
    with pytest.raises(OO.ErroOuroOCR):
        OO.ler_congelado(arq)


def test_medir_conta_so_rotulo_e_inventado_fora_da_revisao():
    p = _pag()
    m = OO.medir([p], {p.img_sha: {"m": f"CNPJ {CNPJ} R$ 1,00 e R$ 7,00"}})
    assert m == {"rotulos": 1, "lidos": 1, "acerto_%": 100.0, "emitidos": 3, "inventados": 1,
                 "inventado_%": 33.33}


def test_revisao_ia_so_depois_de_sabado_e_so_desempata(monkeypatch):
    from datetime import datetime

    from tools import ocr_ouro_revisao_ia as RV
    assert not RV.liberado(datetime(2026, 11, 28, 18, 59, tzinfo=RV.BRT))
    assert RV.liberado(datetime(2026, 11, 28, 19, 0, tzinfo=RV.BRT))
    monkeypatch.setattr(RV, "liberado", lambda agora=None: False)
    assert RV.main(["--ouro", "x", "--revisao", "y", "--recortes", "z"]) == 2        # antes da hora: recusa
    it = {"numero": "valor:1234.56", "leituras": {"surya": ["valor:1234.56"], "tesseract": ["valor:1284.56"]}}
    assert RV.decidir(it, {"lido": "1.284,56", "legivel": True}) == "valor:1284.56"
    assert RV.decidir(it, {"lido": "9.999,99", "legivel": True}) is None             # a IA não inventa número
    assert RV.decidir(it, {"lido": None, "legivel": False}) is None
