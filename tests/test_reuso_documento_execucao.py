# -*- coding: utf-8 -*-
"""Documento de execução reaproveitado entre processos — controles positivo e negativo (COR-03).

Positivos (casos medidos na fonte primária em 18/11/2026):
  • SEHIS × Augusto Velloso: diário de obras com o mesmo corpo em 4 processos/3 contratos;
  • EUREKA × SEEDUC: relatório-modelo de fiscalização (galpão da Dutra, amostragem de 15%) em 3 pagamentos.
Negativos: formulário-padrão do órgão em vários credores, juntada em duplicidade no mesmo processo, o
mesmo nº SEI em dois processos, cópia com as mesmas assinaturas, planilha de medição da mesma ata e
portaria de designação da comissão.

Os testes sintéticos rodam em qualquer máquina; os do acervo real pulam onde ele não existe.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from compliance_agent.sei import reuso_documento_execucao as R

ACERVO = Path(__file__).resolve().parents[1] / "data" / "sei_arquivo"

_ASSIN = ("Documento assinado eletronicamente por {quem}, Fiscal, em {data}, às 10:{min:02d}, conforme horário "
          "oficial de Brasília, com fundamento nos art. 28º e 29º do Decreto nº 48.209, de 19 de setembro de 2022.")
_RODAPE = ("A autenticidade deste documento pode ser conferida no site http://sei.rj.gov.br/sei/controlador_externo.php"
           "?acao=documento_conferir&id_orgao_acesso_externo=6, informando o código verificador {sei} e o código "
           "CRC 5878D407.\nReferência: Processo nº {proc}\tSEI nº {sei}")

DIARIO = """RELATORIO DIARIO DE OBRA | CONTRATO
PAVIMENTAÇÃO LOTE 01 (Baixada Litorânea, Região dos Lagos, Norte e Noroeste)
INICIO CONTRATO | PROCESSO
2025-10-03 | SEI-490001/001323/2024
EFETIVO PESSOAL 8 | 07:00h as 17:00h | LOCAL OBRA CAMBUCI, MIRACEMA - RJ
Engenheiro Civil 1 | Encarregado 1 | Serventes 3 | Retroescavadeira 1 | Cam. Basculante 1
Atividades: mobilização do canteiro, limpeza do terreno e escavação manual de vala para meio-fio na Rua
Projetada A, trecho entre as estacas 12 e 18, com remoção de 14 m3 de material para bota-fora licenciado.
Ocorrências: chuva fraca no período da tarde, sem paralisação; visita do fiscal às 15h para conferência.
Dia 2: continuidade da escavação na Rua Projetada B, estacas 3 a 9, regularização mecânica de 220 m2."""

RELATORIO_MIOLO = """- Condições de recebimento:
A obrigação foi cumprida no prazo e dentro das especificações requeridas pela Administração para o projeto dos
Itinerários Formativos.
- Acondicionamento:
Os materiais encontram-se armazenados no galpão situado à Rodovia Presidente Dutra n° 2.671, Parque Colúmbia,
Rio de Janeiro/RJ, estando de acordo e atendendo às exigências do contrato em tela. A totalidade dos livros
encontra-se bem-acondicionado e de forma organizada.
- Metodologia de Conferência:
A conferência dos livros deu-se por amostragem. Foi verificado aproximado de 15% de volume disposto em diferentes
caixas e em posições diversas. Em nenhum caso se constatou a presença de itens divergentes ou em desacordo com os
especificados no contrato, sendo as caixas abertas aleatoriamente pela equipe em cada uma das fileiras do galpão."""

FORMULARIO = """ATESTADO DE RECEBIMENTO DE MATERIAL
Atestamos, para fins de liquidação da despesa, que os materiais e/ou serviços constantes do documento fiscal abaixo
indicado foram recebidos e conferidos por esta comissão, estando de acordo com as especificações do instrumento
contratual e com a proposta da contratada, nada havendo a opor quanto à sua aceitação nos termos da legislação vigente,
ficando a unidade requisitante responsável pela guarda, conservação e controle dos bens recebidos neste ato."""


def _doc(processo, sei, titulo, corpo, tipo="fiscalizacao", credor="11111111000191", assin=None, contratos=()):
    texto = f"{corpo}\n" + "\n".join(_ASSIN.format(quem=q, data=d, min=i) for i, (q, d) in enumerate(assin or [])) \
        + "\n" + _RODAPE.format(sei=sei, proc=f"SEI-{processo}")
    p = R.preparar({"processo": processo, "sei": sei, "titulo": f"{titulo} ({sei})", "tipo": tipo,
                    "texto": texto, "credor": credor, "contratos": list(contratos)})
    return p


# ── normalização ───────────────────────────────────────────────────────────────────────────────

def test_normalizacao_tira_assinatura_rodape_numero_sei_e_cpf():
    t = ("Relatório do mês.\n" + _ASSIN.format(quem="Fulano", data="17/03/2025", min=1) + "\n"
         + _RODAPE.format(sei="94573672", proc="SEI-030001/025906/2025")
         + "\nFiscal CPF 123.456.789-09 e ***.456.789-** conferiu o doc 94573672 do SEI-030001/025906/2025.")
    c = R.normalizar_corpo(t)
    assert "assinado" not in c and "autenticidade" not in c and "48 209" not in c
    assert "94573672" not in c and "025906" not in c and "456" not in c
    assert "relatorio do mes" in c and "cpf" in c


def test_assinaturas_sao_metadado_extraido():
    t = _ASSIN.format(quem="Leonardo Nicolau", data="17/03/2025", min=3)
    assert R.assinaturas(t) == ["leonardo nicolau|17/03/2025|10:03"]


def test_numero_sei_e_contrato():
    assert R.numero_sei_do_titulo("Diário de Obras (135515994)") == "135515994"
    assert R.contratos_citados("Contrato n° 034/2026 e contrato nº 2/2025") == {"34/2026", "2/2025"}


# ── controles POSITIVOS ────────────────────────────────────────────────────────────────────────

def test_positivo_diario_identico_em_processos_diferentes_e_VERIFICADO():
    a = _doc("490001/000249/2026", "135515994", "Diário de Obras", DIARIO, contratos=["34/2026"])
    b = _doc("490001/000322/2026", "126871249", "Diário de Obras", DIARIO, contratos=["19/2025"])
    r = R.comparar(a, b)
    assert r["classe"] == "reuso_execucao" and r["forma"] == "integral"
    assert r["identico"] and r["estado"] == "VERIFICADO"
    assert r["nivel"] == "identico_contratos_diferentes"
    assert r["contratos_diferentes"] is True and r["mesmo_credor"] is True
    assert r["a"]["sei"] == "135515994" and r["b"]["sei"] == "126871249"   # proveniência
    assert any("rodovia" in t or "estacas 12" in t or "escavacao" in t for t in r["trechos_comuns"])


def test_positivo_relatorio_modelo_com_cabecalho_diferente_dispara_por_trecho():
    cab1 = ("RELATÓRIO DE FISCALIZAÇÃO. Contrato n° 39/2024. Objeto: aquisição de livros dos Itinerários Formativos. "
            "Valor Total do Contrato: R$ 125.949.837,44. Data de Conferência: 08/01/2025. Nota Fiscal nº 4.981, "
            "lote único de 312.400 livros, conforme ordem de fornecimento do processo de origem.")
    cab2 = ("RELATÓRIO DE FISCALIZAÇÃO. Contrato n° 02/2025. Objeto: aquisição de material de apoio pedagógico para a "
            "recomposição das aprendizagens. Valor Total do Contrato: R$ 430.998.247,89. Data de Conferência: 03/02/2025. "
            "Nota Fiscal nº 5.095, segundo lote de 129.426 livros de apoio pedagógico.")
    a = _doc("030001/000071/2025", "90902746", "Relatório de Fiscalização", cab1 + "\n" + RELATORIO_MIOLO,
             assin=[("Jefferson", "08/01/2025")])
    b = _doc("030001/025906/2025", "94573672", "Relatório de Fiscalização", cab2 + "\n" + RELATORIO_MIOLO,
             assin=[("Jefferson", "17/03/2025")])
    r = R.comparar(a, b)
    assert r["classe"] == "reuso_execucao" and r["forma"] == "trecho"
    assert r["estado"] == "PENDENTE"                        # quase idêntico pede leitura humana
    assert "dutra" in r["trecho_mais_longo"]["inicio"] or "galpao" in r["trecho_mais_longo"]["inicio"]


# ── controles NEGATIVOS ────────────────────────────────────────────────────────────────────────

def test_negativo_duplicata_no_mesmo_processo_nao_e_achado():
    a = _doc("490001/000249/2026", "135515994", "Diário de Obras", DIARIO)
    b = _doc("490001/000249/2026", "140206635", "Diário de Obras", DIARIO)
    assert R.comparar(a, b)["classe"] == "mesmo_processo"


def test_negativo_mesmo_numero_sei_em_dois_processos_e_o_mesmo_documento():
    a = _doc("490001/000249/2026", "135515994", "Diário de Obras", DIARIO)
    b = _doc("490001/000999/2026", "135515994", "Diário de Obras", DIARIO)
    assert R.comparar(a, b)["classe"] == "mesmo_documento"


def test_negativo_copia_com_as_mesmas_assinaturas_juntada_noutro_processo():
    ass = [("Jefferson da Silva", "17/03/2025"), ("Leonardo Nicolau", "17/03/2025")]
    a = _doc("030001/025906/2025", "94573672", "Relatório de Fiscalização", RELATORIO_MIOLO, assin=ass)
    b = _doc("030001/030000/2025", "95000001", "Relatório de Fiscalização", RELATORIO_MIOLO, assin=ass)
    assert R.comparar(a, b)["classe"] == "copia_do_mesmo_documento"


def test_negativo_portaria_de_designacao_fica_fora_da_selecao():
    assert R.titulo_e_de_designacao("Portaria Comissão de Fiscalização (126807256)")
    # 2ª rodada: atos e modelos que tinham corpo idêntico em vários processos
    for t in ("Anexo 5D.O._de_21.09.2023__Comissão de Fiscalização", "Documento - Modelo de recebimento provisório",
              "Resolução SECC 28.2021 - Regulamento", "Anexo 02 - PUBLICAÇÃO COMISSÃO DE FISCALIZAÇÃO",
              "Anotação ART /RRT - Comissão de Fiscalização", "Anexo 10 - Nomeção da Comissão de Fiscalização"):
        assert R.titulo_e_de_designacao(t), t
    for t in ("Relatório ART - ATESTADO DE RESPONSABILIDADE TÉCNICA", "Guia de ISS e Comp. Pagto - Belford",
              "Anexo 19 E-MAIL DE SOL./REC. DOC", "Atestado de veracidade (76298022)",
              "Boletim Comissão de Fiscalização de Contratos",
              "Despacho de Atesto de Habilitação Jurídica e Fiscal"):
        assert R.titulo_e_de_designacao(t), t
    assert not R.titulo_e_de_designacao("Parecer 31 Comissão de Fiscalização - Abril/25")
    assert not R.titulo_e_de_designacao("Anexo 15 F - RELATORIO DIARIO DE OBRA")
    assert R.titulo_e_de_designacao("Anexo - Comissão de Gestão e Fiscalização (92999987)")
    assert not R.titulo_e_de_designacao("Relatório de Fiscalização 94573672")
    assert not R.titulo_e_de_designacao("Diário de Obras (135515994)")


def test_negativo_planilha_de_medicao_da_mesma_ata_nao_dispara_por_trecho():
    itens = "\n".join(f"1.{i} | 13.373.00{i}0-0 | PISO DE CONCRETO ARMADO MONOLITICO ESPESSURA 10CM | M2 | "
                      f"{100 + i},00 | 154,3{i}" for i in range(30))
    a = _doc("490001/000249/2026", "135487241", "Planilha 1ª Medição", itens.replace(",00", ",50"), tipo="medicao")
    b = _doc("490001/000322/2026", "126807249", "Planilha 2ª Medição", itens.replace(",00", ",75"), tipo="medicao")
    assert R.comparar(a, b)["classe"] != "reuso_execucao"


def _corpus(tmp_path, docs) -> Path:
    arq = tmp_path / "corpus.jsonl.gz"
    with gzip.open(arq, "wt", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps({"registro": "doc", **{k: d[k] for k in (
                "processo", "sei", "titulo", "tipo", "corpo", "hash", "assinaturas", "texto_bruto_inicio",
                "credor", "contratos")}, "credor_fonte": "teste", "arquivo": None, "pasta": None, "i": 0}) + "\n")
    return arq


def test_negativo_formulario_padrao_do_orgao_em_varios_credores_e_modelo_nao_achado(tmp_path):
    """O mesmo formulário de atesto em 4 credores, cada um com o seu preenchimento: o texto do formulário
    é modelo institucional (≥ B credores) e sai; o preenchimento difere; nenhum par."""
    docs = []
    for n, cred in enumerate(["11111111000191", "22222222000191", "33333333000191", "44444444000191"]):
        corpo = (FORMULARIO + f"\nNota Fiscal nº {1000 + n}, emitida em {10 + n}/02/2025, {50 * (n + 1)} unidades "
                 f"de material de escritório entregues na unidade {n} da secretaria.")
        docs.append(_doc(f"030001/00{n}000/2025", f"9{n}000000", "Atestado de Recebimento", corpo,
                         tipo="aceite", credor=cred))
    # sem o filtro de modelo, o formulário faz os pares parecerem cópia (é isso que o filtro evita)
    bruto = R.comparar(docs[0], docs[1])
    assert bruto["descritivos_comuns"] >= R.MIN_DESCRITIVO
    out = tmp_path / "pares.json"
    r = R.parear(_corpus(tmp_path, docs), out)
    assert r["pares"] == 0 and r["shingles_modelo"] > 0


def test_positivo_ponta_a_ponta_parear_acha_o_diario_e_ignora_o_formulario(tmp_path):
    docs = [_doc(f"490001/00{n}000/2026", f"13{n}000000", "Diário de Obras", DIARIO,
                 credor="60853934000106", contratos=[f"{n}/2025"]) for n in range(3)]
    docs += [_doc(f"030001/00{n}000/2025", f"9{n}000000", "Atestado", FORMULARIO + f"\nNF {n} lote {n}",
                  tipo="aceite", credor=f"{n}{n}{n}{n}{n}{n}{n}{n}000191") for n in range(1, 5)]
    out = tmp_path / "pares.json"
    r = R.parear(_corpus(tmp_path, docs), out)
    pares = json.loads(out.read_text())["pares"]
    assert r["pares"] == 3 and all(p["estado"] == "VERIFICADO" and p["forma"] == "integral" for p in pares)
    assert {p["a"]["processo"][:6] for p in pares} == {"490001"}


# ── acervo REAL (pula onde não existe) ─────────────────────────────────────────────────────────

_SEHIS = ["490001_000249_2026", "490001_000322_2026", "490001_000329_2026", "490001_000486_2026"]
_EUREKA = ["030001_000071_2025", "030001_015319_2025", "030001_025906_2025"]
real = pytest.mark.skipif(not all((ACERVO / p / "manifest.json").exists() for p in _SEHIS + _EUREKA),
                          reason="acervo SEI dos casos de origem não presente nesta máquina")


def _docs_reais(pastas):
    out = {}
    for p in pastas:
        docs, _ = R.documentos_de_execucao(ACERVO / p)
        for d in docs:
            out[d["sei"]] = R.preparar(d)
    return out


@real
def test_real_sehis_os_cinco_diarios_tem_o_mesmo_corpo_e_disparam():
    d = _docs_reais(_SEHIS)
    seis = ["135515994", "140206635", "126871249", "126874480", "129485829"]
    assert len({d[s]["hash"] for s in seis}) == 1
    r = R.comparar(d["135515994"], d["126871249"])
    assert r["classe"] == "reuso_execucao" and r["estado"] == "VERIFICADO"
    assert R.comparar(d["135515994"], d["140206635"])["classe"] == "mesmo_processo"


@real
def test_real_sehis_portaria_da_comissao_nao_entra():
    d = _docs_reais(_SEHIS)
    assert "126807256" not in d and "129485818" not in d


@real
def test_real_eureka_relatorio_modelo_nos_tres_pagamentos():
    d = _docs_reais(_EUREKA)
    for a, b in [("93026239", "94573672"), ("90902746", "93026239"), ("90902746", "94573672")]:
        r = R.comparar(d[a], d[b])
        assert r["classe"] == "reuso_execucao", (a, b, r["contencao"])
        assert r["estado"] == "PENDENTE"


def test_negativo_cabecalho_do_mesmo_contrato_em_relatorios_mensais_nao_dispara_por_trecho():
    """1ª rodada no acervo (18/11/2026): 3.140 'trechos' eram o cabeçalho do MESMO contrato (objeto,
    vigência, fiscais) repetido nos relatórios mensais. Trecho só vale entre contratos diferentes."""
    cab = ("RELATÓRIO DE FISCALIZAÇÃO. Contrato nº 002/2024. Contratada: PRIME CONSULTORIA. Objeto: gestão do "
           "abastecimento com utilização de solução tecnológica e fornecimento de combustíveis através de postos "
           "credenciados para atender às necessidades da frota oficial, conforme especificações do termo de "
           "referência e da proposta comercial vencedora, com vigência de doze meses a contar da assinatura e "
           "fiscalização pela comissão designada em portaria publicada no diário oficial do estado, cabendo à "
           "comissão o acompanhamento mensal do consumo, dos preços praticados e da regularidade dos postos.")
    a = _doc("150001/004542/2026", "130163863", "Relatório de Fiscalização",
             cab + "\nEm março foram abastecidos 1.204 litros em 37 veículos; dois postos sem nota.",
             assin=[("Fiscal A", "05/04/2026")])
    b = _doc("150001/013836/2024", "88253757", "Relatório de Fiscalização",
             cab + "\nEm abril foram abastecidos 980 litros em 35 veículos; nenhuma ocorrência.",
             assin=[("Fiscal A", "06/05/2026")])
    r = R.comparar(a, b)
    assert r.get("forma") != "trecho"
    # sem o texto do contrato, o par fica no nível FRACO (mesmo contrato), nunca nos fortes
    assert r["nivel"] == "quase_identico_mesmo_contrato"
    # com o texto do instrumento no acervo (o objeto vem dele), o cabeçalho sai e não sobra par
    contrato = R.shingles(R.normalizar_corpo(cab.replace("RELATÓRIO DE FISCALIZAÇÃO. ", "")))
    assert R.comparar(a, b, sh_contrato=contrato)["classe"] != "reuso_execucao"


def test_negativo_metodo_recorrente_do_fiscal_em_muitos_documentos_nao_e_trecho():
    """2ª rodada (18/11/2026): o parágrafo de MÉTODO da fiscalização repetido em dezenas de relatórios
    de lotes do mesmo credor virava 'trecho'. Com a frequência do acervo (raros = vazio, isto é, o texto
    está em muitos documentos), o trecho não se sustenta; o par isolado (sem frequência) segue disparando."""
    cab1, cab2 = "Contrato n° 39/2024. Nota Fiscal 4.981.", "Contrato n° 02/2025. Nota Fiscal 5.095."
    a = _doc("030001/000071/2025", "90902746", "Relatório de Fiscalização", cab1 + "\n" + RELATORIO_MIOLO)
    b = _doc("030001/025906/2025", "94573672", "Relatório de Fiscalização", cab2 + "\n" + RELATORIO_MIOLO)
    assert R.comparar(a, b)["classe"] == "reuso_execucao"
    a["raros"], b["raros"] = set(), set()
    assert R.comparar(a, b).get("forma") != "trecho"


def test_identico_com_o_mesmo_titulo_no_mesmo_contrato_e_nivel_de_copia_provavel():
    """A planilha da 31ª medição juntada no processo de pagamento e no de gestão do MESMO contrato é,
    provavelmente, o mesmo documento duas vezes — nível próprio, fora dos fortes."""
    a = _doc("070002/000001/2024", "11111111", "Anexo 2.1 - Planilha 31ª Medição", DIARIO, contratos=["27/2022"])
    b = _doc("070002/000002/2024", "22222222", "Anexo 2.1 - Planilha 31ª Medição", DIARIO, contratos=["27/2022"])
    assert R.comparar(a, b)["nivel"] == "identico_mesmo_contrato_mesmo_titulo"
    c = _doc("070002/000003/2024", "33333333", "Anexo 2.1 - Planilha 32ª Medição", DIARIO, contratos=["27/2022"])
    assert R.comparar(a, c)["nivel"] == "identico_mesmo_contrato_titulos_diferentes"


def test_negativo_formulario_em_branco_igual_em_contratos_diferentes_nao_e_achado():
    """3ª rodada: o 'Anexo 15 F – Relatório Diário de Obras' do CBMERJ e a 'Atestação Física' da SEEDUC,
    EM BRANCO, eram corpo idêntico em contratos diferentes."""
    branco = ("ANEXO II\nATESTAÇÃO FÍSICA\nUnidade Escolar:\nLocal de Entrega:\nEmpresa:\n"
              "Atestamos o recebimento, em _____/______/_____ dos mobiliários e equipamentos conforme quantidades "
              "e especificações estabelecidas no Processo nº_______________.\nItem\nQuantidade Recebida\n"
              "Conjunto Aluno\nConjunto Professor\nQuadro Branco\nCadeira Giratória\nEstante de Aço\n"
              "Diretor ou Diretor Adjunto:\nNome: ____________ Matrícula:__________\nServidor:\n"
              "Nome: ____________ Matrícula:__________\nAssinatura: ______________ (usar preferencialmente o carimbo)")
    assert R.formulario_em_branco(branco)
    assert not R.formulario_em_branco(DIARIO) and not R.formulario_em_branco(RELATORIO_MIOLO)
    a = _doc("030001/013060/2025", "92520116", "Anexo II Atestação Física de Recebimento", branco,
             tipo="aceite", contratos=["25/2024"])
    b = _doc("030001/029132/2025", "95125751", "Anexo II Atestação Física de Recebimento", branco,
             tipo="aceite", contratos=["34/2024"])
    assert R.comparar(a, b)["classe"] == "formulario_em_branco"


def test_negativo_catalogo_emop_exportado_na_planilha_nao_e_corpo():
    """3ª rodada: o catálogo EMOP inteiro vinha na 'Planilha Boletim de Medição Excel' e virava corpo
    idêntico entre credores. Linha de catálogo (código | descrição | unidade | preço) sai; linha de medição
    (mais colunas) fica."""
    cat = "\n".join(["CATEGORIAS CATÁLOGO EMOP", "01 | SERVIÇOS DE ESCRITÓRIO, LABORATÓRIO E CAMPO"]
                    + [f"01.001.0{100 + i}-0 | ENSAIO DE VISCOSIDADE ESPECIFICA ENGLER TIPO {i} | UN | {200 + i}.15"
                       for i in range(50)])
    assert R.normalizar_corpo(cat) == ""
    assert R.predominio_de_catalogo(cat)
    a = _doc("490001/000221/2026", "128209368", "Planilha Boletim de Medição Excel", cat + "\n2202.27\n2064.33",
             tipo="medicao", credor="29622057000104", contratos=["15/2026"])
    b = _doc("490001/000232/2026", "128218811", "Planilha Boletim de Medição em Excel", cat + "\n2202.27\n2064.33",
             tipo="medicao", credor="29622057000104", contratos=["17/2026"])
    assert R.comparar(a, b)["classe"] == "catalogo_de_precos"
    assert not R.predominio_de_catalogo(DIARIO)
    med = "13.373.0020-0 | PISO DE CONCRETO ARMADO | M2 | 100,50 | 154,31 | 50,00 | 7.715,50"
    assert "piso de concreto" in R.normalizar_corpo(med)
