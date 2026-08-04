# -*- coding: utf-8 -*-
"""A triagem lia 17% dos documentos como VAZIOS — 56,5 milhões de caracteres invisíveis.

`_texto_do_doc` localizava o arquivo por glob do identificador NO NOME: `texto/*<id>*`. Mas o nome
do arquivo é o título sanitizado e CORTADO, então em título longo o identificador simplesmente não
está lá. Medido em 2026-08-04 sobre o acervo: **5.722 dos 33.584 documentos com teor (17%)** eram
lidos como vazios, e com eles ~56,5 milhões de caracteres ficavam invisíveis para o A1, o A2 e a
auditoria de acatamento — os três que decidem sobre o art. 53.

O caso que revelou: "Despacho de Encaminhamento de Processo PARECER DE FAVORABILIDADE
(121198855)", 3.144 caracteres, arquivo `003_despacho_de_encaminhamento_de_processo_p.txt` — o
nome acaba antes do número.

O manifesto sempre trouxe o caminho no campo `texto`, e `acervo_texto.ler` é a porta única da
casa. Depois da correção: 5.722 -> 0.
"""
import json

import tools.sei_triagem_pericia as T


def _processo(tmp_path, titulo, corpo, nome_arquivo):
    (tmp_path / "texto").mkdir()
    (tmp_path / "texto" / nome_arquivo).write_text(
        f"[{titulo}] (fase: controle · tipo: parecer)\n\n{corpo}", encoding="utf-8")
    doc = {"i": 0, "titulo": titulo, "tipo": "parecer", "texto": f"texto/{nome_arquivo}"}
    (tmp_path / "manifest.json").write_text(json.dumps({"docs": [doc]}), encoding="utf-8")
    return doc


def test_le_pelo_caminho_do_manifesto_quando_o_nome_perdeu_o_id(tmp_path):
    """O caso real: nome truncado antes do identificador."""
    corpo = "Teor real do parecer, com folga acima de qualquer piso de caracteres."
    doc = _processo(tmp_path,
                    "Despacho de Encaminhamento de Processo PARECER DE FAVORABILIDADE (121198855)",
                    corpo, "003_despacho_de_encaminhamento_de_processo_p.txt")
    assert corpo in T._texto_do_doc(tmp_path, doc)


def test_o_texto_vem_SEM_a_etiqueta(tmp_path):
    """A etiqueta é nossa classificação; deixá-la contamina todo regex que leia o documento."""
    doc = _processo(tmp_path, "Parecer 1 (90454338)", "corpo do parecer aqui, suficientemente longo",
                    "000_parecer_1_90454338.txt")
    lido = T._texto_do_doc(tmp_path, doc)
    assert "(fase: controle" not in lido and "corpo do parecer" in lido


def test_documento_sem_arquivo_continua_vazio(tmp_path):
    """Vazio nunca vira conclusão — a docstring da função sempre disse isso."""
    (tmp_path / "texto").mkdir()
    doc = {"i": 0, "titulo": "Parecer 9 (11111111)", "tipo": "parecer", "texto": "texto/ausente.txt"}
    (tmp_path / "manifest.json").write_text(json.dumps({"docs": [doc]}), encoding="utf-8")
    assert T._texto_do_doc(tmp_path, doc) == ""


def test_fallback_pelo_glob_segue_para_manifesto_sem_o_campo(tmp_path):
    """Manifesto antigo sem `texto` ainda é lido pelo caminho antigo."""
    (tmp_path / "texto").mkdir()
    (tmp_path / "texto" / "000_parecer_90454338.txt").write_text(
        "[Parecer 1 (90454338)] (tipo: parecer)\n\nteor pelo glob, longo o bastante", encoding="utf-8")
    doc = {"i": 0, "titulo": "Parecer 1 (90454338)", "tipo": "parecer"}
    assert "teor pelo glob" in T._texto_do_doc(tmp_path, doc)


def test_MINUTA_nao_e_parecer_para_a_triagem():
    """Minuta revisada pela assessoria é o INSUMO do controle, não a manifestação dele — e suas
    cláusulas condicionais ("desde que devidamente justificado", "caso os recursos não sejam
    totalmente executados") casam com o padrão de ressalva. Medido em 2026-08-04 no
    SEI-080001/037511/2024: o A3 cobrava acatamento de uma cláusula de minuta, quando a sequência
    posterior (nova minuta → Resolução → publicação) é o controle FUNCIONANDO. Mesma doutrina do
    I1/I2: correção antes da assinatura não é vício."""
    assert T._RX_NAO_PARECER.search("Anexo Minuta Revisada Assjur (89598120)")
    assert T._RX_NAO_PARECER.search("Minuta de Termo de Ajuste de Contas")


def test_parecer_de_verdade_nao_e_vetado_pelo_titulo():
    for titulo in ("Parecer 2848 (83434921)", "Parecer Jurídico PGE 12",
                   "Manifestação Jurídica 7 (11111111)"):
        assert not T._RX_NAO_PARECER.search(titulo), titulo
