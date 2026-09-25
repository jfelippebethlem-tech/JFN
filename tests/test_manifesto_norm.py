# -*- coding: utf-8 -*-
"""manifesto_norm — adaptador READ-side dos dois formatos de manifest do sei_arquivo.

Formato A (tools/sei_arquivar.py): fase preenchida, i int, linha_do_tempo dict[fase,int].
Formato B (tools/sei_arquivar_do_cache.py): fase "", i STRING, linha_do_tempo dict[fase,list].
"""
import copy
import json

import pytest

from compliance_agent.sei import manifesto_norm as mn

MAN_A = {
    "processo": "SEI-070026/000705/2021", "origem": "integra", "modalidade": "pregão eletrônico",
    "docs": [
        {"i": 0, "titulo": "Edital de Pregão Eletrônico 12/2021 (12345678)", "fase": "selecao",
         "tipo": "edital", "texto": "texto/000_edital_12345678.txt", "chars": 900, "ocr": False, "fotos": []},
        {"i": 1, "titulo": "Nota de Empenho 2021NE00042 (12345679)", "fase": "despesa",
         "tipo": "nota_empenho", "texto": "texto/001_ne_12345679.txt", "chars": 300, "ocr": False, "fotos": []},
    ],
    "linha_do_tempo": {"selecao": 1, "despesa": 1},
    "lacunas": [], "fotos_total": 0,
}

MAN_B = {
    "processo": "SEI-080002/001953/2026", "origem": "cache", "modalidade": "",
    "docs": [
        {"i": "0", "titulo": "Parecer Jurídico PGE (99000001)", "fase": "",
         "tipo": "parecer_juridico", "texto": "texto/000_parecer_99000001.txt", "chars": 5000,
         "ocr": False, "fotos": [], "via_cache": True},
        {"i": "1", "titulo": "Despacho de Encaminhamento de Processo (99000002)", "fase": "",
         "tipo": "tramitacao", "texto": "texto/001_despacho_99000002.txt", "chars": 200,
         "ocr": False, "fotos": [], "via_cache": True},
        {"i": "2", "titulo": "Nota de Empenho 2026NE00099 (99000003)", "fase": "",
         "tipo": "empenho", "texto": "texto/002_ne_99000003.txt", "chars": 250,
         "ocr": False, "fotos": [], "via_cache": True},
    ],
    "linha_do_tempo": {"controle": ["Parecer Jurídico PGE (99000001)"]},
    "lacunas": [{"falta": "Contrato ou instrumento equivalente", "gravidade": "media"}],
    "fotos_total": 0,
}


def test_mesmo_shape_nos_dois_formatos():
    a, b = mn.normalizar(copy.deepcopy(MAN_A)), mn.normalizar(copy.deepcopy(MAN_B))
    for man in (a, b):
        assert man["_norm"]["versao"] == 1
        for d in man["docs"]:
            assert isinstance(d["i"], int)
            assert d["fase"] in mn.fases.FASES
            assert d["tipo"]  # nunca vazio
        assert all(isinstance(v, list) for v in man["linha_do_tempo"].values())


def test_backfill_de_fase_e_tipo_canonico():
    b = mn.normalizar(copy.deepcopy(MAN_B))
    por_i = {d["i"]: d for d in b["docs"]}
    assert por_i[0]["fase"] == "controle" and por_i[0]["tipo"] == "parecer"       # parecer_juridico→parecer
    assert por_i[1]["fase"] == "tramitacao" and por_i[1]["tipo"] == "despacho"    # tramitacao→resolve pelo título
    assert por_i[2]["fase"] == "despesa" and por_i[2]["tipo"] == "nota_empenho"   # empenho→nota_empenho
    assert por_i[0]["tipo_original"] == "parecer_juridico"


def test_formato_a_preserva_fase_existente():
    a = mn.normalizar(copy.deepcopy(MAN_A))
    assert [d["fase"] for d in a["docs"]] == ["selecao", "despesa"]


def test_idempotente():
    b1 = mn.normalizar(copy.deepcopy(MAN_B))
    b2 = mn.normalizar(copy.deepcopy(b1))
    assert b1 == b2


def test_nao_muta_entrada():
    original = copy.deepcopy(MAN_B)
    mn.normalizar(MAN_B)
    assert MAN_B == original


def test_tipo_canonico_mapa():
    assert mn.tipo_canonico("empenho", "Nota de Empenho 2026NE1") == "nota_empenho"
    assert mn.tipo_canonico("tr", "Termo de Referência") == "termo_referencia"
    assert mn.tipo_canonico("mapa_lances", "Mapa de Lances") == "julgamento"
    # ambíguo resolve pelo título; sem sinal → honesto
    assert mn.tipo_canonico("outros", "Ata de Registro de Preços") == "ata_rp"
    assert mn.tipo_canonico("outros", "zzz") == "outro"
    assert mn.tipo_canonico(None, "Despacho 123") == "despacho"


def test_captura_integra_por_texto(tmp_path):
    man = mn.normalizar(copy.deepcopy(MAN_B))
    pasta = tmp_path / "p"
    (pasta / "texto").mkdir(parents=True)
    ok, ev = mn.captura_integra(man, pasta)
    assert ok is False and ev["n_txt"] == 0            # sem texto → captura NÃO íntegra
    for i in range(3):
        (pasta / "texto" / f"{i:03d}_x_{i}.txt").write_text(
            "Governo do Estado do Rio de Janeiro. Documento com teor de verdade.",
            encoding="utf-8")
    ok, ev = mn.captura_integra(man, pasta)
    assert ok is True and ev["n_txt"] == 3 and ev["n_com_texto"] == 3
    # `captura_vazia` DESMENTIDA pelo disco é dado velho, não veto (2026-08-04): com os três
    # documentos íntegros acima, a bandeira não silencia. O veto que o disco CONFIRMA continua
    # valendo — é o caso coberto por `test_veto_que_o_disco_CONFIRMA_continua_vetando`.
    man2 = dict(man, captura_vazia=True)
    ok, ev2 = mn.captura_integra(man2, pasta)
    assert ok is True and ev2["veto_obsoleto"] is True


def test_captura_integra_nao_conta_arquivo_que_so_tem_a_ETIQUETA(tmp_path):
    """A docstring sempre disse "texto no disco decide" — e quem decidia era a CONTAGEM DE
    ARQUIVOS. Medido em 2026-08-03: 10.332 dos 45.161 arquivos do acervo (22,9%) trazem apenas a
    etiqueta `[título] (fase: … · tipo: …)` que nós mesmos escrevemos, e 7 processos passavam por
    íntegros com quase metade dos textos vazios — recebendo faixa de risco sobre o que não se leu.
    """
    man = mn.normalizar(copy.deepcopy(MAN_B))
    pasta = tmp_path / "p"
    (pasta / "texto").mkdir(parents=True)
    for i in range(3):
        (pasta / "texto" / f"{i:03d}_x_{i}.txt").write_text(
            f"[Despacho de Encaminhamento {i}] (fase: tramitacao · tipo: despacho)\n\n",
            encoding="utf-8")
    ok, ev = mn.captura_integra(man, pasta)
    assert ok is False, "arquivo com só a etiqueta não é documento lido"
    assert ev["n_txt"] == 3 and ev["n_com_texto"] == 0


@pytest.mark.slow
def test_acervo_real_nunca_levanta():
    import pathlib
    base = pathlib.Path.home() / "JFN" / "data" / "sei_arquivo"
    if not base.exists():
        pytest.skip("acervo ausente")
    total = com_fase = docs_total = 0
    for mf in base.glob("*/manifest.json"):
        try:
            man = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            continue
        antes = mf.read_bytes()
        n = mn.normalizar(man)
        assert mf.read_bytes() == antes                 # NUNCA regrava o disco
        total += 1
        for d in n["docs"]:
            docs_total += 1
            if d["fase"]:
                com_fase += 1
    assert total > 2000
    # meta do plano: fase preenchida (≠ "") em ≥95% dos documentos após normalização
    assert docs_total and com_fase / docs_total >= 0.95


def test_veto_do_manifesto_desmentido_pelo_disco_e_dado_velho(tmp_path):
    """Medido em 2026-08-04: **17 processos** carregavam `captura_vazia=True` ou
    `captura_completa=False` tendo 100% dos documentos com teor — 155 de 155, 247 de 247. A marca
    foi posta por uma captura que falhou, uma captura POSTERIOR deu certo e ninguém a limpou; o
    efeito era NAO_AVALIAVEL perpétuo — a casa se recusando a afirmar sobre processo que leu
    inteiro. A docstring desta função sempre disse que o texto no disco decide.
    """
    man = mn.normalizar(copy.deepcopy(MAN_B))
    pasta = tmp_path / "p"
    (pasta / "texto").mkdir(parents=True)
    for i in range(3):
        (pasta / "texto" / f"{i:03d}_x_{i}.txt").write_text(
            "Governo do Estado do Rio de Janeiro. Documento com teor de verdade.",
            encoding="utf-8")
    ok, ev = mn.captura_integra(dict(man, captura_vazia=True), pasta)
    assert ok is True and ev["veto_obsoleto"] is True


def test_veto_que_o_disco_CONFIRMA_continua_vetando(tmp_path):
    """O veto segue valendo quando o disco não o desmente — é o caso dos outros 149 processos."""
    man = mn.normalizar(copy.deepcopy(MAN_B))
    pasta = tmp_path / "p"
    (pasta / "texto").mkdir(parents=True)
    (pasta / "texto" / "000_x.txt").write_text("[X] (tipo: despacho)\n\n", encoding="utf-8")
    ok, ev = mn.captura_integra(dict(man, captura_vazia=True), pasta)
    assert ok is False and ev["veto_obsoleto"] is False
