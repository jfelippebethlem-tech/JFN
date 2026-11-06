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


# ───────── quando o título não diz nada, o TIPO diz (2026-08-04) ─────────

def _docs(tipos):
    return [{"i": i, "titulo": str(80000000 + i), "tipo": t} for i, t in enumerate(tipos)]


def test_processo_so_de_empenho_e_liquidacao_e_PAGAMENTO():
    """Medido em 2026-08-04: **1.129 dos 2.174 processos (52%) ficavam `indefinido`**, e o
    `fases.lacunas` dá ao indefinido o checklist COMPLETO de contratação — o caso menos conhecido
    recebendo o tratamento mais severo. Numa amostra, 65 de 67 indefinidos eram acusados de
    "Planejamento ausente"; abrindo-os, são processos de empenho→liquidação. A causa: parte dos
    manifestos perdeu os TÍTULOS e guarda só o identificador ("86655470 | 84392504 | …"), então as
    regras por título não têm o que ler — mas o `tipo` canônico está lá."""
    docs = _docs(["nota_empenho"] * 6 + ["nota_liquidacao"] * 2)
    assert T.natureza({}, docs) == "pagamento"


def test_uma_peca_de_contratacao_basta_para_NAO_isentar():
    """A isenção é estreita: qualquer contrato, edital, ata ou TR nos autos derruba a regra."""
    docs = _docs(["nota_empenho"] * 6 + ["nota_liquidacao"] * 2 + ["contrato"])
    assert T.natureza({}, docs) != "pagamento"


def test_menos_de_metade_de_despesa_continua_indefinido():
    """Conservador: sem maioria de despesa, a casa não afirma a natureza."""
    docs = _docs(["outro"] * 3 + ["nota_liquidacao"])
    assert T.natureza({}, docs) == "indefinido"


def test_titulo_com_contrato_FORTE_vence_a_regra_de_tipo():
    """O sinal forte do título decide antes — a regra de tipo só entra onde o título é mudo."""
    docs = [{"i": 0, "titulo": "Contrato nº 32/2025", "tipo": "nota_empenho"},
            {"i": 1, "titulo": "Nota de Empenho", "tipo": "nota_empenho"}]
    assert T.natureza({}, docs) == "contratacao"


def test_a_isencao_NAO_alcanca_a_evidencia_de_execucao():
    """O que a natureza `pagamento` dispensa é planejamento, seleção e formalização. Pagar sem
    prova de entrega continua sendo cobrado — é o achado que mais importa."""
    from compliance_agent.sei import fases
    lac = fases.lacunas({"despesa"}, "", com_pagamento=True, natureza="pagamento")
    faltas = " ".join(str(x.get("falta")) for x in lac)
    assert "Evidência de execução" in faltas
    assert "Planejamento" not in faltas and "Seleção" not in faltas


# ───────── ausência de FÓRMULA não é ausência de RESPOSTA (2026-08-04) ─────────

def _proc_com_parecer_e_resposta(tmp_path, texto_resposta):
    (tmp_path / "texto").mkdir(exist_ok=True)
    docs = []
    pecas = [
        ("Parecer 625/2024 (81625942)", "parecer",
         "PARECER Nº 625/2024/SES/ASSJUR\nAssunto: contratação.\n"
         "recomenda-se a instauração de sindicância antes da contratação, desde que apurada a "
         "responsabilidade, conforme o parágrafo 31 deste parecer."),
        ("Despacho de Encaminhamento de Processo 81797000", "despacho", texto_resposta),
    ]
    for i, (titulo, tipo, corpo) in enumerate(pecas):
        nome = f"{i:03d}_doc.txt"
        (tmp_path / "texto" / nome).write_text(f"[{titulo}] (tipo: {tipo})\n\n{corpo}",
                                               encoding="utf-8")
        docs.append({"i": i, "titulo": titulo, "tipo": tipo, "texto": f"texto/{nome}"})
    import json as _j
    (tmp_path / "manifest.json").write_text(_j.dumps({"docs": docs}), encoding="utf-8")
    return tmp_path


def test_resposta_que_CITA_o_parecer_derruba_a_afirmacao_de_ausencia(tmp_path):
    """Medido em 2026-08-04 nos 27 disparos do A3: **18 tinham documento posterior citando o
    IDENTIFICADOR do parecer**, e o que está escrito ali é resposta de verdade — "quanto ao
    apontamento contido no parágrafo 31 do Parecer nº 625/2024 (81625942), cumpre esclarecer que
    a competente sindicância foi instaurada". Dizer "nenhum documento registra acatamento" ali é
    afirmar uma ausência que não existe."""
    p = _proc_com_parecer_e_resposta(
        tmp_path,
        "Preliminarmente, quanto ao apontamento contido no parágrafo 31 do Parecer nº 625/2024 "
        "(81625942), cumpre esclarecer que a competente sindicância foi instaurada no bojo do "
        "processo SEI-080001/013232/2024.")
    r = T.periciar(p)
    a3 = [x for x in (r.get("achados") or []) if str(x.get("codigo", "")).startswith("A3")]
    assert a3, "o achado não some — citar não é acatar"
    assert a3[0]["grau"] == "baixo"
    assert "REPORTA" in a3[0]["diz"]
    assert "81625942" in a3[0]["apoio"]


def test_sem_mencao_ao_parecer_a_afirmacao_de_ausencia_permanece(tmp_path):
    p = _proc_com_parecer_e_resposta(
        tmp_path, "Encaminho os autos à Coordenação para emissão de nota de empenho.")
    r = T.periciar(p)
    a3 = [x for x in (r.get("achados") or []) if str(x.get("codigo", "")).startswith("A3")]
    assert a3 and a3[0]["grau"] == "medio"
    assert "nenhum registra acatamento" in a3[0]["diz"]


def _junta(pasta, titulo, tipo, corpo):
    """Acrescenta uma peça ao fim do processo montado por `_proc_com_parecer_e_resposta`."""
    import json as _j
    man = _j.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    i = len(man["docs"])
    nome = f"{i:03d}_doc.txt"
    (pasta / "texto" / nome).write_text(f"[{titulo}] (tipo: {tipo})\n\n{corpo}", encoding="utf-8")
    man["docs"].append({"i": i, "titulo": titulo, "tipo": tipo, "texto": f"texto/{nome}"})
    (pasta / "manifest.json").write_text(_j.dumps(man), encoding="utf-8")
    return pasta


def test_ato_que_DECIDE_conta_como_resposta_mesmo_fora_do_tipo(tmp_path):
    """O ato que decide não é do tipo "resposta" — e é ele que responde ao parecer. Medido em
    2026-08-05 nos 11 disparos "nenhum registra acatamento": o SEI-070002/013107/2024 traz o
    "Ato de Reconhecimento de Dívida 86639308" enumerando os procedimentos e citando o parecer
    pelo identificador. O classificador o tipa `parecer`, então ele ficava fora de `_RESPOSTA` e
    o achado afirmava uma ausência que os autos desmentem."""
    p = _proc_com_parecer_e_resposta(
        tmp_path, "Encaminho os autos à Coordenação para emissão de nota de empenho.")
    _junta(p, "Ato de Reconhecimento de Dívida 86639308", "parecer",
           "Em atenção ao disposto no artigo 14 do Decreto Estadual nº 41.880/2009 foram "
           "realizados os seguintes procedimentos: (I) Parecer jurídico exarado pela "
           "Procuradoria (81625942) com a conclusão de não ocorrência de prescrição.")
    r = T.periciar(p)
    a3 = [x for x in (r.get("achados") or []) if str(x.get("codigo", "")).startswith("A3")]
    assert a3, "o achado não some — citar não é acatar"
    assert a3[0]["grau"] == "baixo"
    assert "REPORTA" in a3[0]["diz"]


def test_ato_que_decide_sem_citar_o_parecer_nao_derruba_nada(tmp_path):
    """Controle negativo, medido no mesmo dia: o SEI-080001/036964/2025 também tem ato decisório
    posterior, não cita o parecer, e segue `medio` — e é o caso VERDADEIRO (a Deliberação CIB
    nº 1.237/2025 nunca foi referendada). É a conjunção título-de-ato **e** citação que segura a
    regra; alargar `_RESPOSTA` por tipo importaria ruído puro."""
    p = _proc_com_parecer_e_resposta(
        tmp_path, "Encaminho os autos à Coordenação para emissão de nota de empenho.")
    _junta(p, "Termo de Ratificação 99887766", "parecer",
           "Ratifico a dispensa de licitação para a contratação em tela, nos termos do "
           "artigo 75 da Lei nº 14.133/2021.")
    r = T.periciar(p)
    a3 = [x for x in (r.get("achados") or []) if str(x.get("codigo", "")).startswith("A3")]
    assert a3 and a3[0]["grau"] == "medio"
    assert "nenhum registra acatamento" in a3[0]["diz"]
