"""
Base legal e moral da administração pública — fundamentação do auditor.

Núcleo CURADO e VERIFICADO das normas que regem gastos públicos, licitações,
contratos e combate à corrupção. Cada dispositivo traz lei, artigo, resumo
fiel do conteúdo e os temas/violações a que se aplica.

Por que curado (e não só baixado da internet):
  Para um auditor, citar artigo errado é inaceitável. A IA não pode "inventar"
  dispositivos. Esta base dá fundamentação confiável; o texto integral pode ser
  buscado no Planalto via base_legal_fetch.py quando se quiser ler na íntegra.

Camadas:
  PRINCIPIOS    — deveres morais/constitucionais (LIMPE + interesse público)
  DISPOSITIVOS  — artigos específicos de leis, mapeados a tipos de violação
  fundamentar() — dado um tema/alerta, devolve a fundamentação aplicável
"""

from dataclasses import dataclass, field


# ─── Camada MORAL: princípios constitucionais da Administração ────────────────

PRINCIPIOS = [
    {
        "sigla": "Legalidade",
        "base": "CF/88 art. 37, caput",
        "dever": "O agente público só pode fazer o que a lei autoriza. "
                 "Todo gasto precisa de respaldo legal expresso.",
        "violacao": "Pagamento sem amparo legal, despesa sem previsão.",
    },
    {
        "sigla": "Impessoalidade",
        "base": "CF/88 art. 37, caput",
        "dever": "A Administração deve tratar todos sem favorecimento. "
                 "Vedado direcionar contratos ou beneficiar pessoas específicas.",
        "violacao": "Direcionamento de licitação, favorecimento de empresa/pessoa.",
    },
    {
        "sigla": "Moralidade",
        "base": "CF/88 art. 37, caput",
        "dever": "Atuação conforme a honestidade, a boa-fé e a ética pública, "
                 "além da mera legalidade formal.",
        "violacao": "Conflito de interesse, nepotismo, uso da máquina para fim privado.",
    },
    {
        "sigla": "Publicidade",
        "base": "CF/88 art. 37, caput; Lei 12.527/11 (LAI)",
        "dever": "Atos públicos devem ser transparentes e acessíveis. "
                 "Contratos e pagamentos têm de ser publicados.",
        "violacao": "Sigilo indevido, ausência de publicação de contrato/aditivo.",
    },
    {
        "sigla": "Eficiência",
        "base": "CF/88 art. 37, caput (EC 19/98)",
        "dever": "Buscar o melhor resultado com o menor custo. Combate ao gasto "
                 "supérfluo e ao desperdício é dever, não opção.",
        "violacao": "Superfaturamento, gasto supérfluo, contratação antieconômica.",
    },
    {
        "sigla": "Economicidade",
        "base": "CF/88 art. 70",
        "dever": "O controle da Administração fiscaliza a economicidade — a relação "
                 "custo-benefício do gasto público.",
        "violacao": "Preço acima do mercado, despesa desnecessária.",
    },
    {
        "sigla": "Supremacia do interesse público",
        "base": "Princípio geral do Direito Administrativo",
        "dever": "O interesse coletivo prevalece sobre o privado. Recurso público "
                 "serve à população, nunca a interesses particulares.",
        "violacao": "Uso de verba pública para benefício privado/político.",
    },
]


# ─── Camada LEGAL: dispositivos específicos ───────────────────────────────────

@dataclass
class Dispositivo:
    lei: str               # ex: "Lei 14.133/2021"
    apelido: str           # ex: "Nova Lei de Licitações"
    artigo: str            # ex: "art. 75, II"
    resumo: str            # texto fiel do que o dispositivo determina
    temas: list[str]       # tags para retrieval
    tipo_violacao: str     # tipo de alerta a que se aplica


DISPOSITIVOS: list[Dispositivo] = [
    # ── Nova Lei de Licitações (14.133/2021) ──────────────────────────────────
    Dispositivo(
        "Lei 14.133/2021", "Nova Lei de Licitações", "art. 5º",
        "Princípios da licitação: legalidade, impessoalidade, moralidade, "
        "publicidade, eficiência, interesse público, probidade administrativa, "
        "segregação de funções, economicidade, entre outros.",
        ["principios", "licitacao", "moralidade", "probidade"],
        "geral",
    ),
    Dispositivo(
        "Lei 14.133/2021", "Nova Lei de Licitações", "art. 8º, §1º",
        "Veda o fracionamento de despesa: é proibido dividir a contratação para "
        "usar modalidade/dispensa menos rigorosa, fugindo da licitação devida.",
        ["fracionamento", "dispensa", "fuga_licitacao"],
        "fracionamento",
    ),
    Dispositivo(
        "Lei 14.133/2021", "Nova Lei de Licitações", "art. 9º",
        "Veda ao agente público frustrar o caráter competitivo, direcionar ou "
        "estabelecer preferências indevidas no certame.",
        ["direcionamento", "competitividade", "favorecimento"],
        "direcionamento",
    ),
    Dispositivo(
        "Lei 14.133/2021", "Nova Lei de Licitações", "art. 75, I",
        "Dispensa de licitação para obras e serviços de engenharia de valor até "
        "o limite legal atualizado (≈ R$ 119.812,02). Acima disso exige licitação.",
        ["dispensa", "limite", "obras", "engenharia", "fracionamento"],
        "fracionamento",
    ),
    Dispositivo(
        "Lei 14.133/2021", "Nova Lei de Licitações", "art. 75, II",
        "Dispensa de licitação para compras e serviços comuns de valor até o "
        "limite legal atualizado (≈ R$ 59.906,02). Somatório ao mesmo fornecedor "
        "acima do limite caracteriza fracionamento ilegal.",
        ["dispensa", "limite", "compras", "fracionamento"],
        "fracionamento",
    ),
    Dispositivo(
        "Lei 14.133/2021", "Nova Lei de Licitações", "art. 75, VIII",
        "Dispensa por emergência ou calamidade: hipótese TAXATIVA. Emergência "
        "fabricada ou repetida para a mesma empresa é irregular.",
        ["emergencia", "dispensa", "calamidade"],
        "contrato_emergencial",
    ),
    Dispositivo(
        "Lei 14.133/2021", "Nova Lei de Licitações", "art. 74",
        "Inexigibilidade de licitação: hipóteses taxativas (fornecedor exclusivo, "
        "notória especialização). Uso indevido para fugir do certame é ilegal.",
        ["inexigibilidade", "exclusividade", "direcionamento"],
        "inexigibilidade",
    ),
    Dispositivo(
        "Lei 14.133/2021", "Nova Lei de Licitações", "art. 94",
        "Exige a divulgação do contrato no Portal Nacional de Contratações "
        "Públicas (PNCP) como condição de eficácia. Sem publicação, não há eficácia.",
        ["pncp", "publicidade", "contrato", "transparencia"],
        "sem_pncp",
    ),
    Dispositivo(
        "Lei 14.133/2021", "Nova Lei de Licitações", "art. 156",
        "Sanções a contratados: advertência, multa, impedimento de licitar e "
        "declaração de inidoneidade. Empresa sancionada não pode ser contratada.",
        ["sancao", "inidoneidade", "ceis", "impedimento"],
        "empresa_sancionada",
    ),
    Dispositivo(
        "Lei 14.133/2021", "Nova Lei de Licitações", "art. 337-F (CP, incluído)",
        "Tipifica a fraude à licitação e o sobrepreço/superfaturamento como crime, "
        "com pena de reclusão.",
        ["superfaturamento", "sobrepreco", "fraude", "crime"],
        "superfaturamento",
    ),

    # ── Lei 8.666/93 (ainda aplicável a contratos antigos) ────────────────────
    Dispositivo(
        "Lei 8.666/1993", "Lei de Licitações (antiga)", "art. 23, §5º",
        "Veda o fracionamento: proibido dividir compras/obras para usar modalidade "
        "inferior à exigida pelo valor total. Aplica-se a contratos ainda vigentes.",
        ["fracionamento", "modalidade"],
        "fracionamento",
    ),
    Dispositivo(
        "Lei 8.666/1993", "Lei de Licitações (antiga)", "art. 25",
        "Inexigibilidade por inviabilidade de competição. Inexigibilidade indevida "
        "(sem real exclusividade) é desvio.",
        ["inexigibilidade", "exclusividade"],
        "inexigibilidade",
    ),
    Dispositivo(
        "Lei 8.666/1993", "Lei de Licitações (antiga)", "art. 87",
        "Sanções administrativas: advertência, multa, suspensão e declaração de "
        "inidoneidade para licitar e contratar com a Administração.",
        ["sancao", "inidoneidade", "ceis"],
        "empresa_sancionada",
    ),
    Dispositivo(
        "Lei 8.666/1993", "Lei de Licitações (antiga)", "art. 90",
        "Crime: frustrar ou fraudar o caráter competitivo da licitação mediante "
        "ajuste, combinação (cartel) ou qualquer expediente.",
        ["cartel", "conluio", "fraude", "crime", "competitividade"],
        "cartel",
    ),

    # ── Lei de Improbidade Administrativa (8.429/92) ──────────────────────────
    Dispositivo(
        "Lei 8.429/1992", "Lei de Improbidade Administrativa", "art. 9º",
        "Improbidade por enriquecimento ilícito: auferir vantagem patrimonial "
        "indevida em razão do cargo (propina, comissão, uso de bens públicos).",
        ["enriquecimento", "propina", "vantagem", "improbidade"],
        "enriquecimento_ilicito",
    ),
    Dispositivo(
        "Lei 8.429/1992", "Lei de Improbidade Administrativa", "art. 10",
        "Improbidade por dano ao erário: ação ou omissão que cause perda "
        "patrimonial — inclui dispensa indevida de licitação, superfaturamento "
        "e favorecimento de terceiros (art. 10, VIII).",
        ["dano_erario", "superfaturamento", "dispensa_indevida", "fracionamento"],
        "dano_erario",
    ),
    Dispositivo(
        "Lei 8.429/1992", "Lei de Improbidade Administrativa", "art. 11",
        "Improbidade por violação de princípios: atos que atentam contra os "
        "deveres de honestidade, legalidade e impessoalidade (exige dolo).",
        ["principios", "moralidade", "legalidade", "improbidade"],
        "violacao_principios",
    ),

    # ── Lei Anticorrupção (12.846/13) ─────────────────────────────────────────
    Dispositivo(
        "Lei 12.846/2013", "Lei Anticorrupção", "art. 5º",
        "Responsabiliza a EMPRESA (objetivamente) por atos lesivos: prometer/dar "
        "vantagem a agente público, fraudar licitação, dificultar fiscalização.",
        ["empresa", "propina", "fraude_licitacao", "anticorrupcao"],
        "ato_lesivo_empresa",
    ),
    Dispositivo(
        "Lei 12.846/2013", "Lei Anticorrupção", "art. 6º",
        "Sanções à empresa: multa de até 20% do faturamento e publicação "
        "extraordinária da decisão condenatória.",
        ["sancao", "multa", "empresa"],
        "ato_lesivo_empresa",
    ),

    # ── Lei de Responsabilidade Fiscal (LC 101/00) ────────────────────────────
    Dispositivo(
        "LC 101/2000", "Lei de Responsabilidade Fiscal", "art. 16 e 17",
        "Exige estimativa de impacto e adequação orçamentária para criação de "
        "despesa. Despesa sem prévia previsão/comprovação é irregular.",
        ["despesa", "orcamento", "previsao", "lrf"],
        "despesa_sem_previsao",
    ),
    Dispositivo(
        "LC 101/2000", "Lei de Responsabilidade Fiscal", "art. 42",
        "Veda assumir obrigação de despesa nos últimos 2 quadrimestres do mandato "
        "sem disponibilidade de caixa — combate à 'herança' de dívidas.",
        ["fim_mandato", "despesa", "caixa", "rajada"],
        "rajada_fim_periodo",
    ),

    # ── Transparência / nepotismo / pregão ────────────────────────────────────
    Dispositivo(
        "Lei 12.527/2011", "Lei de Acesso à Informação (LAI)", "art. 3º e 8º",
        "Transparência é a regra, sigilo a exceção. Órgãos devem divulgar "
        "ativamente despesas, contratos e repasses.",
        ["transparencia", "publicidade", "lai"],
        "falta_transparencia",
    ),
    Dispositivo(
        "STF", "Súmula Vinculante 13", "SV 13",
        "Veda o nepotismo: proíbe nomear cônjuge, companheiro ou parente até o "
        "3º grau de autoridade nomeante para cargo em comissão/função de confiança.",
        ["nepotismo", "parente", "nomeacao", "moralidade"],
        "nepotismo",
    ),
    Dispositivo(
        "Decreto 10.024/2019", "Pregão Eletrônico", "art. 1º e ss.",
        "Torna o pregão eletrônico obrigatório para bens e serviços comuns no "
        "âmbito federal; é referência de boa prática para estados.",
        ["pregao", "eletronico", "licitacao"],
        "modalidade_inadequada",
    ),
]


# ─── Índices para busca rápida ────────────────────────────────────────────────

_POR_VIOLACAO: dict[str, list[Dispositivo]] = {}
for _d in DISPOSITIVOS:
    _POR_VIOLACAO.setdefault(_d.tipo_violacao, []).append(_d)

# Mapeia tipos de alerta do sistema -> tipo_violacao da base legal
_ALIAS_ALERTA = {
    "fracionamento": "fracionamento",
    "concentracao": "fracionamento",
    "valor_suspeito": "superfaturamento",
    "superfaturamento": "superfaturamento",
    "sem_processo": "violacao_principios",
    "nepotismo": "nepotismo",
    "nomeacao_suspeita": "nepotismo",
    "empresa_sancionada": "empresa_sancionada",
    "historico_sancao_doerj": "empresa_sancionada",
    "sem_pncp": "sem_pncp",
    "investigacao_web": "violacao_principios",
    "investigacao_autonoma": "violacao_principios",
    "contrato_emergencial": "contrato_emergencial",
    "inexigibilidade": "inexigibilidade",
    "cartel": "cartel",
    "rajada_fim_mes": "rajada_fim_periodo",
    "outlier": "superfaturamento",
}


# ─── Retrieval: fundamentação aplicável ───────────────────────────────────────

def fundamentar_por_tipo(tipo_alerta: str) -> list[Dispositivo]:
    """Dado o tipo de alerta do sistema, retorna os dispositivos aplicáveis."""
    chave = _ALIAS_ALERTA.get(tipo_alerta, tipo_alerta)
    return _POR_VIOLACAO.get(chave, [])


def fundamentar_por_texto(texto: str, max_itens: int = 4) -> list[Dispositivo]:
    """Busca dispositivos relevantes por palavras-chave no texto livre."""
    texto_l = (texto or "").lower()
    pontuados = []
    for d in DISPOSITIVOS:
        score = sum(1 for tema in d.temas if tema.replace("_", " ") in texto_l or tema in texto_l)
        # também casa pelo apelido/lei citada no texto
        if d.artigo.lower() in texto_l or d.lei.lower() in texto_l:
            score += 2
        if score:
            pontuados.append((score, d))
    pontuados.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in pontuados[:max_itens]]


def citar(d: Dispositivo) -> str:
    """Formata um dispositivo como citação curta."""
    return f"{d.lei}, {d.artigo} ({d.apelido})"


def fundamentacao_texto(tipo_alerta: str = "", texto: str = "") -> str:
    """
    Retorna um bloco de fundamentação legal pronto para anexar a um alerta
    ou injetar num prompt de IA.
    """
    disp = []
    if tipo_alerta:
        disp = fundamentar_por_tipo(tipo_alerta)
    if not disp and texto:
        disp = fundamentar_por_texto(texto)
    if not disp:
        return ""
    linhas = ["Fundamentação legal aplicável:"]
    for d in disp:
        linhas.append(f"• {citar(d)}: {d.resumo}")
    return "\n".join(linhas)


def contexto_legal_para_prompt(max_principios: int = 7, max_disp: int = 12) -> str:
    """
    Monta um bloco com princípios + principais dispositivos, para dar ao LLM
    o arcabouço moral e legal ao analisar gastos. Injeta nos prompts da IA.
    """
    linhas = ["ARCABOUÇO MORAL E LEGAL DA ADMINISTRAÇÃO PÚBLICA (use para fundamentar):"]
    linhas.append("\nPrincípios (CF/88 art. 37 — LIMPE + economicidade):")
    for p in PRINCIPIOS[:max_principios]:
        linhas.append(f"• {p['sigla']} ({p['base']}): {p['dever']}")
    linhas.append("\nDispositivos-chave:")
    for d in DISPOSITIVOS[:max_disp]:
        linhas.append(f"• {citar(d)}: {d.resumo}")
    return "\n".join(linhas)


def buscar_lei(termo: str) -> list[Dispositivo]:
    """Busca livre na base legal por lei, artigo, apelido ou tema (para /lei)."""
    t = (termo or "").lower().strip()
    if not t:
        return []
    out = []
    for d in DISPOSITIVOS:
        campos = (d.lei + " " + d.apelido + " " + d.artigo + " "
                  + d.resumo + " " + " ".join(d.temas)).lower()
        if t in campos:
            out.append(d)
    return out
