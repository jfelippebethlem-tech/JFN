# -*- coding: utf-8 -*-
"""A porta única do texto do acervo: separar o que o SEI serviu do que nós escrevemos.

Cada caso aqui é uma forma REAL medida em `data/sei_arquivo` (2026-08-03), não hipótese.
"""
import pytest

from compliance_agent.sei import acervo_texto as AT


# ─────────────────────────── a etiqueta que nós escrevemos ───────────────────────────

@pytest.mark.parametrize("cab", [
    "[Parecer 462 (74886257)] (fase: controle · tipo: parecer_juridico)",
    "[Despacho de Encaminhamento de Processo] (fase: tramitacao · tipo: despacho)",
    "[114235964] (tipo: parecer_juridico)",
    "[Nota de Empenho Original - NE] (fase: despesa · tipo: nota_empenho)",
])
def test_remove_a_etiqueta_nas_duas_formas_que_o_arquivo_escreve(cab):
    """`sei_arquivar` grava `(fase: X · tipo: Y)`; `sei_arquivar_do_cache`, só `(tipo: Y)`."""
    bruto = f"{cab}\n\nGoverno do Estado do Rio de Janeiro\nPARECER Nº 462/2024"
    assert AT.sem_etiqueta(bruto).startswith("Governo do Estado")
    assert AT.etiqueta(bruto) == cab


def test_titulo_com_colchete_ANINHADO_nao_deixa_resto_para_tras():
    """Medido: 11 arquivos em 20.000 têm colchete dentro do título. Um casamento não-guloso
    deixava `] (tipo: tramitacao)` no texto — pior que não ter removido nada."""
    bruto = ("[Anexo 7 - Pesquisa_de_Satisfação-[SES_RJ] (80815818)] (tipo: tramitacao)\n\n"
             "GLPI - Pesquisa de satisfação")
    assert AT.sem_etiqueta(bruto) == "GLPI - Pesquisa de satisfação"


def test_documento_que_COMECA_com_colchete_nao_e_etiqueta():
    """A nota fiscal do acervo começa com `[RECEBEMOS DE PROMEFARMA …`. Sem a âncora do parêntese
    — que só nós escrevemos — o texto do documento seria comido como se fosse rótulo."""
    bruto = "[RECEBEMOS DE PROMEFARMA MEDIC. LTDA OS PRODUTOS CONSTANTES DA NOTA FISCAL]\nNF-e"
    assert AT.sem_etiqueta(bruto) == bruto
    assert AT.etiqueta(bruto) == ""


def test_etiqueta_DOBRADA_so_cai_quando_o_titulo_confirma():
    """856 documentos em 58 processos trazem a etiqueta duas vezes — a segunda sem parêntese,
    deixada pelo escritor de PDF da íntegra (`sei/pdf_texto`)."""
    bruto = ("[Despacho de Encaminhamento de Processo] (fase: tramitacao · tipo: despacho)\n\n"
             "[Despacho de Encaminhamento de Processo]\nSEI/ERJ - 83354132 - Despacho")
    assert AT.sem_etiqueta(bruto, "Despacho de Encaminhamento de Processo").startswith("SEI/ERJ")
    # sem o título, a segunda linha é preservada: não se apaga o que não se pode provar rótulo
    assert AT.sem_etiqueta(bruto).startswith("[Despacho de Encaminhamento de Processo]")


def test_segunda_linha_entre_colchetes_que_NAO_e_o_titulo_fica():
    """`[Sa À\\nPODER EXECUTIVO` é texto do Despacho do Governador, não rótulo."""
    bruto = ("[Despacho do Governador (109657600)] (tipo: autorizacao_despesa)\n\n"
             "[PODER EXECUTIVO]\nDESPACHO DO GOVERNADOR")
    assert AT.sem_etiqueta(bruto, "Despacho do Governador (109657600)").startswith("[PODER EXECUTIVO]")


def test_texto_sem_etiqueta_nenhuma_passa_intacto():
    assert AT.sem_etiqueta("PARECER Nº 1. Opino.") == "PARECER Nº 1. Opino."
    assert AT.sem_etiqueta("") == ""
    assert AT.etiqueta("") == ""


# ───────────────────────────── por que isso importa ─────────────────────────────

def test_o_documento_deixa_de_provar_a_si_mesmo():
    """O caso que originou o módulo: a etiqueta punha `parecer_juridico` dentro do texto e o
    "Parecer de Análise para Emissão DL" passava por manifestação jurídica (080002/006705/2024)."""
    bruto = ("[Parecer de Análise para Emissão DL 83167512] (tipo: parecer_juridico)\n\n"
             "Fundação Saúde. Diretoria Administrativa Financeira.\n"
             "Procedida a Revisão do processo referente a indenização de serviços prestados.")
    assert "juridic" in bruto
    assert "juridic" not in AT.sem_etiqueta(bruto).lower()


def test_a_etiqueta_nao_come_mais_a_janela():
    """Mediana de 71 chars, p90 de 119, máximo medido de 478. Quem lê os primeiros 200 caracteres
    perdia 36,5% da janela para o próprio rótulo."""
    cab = "[" + "T" * 300 + " (99999999)] (fase: tramitacao · tipo: despacho)\n\n"
    corpo = "ATO DO ORDENADOR DE DESPESAS. AUTORIZO a despesa."
    assert AT.sem_etiqueta(cab + corpo)[:200] == corpo


# ───────────────────────────── o leitor canônico ─────────────────────────────

def test_ler_devolve_o_texto_limpo_do_disco(tmp_path):
    (tmp_path / "texto").mkdir()
    (tmp_path / "texto" / "001_x.txt").write_text(
        "[Parecer 1 (123)] (tipo: parecer_juridico)\n\nOpino pelo prosseguimento.",
        encoding="utf-8")
    doc = {"texto": "texto/001_x.txt", "titulo": "Parecer 1 (123)"}
    assert AT.ler(tmp_path, doc) == "Opino pelo prosseguimento."
    assert AT.ler(tmp_path, doc, teto=5) == "Opino"


def test_ler_nao_inventa_conteudo_quando_nao_ha_arquivo(tmp_path):
    """INDISPONÍVEL ≠ vazio: a ausência não vira conteúdo, e a decisão é de quem chama."""
    assert AT.ler(tmp_path, {"texto": "texto/nao_existe.txt"}) == ""
    assert AT.ler(tmp_path, {}) == ""
    assert AT.ler(tmp_path, {"texto": ""}) == ""


def test_o_teto_conta_o_texto_do_documento_e_nao_o_nosso_rotulo(tmp_path):
    """Era o efeito silencioso: com teto de 200, a etiqueta consumia 71 e o documento ficava com
    129. O teto é orçamento de LEITURA do documento, não do que escrevemos sobre ele."""
    (tmp_path / "texto").mkdir()
    (tmp_path / "texto" / "001_x.txt").write_text(
        "[Titulo bem longo aqui (99999999)] (fase: despesa · tipo: empenho)\n\n" + "A" * 500,
        encoding="utf-8")
    assert AT.ler(tmp_path, {"texto": "texto/001_x.txt"}, teto=200) == "A" * 200


def test_etiqueta_de_le_so_a_primeira_linha(tmp_path):
    """A `conferencia_captura` precisa do rótulo, e só dele: não se carrega 400 KB para lê-lo."""
    (tmp_path / "texto").mkdir()
    (tmp_path / "texto" / "001_x.txt").write_text(
        "[Relatório de Fiscalização (121178482)] (tipo: tramitacao)\n\n" + "B" * 100_000,
        encoding="utf-8")
    assert AT.etiqueta_de(tmp_path, {"texto": "texto/001_x.txt"}) == \
        "[Relatório de Fiscalização (121178482)] (tipo: tramitacao)"
    assert AT.etiqueta_de(tmp_path, {"texto": "texto/nao_existe.txt"}) == ""
    assert AT.etiqueta_de(tmp_path, {}) == ""


# ───────────── o manifesto é o índice: sobra de captura anterior não é documento ─────────────

def _pasta(tmp_path, docs, extras=()):
    import json
    (tmp_path / "texto").mkdir(parents=True, exist_ok=True)
    man = {"processo": "000000/000000/2020", "docs": []}
    for i, (nome, corpo) in enumerate(docs):
        (tmp_path / "texto" / nome).write_text(corpo, encoding="utf-8")
        man["docs"].append({"i": i, "titulo": nome, "texto": f"texto/{nome}"})
    for nome, corpo in extras:
        (tmp_path / "texto" / nome).write_text(corpo, encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return tmp_path


def test_arquivos_declarados_ignora_sobra_de_captura_anterior(tmp_path):
    """070002/000991/2022: 486 documentos no manifesto, 1.072 arquivos na pasta. Quem varre o
    diretório lê DUAS capturas do mesmo processo e conta cada documento duas vezes."""
    p = _pasta(tmp_path,
               [("000_novo.txt", "Documento atual com teor suficiente para contar como lido.")],
               [("000_despacho_1.txt", "[Despacho] (tipo: despacho)\n\n")])
    assert [f.name for f in AT.arquivos_declarados(p)] == ["000_novo.txt"]
    assert [f.name for f in AT.orfaos(p)] == ["000_despacho_1.txt"]
    assert AT.docs_com_conteudo(p) == 1


def test_sem_manifesto_cai_no_diretorio_e_nao_devolve_orfao(tmp_path):
    """Sem índice não se afirma orfandade: o diretório vira a melhor evidência disponível."""
    (tmp_path / "texto").mkdir()
    (tmp_path / "texto" / "001_x.txt").write_text("teor", encoding="utf-8")
    assert len(AT.arquivos_declarados(tmp_path)) == 1
    assert AT.orfaos(tmp_path) == []


def test_documento_declarado_que_sumiu_do_disco_nao_e_contado(tmp_path):
    """INDISPONÍVEL ≠ 0 também aqui: manifesto que aponta para arquivo inexistente não conta."""
    import json
    (tmp_path / "texto").mkdir()
    (tmp_path / "manifest.json").write_text(
        json.dumps({"docs": [{"i": 0, "titulo": "X", "texto": "texto/sumiu.txt"}]}),
        encoding="utf-8")
    assert AT.arquivos_declarados(tmp_path) == []
    assert AT.docs_com_conteudo(tmp_path) == 0


def test_manifesto_com_docs_VAZIO_e_indice_quebrado_e_nao_indice_vazio(tmp_path):
    """Existe processo com `docs: []` no manifesto e `texto/*.txt` intacto no disco — é a avaria
    que `tools/sei_reparar_manifestos` conserta (num caso, 210 documentos). Confiar no índice aí
    apagaria documentos reais da leitura em silêncio: 080001/003535/2025 tem 20 textos e 0 docs.
    """
    import json
    (tmp_path / "texto").mkdir()
    for i in range(3):
        (tmp_path / "texto" / f"{i:03d}_x.txt").write_text("teor real do documento", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"docs": []}), encoding="utf-8")
    assert len(AT.arquivos_declarados(tmp_path)) == 3
    assert AT.orfaos(tmp_path) == []
