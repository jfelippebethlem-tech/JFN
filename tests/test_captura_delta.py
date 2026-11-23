# -*- coding: utf-8 -*-
"""Captura por delta (Fase 4): o nó baixa só o novo, o sem texto e o retificado; o que sumiu da árvore viva é
registrado e NUNCA apagado; `#2` para número repetido; árvore igual ⇒ nada a baixar; desligado ⇒ nada muda."""
from __future__ import annotations

import asyncio
import copy
import json

from compliance_agent import captura_delta as D


def _no(k: int, numero: str | None, titulo: str | None = None) -> dict:
    """Nó da árvore viva como `sei_integra_completa` monta (linhas 636-637): {t, u, pai}."""
    t = titulo or (f"Despacho {k} ({numero})" if numero else f"Anexo sem numero {k}")
    return {"t": t, "u": f"https://sei.rj.gov.br/sei/controlador.php?acao=arvore_visualizar&id_documento={9000 + k}",
            "pai": ""}


def _manifesto(nos: list[dict], chars: int = 100) -> dict:
    """Manifesto do ARQUIVO (data/sei_arquivo/<tag>) para a mesma árvore."""
    return {"processo": "310003/001042/2025",
            "docs": [{"i": i, "titulo": x["t"], "texto": f"texto/{i:03d}_x.txt", "chars": chars,
                      "id_documento": str(9000 + i)} for i, x in enumerate(nos)]}


ARV = [_no(0, "11111111"), _no(1, "22222222"), _no(2, "33333333")]


def test_arvore_igual_nada_a_baixar():
    p = D.plano_de_captura(ARV, D.guardados(_manifesto(ARV)))
    assert p["baixar"] == [] and len(p["manter"]) == 3 and p["removidos"] == []
    assert p["arvore_igual"] is True and len(p["hash"]) == 64


def test_novo_e_sem_texto_sao_baixados():
    man = _manifesto(ARV)
    man["docs"][1]["chars"] = 0                       # guardado sem texto → baixa de novo
    viva = ARV + [_no(3, "44444444")]                 # documento novo
    p = D.plano_de_captura(viva, D.guardados(man))
    assert {(b["i"], b["motivo"]) for b in p["baixar"]} == {(1, "sem_texto"), (3, "novo")}
    assert p["arvore_igual"] is False


def test_retificado_baixa_e_preserva_anterior():
    viva = [ARV[0], _no(1, "22222222", "Despacho 1 RETIFICADO (22222222)"), ARV[2]]
    g = D.guardados(_manifesto(ARV))
    p = D.plano_de_captura(viva, g)
    assert p["baixar"] == [{"i": 1, "doc_id": "sei:22222222", "motivo": "retificado", "preservar_anterior": True}]
    assert p["arvore_igual"] is True                  # mesmos ids: só a versão mudou
    assert g["sei:22222222"]["titulo"] == "Despacho 1 (22222222)"   # versão antiga intacta


def test_removido_nunca_apagado():
    g = D.guardados(_manifesto(ARV))
    antes = copy.deepcopy(g)
    p = D.plano_de_captura(ARV[:2], g)
    assert p["removidos"] == [{"doc_id": "sei:33333333", "titulo": "Despacho 2 (33333333)", "i": 2}]
    assert g == antes                                 # o plano não toca nos guardados
    assert all(b["doc_id"] != "sei:33333333" for b in p["baixar"])


def test_numero_repetido_vira_hash2():
    rep = [_no(0, "55555555", "Despacho A (55555555)"), _no(1, "55555555", "Despacho A (55555555)")]
    g = D.guardados(_manifesto(rep))
    assert list(g) == ["sei:55555555", "sei:55555555#2"]
    assert D.plano_de_captura(rep, g)["baixar"] == []
    p = D.plano_de_captura(rep + [_no(2, "55555555", "Despacho A (55555555)")], g)
    assert p["baixar"] == [{"i": 2, "doc_id": "sei:55555555#3", "motivo": "novo"}]


def test_pos_so_mantem_com_id_documento_igual():
    viva = [_no(0, None)]
    g = D.guardados(_manifesto(viva))
    assert D.plano_de_captura(viva, g)["manter"] == [{"i": 0, "doc_id": "pos:0"}]
    g["pos:0"]["id_documento"] = "1"                  # outra peça na mesma posição
    assert D.plano_de_captura(viva, g)["baixar"][0]["motivo"] == "pos_sem_id"


def test_exportar_e_carregar_ida_e_volta(tmp_path):
    (tmp_path / "TAG").mkdir()
    (tmp_path / "TAG" / "manifest.json").write_text(json.dumps(_manifesto(ARV)), encoding="utf-8")
    exp = D.exportar_guardados("TAG", arquivo=tmp_path)
    assert exp["docs"][0] == ["sei:11111111", "Despacho 0 (11111111)", 100, "9000"]
    g = D.carregar_guardados(json.dumps(exp))
    assert D.plano_de_captura(ARV, g)["baixar"] == []
    assert D.exportar_guardados("NADA", arquivo=tmp_path)["docs"] == []


def test_encaixe_desligado_e_sombra(tmp_path):
    exp = tmp_path / "exp"
    exp.mkdir()
    (exp / "TAG.json").write_text(json.dumps(D.exportar_guardados("TAG", arquivo=tmp_path)), encoding="utf-8")
    (tmp_path / "TAG").mkdir()
    (tmp_path / "TAG" / "manifest.json").write_text(json.dumps(_manifesto(ARV)), encoding="utf-8")
    onde = {"pasta_exportados": tmp_path / "vazio", "arquivo": tmp_path}
    assert D.encaixe("TAG", ARV, env={}, **onde) == (set(), None)                       # desligado
    assert D.encaixe("TAG", ARV, env={"JFN_CAPTURA_DELTA": "0"}, **onde) == (set(), None)
    assert D.encaixe("OUTRO", ARV, env={"JFN_CAPTURA_DELTA": "1"}, **onde) == (set(), None)   # sem guardados
    pular, reg = D.encaixe("TAG", ARV, env={"JFN_CAPTURA_DELTA": "sombra"}, **onde)
    assert pular == set() and reg["mantidos"] == 3 and reg["arvore_igual"] is True
    pular, reg = D.encaixe("TAG", ARV + [_no(3, "44444444")], env={"JFN_CAPTURA_DELTA": "1"}, **onde)
    assert pular == {0, 1, 2}
    assert {k: reg[k] for k in ("baixados", "mantidos", "arvore_igual")} == \
        {"baixados": 1, "mantidos": 3, "arvore_igual": False}


def test_gerar_pdf_lotes_sem_pular_pede_o_mesmo(tmp_path):
    """O encaixe em `sei_integra_completa`: `pular` vazio (desligado) pede exatamente o que pedia antes."""
    from tools import sei_integra_completa as C

    pedidos: list[list[int]] = []

    async def pedir(lote, destino):
        pedidos.append([i for i, _ in lote])
        return "erro_500", "falso"

    def roda(**kw):
        pedidos.clear()
        out = tmp_path / f"o{len(kw)}"
        out.mkdir()
        asyncio.run(C.gerar_pdf_lotes(None, ARV, out, pedir=pedir, tam=99, **kw))
        return [i for lote in pedidos for i in lote]

    sem = roda()
    assert sorted(set(sem)) == [0, 1, 2]
    assert roda(pular=frozenset()) == sem
    assert 1 not in roda(pular={1}, prazo=None)
