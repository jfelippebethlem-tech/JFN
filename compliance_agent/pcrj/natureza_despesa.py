"""Dicionário oficial da NATUREZA DA DESPESA — Portaria Interministerial STN/SOF nº 163/2001.

POR QUE ISTO EXISTE
-------------------
As lentes municipais liam a natureza por posição (`substr(natureza,5,2)`) e traduziam os códigos
**pelos credores que apareciam neles** — eu sabia que `30.04` era confecção porque os fornecedores
eram indústrias de malha, não porque tivesse a tabela. Isso é inferência, e inferência sobre
código de despesa vira erro de leitura em relatório de controle externo.

Este módulo traz a tabela **da fonte**: os 77 elementos do Anexo II da Portaria 163/2001,
extraídos do PDF oficial, mais as modalidades de aplicação e os grupos de natureza.

⚠️ A TABELA TEM VERSÃO. A Portaria 163 é de 2001 e recebe alterações periódicas; o PDF que serviu
de base é a consolidação de **2014**. Elementos criados depois (40, 82, 85) estão em
`ELEMENTOS_POSTERIORES`, cada um com a norma que o criou. Ao reextrair, **rodar o controle
positivo**: varrer os códigos que o acervo usa e conferir se algum falta na tabela. Foi assim que
a lacuna apareceu — R$ 6,51 bilhões classificados em elementos desconhecidos, sendo R$ 5,52 bi só
no 85 (Contrato de Gestão), que é o dinheiro das organizações sociais.

A ESTRUTURA DO CÓDIGO
---------------------
`C G MM EE (SS)` — categoria econômica, grupo de natureza, modalidade de aplicação, elemento e,
opcionalmente, subelemento (desdobramento facultativo).

    3 3 90 39 11
    │ │ │  │  └─ subelemento 11 — DESDOBRAMENTO DE LIVRE DEFINIÇÃO DO ENTE
    │ │ │  └──── elemento 39 — Outros Serviços de Terceiros - Pessoa Jurídica
    │ │ └─────── modalidade 90 — Aplicações Diretas
    │ └───────── grupo 3 — Outras Despesas Correntes
    └─────────── categoria 3 — Despesa Corrente

⚠️ **O SUBELEMENTO NÃO É PADRONIZADO.** A Portaria 163 fixa até o elemento; o desdobramento em
subelemento é facultativo e cada ente define o seu. Por isso `subelemento()` devolve `None` com
motivo, e nunca um palpite: dizer que `30.04` é "vestuário" no Município do Rio é leitura pelos
credores, não pela norma, e o módulo se recusa a fingir o contrário.
"""
from __future__ import annotations

# Anexo II da Portaria Interministerial STN/SOF nº 163/2001 — extraído do PDF oficial em
# 31/08/2026. Não editar de memória: reextrair da fonte.
#
# ⚠️ ARMADILHA DA EXTRAÇÃO, registrada porque quase entrou aqui: a Portaria traz DUAS listas de
# códigos de dois dígitos — modalidades de aplicação e elementos —, e vários números aparecem nas
# duas com significados distintos. Varrer o documento inteiro por "NN - Nome" faz a lista de
# modalidades vazar para a de elementos: o extrator ingênuo produziu "40: Transferências a
# Municípios", "50: Transferências a Instituições Privadas", "60" e "90" como se fossem
# elementos. **Os elementos 40, 50, 60 e 90 NÃO EXISTEM** — a lista salta de 39 (Serviços de
# Terceiros PJ) direto para 41 (Contribuições). O conserto é fatiar o BLOCO da lista de elementos
# antes de casar o padrão, e o teste `test_elementos_inexistentes_nao_foram_inventados` trava isso.
ELEMENTOS: dict[str, str] = {
    "01": "Aposentadorias, Reserva Remunerada e Reformas",
    "03": "Pensões",
    "04": "Contratação por Tempo Determinado",
    "05": "Outros Benefícios Previdenciários",
    "06": "Benefício Mensal ao Deficiente e ao Idoso",
    "07": "Contribuição a Entidades Fechadas de Previdência",
    "08": "Outros Benefícios Assistenciais",
    "09": "Salário-Família",
    "10": "Outros Benefícios de Natureza Social",
    "11": "Vencimentos e Vantagens Fixas - Pessoal Civil",
    "12": "Vencimentos e Vantagens Fixas - Pessoal Militar",
    "13": "Obrigações Patronais",
    "14": "Diárias - Civil",
    "15": "Diárias - Militar",
    "16": "Outras Despesas Variáveis - Pessoal Civil",
    "17": "Outras Despesas Variáveis - Pessoal Militar",
    "18": "Auxílio Financeiro a Estudantes",
    "19": "Auxílio-Fardamento",
    "20": "Auxílio Financeiro a Pesquisadores",
    "21": "Juros sobre a Dívida por Contrato",
    "22": "Outros Encargos sobre a Dívida por Contrato",
    "23": "Juros, Deságios e Descontos da Dívida Mobiliária",
    "24": "Outros Encargos sobre a Dívida Mobiliária",
    "25": "Encargos sobre Operações de Crédito por Antecipação da Receita",
    "26": "Obrigações decorrentes de Política Monetária",
    "27": "Encargos pela Honra de Avais, Garantias, Seguros e Similares",
    "28": "Remuneração de Cotas de Fundos Autárquicos",
    "29": "Distribuição de Resultado de Empresas Estatais Dependentes",
    "30": "Material de Consumo",
    "31": "Premiações Culturais, Artísticas, Científicas, Desportivas e Outras",
    "32": "Material, Bem ou Serviço para Distribuição Gratuita",
    "33": "Passagens e Despesas com Locomoção",
    "34": "Outras Despesas de Pessoal decorrentes de Contratos de Terceirização",
    "35": "Serviços de Consultoria",
    "36": "Outros Serviços de Terceiros - Pessoa Física",
    "37": "Locação de Mão-de-Obra",
    "38": "Arrendamento Mercantil",
    "39": "Outros Serviços de Terceiros - Pessoa Jurídica",
    "41": "Contribuições",
    "42": "Auxílios",
    "43": "Subvenções Sociais",
    "45": "Subvenções Econômicas",
    "46": "Auxílio-Alimentação",
    "47": "Obrigações Tributárias e Contributivas",
    "48": "Outros Auxílios Financeiros a Pessoas Físicas",
    "49": "Auxílio-Transporte",
    "51": "Obras e Instalações",
    "52": "Equipamentos e Material Permanente",
    "61": "Aquisição de Imóveis",
    "63": "Aquisição de Títulos de Crédito",
    "64": "Aquisição de Títulos Representativos de Capital já Integralizado",
    "65": "Constituição ou Aumento de Capital de Empresas",
    "66": "Concessão de Empréstimos e Financiamentos",
    "67": "Depósitos Compulsórios",
    "70": "Rateio pela Participação em Consórcio Público",
    "71": "Principal da Dívida Contratual Resgatado",
    "72": "Principal da Dívida Mobiliária Resgatado",
    "73": "Correção Monetária ou Cambial da Dívida Contratual Resgatada",
    "74": "Correção Monetária ou Cambial da Dívida Mobiliária Resgatada",
    "75": "Correção Monetária da Dívida de Operações de Crédito por Antecipação da Receita",
    "76": "Principal Corrigido da Dívida Mobiliária Refinanciado",
    "77": "Principal Corrigido da Dívida Contratual Refinanciado",
    "81": "Distribuição Constitucional ou Legal de Receitas",
    "91": "Sentenças Judiciais",
    "92": "Despesas de Exercícios Anteriores",
    "93": "Indenizações e Restituições",
    "94": "Indenizações e Restituições Trabalhistas",
    "95": "Indenização pela Execução de Trabalhos de Campo",
    "96": "Ressarcimento de Despesas de Pessoal Requisitado",
    "97": "Aporte para Cobertura do Déficit Atuarial do RPPS",
    "99": "A Classificar",
}

# ELEMENTOS CRIADOS DEPOIS da versão do PDF que serviu de base (consolidação de 2014). Sem eles,
# a tabela reprovava como "inexistente" código que o Município USA — e foi o próprio acervo que
# denunciou a falta, num controle positivo: R$ 6.514.285.739,62 estavam classificados em
# elementos que a tabela não conhecia.
#
# Cada um com a norma que o criou, conferida na fonte:
ELEMENTOS_POSTERIORES: dict[str, tuple[str, str]] = {
    "40": ("Serviços de Tecnologia da Informação e Comunicação - Pessoa Jurídica",
           "Portaria Conjunta STN/SOF nº 02, de 30/10/2017 — desmembrou itens do elemento 39"),
    "82": ("Aporte de Recursos pelo Parceiro Público em Favor do Parceiro Privado decorrente de "
           "Contrato de Parceria Público-Privada (PPP)",
           "Lei nº 11.079/2004; elemento incluído por alteração da Portaria 163"),
    "85": ("Contrato de Gestão",
           "Portaria SO nº 7, de 18/08/2021 — transferências a organizações sociais e outras "
           "entidades privadas sem fins lucrativos para execução de serviços em contrato de gestão"),
}
ELEMENTOS.update({c: nome for c, (nome, _) in ELEMENTOS_POSTERIORES.items()})

# Códigos que o Município usa e que NÃO foram identificados em norma. Ficam declarados como
# desconhecidos — melhor um buraco nomeado que um rótulo inventado.
ELEMENTOS_NAO_IDENTIFICADOS: dict[str, str] = {
    "59": "usado pelo Município do Rio (5 linhas, R$ 16.322,82) — norma de origem não localizada",
}

MODALIDADES: dict[str, str] = {
    "20": "Transferências à União",
    "22": "Execução Orçamentária Delegada à União",
    "30": "Transferências a Estados e ao Distrito Federal",
    "31": "Transferências a Estados e ao DF - Fundo a Fundo",
    "32": "Execução Orçamentária Delegada a Estados e ao DF",
    "40": "Transferências a Municípios",
    "41": "Transferências a Municípios - Fundo a Fundo",
    "42": "Execução Orçamentária Delegada a Municípios",
    "50": "Transferências a Instituições Privadas sem Fins Lucrativos",
    "60": "Transferências a Instituições Privadas com Fins Lucrativos",
    "70": "Transferências a Instituições Multigovernamentais",
    "71": "Transferências a Consórcios Públicos",
    "72": "Execução Orçamentária Delegada a Consórcios Públicos",
    "80": "Transferências ao Exterior",
    "90": "Aplicações Diretas",
    "91": "Aplicação Direta Decorrente de Operação entre Órgãos, Fundos e Entidades",
    "99": "A Definir",
}

GRUPOS: dict[str, str] = {
    "1": "Pessoal e Encargos Sociais",
    "2": "Juros e Encargos da Dívida",
    "3": "Outras Despesas Correntes",
    "4": "Investimentos",
    "5": "Inversões Financeiras",
    "6": "Amortização da Dívida",
}

CATEGORIAS: dict[str, str] = {"3": "Despesa Corrente", "4": "Despesa de Capital"}


def _pos(natureza: str, ini: int, tam: int) -> str | None:
    s = "".join(ch for ch in str(natureza or "") if ch.isdigit())
    trecho = s[ini:ini + tam]
    return trecho if len(trecho) == tam else None


def categoria(natureza: str) -> str | None:
    return CATEGORIAS.get(_pos(natureza, 0, 1) or "")


def grupo(natureza: str) -> str | None:
    return GRUPOS.get(_pos(natureza, 1, 1) or "")


def modalidade(natureza: str) -> str | None:
    return MODALIDADES.get(_pos(natureza, 2, 2) or "")


def elemento(natureza: str) -> str | None:
    """Nome oficial do elemento. `None` = código fora da tabela — INDISPONÍVEL, não 'outros'."""
    return ELEMENTOS.get(_pos(natureza, 4, 2) or "")


def subelemento(natureza: str) -> None:
    """Sempre `None`, de propósito.

    O subelemento é desdobramento FACULTATIVO e de livre definição de cada ente (Portaria 163,
    que padroniza só até o elemento). Não existe tabela nacional para traduzi-lo, e o Município
    do Rio não publicou a sua em fonte que esteja em casa. Devolver um palpite aqui — "30.04 é
    vestuário porque os credores são confecções" — transformaria inferência em fato dentro de um
    relatório. Quem precisar do rótulo tem de buscar o dicionário do ente."""
    return None


def descrever(natureza: str) -> dict:
    """Decompõe a natureza inteira. Campo desconhecido vem `None`, jamais preenchido por chute."""
    return {
        "natureza": str(natureza or ""),
        "categoria": categoria(natureza),
        "grupo": grupo(natureza),
        "modalidade": modalidade(natureza),
        "elemento": elemento(natureza),
        "codigo_elemento": _pos(natureza, 4, 2),
        "codigo_subelemento": _pos(natureza, 6, 2),
        "subelemento": subelemento(natureza),
        "_nota_subelemento": "desdobramento de livre definição do ente — sem tabela nacional",
    }


# Elementos que NÃO são contraprestação de contrato — usados por `pcrj.universo` para desenhar o
# universo contratual. A razão de cada um está por extenso lá.
ELEMENTOS_NAO_CONTRATUAIS: dict[str, str] = {
    "01": "aposentadoria — pessoal", "03": "pensão — pessoal",
    "05": "benefício previdenciário", "06": "benefício ao deficiente e ao idoso",
    "07": "contribuição a entidade de previdência", "08": "benefício assistencial",
    "09": "salário-família", "10": "benefício de natureza social",
    "18": "auxílio a estudante", "19": "auxílio-fardamento", "20": "auxílio a pesquisador",
    "41": "contribuição — transferência corrente, não contraprestação",
    "42": "auxílio — transferência, não contraprestação",
    "43": "subvenção social", "45": "subvenção econômica",
    "46": "auxílio-alimentação — benefício de pessoal",
    "47": "obrigação tributária e contributiva — tributo, não compra",
    "48": "auxílio financeiro a pessoa física", "49": "auxílio-transporte",
    "81": "distribuição constitucional ou legal de receitas",
    "91": "sentença judicial — nasce de condenação, não de contrato",
    "93": "indenização e restituição — reparação, não aquisição",
    "94": "indenização e restituição trabalhista",
    "95": "indenização pela execução de trabalhos de campo",
    "96": "ressarcimento de pessoal requisitado",
    "97": "aporte para déficit atuarial do RPPS",
}
