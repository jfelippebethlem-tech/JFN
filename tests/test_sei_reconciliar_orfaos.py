# -*- coding: utf-8 -*-
"""Documento no disco e fora do índice: recuperar sem colar teor no título errado.

Medido no acervo em 2026-08-03: 6 processos recapturados cujo `manifest.json` nunca foi
reescrito. O índice aponta para os `.txt` da captura ANTIGA (79-90 bytes, só a etiqueta) e a
captura NOVA — 338 documentos, 3,0 MB — fica órfã: no disco e invisível para todo consumidor.
"""
import json

import pytest

from tools import sei_reconciliar_orfaos as R


def _processo(tmp_path, declarados, orfaos):
    (tmp_path / "texto").mkdir(parents=True)
    man = {"processo": "080001/001711/2026", "docs": []}
    for i, (nome, corpo) in enumerate(declarados):
        (tmp_path / "texto" / nome).write_text(corpo, encoding="utf-8")
        man["docs"].append({"i": i, "titulo": nome, "fase": "tramitacao", "tipo": "despacho",
                            "texto": f"texto/{nome}", "chars": 0})
    for nome, corpo in orfaos:
        (tmp_path / "texto" / nome).write_text(corpo, encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return tmp_path


def test_recupera_o_documento_orfao_com_teor(tmp_path):
    p = _processo(
        tmp_path,
        [("000_despacho_de_encaminhamento.txt",
          "[Despacho de Encaminhamento 123] (fase: tramitacao · tipo: despacho)\n\n")],
        [("000_despacho_de_autoriza_o.txt",
          "[Despacho de Autorização de Emissão e Execução - PD 136302449] "
          "(fase: tramitacao · tipo: despacho)\n\n"
          "Governo do Estado do Rio de Janeiro. AUTORIZO a emissão da programação de desembolso.")])
    r = R.reconciliar(p, aplicar=True)
    assert r["recuperados"] == 1
    man = json.loads((p / "manifest.json").read_text())
    # títulos diferentes: não há prova de substituição, então a entrada antiga PERMANECE
    assert len(man["docs"]) == 2 and "docs_superados" not in man
    novo = man["docs"][-1]
    assert novo["texto"] == "texto/000_despacho_de_autoriza_o.txt"
    assert novo["chars"] > 40 and novo["reconciliado"] is True


def test_o_titulo_vem_da_ETIQUETA_e_nao_do_indice_do_nome(tmp_path):
    """`000_despacho_de_encaminhamento…` (vazio, declarado) e `000_despacho_de_autoriza_o…`
    (7,6 KB, órfão) têm o MESMO índice e são documentos DIFERENTES — a recaptura reordenou a
    árvore. Casar por índice colaria o teor de um documento no título de outro."""
    p = _processo(
        tmp_path,
        [("000_despacho_de_encaminhamento.txt",
          "[Despacho de Encaminhamento 123] (fase: tramitacao · tipo: despacho)\n\n")],
        [("000_anexo_minuta.txt",
          "[Anexo 01 - CARTA DE ENCAMINHAMENTO 3a MEDIÇÃO (118828428)] "
          "(fase: execucao · tipo: medicao)\n\nPlanilha de medição da obra, terceira parcela.")])
    R.reconciliar(p, aplicar=True)
    novo = json.loads((p / "manifest.json").read_text())["docs"][-1]
    assert novo["titulo"] == "Anexo 01 - CARTA DE ENCAMINHAMENTO 3a MEDIÇÃO (118828428)"
    assert novo["i"] == 1, "índice novo: não colide com o do documento declarado"


def test_orfao_SEM_teor_nao_entra(tmp_path):
    """4.893 órfãos do acervo são sobra de captura anterior — só a etiqueta. Resíduo não é
    documento, e inflar o índice com ele seria fabricar captura."""
    p = _processo(
        tmp_path,
        [("000_a.txt", "[A] (tipo: despacho)\n\nTeor real do documento declarado, com folga.")],
        [("001_sobra.txt", "[Despacho de Encaminhamento] (fase: tramitacao · tipo: despacho)\n\n")])
    assert R.reconciliar(p, aplicar=True) is None
    assert len(json.loads((p / "manifest.json").read_text())["docs"]) == 1


def test_processo_sem_orfao_nao_e_tocado(tmp_path):
    p = _processo(tmp_path, [("000_a.txt", "[A] (tipo: despacho)\n\nTeor real e suficiente.")], [])
    antes = (p / "manifest.json").read_text()
    assert R.reconciliar(p, aplicar=True) is None
    assert (p / "manifest.json").read_text() == antes


def test_sem_aplicar_nada_e_escrito(tmp_path):
    p = _processo(
        tmp_path,
        [("000_a.txt", "[A] (tipo: despacho)\n\n")],
        [("001_b.txt", "[B (99)] (tipo: despacho)\n\n"
                       "Teor real, acima do piso de 40 caracteres que a casa exige.")])
    antes = (p / "manifest.json").read_text()
    r = R.reconciliar(p, aplicar=False)
    assert r["recuperados"] == 1
    assert (p / "manifest.json").read_text() == antes


@pytest.mark.parametrize("etiqueta,esperado", [
    ("[Anexo 7 - Pesquisa-[SES_RJ] (80815818)] (tipo: tramitacao)",
     "Anexo 7 - Pesquisa-[SES_RJ] (80815818)"),
    ("", "sem etiqueta aqui"),
])
def test_titulo_do_arquivo_tolera_colchete_aninhado_e_ausencia(tmp_path, etiqueta, esperado):
    f = tmp_path / "003_sem_etiqueta_aqui.txt"
    f.write_text((etiqueta + "\n\n" if etiqueta else "") + "corpo", encoding="utf-8")
    assert R._titulo_do_arquivo(f) == esperado


def test_entrada_superada_exige_PROVA_de_que_o_orfao_a_substitui(tmp_path):
    """Manter as duas capturas lado a lado dobra a lista (97 vazias + 96 reais = 193 documentos,
    cobertura 51% onde a verdade é ~100%). Mas "vazia num processo recapturado" NÃO basta: no
    260007/004617/2024 isso marcaria 519 de 626 entradas como superadas quando só 88 têm
    substituta — as outras 431 nunca foram capturadas, e converter "não capturado" em "superado"
    apagaria a fila de recaptura. A prova é o TÍTULO.
    """
    p = _processo(
        tmp_path,
        [("000_velho.txt", "[Despacho de Encaminhamento 123] (fase: tramitacao · tipo: despacho)\n\n"),
         ("001_nunca_capturado.txt", "[Ofício - NA 72 (77144454)] (tipo: oficio)\n\n"),
         ("002_com_teor.txt", "[Parecer 9 (55)] (tipo: parecer_juridico)\n\n"
                              "Documento da captura antiga que TEM teor e por isso permanece.")],
        [("003_recaptura.txt", "[Despacho de Encaminhamento 123] (fase: tramitacao · tipo: despacho)\n\n"
                               "Agora com o teor de verdade, acima do piso de 40 caracteres.")])
    # o título da entrada declarada é o nome do arquivo no fixture; alinhe-o com o da etiqueta
    man = json.loads((tmp_path / "manifest.json").read_text())
    man["docs"][0]["titulo"] = "Despacho de Encaminhamento 123"
    man["docs"][1]["titulo"] = "Ofício - NA 72 (77144454)"
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")

    R.reconciliar(p, aplicar=True)
    man = json.loads((p / "manifest.json").read_text())
    titulos = [d["titulo"] for d in man["docs"]]
    assert "Despacho de Encaminhamento 123" in titulos, "a recuperada entra"
    assert "002_com_teor.txt" in titulos, "entrada COM teor nunca é considerada superada"
    assert "Ofício - NA 72 (77144454)" in titulos, \
        "entrada vazia SEM substituta permanece — é a fila de recaptura"
    assert [d["titulo"] for d in man["docs_superados"]] == ["Despacho de Encaminhamento 123"]
    assert man["docs_superados"][0]["superado_por"] == "texto/003_recaptura.txt"


def test_entrada_vazia_em_processo_SEM_recaptura_permanece(tmp_path):
    """Entrada vazia sem recaptura é matéria-prima da fila de recaptura (5.050 no acervo). Tirá-la
    daqui faria a fila perder o que ela existe para achar."""
    p = _processo(tmp_path, [("000_vazio.txt", "[Vazio] (tipo: despacho)\n\n")], [])
    assert R.reconciliar(p, aplicar=True) is None
    man = json.loads((p / "manifest.json").read_text())
    assert len(man["docs"]) == 1 and "docs_superados" not in man
