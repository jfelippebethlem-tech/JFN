# -*- coding: utf-8 -*-
"""Da irregularidade ao TIPO: o que ainda falta provar para cada regime de responsabilização.

POR QUE ESTE MÓDULO EXISTE. O JFN aponta vício — cláusula restritiva, fracionamento, aditivo
acima do teto — e para aí. Quem lê o dossiê precisa da pergunta seguinte, que é a que decide a
peça: *isto configura improbidade? crime? responsabilidade da empresa? ou é irregularidade
administrativa que se resolve com determinação?* Sem essa ponte, o produto ou subestima (trata
desvio como formalidade) ou, muito pior, superestima — e chamar de "improbidade" um achado
formal é o erro que derruba a peça inteira e queima o mandato.

O QUE MUDOU EM 2021, E QUE O SISTEMA IGNORAVA. A Lei 14.230/2021 reescreveu a Lei 8.429 e tornou
a improbidade MUITO mais difícil de configurar:

  · art. 1º §1º — só há improbidade em conduta DOLOSA; a modalidade culposa foi extinta;
  · art. 1º §2º — "dolo é a vontade livre e consciente de alcançar o resultado ilícito ...,
    NÃO BASTANDO A VOLUNTARIEDADE do agente" (dolo específico);
  · art. 1º §3º — "o mero exercício da função ..., sem comprovação de ato doloso com fim
    ilícito, AFASTA a responsabilidade";
  · art. 10 caput — a lesão ao erário passou a exigir perda patrimonial "EFETIVA E
    COMPROVADAMENTE" demonstrada;
  · art. 10, VIII — frustrar a licitude ou dispensá-la indevidamente só é improbidade
    "ACARRETANDO PERDA PATRIMONIAL EFETIVA";
  · art. 11, V — frustrar o caráter concorrencial exige ser "em ofensa à imparcialidade" e
    "COM VISTAS À OBTENÇÃO DE BENEFÍCIO próprio, direto ou indireto, ou de terceiros";
  · art. 17-C, I — a sentença deve demonstrar os elementos, "QUE NÃO PODEM SER PRESUMIDOS";
    os incisos II e III trazem para dentro da lei o consequencialismo e os obstáculos reais do
    gestor (LINDB arts. 20 a 22).

CONSEQUÊNCIA PRÁTICA, e é ela que este módulo implementa: **cláusula restritiva sem dano
comprovado e sem beneficiário identificado NÃO é improbidade** sob a lei vigente. Continua sendo
irregularidade administrativa (representação ao Tribunal de Contas), e pode ser ilícito da
PESSOA JURÍDICA pela Lei 12.846 — que dispensa dolo do agente público. Escolher o regime certo é
o que separa uma peça que prospera de uma que morre na inicial.

O PRODUTO ÚTIL. `o_que_falta()` devolve o checklist de lacunas probatórias: é ele que vira pedido
de diligência, requisição de informação ou requerimento de CPI. Dizer "não consigo provar X" com
precisão vale mais, para um mandato, do que afirmar o que não se sustenta.

HONESTIDADE. Este módulo NÃO tipifica: ele qualifica hipóteses e lista o que falta. A tipificação
é do Ministério Público, do Tribunal de Contas e do Judiciário — nunca do JFN.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ─────────────────────────── regimes de responsabilização ─────────────────────────────────────


@dataclass(frozen=True)
class Regime:
    """Um regime sancionador e o que ele exige para incidir."""

    id: str
    nome: str
    dispositivo: str
    elemento_subjetivo: str          # "dolo_especifico" | "dolo_ou_culpa" | "objetiva" | "nenhum"
    sujeito: str                     # "agente_publico" | "pessoa_juridica" | "ambos"
    standard: str                    # ver knowledge/standard_prova
    elementos: tuple[str, ...] = ()  # o que PRECISA estar provado
    verbatim: str = ""               # texto legal, quando é ele que carrega a exigência
    orgao_competente: str = ""


REGIMES: dict[str, Regime] = {
    "improbidade_dano": Regime(
        id="improbidade_dano",
        nome="Improbidade — lesão ao erário",
        dispositivo="Lei 8.429/1992, art. 10 (redação da Lei 14.230/2021)",
        elemento_subjetivo="dolo_especifico",
        sujeito="agente_publico",
        standard="clara_e_convincente",
        elementos=(
            "conduta descrita em um dos incisos do art. 10",
            "perda patrimonial EFETIVA e COMPROVADA (não presumida)",
            "nexo entre a conduta e a perda",
            "dolo específico: vontade livre e consciente de alcançar o resultado ilícito",
        ),
        verbatim=("Art. 10. Constitui ato de improbidade administrativa que causa lesão ao "
                  "erário qualquer ação ou omissão dolosa, que enseje, efetiva e "
                  "comprovadamente, perda patrimonial, desvio, apropriação, malbaratamento ou "
                  "dilapidação dos bens ou haveres das entidades referidas no art. 1º desta Lei"),
        orgao_competente="Ministério Público / Judiciário",
    ),
    "improbidade_principios": Regime(
        id="improbidade_principios",
        nome="Improbidade — violação de princípios (rol TAXATIVO)",
        dispositivo="Lei 8.429/1992, art. 11 (redação da Lei 14.230/2021)",
        elemento_subjetivo="dolo_especifico",
        sujeito="agente_publico",
        standard="clara_e_convincente",
        elementos=(
            "conduta que se enquadre em UM dos incisos vigentes do art. 11 (rol taxativo)",
            "ofensa à imparcialidade",
            "finalidade específica de obter benefício próprio, direto ou indireto, ou de terceiro",
            "dolo específico (art. 1º §2º)",
        ),
        verbatim=("Art. 11, V - frustrar, em ofensa à imparcialidade, o caráter concorrencial "
                  "de concurso público, de chamamento ou de procedimento licitatório, com "
                  "vistas à obtenção de benefício próprio, direto ou indireto, ou de terceiros"),
        orgao_competente="Ministério Público / Judiciário",
    ),
    "improbidade_enriquecimento": Regime(
        id="improbidade_enriquecimento",
        nome="Improbidade — enriquecimento ilícito",
        dispositivo="Lei 8.429/1992, art. 9º",
        elemento_subjetivo="dolo_especifico",
        sujeito="agente_publico",
        standard="clara_e_convincente",
        elementos=(
            "auferimento de vantagem patrimonial indevida pelo agente",
            "vínculo entre a vantagem e o exercício da função",
            "dolo específico",
        ),
        orgao_competente="Ministério Público / Judiciário",
    ),
    "crime_licitatorio": Regime(
        id="crime_licitatorio",
        nome="Crimes em licitações e contratos (incorporados ao Código Penal)",
        dispositivo="Lei 14.133/2021, arts. 178 e ss.; CP arts. 337-E a 337-P",
        elemento_subjetivo="dolo_especifico",
        sujeito="ambos",
        standard="alem_de_duvida_razoavel",
        elementos=(
            "tipo penal específico (frustração do caráter competitivo, contratação direta "
            "ilegal, fraude, patrocínio de contratação indevida)",
            "dolo",
            "materialidade e autoria",
        ),
        orgao_competente="Ministério Público (esfera penal)",
    ),
    "anticorrupcao_pj": Regime(
        id="anticorrupcao_pj",
        nome="Responsabilização da PESSOA JURÍDICA (Lei Anticorrupção)",
        dispositivo="Lei 12.846/2013, arts. 5º e 6º",
        elemento_subjetivo="objetiva",
        sujeito="pessoa_juridica",
        standard="preponderancia",
        elementos=(
            "ato lesivo do art. 5º praticado no interesse ou benefício da empresa",
            "prova do ato — NÃO se exige dolo nem culpa da empresa (responsabilidade objetiva)",
        ),
        verbatim=("Art. 5º Constituem atos lesivos à administração pública ... IV - no tocante "
                  "a licitações e contratos: a) frustrar ou fraudar, mediante ajuste, combinação "
                  "ou qualquer outro expediente, o caráter competitivo de procedimento "
                  "licitatório público"),
        orgao_competente="CGU/Controladoria estadual; Advocacia Pública; Judiciário",
    ),
    "controle_externo": Regime(
        id="controle_externo",
        nome="Irregularidade administrativa — controle externo",
        dispositivo="CF/88 arts. 70 e 71; Lei Orgânica do TCE-RJ",
        elemento_subjetivo="nenhum",
        sujeito="agente_publico",
        standard="indicio_qualificado",
        elementos=(
            "violação de norma de licitação/contrato demonstrada nos autos",
        ),
        orgao_competente="Tribunal de Contas",
    ),
    "ressarcimento": Regime(
        id="ressarcimento",
        nome="Ressarcimento ao erário",
        dispositivo="CF/88 art. 37 §5º; Lei 8.429/1992 art. 21 §5º",
        elemento_subjetivo="nenhum",
        sujeito="ambos",
        standard="preponderancia",
        elementos=(
            "dano quantificado com memória de cálculo",
            "nexo com a conduta",
        ),
        orgao_competente="Tribunal de Contas / Advocacia Pública",
    ),
    "lrf": Regime(
        id="lrf",
        nome="Responsabilidade fiscal",
        dispositivo="LC 101/2000, arts. 15 a 17 e 42",
        elemento_subjetivo="nenhum",
        sujeito="agente_publico",
        standard="indicio_qualificado",
        elementos=(
            "despesa criada/aumentada sem estimativa de impacto ou sem compensação",
        ),
        orgao_competente="Tribunal de Contas",
    ),
}

# Provas que costumam sustentar cada elemento — o vocabulário de `o_que_falta`.
PROVAS = {
    "dano": "dano quantificado (comparação com referência de preço + medição/OB, com memória "
            "de cálculo)",
    "beneficiario": "beneficiário identificado (vencedor + vínculo societário, endereço, "
                    "contador, doação eleitoral ou parentesco)",
    "dolo": "elemento de intenção (documento que revele a finalidade, sequência temporal "
            "improvável, contato prévio, reiteração após alerta do controle)",
    "conduta": "conduta descrita e datada, com o documento que a comprova",
    "nexo": "encadeamento entre o ato e o resultado (linha do tempo dos atos e pagamentos)",
    "vantagem": "vantagem patrimonial recebida pelo agente (patrimônio incompatível, "
                "movimentação, bem em nome de terceiro)",
    "ato_lesivo": "ato lesivo do art. 5º da Lei 12.846 praticado no interesse da empresa",
    "norma": "dispositivo violado, com o número aferido contra o teto legal",
    "impacto_fiscal": "ausência de estimativa de impacto orçamentário-financeiro nos autos",
}


# ─────────────────────────── vício → regimes potencialmente aplicáveis ─────────────────────────


@dataclass(frozen=True)
class Enquadramento:
    """Hipóteses de enquadramento de um vício, com o que cada uma exige."""

    vicio: str
    regimes: tuple[str, ...]
    provas_necessarias: dict[str, tuple[str, ...]] = field(default_factory=dict)
    nota: str = ""


# Fonte dos ids de vício: `knowledge/catalogo_vicios.py` (42 vícios). `validar()` trava o mapa.
ENQUADRAMENTOS: dict[str, Enquadramento] = {
    "especificacao_dirigida": Enquadramento(
        "especificacao_dirigida",
        ("controle_externo", "improbidade_principios", "anticorrupcao_pj", "crime_licitatorio"),
        {"improbidade_principios": ("conduta", "beneficiario", "dolo"),
         "anticorrupcao_pj": ("ato_lesivo", "beneficiario"),
         "controle_externo": ("conduta", "norma")},
        nota="Sem beneficiário identificado e sem finalidade demonstrada, o art. 11, V não "
             "incide: a exigência restritiva é irregularidade administrativa.",
    ),
    "barreira_habilitacao": Enquadramento(
        "barreira_habilitacao",
        ("controle_externo", "improbidade_principios", "anticorrupcao_pj"),
        {"improbidade_principios": ("conduta", "beneficiario", "dolo"),
         "controle_externo": ("conduta", "norma")},
        nota="Exigência acima do teto sumulado é achado objetivo (grau A); a improbidade exige, "
             "além dela, o fim de beneficiar.",
    ),
    "clausula_restritiva_combinada": Enquadramento(
        "clausula_restritiva_combinada",
        ("controle_externo", "improbidade_principios", "anticorrupcao_pj"),
        {"improbidade_principios": ("conduta", "beneficiario", "dolo")},
    ),
    "pontuacao_dirigida": Enquadramento(
        "pontuacao_dirigida",
        ("controle_externo", "improbidade_principios", "anticorrupcao_pj"),
        {"improbidade_principios": ("conduta", "beneficiario", "dolo")},
    ),
    "fracionamento_despesa": Enquadramento(
        "fracionamento_despesa",
        ("controle_externo", "improbidade_dano", "crime_licitatorio"),
        {"improbidade_dano": ("conduta", "dano", "nexo", "dolo"),
         "controle_externo": ("conduta", "norma")},
        nota="Art. 10, VIII exige perda patrimonial EFETIVA: fracionamento sem sobrepreço "
             "demonstrado não fecha o tipo, ainda que a burla ao art. 75 esteja provada.",
    ),
    "contratacao_direta_indevida": Enquadramento(
        "contratacao_direta_indevida",
        ("controle_externo", "improbidade_dano", "crime_licitatorio"),
        {"improbidade_dano": ("conduta", "dano", "nexo", "dolo")},
        nota="Mesma exigência de dano efetivo do art. 10, VIII.",
    ),
    "emergencia_fabricada": Enquadramento(
        "emergencia_fabricada",
        ("controle_externo", "improbidade_dano", "crime_licitatorio"),
        {"improbidade_dano": ("conduta", "dano", "nexo", "dolo")},
    ),
    "sobrepreco_estimativa": Enquadramento(
        "sobrepreco_estimativa",
        ("controle_externo", "ressarcimento", "improbidade_dano"),
        {"improbidade_dano": ("conduta", "dano", "nexo", "dolo"),
         "ressarcimento": ("dano", "nexo")},
        nota="Sobrepreço na estimativa é vício do orçamento; só vira dano com execução e "
             "pagamento comprovados (OB, nunca empenho).",
    ),
    "jogo_planilha": Enquadramento(
        "jogo_planilha",
        ("controle_externo", "ressarcimento", "improbidade_dano"),
        {"improbidade_dano": ("conduta", "dano", "nexo", "dolo"),
         "ressarcimento": ("dano", "nexo")},
        nota="O TCU firma que a caracterização do jogo de planilha INDEPENDE de demonstração "
             "de dolo — o que sustenta representação e ressarcimento mesmo sem vencer a "
             "barreira do dolo específico da Lei 8.429.",
    ),
    "aditivo_excessivo": Enquadramento(
        "aditivo_excessivo",
        ("controle_externo", "ressarcimento", "improbidade_dano"),
        {"improbidade_dano": ("conduta", "dano", "nexo", "dolo"),
         "controle_externo": ("conduta", "norma")},
        nota="Estouro do teto do art. 125 é achado objetivo; o dano depende de o acréscimo ter "
             "sido pago e de o preço ser superior ao de mercado.",
    ),
    "prorrogacao_perpetua": Enquadramento(
        "prorrogacao_perpetua",
        ("controle_externo", "improbidade_dano"),
        {"improbidade_dano": ("conduta", "dano", "nexo", "dolo")},
    ),
    "cartel_rodizio": Enquadramento(
        "cartel_rodizio",
        ("anticorrupcao_pj", "crime_licitatorio", "controle_externo", "improbidade_principios"),
        {"anticorrupcao_pj": ("ato_lesivo",),
         "crime_licitatorio": ("conduta", "dolo"),
         "improbidade_principios": ("conduta", "beneficiario", "dolo")},
        nota="Cartel é o caso em que a Lei 12.846 é a via mais direta: responsabilidade "
             "OBJETIVA da empresa, sem precisar provar dolo de agente público.",
    ),
    "propostas_cobertura": Enquadramento(
        "propostas_cobertura",
        ("anticorrupcao_pj", "crime_licitatorio", "controle_externo"),
        {"anticorrupcao_pj": ("ato_lesivo",)},
    ),
    "empresa_fachada": Enquadramento(
        "empresa_fachada",
        ("anticorrupcao_pj", "crime_licitatorio", "improbidade_dano", "controle_externo"),
        {"improbidade_dano": ("conduta", "dano", "nexo", "dolo"),
         "anticorrupcao_pj": ("ato_lesivo",)},
    ),
    "servidor_socio": Enquadramento(
        "servidor_socio",
        ("improbidade_principios", "controle_externo", "improbidade_enriquecimento"),
        {"improbidade_enriquecimento": ("vantagem", "conduta", "dolo"),
         "improbidade_principios": ("conduta", "dolo")},
        nota="Art. 14, I da Lei 14.133 veda a participação; o enriquecimento exige provar a "
             "vantagem efetivamente auferida.",
    ),
    "sancionada_contratada": Enquadramento(
        "sancionada_contratada",
        ("controle_externo", "improbidade_principios"),
        {"controle_externo": ("conduta", "norma")},
    ),
    "entrega_fantasma": Enquadramento(
        "entrega_fantasma",
        ("improbidade_dano", "crime_licitatorio", "ressarcimento", "controle_externo"),
        {"improbidade_dano": ("conduta", "dano", "nexo", "dolo"),
         "ressarcimento": ("dano", "nexo")},
        nota="Pagamento sem contraprestação é o caso em que o dano é mais fácil de comprovar: "
             "a OB existe e a entrega não.",
    ),
    "execucao_financeira_anomala": Enquadramento(
        "execucao_financeira_anomala",
        ("controle_externo", "lrf"),
        {"lrf": ("impacto_fiscal",)},
    ),
    "carona_abusiva": Enquadramento(
        "carona_abusiva", ("controle_externo", "improbidade_dano"),
        {"improbidade_dano": ("conduta", "dano", "nexo", "dolo")},
    ),
    "lote_pacote": Enquadramento("lote_pacote", ("controle_externo", "improbidade_principios"),
                                 {"improbidade_principios": ("conduta", "beneficiario", "dolo")}),
    "planejamento_fachada": Enquadramento("planejamento_fachada", ("controle_externo",),
                                          {"controle_externo": ("conduta", "norma")}),
    "vinculo_politico": Enquadramento(
        "vinculo_politico", ("controle_externo", "improbidade_principios"),
        {"improbidade_principios": ("conduta", "beneficiario", "dolo")}),
    "sub_rogacao_ilegal": Enquadramento(
        "sub_rogacao_ilegal", ("controle_externo", "improbidade_principios"),
        {"improbidade_principios": ("conduta", "dolo")}),
}


def enquadrar(vicio: str) -> Enquadramento | None:
    """Hipóteses de enquadramento do vício. `None` = ainda não mapeado (declarado, não chutado)."""
    return ENQUADRAMENTOS.get(str(vicio or "").strip())


def regime(regime_id: str) -> Regime | None:
    return REGIMES.get(str(regime_id or "").strip())


def o_que_falta(vicio: str, provas_disponiveis: set[str] | list[str] | None = None) -> dict:
    """O produto útil: por regime, o que já se tem e o que falta provar.

    `provas_disponiveis` usa o vocabulário de `PROVAS` ("dano", "beneficiario", "dolo"…). O
    resultado ordena os regimes do mais próximo de fechar para o mais distante — é a ordem em
    que um controlador decide o que perseguir.
    """
    e = enquadrar(vicio)
    if not e:
        return {"vicio": vicio, "mapeado": False, "regimes": [],
                "nota": "vício ainda não mapeado em knowledge/tipicidade — lacuna declarada"}
    tem = {str(p) for p in (provas_disponiveis or set())}
    linhas = []
    for rid in e.regimes:
        r = REGIMES[rid]
        exigidas = e.provas_necessarias.get(rid, ())
        faltam = [p for p in exigidas if p not in tem]
        linhas.append({
            "regime": rid,
            "nome": r.nome,
            "dispositivo": r.dispositivo,
            "elemento_subjetivo": r.elemento_subjetivo,
            "sujeito": r.sujeito,
            "standard": r.standard,
            "orgao_competente": r.orgao_competente,
            "elementos_do_tipo": list(r.elementos),
            "provas_exigidas": list(exigidas),
            "provas_presentes": [p for p in exigidas if p in tem],
            "provas_faltantes": faltam,
            "faltam_descrito": [PROVAS.get(p, p) for p in faltam],
            "fecha": not faltam and bool(exigidas),
        })
    linhas.sort(key=lambda d: (len(d["provas_faltantes"]), d["regime"]))
    return {"vicio": vicio, "mapeado": True, "nota": e.nota, "regimes": linhas,
            "algum_fecha": any(d["fecha"] for d in linhas),
            "ressalva": ("Qualificação HIPOTÉTICA para orientar diligência. A tipificação é do "
                         "órgão competente; os elementos não podem ser presumidos "
                         "(Lei 8.429/1992, art. 17-C, I).")}


def validar() -> list[str]:
    """Todo ponteiro do mapa resolve? Roda no teste, como `catalogo_vicios.validar()`."""
    from compliance_agent.knowledge.catalogo_vicios import obter

    erros: list[str] = []
    for vid, e in ENQUADRAMENTOS.items():
        if obter(vid) is None:
            erros.append(f"vício inexistente no catálogo canônico: {vid}")
        for rid in e.regimes:
            if rid not in REGIMES:
                erros.append(f"{vid}: regime desconhecido {rid}")
        for rid, provas in e.provas_necessarias.items():
            if rid not in e.regimes:
                erros.append(f"{vid}: provas para regime fora da lista ({rid})")
            for p in provas:
                if p not in PROVAS:
                    erros.append(f"{vid}/{rid}: prova fora do vocabulário ({p})")
    return erros


def cobertura() -> dict:
    """Quantos dos 42 vícios já têm enquadramento — e quais faltam, nominalmente."""
    from compliance_agent.knowledge.catalogo_vicios import CATALOGO

    todos = {v.id for v in CATALOGO}
    mapeados = set(ENQUADRAMENTOS) & todos
    return {"total_catalogo": len(todos), "mapeados": len(mapeados),
            "faltando": sorted(todos - mapeados)}
