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
