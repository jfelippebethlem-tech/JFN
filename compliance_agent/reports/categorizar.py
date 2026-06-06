# -*- coding: utf-8 -*-
"""
Categorização de OBs por ÁREA/OBJETO e mapeamento de UG → nome do órgão pagador.

A grade do SIAFE entrega por OB: UG Emitente, UG Pagadora (códigos), Tipo de OB e Nome do Favorecido.
A partir disso inferimos a ÁREA/OBJETO do gasto (Saúde, Pessoal/Folha, Obras, Precatórios, etc.) e o
NOME DO ÓRGÃO que pagou (UG Pagadora → nome). Para o OBJETO contratual exato (nº do contrato/empenho),
é preciso abrir o detalhe da OB no SIAFE (btnView → empenho/elemento de despesa) — fica como passo fino.
"""

# UGs financeiras/orçamentárias frequentes (best-effort; completar conforme aparecem).
UG_NOMES = {
    "999900": "Tesouro do Estado do RJ",
    "100100": "Governadoria / Casa Civil",
    "370300": "Encargos Gerais do Estado (Precatórios/SEFAZ)",
    "270005": "Fundo Especial do TJ (FUNETJ)",
    "270009": "Fundo Especial da PGE",
    "270016": "Fundo Especial do Corpo de Bombeiros (FUNESBOM)",
    "270020": "RIOPREVIDÊNCIA",
    "270024": "INEA",
    "270029": "Fundo Estadual de Saúde",
    "270042": "ITERJ",
    "270051": "Secretaria de Polícia Militar",
    "270060": "Casa Civil",
    "300100": "Tesouro Estadual",
    "010100": "ALERJ", "030100": "Tribunal de Justiça", "020100": "TCE-RJ",
    "090100": "PGE", "044100": "DER-RJ", "045200": "EMOP", "070200": "CEDAE",
}


def orgao_pagador(ug_pagadora, ug_emitente=""):
    ug = (ug_pagadora or ug_emitente or "").strip()
    return UG_NOMES.get(ug, f"UG {ug}" if ug else "—")


# regras de área/objeto por palavra-chave no Nome do Favorecido (ordem importa)
_REGRAS = [
    ("Pessoal / Folha", ["FOLHA DE PAGAMENTO", "FOLHA DE PESSOAL", "VENCIMENTOS", "SALARIO", "SUBSIDIO"]),
    ("Pessoal / Pensão e Benefícios", ["PENSAO", "PENSÃO", "APOSENTAD", "BENEFICIO", "AUXILIO", "AUXÍLIO"]),
    ("Judicial / Precatórios", ["PRECATORIO", "PRECATÓRIO", "RPV", "DEPOSITO JUDICIAL", "DEPÓSITO JUDICIAL"]),
    ("Transferência ao Tesouro / Financeira", ["TESOURO", "FUNDO ÚNICO", "FUNDO UNICO", "CONTA UNICA", "CONTA ÚNICA"]),
    ("Encargos / Dívida", ["ENCARGOS GERAIS", "DIVIDA", "DÍVIDA", "AMORTIZACAO", "AMORTIZAÇÃO", "JUROS"]),
    ("Saúde", ["HOSPITAL", "SAUDE", "SAÚDE", "FARMAC", "MEDICAMENT", "UPA", "SUS", "SANTA CASA", "INSTITUTO DE MEDICINA", "HEMORIO"]),
    ("Educação", ["EDUCA", "ESCOLA", "UNIVERSIDADE", "UERJ", "FAETEC", "COLEGIO", "COLÉGIO", "ENSINO"]),
    ("Segurança Pública", ["POLICIA", "POLÍCIA", "BOMBEIRO", "SEGURANCA PUBLICA", "SEGURANÇA PÚBLICA", "PENITENC", "SEAP"]),
    ("Obras / Infraestrutura", ["CONSTRU", "OBRAS", "ENGENHARIA", "PAVIMENT", "EMPREITEIRA", "INFRAESTRUTURA", "EDIFICA"]),
    ("Serviços (limpeza/conservação/vigilância)", ["LIMPEZA", "CONSERVA", "VIGILAN", "VIGILÂN", "MGS", "COMLURB", "TERCEIRIZA", "FACILITIES"]),
    ("Transporte / Mobilidade", ["TRANSPORTE", "MOBILIDADE", "RODOVIA", "BILHETE", "RIOCARD", "VLT", "METRO", "METRÔ", "BARCAS"]),
    ("Utilidades (energia/água/saneamento)", ["ENERGIA", "LIGHT", "ELETRIC", "ELÉTRIC", "ENEL", "CEDAE", "AGUA", "ÁGUA", "SANEAMENTO", "GAS", "GÁS", "NATURGY"]),
    ("Telecom / TI", ["TELECOM", "OI S", "CLARO", "VIVO", "TIM ", "TELEFONIC", "INTERNET", "DATACENTER", "SOFTWARE", "TECNOLOGIA DA INFORMACAO"]),
    ("Tributos / Retenção", ["IMPOSTO", "ICMS", "ISS", "INSS", "FGTS", "DARF", "RETENCAO", "RETENÇÃO", "RECEITA FEDERAL"]),
    ("Assistência / Social", ["ASSISTENCIA", "ASSISTÊNCIA", "SOCIAL", "CRAS", "CREAS", "BOLSA", "CARTAO SOCIAL"]),
    # padrões extraídos do Histórico das OBs (reduzem "Outros")
    ("Diárias / Viagens a serviço", ["DIARIA", "DIÁRIA", "DIARIAS", "DIÁRIAS", "VIAGEM A SERVICO", "AJUDA DE CUSTO", "DESLOCAMENTO"]),
    ("Alimentação", ["ALIMENTACAO", "ALIMENTAÇÃO", "REFEICAO", "REFEIÇÃO", "MERENDA", "CESTA BASICA", "CESTA BÁSICA"]),
    ("Locação", ["LOCACAO", "LOCAÇÃO", "ALUGUEL", "LOCATIVA", "ARRENDAMENTO"]),
    ("Manutenção", ["MANUTENCAO", "MANUTENÇÃO", "REPARO", "CONSERTO", "REVISAO", "REVISÃO"]),
    ("Locação de veículos / Frota", ["LOCACAO DE VEICULO", "FROTA", "VEICULOS", "VEÍCULOS", "COMBUSTIVEL", "COMBUSTÍVEL"]),
    ("Aluguel social / Habitação", ["ALUGUEL SOCIAL", "HABITACAO", "HABITAÇÃO", "MORADIA"]),
    ("Serviços gerais (PJ)", ["PRESTACAO DE SERVICO", "PRESTAÇÃO DE SERVIÇO", "PRESTACAO DE SERVICOS", "CONTRATACAO DE EMPRESA", "CONTRATAÇÃO DE EMPRESA"]),
]


def area_objeto(nome_fav, tipo_ob=""):
    n = (nome_fav or "").upper()
    for area, kws in _REGRAS:
        if any(k in n for k in kws):
            return area
    t = (tipo_ob or "").upper()
    if "RETEN" in t: return "Tributos / Retenção"
    if "TRANSFER" in t: return "Transferência financeira"
    if "DEDU" in t: return "Dedução"
    if "EXTRA" in t: return "Extra-orçamentária"
    return "Outros / a classificar"


def enriquecer(ob):
    """Adiciona orgao_pagador e area_objeto a um dict de OB (in place) e retorna-o."""
    ob["orgao_pagador"] = orgao_pagador(ob.get("ug_pagadora"), ob.get("ug_emitente") or ob.get("ug_codigo"))
    ob["area_objeto"] = area_objeto(ob.get("nome_favorecido") or ob.get("favorecido_nome"), ob.get("tipo_ob"))
    return ob
