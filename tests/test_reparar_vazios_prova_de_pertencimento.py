# -*- coding: utf-8 -*-
"""Reparar com o PDF errado é pior do que deixar o documento vazio.

`sei_reparar_vazios` recupera o texto de documentos sem teor usando o PDF já guardado em
`data/sei_cache/integra_<processo>/<i:03d>.pdf`, e assumia que o índice do arquivo corresponde ao
índice do documento no manifesto. **Não corresponde.**

Medido em 2026-08-04, entre os 24 candidatos ao reparo: 7 permitiam conferência e **6 traziam o
PDF de OUTRO documento** — "Nota de Autorização de Despesa - NAD 3378" devolvia o texto de um
"Despacho de Encaminhamento"; "Anexo 2024PD26195 - IRRF" devolvia um e-mail; e o mesmo arquivo de
18 MB aparecia em dois processos, sob índices e títulos diferentes, com md5 idêntico.

Vazio é lacuna declarada; trocado é PROVA FALSA — e entraria no dossiê com o título de outra peça.
É a mesma armadilha que a reconciliação de órfãos já documentou: casar por índice do nome cola o
teor de um documento no título de outro.

Antes desta guarda a ferramenta relatava "nada a reparar" por outro defeito (media o arquivo COM a
etiqueta, que sozinha passa dos 80 caracteres). Corrigido isso, ela passou a encontrar 24
candidatos — e teria gravado 23 errados.
"""
import tools.sei_reparar_vazios as R


def test_texto_do_documento_certo_e_aceito():
    """A prova é o identificador SEI do título aparecendo no texto extraído — o SEI o imprime no
    cabeçalho de cada peça."""
    assert R.pertence("Termo de Ajuste de Contas Minuta nº 2000/2024 (83406122)",
                      "[Termo de Ajuste de Contas Minuta (83406122)] Governo do Estado ...") is True


def test_texto_de_OUTRO_documento_e_recusado():
    """O caso real: título de Nota de Autorização de Despesa, conteúdo de despacho."""
    assert R.pertence("Nota de Autorização de Despesa - NAD 3378 (82011111)",
                      "[Despacho de Encaminhamento de Processo 81715749] Governo do Estado ...") is False


def test_id_sem_parenteses_tambem_conta():
    """"Despacho de Encaminhamento de Processo 83371025" traz o id solto; exigir parênteses
    deixava indeterminado o que era conferível."""
    assert R.pertence("Despacho de Encaminhamento de Processo 83371025",
                      "cabeçalho 83371025 do documento ...") is True


def test_numero_do_processo_no_titulo_nao_confunde_o_id():
    """O identificador é o ÚLTIMO grupo de 6+ dígitos: em "Pesquisa de preços SEI
    080002/000996/2024 (83371931)" o id é 83371931, não 080002 nem 000996."""
    assert R.pertence("Pesquisa de preços SEI 080002/000996/2024 (83371931)",
                      "documento 080002/000996/2024 ... sem o id da peça") is False


def test_sem_id_no_titulo_e_INDETERMINADO_nao_falso():
    """Indeterminado não é 'não pertence' — e também não se grava. Distinguir os dois é o que
    permite dizer ao operador o que falta."""
    assert R.pertence("Anexo sem número", "qualquer texto") is None


def test_sem_texto_extraido_e_INDETERMINADO():
    assert R.pertence("Documento (12345678)", "") is None
    assert R.pertence("Documento (12345678)", "   ") is None


def test_o_gravador_so_escreve_o_que_prova(tmp_path, monkeypatch):
    """Guarda de ponta: `reparar(aplicar=True)` não pode tocar o arquivo de um documento cujo PDF
    não se provou pertencer a ele."""
    txt = tmp_path / "000_doc.txt"
    txt.write_text("[Nota de Autorização (82011111)] (tipo: outro)\n", encoding="utf-8")
    man = tmp_path / "manifest.json"
    man.write_text('{"docs": [{"i": 0, "titulo": "Nota de Autorização (82011111)", '
                   '"texto": "000_doc.txt"}]}', encoding="utf-8")
    pdf = tmp_path / "000.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(
        "compliance_agent.sei.ocr_docs.ocr_documento",
        lambda *a, **k: "[Despacho de Encaminhamento 81715749] texto de OUTRO documento, longo o "
                        "bastante para passar do piso de caracteres exigido pela ferramenta.")
    antes = txt.read_text(encoding="utf-8")
    r = R.reparar([{"processo": "p", "i": 0, "tipo": "outro",
                    "titulo": "Nota de Autorização (82011111)", "pdf": pdf, "txt": txt,
                    "manifest": man, "kb": 10.0}], aplicar=True)
    assert r["recuperados"] == 0 and r["nao_conferidos"] == 1
    assert txt.read_text(encoding="utf-8") == antes, "gravou o teor de outro documento"


# ───────── realinhamento por identificador: as duas ambiguidades ─────────

def _pdf_com_texto(caminho, texto):
    """PDF de uma página com o texto dado (pymupdf grava; o teste lê pelo mesmo caminho)."""
    import pymupdf
    doc = pymupdf.open()
    pagina = doc.new_page()
    pagina.insert_text((40, 60), texto, fontsize=9)
    doc.save(caminho)
    doc.close()


def test_o_dono_e_quem_EXIBE_o_id_do_titulo(tmp_path):
    _pdf_com_texto(tmp_path / "007.pdf", "Parecer 2848 (83434921) Fundacao Saude")
    topos = R.topos_da_integra(tmp_path)
    assert R.dono_do_documento("83434921", topos) == tmp_path / "007.pdf"


def test_a_direcao_da_busca_importa_o_cabecalho_tem_outros_numeros(tmp_path):
    """A primeira versão montava o mapa ao contrário — extraía "o id" do cabeçalho de cada PDF e o
    tomava como dono. O cabeçalho tem outros números de seis dígitos: a Ordem Bancária traz o
    código da UG ("404340 - HUPE", "296100"), e o resultado foi **zero donos em 7.669 candidatos**,
    porque todo topo parecia ambíguo. O identificador autoritativo é o do TÍTULO."""
    _pdf_com_texto(tmp_path / "000.pdf", "Ordem Bancaria UG Emitente 404340 HUPE 296100 (83434921)")
    topos = R.topos_da_integra(tmp_path)
    assert R.dono_do_documento("83434921", topos) == tmp_path / "000.pdf"
    assert R.dono_do_documento("99999999", topos) is None


def test_dois_pdfs_exibindo_o_MESMO_id_invalidam_os_dois(tmp_path):
    """Preferir o primeiro seria escolher ao acaso qual prova entra no dossiê."""
    _pdf_com_texto(tmp_path / "001.pdf", "Documento (83434921) versao A")
    _pdf_com_texto(tmp_path / "002.pdf", "Documento (83434921) versao B")
    assert R.dono_do_documento("83434921", R.topos_da_integra(tmp_path)) is None


def test_pdf_escaneado_fica_sem_dono_limite_declarado(tmp_path):
    """Topo sem texto nativo não identifica ninguém — e OCR nesta fase custaria horas para achar
    o dono, não para extrair o conteúdo."""
    import pymupdf
    doc = pymupdf.open(); doc.new_page(); doc.save(tmp_path / "003.pdf"); doc.close()
    assert R.dono_do_documento("83434921", R.topos_da_integra(tmp_path)) is None


def test_realinhar_troca_o_pdf_posicional_pelo_dono_de_verdade(tmp_path):
    _pdf_com_texto(tmp_path / "000.pdf", "Peca alheia (11111111)")
    _pdf_com_texto(tmp_path / "009.pdf", "Termo de Ajuste (83406122) Fundacao Saude")
    alvo = {"processo": "p", "i": 0, "tipo": "outro",
            "titulo": "Termo de Ajuste de Contas (83406122)",
            "pdf": tmp_path / "000.pdf", "txt": tmp_path / "t.txt",
            "manifest": tmp_path / "m.json", "kb": 1.0}
    saida, sem_dono = R.realinhar([alvo])
    assert sem_dono == 0
    assert saida[0]["pdf"] == tmp_path / "009.pdf"


def test_alvo_sem_dono_no_diretorio_e_descartado(tmp_path):
    """Sem dono não há reparo honesto — e a `pertence` recusaria depois de qualquer forma."""
    _pdf_com_texto(tmp_path / "000.pdf", "Peca alheia (11111111)")
    alvo = {"processo": "p", "i": 0, "tipo": "outro", "titulo": "Documento (99999999)",
            "pdf": tmp_path / "000.pdf", "txt": tmp_path / "t.txt",
            "manifest": tmp_path / "m.json", "kb": 1.0}
    saida, sem_dono = R.realinhar([alvo])
    assert saida == [] and sem_dono == 1
