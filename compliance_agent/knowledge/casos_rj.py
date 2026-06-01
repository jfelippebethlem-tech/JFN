"""
Base de conhecimento: casos de corrupção documentados no RJ.

Cada caso tem:
  - id, nome, periodo, descricao
  - atores: tipos de agentes envolvidos
  - padroes: fingerprints detectáveis automaticamente
  - palavras_chave: termos associados (para busca em DOERJ/contratos)
  - base_legal: infrações cometidas
  - fontes: referências públicas

Uso pelo agente: o sistema compara novos alertas contra esses padrões
para calcular um "score de similaridade" com casos conhecidos.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CasoCorrupcao:
    id: str
    nome: str
    periodo: str
    descricao: str
    orgaos_envolvidos: list[str]
    atores_tipo: list[str]           # servidor | político | empresário | milícia
    padroes: list[str]               # IDs de FraudePattern
    palavras_chave: list[str]
    valor_estimado_reais: Optional[float]
    base_legal_violada: list[str]
    fontes: list[str]
    status: str                      # condenado | investigado | arquivado | prescrito


CASOS_RJ: list[CasoCorrupcao] = [

    CasoCorrupcao(
        id="cabral_propinas",
        nome="Governo Sérgio Cabral — Esquema de Propinas",
        periodo="2007–2014",
        descricao=(
            "Governador Sérgio Cabral e cúpula do governo recebiam propinas de 5% a 15% "
            "em contratos de obras públicas (PAC, UPPs, Copa do Mundo, Olimpíadas). "
            "Dinheiro era lavado via offshores, empresas de fachada e doleiros. "
            "Construtoras Andrade Gutierrez, OAS, Odebrecht e outras pagaram propina "
            "sistematicamente. Mais de R$ 200 milhões desviados documentados."
        ),
        orgaos_envolvidos=["Governo do Estado RJ", "SEOBRAS", "EMOP", "RIOTUR"],
        atores_tipo=["político", "empresário", "servidor alto escalão"],
        padroes=["superfaturamento_obras", "empresa_offshore", "propina_percentual",
                 "contrato_sem_licitacao", "aditivo_excessivo"],
        palavras_chave=["cabral", "andrade gutierrez", "OAS", "odebrecht", "EMOP",
                        "PAC", "copa", "olimpíadas", "offshore", "doleiro"],
        valor_estimado_reais=224_000_000,
        base_legal_violada=["Lei 8.429/92 arts. 9, 10", "CP art. 317 (corrupção passiva)",
                            "CP art. 337-B (lavagem de dinheiro)"],
        fontes=["Operação Calicute (PF, 2016)", "Operação Eficiência (PF, 2016)",
                "Operação Totem (PF, 2017)", "MPF - denúncias 2017-2019"],
        status="condenado",
    ),

    CasoCorrupcao(
        id="mensalao_alerj",
        nome="Mensalão da ALERJ — Deputados × Milícias",
        periodo="2008–2017",
        descricao=(
            "Esquema de pagamento de propina a deputados estaduais pelo domínio de milícias "
            "sobre regiões do RJ. Deputados recebiam mensalmente por votar a favor de projetos "
            "e omitir investigações. 'Doutor Ecko' (Adriano Magalhães da Nóbrega) e outras "
            "lideranças de milícias pagavam via empresas de fachada (segurança, transporte, "
            "construção), algumas contratadas pelo próprio governo estadual."
        ),
        orgaos_envolvidos=["ALERJ", "Secretaria de Segurança Pública RJ",
                           "PM-RJ", "Prefeituras ligadas a deputados"],
        atores_tipo=["político", "milícia", "empresário fachada"],
        padroes=["empresa_fachada_milicia", "contrato_seguranca_suspeito",
                 "pagamento_mensal_recorrente", "sócio_policial"],
        palavras_chave=["milícia", "ecko", "escritório do crime", "PMDB", "segurança privada",
                        "transporte alternativo", "grilagem", "lan house milícia"],
        valor_estimado_reais=None,
        base_legal_violada=["Lei 8.429/92", "CP art. 288 (organização criminosa)",
                            "Lei 12.850/13"],
        fontes=["Operação Furna da Onça (PF, 2018)",
                "CPI das Milícias ALERJ 2008",
                "MP-RJ investigações 2019-2021"],
        status="investigado",
    ),

    CasoCorrupcao(
        id="witzel_saude_covid",
        nome="Wilson Witzel — Fraude em Contratos de Saúde (COVID-19)",
        periodo="2019–2020",
        descricao=(
            "Governador Wilson Witzel e secretários desviaram recursos destinados ao "
            "combate à COVID-19. Contratos com OSs (Organizações Sociais) sem licitação, "
            "superfaturados, com empresas ligadas à esposa do governador (Ana Lúcia Witzel) "
            "e a pastores evangélicos aliados políticos. "
            "Hospital de campanha de Maracanã: R$ 1,9 bi contratados, obra entregue incompleta. "
            "Witzel foi afastado pelo STJ e perdeu o mandato por impeachment."
        ),
        orgaos_envolvidos=["Governo do Estado RJ", "SES-RJ", "SESDEC",
                           "Hospital de campanha Maracanã", "OSs contratadas"],
        atores_tipo=["político", "servidor alto escalão", "OS fraudulenta",
                     "parente de político"],
        padroes=["os_sem_licitacao", "superfaturamento_saude", "empresa_parente_governador",
                 "contrato_emergencial_covid", "medição_obra_incompleta"],
        palavras_chave=["witzel", "ana lúcia", "OS saúde", "hospital de campanha",
                        "maracanã", "covid", "IECIS", "biotech", "respirador"],
        valor_estimado_reais=1_900_000_000,
        base_legal_violada=["Lei 8.429/92 arts. 9, 10, 11",
                            "Lei 14.133/21 art. 178",
                            "CF/88 art. 37, XXI"],
        fontes=["TCE-RJ Relatório 2020", "MP-RJ denúncia 2020",
                "STJ - Ação Penal 2020", "TCU Relatório COVID-19 2021"],
        status="condenado",
    ),

    CasoCorrupcao(
        id="esquema_sa_saude",
        nome="Esquema S.A. — OSs na Saúde RJ",
        periodo="2014–2019",
        descricao=(
            "Rede de organizações sociais (OSs) contratadas para gerir hospitais estaduais "
            "superfaturava serviços, pagava salários de funcionários fantasmas e desviava "
            "verbas para políticos e partidos. As OSs eram criadas por políticos ou aliados "
            "como veículos de captação de contratos sem licitação (inexigibilidade e dispensa). "
            "Hospitais: Albert Schweitzer, Carlos Chagas, Getúlio Vargas e outros."
        ),
        orgaos_envolvidos=["SES-RJ", "Hospitais estaduais geridos por OS",
                           "Secretaria de Fazenda RJ"],
        atores_tipo=["OS fraudulenta", "servidor saúde", "político"],
        padroes=["os_sem_licitacao", "funcionario_fantasma_saude", "superfaturamento_insumos",
                 "dispensa_indevida", "cnpj_recente_contrato_grande"],
        palavras_chave=["organização social", "OS", "hospital", "SES", "SESDEC",
                        "gestão hospitalar", "Albert Schweitzer", "Carlos Chagas",
                        "insumo hospitalar", "inexigibilidade"],
        valor_estimado_reais=800_000_000,
        base_legal_violada=["Lei 9.637/98 (OSs)", "Lei 8.429/92",
                            "Lei 8.666/93 art. 25 (inexigibilidade indevida)"],
        fontes=["TCE-RJ auditorias 2016-2020",
                "MP-RJ investigações OSs 2018",
                "Tribunal de Justiça RJ ações 2019-2022"],
        status="investigado",
    ),

    CasoCorrupcao(
        id="unfair_play_olimpiadas",
        nome="Operação Unfair Play — Rio 2016 / COI",
        periodo="2009–2017",
        descricao=(
            "Pagamento de US$ 2 milhões em propinas a membros do COI para garantir "
            "a escolha do Rio de Janeiro como sede dos Jogos Olímpicos de 2016. "
            "Dinheiro passou por contas offshore e foi operacionalizado por Carlos Nuzman "
            "(COB) e Arthur Soares (empresário). Paralelamente, contratos de obras "
            "olímpicas foram superfaturados (Transolímpica, Porto Maravilha, Maracanã)."
        ),
        orgaos_envolvidos=["COB", "Governo Estado RJ", "Prefeitura Rio",
                           "CDURP (Porto Maravilha)"],
        atores_tipo=["político", "empresário", "dirigente esportivo"],
        padroes=["propina_offshore", "superfaturamento_obras", "contrato_sem_licitacao",
                 "obra_superfaturada_evento"],
        palavras_chave=["olimpíadas", "COB", "nuzman", "porto maravilha", "transolímpica",
                        "maracanã", "offshore", "COI", "legado olímpico"],
        valor_estimado_reais=500_000_000,
        base_legal_violada=["CP art. 333 (corrupção ativa internacional)",
                            "Lei 12.846/13 (Lei Anticorrupção)",
                            "Lei 9.613/98 (lavagem)"],
        fontes=["Operação Unfair Play (PF, 2017)",
                "DOJ USA - acordo de leniência 2017",
                "TCU Relatório Obras Olímpicas 2017"],
        status="condenado",
    ),

    CasoCorrupcao(
        id="detran_habilitacoes",
        nome="DETRAN-RJ — Carteiras de Habilitação Fraudulentas",
        periodo="2010–2022",
        descricao=(
            "Rede de servidores do DETRAN-RJ e autoescolas fraudulentas emitiam CNHs "
            "sem que os candidatos fizessem os exames. Propinas de R$ 3.000 a R$ 8.000 "
            "por carteira. Terceirizados das autoescolas (muitas contratadas pelo DETRAN) "
            "eram cúmplices. Servidores usavam CPFs de candidatos reais para registrar "
            "aprovações fictícias no sistema."
        ),
        orgaos_envolvidos=["DETRAN-RJ", "Autoescolas credenciadas"],
        atores_tipo=["servidor", "empresário autoescola", "terceirizado"],
        padroes=["fraude_sistema_informatizado", "cpf_aprovacao_ficticia",
                 "empresa_credenciada_suspeita", "propina_servidor"],
        palavras_chave=["DETRAN", "habilitação", "CNH", "autoescola", "exame",
                        "credenciamento", "vistoria", "laudo"],
        valor_estimado_reais=50_000_000,
        base_legal_violada=["CP art. 297 (falsificação documento público)",
                            "CP art. 317 (corrupção passiva)",
                            "Lei 8.429/92"],
        fontes=["Operação Carteira Falsa (PCERJ, 2019)",
                "MP-RJ denúncias 2021",
                "CGE-RJ relatório DETRAN 2022"],
        status="investigado",
    ),

    CasoCorrupcao(
        id="cedae_quinto_ouro",
        nome="Operação Quinto do Ouro — CEDAE",
        periodo="2019–2022",
        descricao=(
            "Esquema de corrupção na CEDAE (Companhia Estadual de Águas e Esgotos) "
            "envolvendo contratos de obras de saneamento. Servidores recebiam propinas "
            "de empreiteiras para direcionar licitações e aprovar medições de obras "
            "não realizadas ou superfaturadas. Coincidiu com o processo de privatização "
            "da companhia, com suspeita de manipulação de dados para valorizar os ativos."
        ),
        orgaos_envolvidos=["CEDAE", "Governo Estado RJ", "BNDES"],
        atores_tipo=["servidor estatais", "empresário construção", "político"],
        padroes=["medicao_obra_ficticia", "direcao_licitacao", "propina_servidor_estatal",
                 "manipulacao_dados_privatizacao"],
        palavras_chave=["CEDAE", "saneamento", "esgoto", "água", "obra hidráulica",
                        "privatização", "concessão", "ETE", "ETA"],
        valor_estimado_reais=120_000_000,
        base_legal_violada=["Lei 8.429/92", "CP art. 317", "Lei 13.303/16 (estatais)"],
        fontes=["Operação Quinto do Ouro (MPRJ, 2022)",
                "TCE-RJ Auditoria CEDAE 2021",
                "CGU Relatório Concessão CEDAE 2022"],
        status="investigado",
    ),

    CasoCorrupcao(
        id="furna_da_onca",
        nome="Operação Furna da Onça — ALERJ e Crime Organizado",
        periodo="2014–2018",
        descricao=(
            "Deputados estaduais recebiam propinas do 'escritório do crime' (grupo "
            "criminoso ligado a Rogério 157 e Marcos Willians/Ecko) para interferir "
            "em investigações policiais, liberar presos e proteger tráfico e milícias. "
            "Propinas pagas em dinheiro vivo e via empresas de fachada. "
            "Oito deputados presos. Presidente da ALERJ Jorge Picciani entre os detidos."
        ),
        orgaos_envolvidos=["ALERJ", "Secretaria de Segurança Pública RJ",
                           "PCERJ", "PM-RJ"],
        atores_tipo=["político", "crime organizado", "servidor segurança pública"],
        padroes=["propina_crime_organizado", "interferencia_investigacao",
                 "empresa_fachada_lavagem", "pagamento_dinheiro_vivo"],
        palavras_chave=["picciani", "ecko", "rogério 157", "escritório do crime",
                        "ALERJ", "preso", "investigação policial", "milícia tráfico"],
        valor_estimado_reais=None,
        base_legal_violada=["CP art. 317 (corrupção passiva)",
                            "Lei 12.850/13 (organização criminosa)",
                            "Lei 8.429/92"],
        fontes=["Operação Furna da Onça (PF/MPRJ, 2018)",
                "STJ - APn 960 e outras",
                "Relatório GAECO-RJ 2019"],
        status="condenado",
    ),

    CasoCorrupcao(
        id="secretaria_obras_obras",
        nome="Secretaria de Obras RJ — Cartel de Empreiteiras",
        periodo="2006–2020",
        descricao=(
            "Cartel de empreiteiras — Odebrecht, Carioca Engenharia, Delta, Galvão, "
            "Queiroz Galvão e outras — combinavam preços e dividiam contratos de obras "
            "públicas do Estado do RJ entre si. Propinas de 3% a 10% dos contratos "
            "eram pagas ao secretário de Obras e ao governador. Irregularidades: "
            "superfaturamento, aditivos não justificados, medições de obras inexistentes."
        ),
        orgaos_envolvidos=["SEOBRAS-RJ", "EMOP", "DNIT-RJ", "DER-RJ"],
        atores_tipo=["empreiteira cartel", "servidor obras", "político"],
        padroes=["cartel_empreiteiras", "aditivo_excessivo", "superfaturamento_obras",
                 "rotatividade_vencedor", "propina_percentual"],
        palavras_chave=["empreiteira", "Carioca Engenharia", "Delta Construções",
                        "Galvão", "Odebrecht", "obra pública", "EMOP", "DER",
                        "reforma", "pavimentação", "viaduto", "cartel"],
        valor_estimado_reais=400_000_000,
        base_legal_violada=["Lei 12.529/11 (CADE — cartel)",
                            "Lei 8.429/92",
                            "Lei 8.666/93 art. 90 (fraude licitação)"],
        fontes=["Operação Calicute (PF, 2016)",
                "CADE Processo 08700.003188/2015",
                "TCU Relatório Obras PAC-RJ 2018"],
        status="condenado",
    ),

    CasoCorrupcao(
        id="codin_fundo_estado",
        nome="CODIN / Fundo de Desenvolvimento — Incentivos Fiscais Fraudulentos",
        periodo="2012–2021",
        descricao=(
            "Empresas fantasmas ou inativas obtinham incentivos fiscais do Estado do RJ "
            "(ICMS, FDI) mediante laudos técnicos falsos emitidos por servidores da CODIN "
            "e Secretaria de Fazenda. Benefícios chegavam a R$ 50 milhões por empresa. "
            "Algumas empresas beneficiadas não possuíam funcionários, endereço real "
            "ou atividade econômica comprovada."
        ),
        orgaos_envolvidos=["CODIN", "SEFAZ-RJ", "Governo Estado RJ"],
        atores_tipo=["servidor fazenda", "empresário fachada", "contador"],
        padroes=["empresa_fachada_incentivo", "laudo_falso", "beneficio_fiscal_indevido",
                 "cnpj_sem_atividade_real"],
        palavras_chave=["CODIN", "incentivo fiscal", "ICMS", "FDI", "benefício fiscal",
                        "isenção", "laudo técnico", "SEFAZ", "desenvolvimento industrial"],
        valor_estimado_reais=300_000_000,
        base_legal_violada=["Lei 8.429/92 art. 11 (violação princípios)",
                            "CP art. 299 (falsidade ideológica)",
                            "CTN art. 156 (benefício fiscal indevido)"],
        fontes=["CGE-RJ Relatório CODIN 2020",
                "TCE-RJ Auditoria Incentivos Fiscais 2021",
                "MP-RJ investigações 2022"],
        status="investigado",
    ),

    # ── CASO EM INVESTIGAÇÃO ATIVA ─────────────────────────────────────────────

    CasoCorrupcao(
        id="reforma_escolar_thiago_rangel",
        nome="Fraude em Reformas Escolares — Dep. Thiago Rangel (ALERJ)",
        periodo="2022–2025",
        descricao=(
            "Esquema em investigação envolvendo contratos de reforma e manutenção de "
            "unidades escolares da rede estadual do RJ (SEEDUC). Indícios apontam para "
            "superfaturamento sistemático, medições fraudulentas de obras não realizadas "
            "ou executadas parcialmente, e direcionamento de contratos para empresas "
            "ligadas ao deputado Thiago Rangel (ALERJ). O esquema teria movimentado "
            "dezenas de milhões em contratos da Secretaria de Educação e do Fundo Estadual "
            "de Educação. Processos SEI e despesas SIAFE-RJ2 são evidências centrais. "
            "COMO INVESTIGAR: buscar no SIAFE os empenhos de 'reforma' + 'escola' ligados "
            "à SEEDUC; localizar os processos SEI associados; comparar medições pagas com "
            "o estado real das obras via google maps/fotos; checar se empresas contratadas "
            "têm sócios ligados a Thiago Rangel ou seu entorno político."
        ),
        orgaos_envolvidos=[
            "SEEDUC-RJ",
            "FAETEC",
            "Fundo Estadual de Educação",
            "ALERJ",
        ],
        atores_tipo=["político", "servidor educação", "empreiteira reforma", "empresário fachada"],
        padroes=[
            "superfaturamento_obras",
            "medicao_fraudulenta",
            "direcionamento_edital",
            "empresa_recente_grande_contrato",
            "aditivo_excessivo",
        ],
        palavras_chave=[
            "thiago rangel", "reforma escola", "unidade escolar", "SEEDUC",
            "manutenção escolar", "obra escolar", "FAETEC", "recuperação escola",
            "pintura escola", "reforma banheiro escola", "contrato educação",
            "fundo educação", "empreiteira escola", "obra pública escola",
            "manutenção predial escola", "serviços de engenharia escolar",
        ],
        valor_estimado_reais=None,
        base_legal_violada=[
            "Lei 14.133/21 art. 178 (fraude em licitação)",
            "Lei 8.429/92 arts. 9, 10 (improbidade)",
            "CP art. 312 (peculato)",
            "CF/88 art. 37 (moralidade)",
        ],
        fontes=[
            "Investigação MPRJ em andamento (2024-2025)",
            "TCE-RJ — auditoria contratos SEEDUC (em andamento)",
            "Processos SEI: portalsei.rj.gov.br (consulta pública)",
            "SIAFE-RJ2 — execução orçamentária SEEDUC",
        ],
        status="investigado",
    ),

]


# ── Índices para acesso rápido ────────────────────────────────────────────────
CASOS_POR_ID: dict[str, CasoCorrupcao] = {c.id: c for c in CASOS_RJ}

CASOS_POR_STATUS: dict[str, list[CasoCorrupcao]] = {}
for _c in CASOS_RJ:
    CASOS_POR_STATUS.setdefault(_c.status, []).append(_c)

TODOS_TERMOS_CASOS: list[tuple[str, str]] = [
    (termo.lower(), caso.id)
    for caso in CASOS_RJ
    for termo in caso.palavras_chave
]
