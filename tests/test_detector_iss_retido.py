# -*- coding: utf-8 -*-
"""Controles do detector "ISS declarado retido na NF × OB paga sem a retenção" (COR-03, COR-05).

Textos sintéticos no layout REAL de cada emissor (ISSnet de Duque de Caxias, Nota Carioca, Futurize de Matias
Barbosa, DANFSe nacional), com os números dos casos-índice de 18/11/2026. Os controles no acervo real ficam no fim
(pulados onde `data/sei_arquivo` não existe, como na nuvem)."""
from __future__ import annotations

from pathlib import Path

import pytest

from compliance_agent import detector_iss_retido as D

# ─────────────────────────── layouts ───────────────────────────


def _br(v: float) -> str:
    return D._fmt(v)


def issnet(bruto, pis, cofins, inss, irrf, csll, iss, retido="Sim", numero="14159", aliq="5,00",
           cnpj="00.801.512/0001-57") -> str:
    liq = round(bruto - pis - cofins - inss - irrf - csll - iss, 2)
    return f"""Prefeitura Municipal de Duque de Caxias - RJ
Agile Corp Serviços Especializados Ltda
Inscrição Municipal 7731748 - CPF/CNPJ {cnpj}
Natureza da Operação
Tributação fora do município
Número da Nota Fiscal
{numero}
Consulte a autenticidade deste documento acessando o site: https://www.issnetonline.com.br/duquedecaxias/online
Imposto Sobre Serviços de Qualquer Natureza-ISSQN
Atividade do Município
Alíquota
Item da LC116/2003
Cód. Nacional Atividade Econômica
710 - 07.10 - Limpeza
{aliq}
710
8129000
Valor Total dos Serviços
Desconto Incondicionado
Deduções Base Cálculo
Base de Cálculo
Total do ISSQN
ISSQN Retido
Desconto Condicionado
R$ {_br(bruto)}
R$ 0,00
R$ 0,00  R$ {_br(bruto)}
R$ 0,00  {retido}
R$ 0,00
Retenções de Impostos
PIS
COFINS
INSS
IRRF
CSLL
Outras Retenções
ISSQN
R$ {_br(pis)}
R$ {_br(cofins)}
R$ {_br(inss)}
R$ {_br(irrf)}
R$ {_br(csll)}
R$ 0,00
R$ {_br(iss)}
Valor Líquido da Nota Fiscal
R$ {_br(liq)}
"""


def carioca(bruto, iss, retido=True, numero="00000785", cnpj="28.470.707/0001-S0", liquido=True) -> str:
    rodape = ("- O ISS desta NFS-e será RETIDO pelo Tomador de Serviço que deverá recolher através de DARM, gerado "
              "pelo sistema de NFS-e.\n" if retido else "- Data de vencimento do ISS desta NFS-e: 03/10/2024.\n")
    liq = f"- Valor Líquido a Pagar: R$ {_br(round(bruto - iss, 2))}\n" if retido and liquido else ""
    return f"""Número da Nota

PREFEITURA DA CIDADE DO RIO DE JANEIRO {numero}
NOTA FISCAL DE SERVIÇOS ELETRÔNICA - NFS-e Código de Verificação
- NOTA CARIOCA - 7TUNG-BKPV
PRESTADOR DE SERVIÇOS
CPF/CNPJ: {cnpj} Inscrição Municipal: 1.298,689-6
TOMADOR DE SERVIÇOS
CPF/CNPJ: 10.834.118/0001-79
VALOR DA NOTA = R$ {_br(bruto)}

Deduções (R$) Desconto Incond. (R$) |Base de Cálculo (R$) | Alíquota (%) Valor do I3S (R$) Crédito p/ IPTU (R$)
0,00 0,00 {_br(bruto)} 5,00% {_br(iss)} 0,00

OUTRAS INFORMAÇÕES
{rodape}- Esta NFS-e não gera crédito para abatimento no IPTU.
{liq}"""


def futurize(bruto, iss_ret, numero="210/2025") -> str:
    iss = round(bruto * 0.05, 2)
    return f"""PREFEITURA MUNICIPAL DE MATIAS BARBOSA
Nº da Nota
{numero}
TRIBUTAÇÃO FORA DO MUNICÍPIO
CNPJ: 28.470.707/0001-80
VALOR TOTAL DE SERVIÇOS = R$ {_br(bruto)}
PIS (R$)
COFINS (R$)
INSS (R$)
IR (R$)
CSLL (R$)
SEST SENAT (R$)
Outras Retenções (R$)
0,00
0,00
0,00
0,00
0,00
0,00
0,00
Deduções (R$)
Desc. Incond + Cond(R$)
Base de Cálculo (R$)
Alíquota (%)
Valor do ISS (R$)
ISS Retido (R$)
ISS Devido (R$)
Valor Líquido (R$)
0,00
0,00
{_br(bruto)}
5,00
{_br(iss)}
{_br(iss_ret)}
0,00
{_br(round(bruto - iss_ret, 2))}
"""


def danfse(bruto, iss, irrf, cp, retido=True, cnpj="42.270.181/0001-16") -> str:
    liq = round(bruto - (iss if retido else 0) - irrf - cp, 2)
    return f"""DANFSe v1.0
Documento Auxiliar da NFS-e
Número da NFS-e
13
Prestador do Serviço
CNPJ / CPF / NIF
{cnpj}
Valor do Serviço
R$ {_br(bruto)}
BC ISSQN
R$ {_br(bruto)}
Alíquota Aplicada
5,00%
Retenção do ISSQN
{"Retido pelo Tomador" if retido else "Não Retido"}
ISSQN Apurado
R$ {_br(iss)}
TRIBUTAÇÃO FEDERAL
IRRF
R$ {_br(irrf)}
CP Retido
R$ {_br(cp)}
PIS/COFINS/CSLL Retidos
-
Valor Líquido da NFS-e
R$ {_br(liq)}
"""


def ob(valor, credor="00801512000157", nl="2024NL00089", numero="2024OB02290", nome="FORNECEDOR", ug="180100"):
    return {"numero_ob": numero, "ug_emitente": ug, "data_emissao": "29/02/2024", "nl": nl, "credor": credor,
            "nome_credor": nome, "valor": valor, "exercicio": 2024, "processo": "SEI-1"}


AGILE = dict(bruto=3293120.16, pis=21405.28, cofins=98793.60, inss=362243.22, irrf=158069.77, csll=32931.20,
             iss=164656.01)


def _avaliar(texto, obs, obs_nl=None):
    nfs = D.extrair_nfs(texto)
    for n in nfs:
        n["documento"] = "x"
    return D.avaliar_processo("SEI-1", nfs, obs, obs_nl)


# ─────────────────────────── controle positivo ───────────────────────────


def test_controle_positivo_agile_ob_igual_bruto_menos_inss_irrf():
    """AGILE × SEEDUC, SEI-030029/016163/2023: OB 2024OB02290 = 3.293.120,16 − 362.243,22 − 158.069,77."""
    r = _avaliar(issnet(**AGILE), [ob(2772807.17)])
    assert len(r) == 1 and r[0]["classe"] == "ISS_NAO_RETIDO" and r[0]["estado"] == "VERIFICADO"
    assert r[0]["iss_nao_retido"] == 164656.01 and sorted(r[0]["subconjunto_federal"]) == ["INSS", "IRRF"]
    assert r[0]["nfs"][0]["numero"] == "14159" and r[0]["obs"][0]["numero_ob"] == "2024OB02290"


def test_controle_positivo_idesi_nota_carioca_ob_igual_bruto():
    """IDESI × FSERJ, SEI-080002/013337/2024: NF 785 manda reter R$ 44.307,94; OB 2024OB21011 = bruto."""
    r = _avaliar(carioca(886158.80, 44307.94), [ob(886158.80, credor="28470707000180", nl="2024NL09310")])
    assert r[0]["classe"] == "ISS_NAO_RETIDO" and r[0]["estado"] == "VERIFICADO" and r[0]["iss_nao_retido"] == 44307.94
    assert r[0]["subconjunto_federal"] == []


def test_controle_positivo_idesi_matias_barbosa_iss_retido_5pct():
    r = _avaliar(futurize(1340090.93, 67004.55), [ob(1340090.93, credor="28470707000180")])
    assert r[0]["classe"] == "ISS_NAO_RETIDO" and r[0]["iss_nao_retido"] == 67004.55


def test_controle_positivo_danfse_nacional():
    r = _avaliar(danfse(390601.51, 19530.08, 18748.87, 6444.92), [ob(390601.51 - 18748.87 - 6444.92, credor="42270181000116")])
    assert r[0]["classe"] == "ISS_NAO_RETIDO" and r[0]["iss_nao_retido"] == 19530.08


# ─────────────────────────── controle negativo (hipóteses inocentes) ───────────────────────────


def test_controle_negativo_idesi_ago_set_2024_prestador_recolhe():
    """Mesmo fornecedor, regime trocado: 'Data de vencimento do ISS' = o prestador recolhe; OB = bruto é correto."""
    r = _avaliar(carioca(681234.34, 34061.71, retido=False), [ob(681234.34, credor="28470707000180")])
    assert [x["classe"] for x in r] == ["FORA_DO_DOMINIO"] and r[0]["iss_nao_retido"] == 0.0


def test_controle_negativo_iss_retido_corretamente():
    r = _avaliar(issnet(**AGILE), [ob(round(2772807.17 - 164656.01, 2))])
    assert r[0]["classe"] == "RETIDO" and r[0]["iss_nao_retido"] == 0.0


def test_controle_negativo_pis_cofins_csll_nao_retidos_pelo_estado_nao_viram_iss():
    """Tomador estadual não retém PIS/COFINS/CSLL: OB = bruto − INSS − IRRF − ISS é o pagamento correto."""
    liq_estado = round(AGILE["bruto"] - AGILE["inss"] - AGILE["irrf"] - AGILE["iss"], 2)
    assert _avaliar(issnet(**AGILE), [ob(liq_estado)])[0]["classe"] == "RETIDO"
    # e o Estado que retém TUDO (federais + ISS) também está correto
    liq_nf = round(AGILE["bruto"] - sum(v for k, v in AGILE.items() if k != "bruto"), 2)
    assert _avaliar(issnet(**AGILE), [ob(liq_nf)])[0]["classe"] == "RETIDO"


def test_controle_negativo_retencao_em_ob_separada_ao_municipio_fica_pendente():
    obs = [ob(886158.80 - 44307.94 + 44307.94, credor="28470707000180", nl="2024NL09310"),
           ob(44307.94, credor="42498733000148", nome="MUNICIPIO DO RIO DE JANEIRO", numero="2024OB21012")]
    r = [x for x in _avaliar(carioca(886158.80, 44307.94), obs) if x["credor"] == "28470707000180"]
    assert r[0]["classe"] == "ISS_NAO_RETIDO" and r[0]["estado"] == "PENDENTE"
    s = D.resumir(r)
    assert s["totais"]["iss_nao_retido_verificado"] == 0 and s["totais"]["processos_pendentes"] == 1


def test_controle_negativo_ob_a_terceiro_na_mesma_nl_fora_do_processo_fica_pendente():
    o = ob(886158.80, credor="28470707000180", nl="2024NL09310", ug="294200")
    ter = {("2024NL09310", "294200"): [ob(44307.94, credor="29468055000102", nl="2024NL09310", numero="2024OB9",
                                          nome="FUNDO MUNICIPAL", ug="294200")]}
    r = _avaliar(carioca(886158.80, 44307.94), [o], ter)
    assert r[0]["estado"] == "PENDENTE"


def test_controle_negativo_arredondamento_de_centavos():
    """Diferença de centavos não é ISS: OB 3 centavos abaixo do líquido correto continua RETIDO."""
    certo = round(AGILE["bruto"] - AGILE["inss"] - AGILE["irrf"] - AGILE["iss"], 2)
    assert _avaliar(issnet(**AGILE), [ob(certo - 0.03)])[0]["classe"] == "RETIDO"
    # e uma OB que não fecha com hipótese nenhuma (glosa, parcial) é INDISPONÍVEL, nunca ISS
    r = _avaliar(issnet(**AGILE), [ob(certo - 1500.00)])
    assert r[0]["classe"] == "INDISPONIVEL" and r[0]["iss_nao_retido"] == 0.0


def test_ambiguo_quando_a_conta_fecha_com_e_sem_o_iss():
    """IRRF = ISS: OB = bruto − INSS − IRRF fecha também como bruto − INSS − ISS → INDISPONÍVEL."""
    v = dict(AGILE, irrf=AGILE["iss"])
    r = _avaliar(issnet(**v), [ob(round(v["bruto"] - v["inss"] - v["irrf"], 2))])
    assert r[0]["classe"] == "INDISPONIVEL" and "ambíguo" in r[0]["motivo"]


def test_sem_ob_paga_e_indisponivel_nao_zero():
    nfs = D.extrair_nfs(issnet(**AGILE))
    d = D.decidir(nfs, [], [])
    assert d["classe"] == "INDISPONIVEL" and d["estado"] == "INDISPONÍVEL"


def test_nf_que_nao_fecha_a_propria_conta_nao_e_lida():
    """OCR que troca um dígito do INSS: a NF não fecha (líquido ≠ bruto − retenções) e fica fora."""
    t = issnet(**AGILE).replace("R$ 362.243,22", "R$ 362.248,22")
    assert D.extrair_nfs(t) == []
    assert D.nf_menciona_iss_retido(t)


def test_iss_que_nao_e_base_vezes_aliquota_nao_e_lido():
    assert D.extrair_nfs(carioca(886158.80, 44370.94)) == []


def test_nf_de_outro_prestador_nao_casa_com_a_ob():
    r = _avaliar(issnet(**AGILE), [ob(2772807.17, credor="11222333000144")])
    assert r == []


def test_duas_nfs_no_processo_pagas_em_nls_separadas():
    t = issnet(**AGILE) + "\n" + issnet(**dict(AGILE, bruto=1000000.00, pis=6500.0, cofins=30000.0, inss=110000.0,
                                               irrf=48000.0, csll=10000.0, iss=50000.0), numero="14160")
    obs = [ob(2772807.17, nl="2024NL00089"), ob(1000000.0 - 110000.0 - 48000.0 - 50000.0, nl="2024NL00090",
                                                 numero="2024OB02300")]
    r = sorted(_avaliar(t, obs), key=lambda x: x["nfs"][0]["numero"])
    assert [x["classe"] for x in r] == ["ISS_NAO_RETIDO", "RETIDO"]


def test_controle_de_grupo_conta_os_demais_fornecedores_da_ug():
    base = {"ug": "180100", "estado": "VERIFICADO", "bruto": 100.0, "iss": 5.0, "nome_credor": "X"}
    regs = [dict(base, processo="P1", credor="A", classe="ISS_NAO_RETIDO"),
            dict(base, processo="P2", credor="B", classe="RETIDO"),
            dict(base, processo="P3", credor="C", classe="RETIDO")]
    linha = next(x for x in D.resumir(regs)["por_fornecedor"] if x["credor"] == "A")
    assert linha["controle_ug"] == {"fornecedores_decididos": 2, "fornecedores_com_nao_retido": 0,
                                    "processos_nao_retido": 0, "processos_retido": 2, "taxa_nao_retido": 0.0}


# ─────────────────────────── controles no acervo real (fonte primária) ───────────────────────────

ACERVO = Path(__file__).resolve().parents[1] / "data" / "sei_arquivo"
_DB = Path(__file__).resolve().parents[1] / "data" / "compliance.db"
real = pytest.mark.skipif(not (ACERVO / "030029_016163_2023").exists() or not _DB.exists(),
                          reason="acervo SEI/SIAFE local ausente")


def _real(sei):
    return D.varrer(so=sei)["registros"]


@real
@pytest.mark.parametrize("sei,credor,iss", [
    ("SEI-030029/016163/2023", "00801512000157", 164656.01),   # AGILE, NFS-e 14159, OB 2024OB02290
    ("SEI-080002/013337/2024", "28470707000180", 44307.94),    # IDESI, NF Carioca 785, OB 2024OB21011
    ("SEI-080002/015714/2025", "28470707000180", 67004.55),    # IDESI, NF Matias Barbosa 210/2025
])
def test_controle_positivo_real(sei, credor, iss):
    r = [x for x in _real(sei) if x["credor"] == credor and x["classe"] == "ISS_NAO_RETIDO"]
    assert r and r[0]["estado"] == "VERIFICADO" and r[0]["iss_nao_retido"] == iss


@real
def test_controle_negativo_real_idesi_ago_2024():
    r = _real("SEI-080002/019041/2024")
    assert r and all(x["classe"] != "ISS_NAO_RETIDO" for x in r)


# ─────────────────────────── recolhimento comprovado nos autos (falso positivo medido em 18/11/2026) ───────────────────────────


def test_controle_negativo_guia_de_iss_paga_pelo_prestador_rebaixa_a_pendente():
    """Construverde, SEI-070001/000948/2025: 'IMPOSTO ISS PAG ANTECIPADO REF NF 4732' — o prestador recolheu."""
    provas = D.provas_de_recolhimento([
        ("texto/119_nota_fiscal_nf_atesto_fiscais_e_guia_de.txt", "Nota Fiscal - NF Atesto Fiscais e Guia de ISS",
         "PAGAMENTO DE BOLETO\nIMPOSTO ISS PAG ANTECIPADO REF NF 4732")])
    assert provas
    r = D.avaliar_processo("SEI-1", D.extrair_nfs(carioca(886158.80, 44307.94)),
                           [ob(886158.80, credor="28470707000180")], None, provas)
    assert r[0]["classe"] == "ISS_NAO_RETIDO" and r[0]["estado"] == "PENDENTE" and r[0]["provas_recolhimento"]
    assert D.resumir(r)["totais"]["iss_nao_retido_verificado"] == 0


@pytest.mark.parametrize("arq,tit,txt", [
    ("texto/010_guia_de_iss_e_comp_pagto_15_a_17_medi_o.txt", "Guia de ISS e Comp Pagto", ""),
    ("texto/057_anexo.txt", "Anexo", "DOCUMENTO DE ARRECADAÇÃO MUNICIPAL\nISS"),
    ("texto/007_pd.txt", "Programação de Desembolso - PD 2024PD00999 ISS", ""),
])
def test_guia_darm_ou_pd_de_iss_contam_como_prova(arq, tit, txt):
    assert D.provas_de_recolhimento([(arq, tit, txt)])


def test_checklist_que_pede_comprovante_de_iss_nao_e_prova():
    """E-mail de faturamento da SEEDUC (AGILE): o item 9 PEDE a guia; pedir não é provar."""
    txt = "9. Guia e comprovante de pagamento de ISS de  Nota  Fiscal  (documentação relativa ao mês anterior"
    assert D.provas_de_recolhimento([("texto/026_e_mail_faturamento_65524348.txt", "E-mail Faturamento", txt)]) == []
    # e a PD de retenção de INSS (federal) não é prova de ISS
    assert D.provas_de_recolhimento([("texto/005_programacao_de_desembolso_pd_2024pd00534_inss.txt",
                                      "Programação de Desembolso - PD 2024PD00534 INSS",
                                      "Tipo de Retenção\nINSS SERVIÇOS DE TERCEIROS")]) == []


def test_mesma_nf_em_dois_processos_soma_uma_vez():
    base = {"ug": "180100", "estado": "VERIFICADO", "bruto": 100.0, "iss": 5.0, "nome_credor": "X", "credor": "A",
            "classe": "ISS_NAO_RETIDO", "nfs": [{"numero": "1", "bruto": 100.0}]}
    t = D.resumir([dict(base, processo="P1"), dict(base, processo="P2")])["totais"]
    assert t["iss_nao_retido_verificado"] == 5.0


# ─────────────── NF quitada por OB de NL diferentes (Scalle × EMOP, SEI-330003/002626/2024) ───────────────

def _nf_scalle() -> dict:
    return {"formato": "mage", "numero": "1002000", "bruto": 9705421.03, "iss": 145581.32, "aliquota": 1.5,
            "iss_retido_tomador": True, "liquido_nf": None, "_digitos": "",
            "componentes": {"PIS": 63085.24, "COFINS": 291162.63, "IRRF": 116465.05, "INSS": 533798.16,
                            "CSLL": 97054.21}}


def _ob(n, nl, v):
    return {"numero_ob": n, "nl": nl, "valor": v, "ug_emitente": "1", "credor": "X", "nome_credor": "X",
            "data_emissao": "01/12/2024"}


# 8.603.855,74 = bruto − federais (sem ISS), pago em 3 OB de 3 NL; 2024OB03306 é de OUTRA medição
_OBS_SCALLE = [_ob("2024OB03897", "2024NL1", 3000000.00), _ob("2024OB03898", "2024NL2", 3000000.00),
               _ob("2024OB03899", "2024NL3", 2603855.74)]


def test_nf_paga_em_ob_de_nl_diferentes_fecha_por_subconjunto():
    r = D._casar([_nf_scalle()], _OBS_SCALLE + [_ob("2024OB03306", "2024NL9", 3636723.87)], [])
    assert r[0]["classe"] == "ISS_NAO_RETIDO" and r[0]["iss"] == 145581.32
    assert {o["numero_ob"] for o in r[0]["obs"]} == {"2024OB03897", "2024OB03898", "2024OB03899"}


def test_ob_de_outra_medicao_nao_completa_a_nf():
    # sem uma das parcelas, a OB de outra medição não pode "tapar o buraco"
    r = D._casar([_nf_scalle()], _OBS_SCALLE[:2] + [_ob("2024OB03306", "2024NL9", 3636723.87)], [])
    assert r[0]["classe"] == "INDISPONIVEL" and not r[0]["obs"]
